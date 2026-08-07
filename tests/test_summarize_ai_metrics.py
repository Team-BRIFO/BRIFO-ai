"""
scripts/summarize_ai_metrics.py의 _percentile()·_model_contributions()·
_print_stability() 검증 실패율·eval 트래픽 제외 계산 테스트.
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.summarize_ai_metrics import (
    EVAL_TASK_TYPES,
    _model_contributions,
    _print_cache,
    _print_stability,
    _percentile,
    main,
)


class PercentileTests(unittest.TestCase):
    def test_p50_uses_nearest_rank_for_two_values(self):
        # 통계적 중앙값 (10+20)/2=15와는 다른 값이며, 의도된 동작이다
        self.assertEqual(_percentile([10, 20], 0.50), 10)

    def test_p50_of_three_values_matches_middle_value(self):
        self.assertEqual(_percentile([10, 20, 30], 0.50), 20)

    def test_empty_list_returns_zero(self):
        self.assertEqual(_percentile([], 0.50), 0.0)

    def test_p95_of_ordered_values(self):
        values = list(range(1, 28))  # 1..27
        self.assertEqual(_percentile(values, 0.95), 26)


class ModelContributionsTests(unittest.TestCase):
    def test_no_fallback_attributes_everything_to_actual_model(self):
        event = {
            "fallback_used": False,
            "actual_model": "model-a",
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost_usd": 0.01,
            "latency_ms": 1000,
            "status": "success",
        }
        contributions = _model_contributions(event)
        self.assertEqual(len(contributions), 1)
        self.assertEqual(contributions[0]["model"], "model-a")
        self.assertEqual(contributions[0]["cost"], 0.01)

    def test_fallback_splits_cost_and_tokens_between_requested_and_actual_model(self):
        event = {
            "fallback_used": True,
            "requested_model": "claude",
            "actual_model": "gpt",
            "input_tokens": 300,
            "output_tokens": 150,
            "estimated_cost_usd": 0.03,
            "primary_wasted_input_tokens": 100,
            "primary_wasted_output_tokens": 50,
            "primary_wasted_cost_usd": 0.01,
            "latency_ms": 2000,
            "status": "success",
        }
        contributions = _model_contributions(event)
        by_model = {c["model"]: c for c in contributions}

        self.assertEqual(by_model["claude"]["input_tokens"], 100)
        self.assertEqual(by_model["claude"]["output_tokens"], 50)
        self.assertAlmostEqual(by_model["claude"]["cost"], 0.01)
        self.assertEqual(by_model["claude"]["status"], "error")

        self.assertEqual(by_model["gpt"]["input_tokens"], 200)
        self.assertEqual(by_model["gpt"]["output_tokens"], 100)
        self.assertAlmostEqual(by_model["gpt"]["cost"], 0.02)
        self.assertEqual(by_model["gpt"]["status"], "success")

        # latency_ms(2000)는 primary 실패 시간까지 포함된 전체 소요시간이라
        # fallback 모델(gpt) 혼자만의 속도가 아니므로, 모델별 latency 집계에서 제외되어야 한다
        self.assertIsNone(by_model["claude"]["latency_ms"])
        self.assertIsNone(by_model["gpt"]["latency_ms"])


class ValidationErrorRateTests(unittest.TestCase):
    def test_denominator_is_successful_llm_requests_only(self):
        llm_events = [
            {"latency_ms": 100, "status": "success", "json_retry_count": 0, "fallback_used": False}
            for _ in range(42)
        ]
        validation_error_events = [{}] * 3

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_stability(llm_events, validation_error_events)
        output = buf.getvalue()

        self.assertIn("응답 스키마 검증 실패율: 7.1%", output)


class EvalTrafficExclusionTests(unittest.TestCase):
    def _write_log(self, events: list[dict]) -> Path:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        path = Path(tmp_dir.name) / "usage.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        return path

    def _base_event(self, task_type: str) -> dict:
        return {
            "event_type": "llm_request",
            "task_type": task_type,
            "agent_type": "ROOKIE",
            "requested_model": "m",
            "actual_model": "m",
            "model_name": "m",
            "input_tokens": 10,
            "output_tokens": 5,
            "estimated_cost_usd": 0.001,
            "latency_ms": 100,
            "fallback_used": False,
            "json_retry_count": 0,
            "finish_reason": "stop",
            "status": "success",
        }

    def test_eval_task_types_excluded_by_default(self):
        events = [self._base_event("briefing"), self._base_event("briefing_content_judge")]
        self.assertIn("briefing_content_judge", EVAL_TASK_TYPES)
        path = self._write_log(events)

        buf = io.StringIO()
        with (
            patch.object(sys, "argv", ["summarize_ai_metrics.py", "--input", str(path)]),
            redirect_stdout(buf),
        ):
            main()

        self.assertIn("논리 요청 수: 1", buf.getvalue())

    def test_briefing_eval_task_type_excluded_by_default(self):
        events = [self._base_event("briefing"), self._base_event("briefing_eval")]
        self.assertIn("briefing_eval", EVAL_TASK_TYPES)
        path = self._write_log(events)

        buf = io.StringIO()
        with (
            patch.object(sys, "argv", ["summarize_ai_metrics.py", "--input", str(path)]),
            redirect_stdout(buf),
        ):
            main()

        self.assertIn("논리 요청 수: 1", buf.getvalue())

    def test_include_eval_flag_includes_eval_task_types(self):
        events = [self._base_event("briefing"), self._base_event("briefing_content_judge")]
        path = self._write_log(events)

        buf = io.StringIO()
        with (
            patch.object(
                sys, "argv", ["summarize_ai_metrics.py", "--input", str(path), "--include-eval"]
            ),
            redirect_stdout(buf),
        ):
            main()

        self.assertIn("논리 요청 수: 2", buf.getvalue())


class CacheHitRateSeparationTests(unittest.TestCase):
    def _cache_event(self, task_type: str, cache_status: str) -> dict:
        return {
            "event_type": "cache_event",
            "task_type": task_type,
            "agent_type": "ROOKIE",
            "cache_status": cache_status,
            "cache_lookup_ms": 1.0,
            "latency_ms": 1.0,
        }

    def _llm_event(self, task_type: str, cost: float) -> dict:
        return {
            "event_type": "llm_request",
            "task_type": task_type,
            "agent_type": "ROOKIE",
            "estimated_cost_usd": cost,
        }

    def test_latest_news_summary_hit_excluded_from_llm_skipping_rate_and_savings(self):
        cache_events = [
            self._cache_event("briefing", "hit"),
            self._cache_event("briefing", "miss"),
            self._cache_event("latest_news_summary", "hit"),
            self._cache_event("latest_news_summary", "hit"),
            self._cache_event("latest_news_summary", "hit"),
            self._cache_event("latest_news_summary", "miss"),
        ]
        llm_events = [self._llm_event("briefing", 0.02)]

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_cache(cache_events, llm_events)
        output = buf.getvalue()

        self.assertIn("전체 캐시 조회 적중률: 66.7%", output)
        self.assertIn("LLM 호출 생략형 캐시 적중률: 50.0%", output)
        self.assertIn("방지한 LLM 호출 수: 1건", output)
        self.assertIn("절감 추정 비용: $0.0200", output)
        self.assertIn("latest_news_summary: hit 3 / miss 1", output)


class CacheErrorInvalidSeparationTests(unittest.TestCase):
    """
    회귀 테스트: Valkey 연결 실패(error)와 저장된 값이 손상된 경우(invalid)를 하나의
    error rate로 합치면, 인프라는 멀쩡한데 오래된 캐시 값 하나 때문에 "Valkey 장애율"이
    올라간 것처럼 보인다. 원인 파악을 위해 둘을 분리해서 보여줘야 한다.
    """

    def _cache_event(self, cache_status: str) -> dict:
        return {
            "event_type": "cache_event",
            "task_type": "briefing",
            "agent_type": "ROOKIE",
            "cache_status": cache_status,
            "cache_lookup_ms": 1.0,
            "latency_ms": 1.0,
        }

    def test_error_and_invalid_rates_are_reported_separately(self):
        cache_events = [
            self._cache_event("hit"),
            self._cache_event("miss"),
            self._cache_event("error"),
            self._cache_event("invalid"),
        ]

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_cache(cache_events, [])
        output = buf.getvalue()

        self.assertIn("hit: 1  miss: 1  error: 1  invalid: 1", output)
        self.assertIn("Valkey 조회 오류율: 25.0%", output)
        self.assertIn("캐시 데이터 무효율: 25.0%", output)
        self.assertIn("전체 캐시 조회 적중률: 50.0%", output)


if __name__ == "__main__":
    unittest.main()
