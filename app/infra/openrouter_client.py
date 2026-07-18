"""
OpenRouter LLM 호출

http_client.py의 공유 클라이언트를 사용해 실제 LLM을 호출한다.
primary 모델이 실패하면 fallback 모델로 1회 재시도하고, 최종 실패 시 원인에 맞는 예외(LLMTimeout / RateLimit / AllModelsFailed)를 던진다.
"""

import time
import httpx
from app.exceptions import AllModelsFailed, LLMTimeout, RateLimit
from app.infra.http_client import get_openrouter_client
from app.infra.usage_tracker import record_usage

_COMPLETIONS_PATH = "/chat/completions"


async def call_llm(
    prompt: str,
    primary_model: str,
    fallback_model: str,
    *,
    agent_type: str,
    task_type: str,
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

    primary·fallback 둘 다 실패하면 마지막 실패 원인에 맞는 예외를 던진다
    (타임아웃 → LLMTimeout, 한도초과 → RateLimit, 그 외 → AllModelsFailed).
    """
    client = get_openrouter_client()
    started = time.perf_counter()

    try:
        result = await _try_model(client, primary_model, prompt)
        fallback_used = False
        used_model = primary_model
    except Exception:
        try:
            result = await _try_model(client, fallback_model, prompt)
            fallback_used = True
            used_model = fallback_model
        except Exception as fallback_exc:
            latency_ms = (time.perf_counter() - started) * 1000
            error_type = _classify_error(fallback_exc)
            await record_usage(
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
    usage = result.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    await record_usage(
        model_name=result.get("model", used_model),
        agent_type=agent_type,
        task_type=task_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        fallback_used=fallback_used,
        status="success",
    )

    return {
        "model": result.get("model", used_model),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "fallback_used": fallback_used,
        "content": result["choices"][0]["message"]["content"],
    }


async def _try_model(client: httpx.AsyncClient, model: str, prompt: str) -> dict:
    """
    모델 1개에 대해 1회 호출을 시도한다.
    """
    response = await client.post(
        _COMPLETIONS_PATH,
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
    )
    response.raise_for_status()
    result = response.json()

    choices = result.get("choices")
    if not choices:
        raise ValueError(f"'{model}' 응답에 choices가 없습니다.")

    choice = choices[0]
    if choice.get("finish_reason") == "error":
        raise ValueError(f"'{model}' 생성 중 실패했습니다 (finish_reason=error).")

    content = choice.get("message", {}).get("content")
    if not content:
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