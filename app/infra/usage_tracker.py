"""
LLM 사용량·비용 기록
MVP는 JSON 로그부터 시작, 추후 DB 테이블로 확장 가능.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


LOG_PATH = Path("logs/llm_usage.jsonl")


async def record_usage(
    *,  # 키워드 전용
    model_name: str,
    agent_type: str,
    task_type: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    cache_hit: bool = False,
    fallback_used: bool = False,
    estimated_cost_usd: float | None = None,
    status: Literal["success", "error"] = "success",
    error_type: str | None = None,
) -> None:
    """
    LLM 호출 1건의 사용량, 비용, 지연시간, 캐시 여부를 JSONL 파일로 기록한다.
    """

    usage_log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_name": model_name,
        "agent_type": agent_type,
        "task_type": task_type,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "latency_ms": latency_ms,
        "cache_hit": cache_hit,
        "fallback_used": fallback_used,
        "status": status,
        "error_type": error_type,
    }

    await asyncio.to_thread(_write_log, usage_log)


def _write_log(usage_log: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(usage_log, ensure_ascii=False) + "\n")
