"""
OpenRouter LLM 호출

http_client.py의 공유 클라이언트를 사용해 실제 LLM을 호출한다.
primary 모델이 실패하면 fallback 모델로 1회 재시도하고, 최종 실패 시 원인에 맞는 예외(LLMTimeout / RateLimit / AllModelsFailed)를 던진다.
require_json=True인데 응답이 JSON 형식이 아니면, 같은 모델에 JSON 형식을 강조한 재질문을 1회 보낸다.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.exceptions import AllModelsFailed, LLMTimeout, RateLimit
from app.infra.http_client import get_openrouter_client
from app.infra.usage_tracker import record_usage

_COMPLETIONS_PATH = "/chat/completions"
_logger = logging.getLogger(__name__)

# contentText 최대 400자(TANKER 기준) + 나머지 필드를 감안해 여유 있게 설정한 출력 토큰 상한
# 이 값에 걸려 응답이 잘리면 finish_reason="length"로 감지해 fallback으로 재시도한다
_MAX_OUTPUT_TOKENS = 2048

# response_format=json_object를 요청했음에도 순수 텍스트로 응답하는 경우를 대비한 재질문 문구
_JSON_RETRY_SUFFIX = "\n\n반드시 순수한 JSON 객체로만 응답하세요. 다른 설명이나 코드블록 마크다운 없이 JSON만 출력하세요."


@dataclass
class _ModelAttemptResult:
    """한 모델에 대한 시도(재질문 포함) 결과와 그동안 소모된 토큰 합계."""

    result: dict
    prompt_tokens: int
    completion_tokens: int


class _JsonRetryFailed(ValueError):
    """JSON 재질문 후에도 유효한 JSON 객체를 받지 못했을 때, 그동안 소모된 토큰과 함께 던진다."""

    def __init__(
        self, message: str, prompt_tokens: int, completion_tokens: int
    ) -> None:
        super().__init__(message)
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


async def call_llm(
    prompt: str,
    primary_model: str,
    fallback_model: str,
    *,
    agent_type: str,
    task_type: str,
    require_json: bool = True,
) -> dict:
    """
    LLM을 호출한다. primary 실패 시 fallback으로 1회 재시도한다.

    반환: {
        "model": 실제로 응답한 모델명,
        "input_tokens": int,
        "output_tokens": int,
        "fallback_used": bool,
        "content": str
    }

    예상 가능한 HTTP·응답 검증 오류만 fallback 처리하며,
    최종 실패 시 원인에 맞는 예외를 발생시킨다

    require_json=False이면 JSON 응답 형식을 강제하지 않는다.
    """
    client = get_openrouter_client()
    started = time.perf_counter()
    wasted_prompt_tokens = 0
    wasted_completion_tokens = 0

    try:
        attempt = await _try_model_with_json_retry(
            client, primary_model, prompt, require_json=require_json
        )
        fallback_used = False
        used_model = primary_model
        input_tokens = attempt.prompt_tokens
        output_tokens = attempt.completion_tokens
    except (httpx.HTTPError, ValueError) as primary_exc:
        wasted_prompt_tokens = getattr(primary_exc, "prompt_tokens", 0)
        wasted_completion_tokens = getattr(primary_exc, "completion_tokens", 0)
        try:
            attempt = await _try_model_with_json_retry(
                client, fallback_model, prompt, require_json=require_json
            )
            fallback_used = True
            used_model = fallback_model
            input_tokens = wasted_prompt_tokens + attempt.prompt_tokens
            output_tokens = wasted_completion_tokens + attempt.completion_tokens
        except (httpx.HTTPError, ValueError) as fallback_exc:
            wasted_prompt_tokens += getattr(fallback_exc, "prompt_tokens", 0)
            wasted_completion_tokens += getattr(fallback_exc, "completion_tokens", 0)
            latency_ms = (time.perf_counter() - started) * 1000
            error_type = _classify_error(fallback_exc)
            await _record_usage_safely(
                model_name=fallback_model,
                agent_type=agent_type,
                task_type=task_type,
                input_tokens=wasted_prompt_tokens,
                output_tokens=wasted_completion_tokens,
                latency_ms=latency_ms,
                fallback_used=True,
                status="error",
                error_type=error_type,
            )
            _raise_for_error_type(
                error_type, primary_model, fallback_model, fallback_exc
            )

    latency_ms = (time.perf_counter() - started) * 1000
    result = attempt.result

    await _record_usage_safely(
        model_name=result.get("model") or used_model,
        agent_type=agent_type,
        task_type=task_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        fallback_used=fallback_used,
        status="success",
    )

    return {
        "model": result.get("model") or used_model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "fallback_used": fallback_used,
        "content": result["choices"][0]["message"]["content"],
    }


async def _try_model(
    client: httpx.AsyncClient, model: str, prompt: str, *, require_json: bool
) -> dict:
    """
    모델 1개에 대해 1회 호출을 시도한다.

    choices, message, content가 없거나 생성 중 오류가 발생하면
    ValueError를 발생시켜 fallback으로 넘긴다.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": _MAX_OUTPUT_TOKENS,
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    response = await client.post(_COMPLETIONS_PATH, json=payload)
    response.raise_for_status()
    result = response.json()

    if not isinstance(result, dict):
        raise ValueError(f"'{model}' 응답이 객체 형식이 아닙니다.")

    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError(f"'{model}' 응답에 유효한 choices가 없습니다.")

    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError(f"'{model}' 응답의 choice 형식이 올바르지 않습니다.")

    if choice.get("finish_reason") == "error":
        raise ValueError(f"'{model}' 생성이 실패했습니다 (finish_reason=error).")
    if choice.get("finish_reason") == "length":
        raise ValueError(
            f"'{model}' 응답이 최대 토큰 길이에 도달해 잘렸습니다 (finish_reason=length)."
        )

    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError(f"'{model}' 응답에 유효한 message가 없습니다.")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"'{model}' 응답에 content가 없습니다.")

    return result


