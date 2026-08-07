"""
llm_request로 다시 기록하면 집계 스크립트가 같은 호출을 요청 2건으로 이중 계산한다.
"""

import unittest
from unittest.mock import AsyncMock, patch

from app.core.services import summary_service


class RecordParseFailureLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_parse_failure_as_validation_error_not_llm_request(self):
        llm_response = {
            "model": "test-model",
            "fallback_used": False,
            "content": "이것은 JSON이 아닙니다.",
        }
        record_usage_mock = AsyncMock()

        with patch.object(summary_service, "record_usage", record_usage_mock):
            await summary_service._record_parse_failure(llm_response)

        record_usage_mock.assert_awaited_once()
        _, kwargs = record_usage_mock.call_args
        self.assertEqual(kwargs["event_type"], "llm_validation_error")


if __name__ == "__main__":
    unittest.main()
