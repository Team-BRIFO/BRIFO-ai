"""
app/schemas/briefing.py의 검증 규칙 테스트.
- CommonBriefing.confidence_rate: 0~100 범위만 허용
- RecentDecision.confidence: 1~5 범위만 허용
- BriefingGenerateRequest.level_range: "1-3"/"4-6"/"7-10"만 허용
"""

import unittest

from pydantic import ValidationError

from app.schemas.briefing import BriefingGenerateRequest, CommonBriefing, RecentDecision


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


def _make_recent_decision(confidence: int = 3) -> dict:
    return {
        "stockName": "삼성전자",
        "direction": "UP",
        "confidence": confidence,
        "isCorrect": True,
        "actualChange": 1.5,
    }


def _make_briefing_request(level_range: str = "1-3") -> dict:
    return {
        "newsCard": [
            {"cardId": "card-1", "newsId": "news-1", "headline": "헤드라인", "points": ["포인트"]}
        ],
        "userId": "user-1",
        "agentTypes": ["ROOKIE"],
        "levelRange": level_range,
        "recentDecisions": [],
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


class RecentDecisionConfidenceTests(unittest.TestCase):
    def test_boundary_values_are_accepted(self):
        for value in (1, 5):
            with self.subTest(confidence=value):
                decision = RecentDecision(**_make_recent_decision(confidence=value))
                self.assertEqual(decision.confidence, value)

    def test_out_of_range_values_are_rejected(self):
        for value in (0, 6):
            with self.subTest(confidence=value):
                with self.assertRaises(ValidationError):
                    RecentDecision(**_make_recent_decision(confidence=value))


class BriefingGenerateRequestLevelRangeTests(unittest.TestCase):
    def test_allowed_level_ranges_are_accepted(self):
        for value in ("1-3", "4-6", "7-10"):
            with self.subTest(level_range=value):
                request = BriefingGenerateRequest(**_make_briefing_request(level_range=value))
                self.assertEqual(request.level_range, value)

    def test_unsupported_level_range_is_rejected(self):
        for value in ("0-2", "11-15", ""):
            with self.subTest(level_range=value):
                with self.assertRaises(ValidationError):
                    BriefingGenerateRequest(**_make_briefing_request(level_range=value))


if __name__ == "__main__":
    unittest.main()