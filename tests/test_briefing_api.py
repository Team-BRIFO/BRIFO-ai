"""
POST /ai/briefing/generate API 레벨 검증 테스트.
- levelRange가 허용되지 않은 값이면 RequestValidationError -> COMMON400(400)으로 응답하는지 확인
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


class GenerateBriefingLevelRangeApiTests(unittest.TestCase):
    def test_unsupported_level_range_returns_common400(self):
        for value in ("0-2", "11-15", ""):
            with self.subTest(level_range=value):
                response = client.post(
                    "/ai/briefing/generate",
                    json=_make_briefing_request(level_range=value),
                    headers={"AI_INTERNAL_API_KEY": TEST_INTERNAL_API_KEY},
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "COMMON400")


if __name__ == "__main__":
    unittest.main()