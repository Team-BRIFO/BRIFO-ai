"""
OpenRouter LLM 호출

http_client.py의 공유 클라이언트를 사용해 실제 LLM을 호출한다.
primary 모델이 실패하면 fallback 모델로 1회 재시도하고, 최종 실패 시 원인에 맞는 예외(LLMTimeout / RateLimit / AllModelsFailed)를 던진다.
"""

import logging
import time
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

    try:
        result = await _try_model(client, primary_model, prompt, require_json=require_json)
        fallback_used = False
        used_model = primary_model
    except (httpx.HTTPError, ValueError):
        try:
            result = await _try_model(
                client, fallback_model, prompt, require_json=require_json
            )
            fallback_used = True
            used_model = fallback_model
        except (httpx.HTTPError, ValueError) as fallback_exc:
            latency_ms = (time.perf_counter() - started) * 1000
            error_type = _classify_error(fallback_exc)
            await _record_usage_safely(
                model_name=fallback_model,
                agent_type=agent_type,
                task_type=task_type,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                fallback_used=True,
                status="error",
                error_type=error_type,
            )
            _raise_for_error_type(error_type, primary_model, fallback_model, fallback_exc)

    latency_ms = (time.perf_counter() - started) * 1000
    usage = result.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = _safe_int(usage.get("prompt_tokens"))
    output_tokens = _safe_int(usage.get("completion_tokens"))

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
        raise ValueError(f"'{model}' 응답이 최대 토큰 길이에 도달해 잘렸습니다 (finish_reason=length).")

    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError(f"'{model}' 응답에 유효한 message가 없습니다.")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"'{model}' 응답에 content가 없습니다.")

    return result


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