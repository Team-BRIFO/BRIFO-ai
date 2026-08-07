"""
briefing_api.py의 파싱 실패 시 LLM 원문 응답 로깅 테스트.
파싱/검증 실패의 원인(빈 응답·잘림·형식 오류 등)을 사후에 특정할 수 있도록
_record_parse_failure가 llm_response의 원문 content를 로그로 남기는지 확인한다.
"""

import unittest
from unittest.mock import AsyncMock, patch

from app.core.agents import briefing_api


class RecordParseFailureLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_logs_raw_llm_content_on_parse_failure(self):
        llm_response = {
            "model": "test-model",
            "fallback_used": False,
            "content": '{"headline": "잘린 응답',
        }

        with (
            patch.object(briefing_api, "record_usage", new=AsyncMock()),
            self.assertLogs(briefing_api._logger, level="ERROR") as logs,
        ):
            await briefing_api._record_parse_failure(llm_response, "ROOKIE")

        self.assertTrue(
            any('{"headline": "잘린 응답' in message for message in logs.output)
        )

    async def test_records_parse_failure_as_validation_error_not_llm_request(self):
        llm_response = {
            "model": "test-model",
            "fallback_used": False,
            "content": "이것은 JSON이 아닙니다.",
        }
        record_usage_mock = AsyncMock()

        with patch.object(briefing_api, "record_usage", record_usage_mock):
            await briefing_api._record_parse_failure(llm_response, "ROOKIE")

        record_usage_mock.assert_awaited_once()
        _, kwargs = record_usage_mock.call_args
        self.assertEqual(kwargs["event_type"], "llm_validation_error")


if __name__ == "__main__":
    unittest.main()
