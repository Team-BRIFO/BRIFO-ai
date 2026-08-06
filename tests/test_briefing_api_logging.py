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

        self.assertTrue(any('{"headline": "잘린 응답' in message for message in logs.output))


if __name__ == "__main__":
    unittest.main()