async def _try_model_with_json_retry(
    client: httpx.AsyncClient, model: str, prompt: str, *, require_json: bool
) -> _ModelAttemptResult:
    """
    _try_model을 호출하고, require_json인데 응답이 유효한 JSON이 아니면
    같은 모델에 JSON 형식을 강조한 재질문을 1회 보낸다.

    재질문까지 포함해 실제로 소모된 토큰 합계를 함께 반환한다.
    재질문 후에도 유효한 JSON이 아니면 그동안 소모된 토큰을 담은
    _JsonRetryFailed(ValueError)를 발생시켜 fallback으로 넘긴다.
    """
    result = await _try_model(client, model, prompt, require_json=require_json)
    prompt_tokens, completion_tokens = _extract_usage(result)
    if not require_json:
        return _ModelAttemptResult(result, prompt_tokens, completion_tokens)

    content = result["choices"][0]["message"]["content"]
    if _is_valid_json_object(content):
        return _ModelAttemptResult(result, prompt_tokens, completion_tokens)

    _logger.warning("'%s' 응답이 JSON 객체 형식이 아니어서 재질문합니다.", model)
    retry_result = await _try_model(
        client, model, prompt + _JSON_RETRY_SUFFIX, require_json=require_json
    )
    retry_prompt_tokens, retry_completion_tokens = _extract_usage(retry_result)
    prompt_tokens += retry_prompt_tokens
    completion_tokens += retry_completion_tokens

    content = retry_result["choices"][0]["message"]["content"]
    if not _is_valid_json_object(content):
        raise _JsonRetryFailed(
            f"'{model}' 응답이 JSON 재질문 후에도 JSON 객체 형식이 아닙니다.",
            prompt_tokens,
            completion_tokens,
        )

    return _ModelAttemptResult(retry_result, prompt_tokens, completion_tokens)


def _extract_usage(result: dict) -> tuple[int, int]:
    """응답에서 prompt_tokens, completion_tokens를 안전하게 추출한다."""
    usage = result.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return _safe_int(usage.get("prompt_tokens")), _safe_int(
        usage.get("completion_tokens")
    )


def _is_valid_json_object(text: str) -> bool:
    """문자열이 JSON 객체로 파싱되는지 확인한다."""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(parsed, dict)


def _classify_error(exc: Exception) -> str:
    """예외를 record_usage의 error_type 문자열로 분류한다."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 429:
            return "rate_limit"
        return "api_error"
    if isinstance(exc, ValueError):
        return "invalid_response"
    return "unknown"


def _raise_for_error_type(
    error_type: str, primary_model: str, fallback_model: str, cause: Exception
) -> None:
    """분류된 에러 종류에 맞는 예외를 던진다."""
    message = f"primary({primary_model})·fallback({fallback_model}) 모두 실패했습니다."
    if error_type == "timeout":
        raise LLMTimeout(message) from cause
    if error_type == "rate_limit":
        raise RateLimit(message) from cause
    raise AllModelsFailed(message) from cause


def _safe_int(value: object) -> int:
    """0 이상의 정수만 허용하고, 그 외 값은 0으로 처리한다."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


async def _record_usage_safely(**kwargs: Any) -> None:
    """
    사용량을 기록한다.
    기록 실패가 LLM 호출 결과에 영향을 주지 않도록 예외는 로그만 남긴다.
    """
    try:
        await record_usage(**kwargs)
    except Exception:
        _logger.exception("record_usage 기록 실패 (LLM 호출 결과에는 영향 없음)")
