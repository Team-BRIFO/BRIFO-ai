"""
LLM 사용량·비용 기록
MVP는 JSON 로그부터 시작, 추후 DB 테이블로 확장 가능.
"""

import asyncio
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

LOG_PATH = Path("logs/llm_usage.jsonl")

_write_lock = threading.Lock()


async def record_usage(
    *,  # 키워드 전용
    model_name: str,
    agent_type: str,
    task_type: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    event_type: Literal["llm_request", "llm_validation_error"] = "llm_request",
    requested_model: str | None = None,
    cache_hit: bool = False,
    fallback_used: bool = False,
    estimated_cost_usd: float | None = None,
    json_retry_count: int = 0,
    finish_reason: str | None = None,
    status: Literal["success", "error"] = "success",
    error_type: str | None = None,
    primary_wasted_input_tokens: int = 0,
    primary_wasted_output_tokens: int = 0,
    primary_wasted_cost_usd: float | None = None,
    primary_finish_reason: str | None = None,
) -> None:
    """
    LLM 호출의 사용량, 비용, 지연시간, 재시도 정보를 JSONL로 기록한다.

    - 검증 실패는 `llm_validation_error` 이벤트로 분리한다.
    - fallback 발생 시 primary 낭비 사용량을 별도 기록해 모델별 비용을 정확히 집계한다.
    - primary의 finish_reason도 기록해 응답 잘림이 집계에서 누락되지 않도록 한다.
    """

    usage_log = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "requested_model": requested_model or model_name,
        "actual_model": model_name,
        "model_name": model_name,  # 현재는 중복이지만 이전 로그도 처리할 수 있도록 유지
        "agent_type": agent_type,
        "task_type": task_type,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "latency_ms": latency_ms,
        "cache_hit": cache_hit,
        "fallback_used": fallback_used,
        "json_retry_count": json_retry_count,
        "finish_reason": finish_reason,
        "status": status,
        "error_type": error_type,
        "primary_wasted_input_tokens": primary_wasted_input_tokens,
        "primary_wasted_output_tokens": primary_wasted_output_tokens,
        "primary_wasted_cost_usd": primary_wasted_cost_usd,
        "primary_finish_reason": primary_finish_reason,
    }

    await asyncio.to_thread(_write_log, usage_log)


async def record_cache_event(
    *,
    agent_type: str,
    task_type: str,
    cache_status: Literal["hit", "miss", "error", "invalid"],
    lookup_ms: float,
) -> None:
    """
    캐시 조회 1건을 JSONL 파일로 기록한다. LLM을 호출하지 않으므로 토큰·비용은 0으로
    기록한다.

    cache_status:
    - hit/miss: 정상적인 캐시 조회 결과
    - error: Valkey 연결·조회 자체가 실패함
    - invalid: 조회는 성공했지만 캐시에 저장된 값이 손상되어 검증에 실패함
    """

    cache_log = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": "cache_event",
        "agent_type": agent_type,
        "task_type": task_type,
        "cache_status": cache_status,
        "cache_lookup_ms": lookup_ms,
        "latency_ms": lookup_ms,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0,
    }

    await asyncio.to_thread(_write_log, cache_log)


def _write_log(log_entry: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _write_lock, LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
