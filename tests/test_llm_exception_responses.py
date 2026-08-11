"""
BrifoAIException 핸들러(app/main.py)가 LLM 관련 4개 예외의
status_code/code/message를 HTTP 응답에 그대로 전달하는지 검증한다.
- LLMTimeout, RateLimit, AllModelsFailed, InvalidLLMResponse가
  서로 다른 code를 가져야 하며(#36), 각 응답 바디에 그대로 반영돼야 한다.
"""

import json
import unittest

from app.exceptions import AllModelsFailed, InvalidLLMResponse, LLMTimeout, RateLimit
from app.main import brifo_ai_exception_handler


class LLMExceptionResponseContractTests(unittest.IsolatedAsyncioTestCase):
    async def _assert_response_matches_exception(self, exc):
        response = await brifo_ai_exception_handler(None, exc)
        self.assertEqual(response.status_code, exc.status_code)
        body = json.loads(response.body)
        self.assertEqual(
            body, {"isSuccess": False, "code": exc.code, "message": exc.message}
        )

    async def test_llm_timeout_response_matches_exception(self):
        await self._assert_response_matches_exception(LLMTimeout())

    async def test_rate_limit_response_matches_exception(self):
        await self._assert_response_matches_exception(RateLimit())

    async def test_all_models_failed_response_matches_exception(self):
        await self._assert_response_matches_exception(AllModelsFailed())

    async def test_invalid_llm_response_matches_exception(self):
        await self._assert_response_matches_exception(InvalidLLMResponse())

    def test_all_four_codes_are_distinct(self):
        codes = {
            exc_cls().code
            for exc_cls in (LLMTimeout, RateLimit, AllModelsFailed, InvalidLLMResponse)
        }
        self.assertEqual(len(codes), 4)


if __name__ == "__main__":
    unittest.main()
