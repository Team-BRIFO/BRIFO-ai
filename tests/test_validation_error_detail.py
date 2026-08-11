"""
RequestValidationError 세분화 테스트 (이슈 #36).
- JSON 파싱 실패 -> COMMON400_INVALID_JSON
- 필수 필드 누락 -> COMMON400_MISSING_FIELD (누락된 필드명 포함)
- 타입 불일치 -> COMMON400_INVALID_TYPE (필드명 포함, *_type/*_parsing 모두 포함)
- 그 외(예: 허용되지 않은 값) -> 기존과 동일하게 COMMON400 유지
"""

import unittest

from fastapi.testclient import TestClient

from app.config.settings import Settings, get_settings
from app.main import app
from tests.test_briefing_schema import _make_briefing_request

TEST_INTERNAL_API_KEY = "test-internal-key"


def _override_settings() -> Settings:
    return Settings(
        **{
            "AI_INTERNAL_API_KEY": TEST_INTERNAL_API_KEY,
            "openrouter_api_key": "test-openrouter-key",
            "redis_url": "redis://localhost:6379/0",
        }
    )


app.dependency_overrides[get_settings] = _override_settings
client = TestClient(app)

HEADERS = {"AI_INTERNAL_API_KEY": TEST_INTERNAL_API_KEY}


class InvalidJsonBodyTests(unittest.TestCase):
    def test_broken_json_body_returns_invalid_json_code(self):
        response = client.post(
            "/ai/news/summarize",
            content=b'{"newsId": "x", "stockName": broken}',
            headers={**HEADERS, "Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "COMMON400_INVALID_JSON")
        self.assertIn("JSON", body["message"])


class MissingRequiredFieldTests(unittest.TestCase):
    def test_missing_fields_returns_missing_field_code_with_field_names(self):
        response = client.post(
            "/ai/news/summarize",
            json={"newsId": "news-1"},
            headers=HEADERS,
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "COMMON400_MISSING_FIELD")
        self.assertIn("stockName", body["message"])
        self.assertIn("newsContent", body["message"])


class InvalidFieldTypeTests(unittest.TestCase):
    def test_wrong_type_returns_invalid_type_code_with_field_name(self):
        response = client.post(
            "/ai/news/summarize",
            json={
                "newsId": "news-1",
                "stockName": "삼성전자",
                "newsContent": "본문",
                "excludeTerms": "not-a-list",
            },
            headers=HEADERS,
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "COMMON400_INVALID_TYPE")
        self.assertIn("excludeTerms", body["message"])

    def test_unparseable_value_returns_invalid_type_code_with_field_name(self):
        """숫자로 변환 불가능한 문자열(int_parsing)도 타입 오류로 분류돼야 한다."""
        request_body = _make_briefing_request()
        request_body["recentDecisions"] = [
            {
                "stockName": "삼성전자",
                "direction": "UP",
                "confidence": "abc",
                "isCorrect": True,
                "actualChange": 1.0,
            }
        ]
        response = client.post(
            "/ai/briefing/generate",
            json=request_body,
            headers=HEADERS,
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], "COMMON400_INVALID_TYPE")
        self.assertIn("confidence", body["message"])


class UnsupportedValueFallsBackToCommon400Tests(unittest.TestCase):
    def test_unsupported_level_range_still_returns_common400(self):
        response = client.post(
            "/ai/briefing/generate",
            json=_make_briefing_request(level_range="0-2"),
            headers=HEADERS,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "COMMON400")


if __name__ == "__main__":
    unittest.main()
