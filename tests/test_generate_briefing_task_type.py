"""
briefing_api.generate_briefing()의 task_type 파라미터 테스트.
회귀 테스트: eval/run_agent_eval.py가 generate_briefing()을 직접 호출하면
call_llm에 항상 task_type="briefing"이 찍혀서, 실서비스 브리핑 요청과 구분 없이
집계되던 문제. task_type을 선택적으로 넘길 수 있어야 한다.
"""

import unittest
from unittest.mock import AsyncMock, patch

from app.core.agents import briefing_api
from app.exceptions import InvalidLLMResponse
from app.schemas.briefing import NewsInput


def _news_cards() -> list[NewsInput]:
    return [NewsInput(cardId="c1", newsId="n1", headline="h", points=["p1", "p2"])]


def _llm_response() -> dict:
    return {
        "model": "test-model",
        "fallback_used": False,
        "content": (
            '{"headline": "h", "summary": "s", "contentText": "c", "oneLiner": "o", '
            '"direction": "UP", "confidenceRate": 50}'
        ),
    }


class GenerateBriefingTaskTypeTests(unittest.IsolatedAsyncioTestCase):
    async def test_defaults_to_briefing_task_type(self):
        call_llm_mock = AsyncMock(return_value=_llm_response())
        with patch.object(briefing_api, "call_llm", call_llm_mock):
            await briefing_api.generate_briefing(_news_cards(), "ROOKIE", "1-3")

        _, kwargs = call_llm_mock.call_args
        self.assertEqual(kwargs["task_type"], "briefing")

    async def test_forwards_custom_task_type(self):
        call_llm_mock = AsyncMock(return_value=_llm_response())
        with patch.object(briefing_api, "call_llm", call_llm_mock):
            await briefing_api.generate_briefing(
                _news_cards(), "ROOKIE", "1-3", task_type="briefing_eval"
            )

        _, kwargs = call_llm_mock.call_args
        self.assertEqual(kwargs["task_type"], "briefing_eval")

    async def test_parse_failure_is_logged_with_the_same_task_type(self):
        llm_response = {**_llm_response(), "content": "이것은 JSON이 아닙니다."}
        call_llm_mock = AsyncMock(return_value=llm_response)
        record_usage_mock = AsyncMock()

        with (
            patch.object(briefing_api, "call_llm", call_llm_mock),
            patch.object(briefing_api, "record_usage", record_usage_mock),
        ):
            with self.assertRaises(InvalidLLMResponse):
                await briefing_api.generate_briefing(
                    _news_cards(), "ROOKIE", "1-3", task_type="briefing_eval"
                )

        record_usage_mock.assert_awaited_once()
        _, kwargs = record_usage_mock.call_args
        self.assertEqual(kwargs["task_type"], "briefing_eval")


if __name__ == "__main__":
    unittest.main()
