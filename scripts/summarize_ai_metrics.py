"""
logs/llm_usage.jsonl 집계 스크립트

전체 요약(성공률/latency/비용), 캐시(hit rate/절감 추정 비용), 안정성(재질문율/
fallback율/에러율), 모델별/사원별/작업별 통계를 출력한다.

사용법:
    uv run python scripts/summarize_ai_metrics.py --input logs/llm_usage.jsonl
"""

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVAL_TASK_TYPES = {
    "news_summary_eval",
    "briefing_eval",
    "briefing_content_judge",
    "card_news_content_judge",
}

NON_LLM_SKIPPING_CACHE_TASK_TYPES = {"latest_news_summary"}


def _load_events(path: Path) -> list[dict[str, Any]]:
    events = []
    skipped = 0
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            event.setdefault("event_type", "llm_request")
            events.append(event)
    if skipped:
        print(f"경고: 손상된 로그 줄 {skipped}개를 건너뛰었습니다.", file=sys.stderr)
    return events


def _parse_timestamp(value: str) -> datetime:
    """
    ISO8601 타임스탬프를 datetime으로 파싱한다. tzinfo가 없으면 UTC로 간주한다.
    문자열 그대로 사전식 비교하면 "Z"·"+09:00" 등 표기가 섞였을 때 틀리게 비교되므로,
    --since 필터링은 반드시 이 함수로 파싱한 datetime끼리 비교해야 한다.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _percentile(values: list[float], pct: float) -> float:
    """
    nearest-rank 방식으로 백분위수를 계산한다.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * pct) - 1)
    index = min(index, len(ordered) - 1)
    return ordered[index]


