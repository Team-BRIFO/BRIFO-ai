"""
app/schemas/briefing.py의 CommonBriefing 검증 규칙 테스트.
- confidence_rate: 0~100 범위만 허용
"""

import unittest

from pydantic import ValidationError

from app.schemas.briefing import CommonBriefing


def _make_briefing(confidence_rate: int = 50) -> dict:
    return {
        "agent_type": "ROOKIE",
        "direction": "UP",
        "confidence_rate": confidence_rate,
        "headline": "헤드라인",
        "summary": "요약",
        "content_text": "본문",
        "one_liner": "한마디",
        "model_name": "test-model",
        "cached": False,
    }


class CommonBriefingConfidenceRateTests(unittest.TestCase):
    def test_boundary_values_are_accepted(self):
        for value in (0, 100):
            with self.subTest(confidence_rate=value):
                briefing = CommonBriefing(**_make_briefing(confidence_rate=value))
                self.assertEqual(briefing.confidence_rate, value)

    def test_out_of_range_values_are_rejected(self):
        for value in (-1, 101):
            with self.subTest(confidence_rate=value):
                with self.assertRaises(ValidationError):
                    CommonBriefing(**_make_briefing(confidence_rate=value))


if __name__ == "__main__":
    unittest.main()