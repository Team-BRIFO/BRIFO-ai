"""
app/schemas/news.py의 CardNewsItem/CardNewsResult 검증 규칙 테스트.
- CardNewsItem: points 정확히 3개, keywords/terms 개수 일치
- CardNewsResult: card_news 정확히 1개 (min_length/max_length=1)
"""

import unittest

from pydantic import ValidationError

from app.schemas.news import CardNewsItem, CardNewsResult, Term


def _make_item(
    points_count: int = 3, keywords_count: int = 2, terms_count: int = 2
) -> dict:
    return {
        "headline": "헤드라인",
        "points": [f"포인트{i}" for i in range(points_count)],
        "keywords": [f"용어{i}" for i in range(keywords_count)],
        "terms": [
            {"surface": f"용어{i}", "term": f"정식용어{i}", "definition": f"설명{i}"}
            for i in range(terms_count)
        ],
    }


class CardNewsItemTests(unittest.TestCase):
    def test_valid_item_with_3_points_and_matching_keywords_terms(self):
        item = CardNewsItem(
            **_make_item(points_count=3, keywords_count=2, terms_count=2)
        )
        self.assertEqual(len(item.points), 3)
        self.assertEqual(len(item.keywords), len(item.terms))

    def test_points_not_exactly_3_is_rejected(self):
        for count in (2, 4):
            with self.subTest(points_count=count):
                with self.assertRaises(ValidationError):
                    CardNewsItem(**_make_item(points_count=count))

    def test_keywords_terms_length_mismatch_is_rejected(self):
        with self.assertRaises(ValidationError):
            CardNewsItem(**_make_item(keywords_count=2, terms_count=3))

    def test_empty_keywords_is_rejected(self):
        with self.assertRaises(ValidationError):
            CardNewsItem(**_make_item(keywords_count=0, terms_count=0))

    def test_keyword_not_matching_term_surface_at_same_index_is_rejected(self):
        item = _make_item(keywords_count=1, terms_count=1)
        item["keywords"] = ["영업이익"]
        item["terms"] = [{"surface": "매출", "term": "매출액", "definition": "설명"}]
        with self.assertRaises(ValidationError):
            CardNewsItem(**item)


class CardNewsResultTests(unittest.TestCase):
    def _item(self) -> CardNewsItem:
        return CardNewsItem(**_make_item())

    def test_exactly_one_card_is_accepted(self):
        result = CardNewsResult(news_id="news-1", card_news=[self._item()])
        self.assertEqual(len(result.card_news), 1)

    def test_zero_cards_is_rejected(self):
        with self.assertRaises(ValidationError):
            CardNewsResult(news_id="news-1", card_news=[])

    def test_two_or_more_cards_is_rejected(self):
        with self.assertRaises(ValidationError):
            CardNewsResult(news_id="news-1", card_news=[self._item(), self._item()])


if __name__ == "__main__":
    unittest.main()