def _avg(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _print_overall(llm_events: list[dict]) -> None:
    print("=== 전체 요약 ===")
    total = len(llm_events)
    if total == 0:
        print("요청 없음")
        return

    success = [e for e in llm_events if e.get("status") == "success"]
    latencies = [e["latency_ms"] for e in llm_events if e.get("latency_ms") is not None]
    costs = [
        e["estimated_cost_usd"]
        for e in llm_events
        if e.get("estimated_cost_usd") is not None
    ]
    api_attempts = sum(
        1 + e.get("json_retry_count", 0) + (1 if e.get("fallback_used") else 0)
        for e in llm_events
    )

    print(f"논리 요청 수: {total}")
    print(f"실제 LLM API 호출 시도 수: {api_attempts} (JSON 재질문·fallback 포함)")
    print(f"성공률: {len(success) / total * 100:.1f}%")
    print(f"평균 latency: {_avg(latencies):.0f}ms")
    print(f"p50 latency: {_percentile(latencies, 0.50):.0f}ms")
    print(f"p95 latency: {_percentile(latencies, 0.95):.0f}ms")
    print(
        f"총비용: ${sum(costs):.4f}"
        if costs
        else "총비용: 알 수 없음 (단가표에 없는 모델)"
    )
    print(f"평균 비용: ${_avg(costs):.4f}" if costs else "평균 비용: 알 수 없음")
    print()


def _print_cache(cache_events: list[dict], llm_events: list[dict]) -> None:
    print("=== 캐시 ===")
    total = len(cache_events)
    if total == 0:
        print("캐시 조회 이벤트 없음 (cache_status 로깅이 아직 없는 옛 로그일 수 있음)")
        print()
        return

    by_status: dict[str, list[dict]] = defaultdict(list)
    for e in cache_events:
        by_status[e.get("cache_status", "unknown")].append(e)

    hit = by_status.get("hit", [])
    miss = by_status.get("miss", [])
    error = by_status.get("error", [])
    invalid = by_status.get("invalid", [])

    # error와 invalid 제외
    resolved = len(hit) + len(miss)

    # LLM 호출을 실제로 생략시키는 hit/miss
    llm_skip_hit = [
        e for e in hit if e.get("task_type") not in NON_LLM_SKIPPING_CACHE_TASK_TYPES
    ]
    llm_skip_miss = [
        e for e in miss if e.get("task_type") not in NON_LLM_SKIPPING_CACHE_TASK_TYPES
    ]
    llm_skip_resolved = len(llm_skip_hit) + len(llm_skip_miss)

    print(f"조회 수: {total}")
    print(
        f"hit: {len(hit)}  miss: {len(miss)}  error: {len(error)}  invalid: {len(invalid)}"
    )
    print(f"Valkey 조회 오류율: {len(error) / total * 100:.1f}% (연결·조회 자체 실패)")
    print(
        f"캐시 데이터 무효율: {len(invalid) / total * 100:.1f}% (연결은 됐지만 저장된 값이 손상됨)"
    )
    print(
        f"전체 캐시 조회 적중률: {len(hit) / resolved * 100:.1f}%"
        if resolved
        else "전체 캐시 조회 적중률: 데이터 없음"
    )
    print(
        f"LLM 호출 생략형 캐시 적중률: {len(llm_skip_hit) / llm_skip_resolved * 100:.1f}% "
        f"(latest_news_summary 제외 — 이건 hit여도 브리핑 LLM은 그대로 호출됨)"
        if llm_skip_resolved
        else "LLM 호출 생략형 캐시 적중률: 데이터 없음"
    )
    # 실제 사용자 응답 시간이 아닌 조회 시간
    print(f"hit 평균 lookup 시간: {_avg([e['cache_lookup_ms'] for e in hit]):.0f}ms")
    print(f"miss 평균 lookup 시간: {_avg([e['cache_lookup_ms'] for e in miss]):.0f}ms")

    print("\n작업별 캐시 조회:")
    by_task: dict[str, dict[str, int]] = defaultdict(
        lambda: {"hit": 0, "miss": 0, "error": 0, "invalid": 0}
    )
    for e in cache_events:
        by_task[e.get("task_type", "unknown")][e.get("cache_status", "unknown")] += 1
    for task_type, counts in sorted(by_task.items()):
        skip_note = (
            " (LLM 호출 생략 안 됨)"
            if task_type in NON_LLM_SKIPPING_CACHE_TASK_TYPES
            else ""
        )
        print(
            f"  {task_type}: hit {counts['hit']} / miss {counts['miss']} / "
            f"error {counts['error']} / invalid {counts['invalid']}{skip_note}"
        )

    # 조합별 llm_request 평균 비용
    cost_by_key: dict[tuple, list[float]] = defaultdict(list)
    for e in llm_events:
        if e.get("estimated_cost_usd") is not None:
            cost_by_key[(e.get("agent_type"), e.get("task_type"))].append(
                e["estimated_cost_usd"]
            )

    saved = 0.0
    for e in llm_skip_hit:
        key = (e.get("agent_type"), e.get("task_type"))
        costs = cost_by_key.get(key)
        if costs:
            saved += _avg(costs)
    print(f"\n방지한 LLM 호출 수: {len(llm_skip_hit)}건 (latest_news_summary 제외)")
    print(
        f"절감 추정 비용: ${saved:.4f} (동일 agent_type·task_type의 평균 LLM 비용 기준 추정치)"
    )
    print()


def _print_stability(
    llm_events: list[dict], validation_error_events: list[dict]
) -> None:
    print("=== 안정성 ===")
    total = len(llm_events)
    if total == 0:
        print("요청 없음")
        return

    retried = [e for e in llm_events if e.get("json_retry_count", 0) > 0]
    fallback = [e for e in llm_events if e.get("fallback_used")]
    errors = [e for e in llm_events if e.get("status") == "error"]
    truncated = [
        e
        for e in llm_events
        if e.get("finish_reason") == "length"
        or e.get("primary_finish_reason") == "length"
    ]
    successful = total - len(errors)

    print(f"LLM 호출 성공률: {successful / total * 100:.1f}%")
    print(f"JSON 재질문율: {len(retried) / total * 100:.1f}%")
    print(f"fallback율: {len(fallback) / total * 100:.1f}%")
    print(f"에러율: {len(errors) / total * 100:.1f}%")
    print(f"응답 잘림률: {len(truncated) / total * 100:.1f}%")
    # LLM 호출은 성공했지만 이후 스키마 검증에 실패한 경우
    validation_rate = (
        len(validation_error_events) / successful * 100 if successful else 0.0
    )
    print(
        f"응답 스키마 검증 실패율: {validation_rate:.1f}% "
        f"({len(validation_error_events)}건, LLM 호출 성공 {successful}건 대비)"
    )
    print()


def _stats_for_rows(rows: list[dict]) -> dict[str, Any]:
    """rows: input_tokens/output_tokens/cost/latency_ms/status 키를 가진 정규화된 행 목록."""
    costs = [r["cost"] for r in rows if r.get("cost") is not None]
    latencies = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
    errors = [r for r in rows if r.get("status") == "error"]
    input_tokens = sum(r.get("input_tokens", 0) for r in rows)
    output_tokens = sum(r.get("output_tokens", 0) for r in rows)
    return {
        "calls": len(rows),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_cost": sum(costs),
        "avg_cost": _avg(costs),
        "cost_samples": len(costs),  # 비용이 실제로 기록된 건수
        "avg_latency": _avg(latencies),
        "p95_latency": _percentile(latencies, 0.95),
        "error_rate": len(errors) / len(rows) * 100 if rows else 0.0,
    }


def _group_stats(events: list[dict], key_fn) -> dict[Any, dict[str, Any]]:
    grouped: dict[Any, list[dict]] = defaultdict(list)
    for e in events:
        grouped[key_fn(e)].append(
            {
                "input_tokens": e.get("input_tokens", 0),
                "output_tokens": e.get("output_tokens", 0),
                "cost": e.get("estimated_cost_usd"),
                "latency_ms": e.get("latency_ms"),
                "status": e.get("status"),
            }
        )
    return {key: _stats_for_rows(rows) for key, rows in grouped.items()}


def _model_contributions(event: dict) -> list[dict]:
    """
    LLM 요청의 모델별 토큰·비용 기여분을 분리한다.

    fallback 발생 시 primary의 낭비 사용량과 fallback 사용량을 나눠 집계한다.
    개별 모델 latency는 분리할 수 없으므로 fallback 이벤트는 모델별 latency 집계에서 제외한다.
    """
    if not event.get("fallback_used"):
        return [
            {
                "model": event.get("actual_model") or event.get("model_name"),
                "input_tokens": event.get("input_tokens", 0),
                "output_tokens": event.get("output_tokens", 0),
                "cost": event.get("estimated_cost_usd"),
                "latency_ms": event.get("latency_ms"),
                "status": event.get("status"),
            }
        ]

    primary_model = event.get("requested_model")
    primary_in = event.get("primary_wasted_input_tokens", 0)
    primary_out = event.get("primary_wasted_output_tokens", 0)
    primary_cost = event.get("primary_wasted_cost_usd")

    fallback_model = event.get("actual_model") or event.get("model_name")
    total_cost = event.get("estimated_cost_usd")
    fallback_cost = (
        None
        if total_cost is None or primary_cost is None
        else total_cost - primary_cost
    )

    contributions = []
    if primary_model:
        contributions.append(
            {
                "model": primary_model,
                "input_tokens": primary_in,
                "output_tokens": primary_out,
                "cost": primary_cost,
                "latency_ms": None,
                "status": "error",
            }
        )
    contributions.append(
        {
            "model": fallback_model,
            "input_tokens": event.get("input_tokens", 0) - primary_in,
            "output_tokens": event.get("output_tokens", 0) - primary_out,
            "cost": fallback_cost,
            "latency_ms": None,
            "status": event.get("status"),
        }
    )
    return contributions


def _group_stats_by_model(events: list[dict]) -> dict[Any, dict[str, Any]]:
    grouped: dict[Any, list[dict]] = defaultdict(list)
    for e in events:
        for contribution in _model_contributions(e):
            model = contribution.pop("model")
            grouped[model].append(contribution)
    return {key: _stats_for_rows(rows) for key, rows in grouped.items()}


def _print_group(title: str, stats: dict[Any, dict[str, Any]]) -> None:
    print(f"=== {title} ===")
    if not stats:
        print("데이터 없음")
        print()
        return

    header = f"{'key':<32}{'calls':>7}{'in_tok':>10}{'out_tok':>10}{'total_$':>10}{'avg_$':>9}{'avg_ms':>9}{'p95_ms':>9}{'err%':>7}"
    print(header)
    for key, s in sorted(stats.items(), key=lambda kv: -kv[1]["calls"]):
        total_cost_str = (
            f"{s['total_cost']:>10.4f}" if s["cost_samples"] else f"{'N/A':>10}"
        )
        avg_cost_str = f"{s['avg_cost']:>9.4f}" if s["cost_samples"] else f"{'N/A':>9}"
        print(
            f"{key!s:<32}{s['calls']:>7}{s['input_tokens']:>10}{s['output_tokens']:>10}"
            f"{total_cost_str}{avg_cost_str}{s['avg_latency']:>9.0f}"
            f"{s['p95_latency']:>9.0f}{s['error_rate']:>6.1f}%"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 사용량 로그 집계")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("logs/llm_usage.jsonl"),
        help="집계할 JSONL 로그 경로",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="이 ISO8601 타임스탬프(UTC) 이후 이벤트만 집계 (예: 2026-08-07T00:00:00+00:00)",
    )
    parser.add_argument(
        "--include-eval",
        action="store_true",
        help="eval/ 스크립트(judge_*.py 등)가 남긴 평가용 호출도 집계에 포함한다. 기본값은 제외.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"로그 파일이 없습니다: {args.input}")
        return

    since_dt = None
    if args.since:
        try:
            since_dt = _parse_timestamp(args.since)
        except ValueError:
            print(
                f"--since 값을 파싱할 수 없습니다: {args.since!r} (ISO8601 형식이어야 함)",
                file=sys.stderr,
            )
            return

    events = _load_events(args.input)
    if since_dt is not None:
        filtered_events = []
        for e in events:
            timestamp = e.get("timestamp")
            if not timestamp:
                continue
            try:
                event_dt = _parse_timestamp(timestamp)
            except ValueError:
                continue
            if event_dt >= since_dt:
                filtered_events.append(e)
        events = filtered_events
    if not args.include_eval:
        events = [e for e in events if e.get("task_type") not in EVAL_TASK_TYPES]
    llm_events = [e for e in events if e["event_type"] == "llm_request"]
    cache_events = [e for e in events if e["event_type"] == "cache_event"]
    validation_error_events = [
        e for e in events if e["event_type"] == "llm_validation_error"
    ]

    _print_overall(llm_events)
    _print_cache(cache_events, llm_events)
    _print_stability(llm_events, validation_error_events)
    _print_group("모델별", _group_stats_by_model(llm_events))
    _print_group("사원별", _group_stats(llm_events, lambda e: e.get("agent_type")))
    _print_group("작업별", _group_stats(llm_events, lambda e: e.get("task_type")))


if __name__ == "__main__":
    main()
