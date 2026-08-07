"""
cache.py의 캐시 hit/miss/error 계측(record_cache_event) 테스트.
"""

import unittest
from unittest.mock import AsyncMock, patch

from app.infra import cache


def _fake_redis_client(get_return=None, get_side_effect=None):
    client = AsyncMock()
    if get_side_effect is not None:
        client.get.side_effect = get_side_effect
    else:
        client.get.return_value = get_return
    return client


class GetBriefingCacheEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_miss_when_key_not_found(self):
        record_event_mock = AsyncMock()
        with (
            patch.object(
                cache, "get_redis_client", return_value=_fake_redis_client(None)
            ),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_briefing("news_1", "ROOKIE", "1-3")

        self.assertIsNone(result)
        record_event_mock.assert_awaited_once()
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "miss")
        self.assertEqual(kwargs["agent_type"], "ROOKIE")
        self.assertEqual(kwargs["task_type"], "briefing")

    async def test_records_hit_when_valid_value_found(self):
        raw = (
            '{"agent_type": "ROOKIE", "direction": "UP", "confidence_rate": 50, '
            '"headline": "h", "summary": "s", "content_text": "c", "one_liner": "o", '
            '"model_name": "m", "cached": false}'
        )
        record_event_mock = AsyncMock()
        with (
            patch.object(
                cache, "get_redis_client", return_value=_fake_redis_client(raw)
            ),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_briefing("news_1", "ROOKIE", "1-3")

        self.assertIsNotNone(result)
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "hit")

    async def test_records_error_when_redis_raises(self):
        record_event_mock = AsyncMock()
        with (
            patch.object(
                cache,
                "get_redis_client",
                return_value=_fake_redis_client(
                    get_side_effect=ConnectionError("down")
                ),
            ),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_briefing("news_1", "ROOKIE", "1-3")

        self.assertIsNone(result)
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "error")

    async def test_records_invalid_when_cached_value_is_corrupted(self):
        fake_client = _fake_redis_client("이건 유효한 JSON이 아닙니다")
        record_event_mock = AsyncMock()
        with (
            patch.object(cache, "get_redis_client", return_value=fake_client),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_briefing("news_1", "ROOKIE", "1-3")

        self.assertIsNone(result)
        fake_client.delete.assert_awaited_once()
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "invalid")


class GetPersonalCacheEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_hit_and_passes_agent_type(self):
        record_event_mock = AsyncMock()
        with (
            patch.object(
                cache, "get_redis_client", return_value=_fake_redis_client("comment")
            ),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_personal("user_1", "briefing_1", "TANKER")

        self.assertEqual(result, "comment")
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "hit")
        self.assertEqual(kwargs["agent_type"], "TANKER")
        self.assertEqual(kwargs["task_type"], "personal")


def _card_news_json(news_id: str) -> str:
    return (
        f'{{"news_id": "{news_id}", "card_news": [{{'
        '"headline": "h", "points": ["p1", "p2", "p3"], '
        '"keywords": ["용어"], '
        '"terms": [{"surface": "용어", "term": "정식용어", "definition": "설명"}]'
        "}]}"
    )


class GetSummaryCacheEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_miss_when_key_not_found(self):
        record_event_mock = AsyncMock()
        with (
            patch.object(
                cache, "get_redis_client", return_value=_fake_redis_client(None)
            ),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_summary("news_1", [])

        self.assertIsNone(result)
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "miss")
        self.assertEqual(kwargs["agent_type"], "SUMMARY")
        self.assertEqual(kwargs["task_type"], "news_summary")

    async def test_records_hit_when_valid_value_found(self):
        record_event_mock = AsyncMock()
        with (
            patch.object(
                cache,
                "get_redis_client",
                return_value=_fake_redis_client(_card_news_json("news_1")),
            ),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_summary("news_1", [])

        self.assertIsNotNone(result)
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "hit")

    async def test_records_error_when_redis_raises(self):
        record_event_mock = AsyncMock()
        with (
            patch.object(
                cache,
                "get_redis_client",
                return_value=_fake_redis_client(
                    get_side_effect=ConnectionError("down")
                ),
            ),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_summary("news_1", [])

        self.assertIsNone(result)
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "error")


class NewsIdMismatchTests(unittest.IsolatedAsyncioTestCase):
    """
    캐시된 카드뉴스의 news_id가 조회하려던 news_id와 다르면, 엉뚱한 뉴스가 브리핑에
    섞이는 걸 막기 위해 해당 키를 삭제하고 miss로 처리해야 한다.
    """

    async def test_get_summary_with_mismatched_news_id_is_deleted_and_treated_as_miss(
        self,
    ):
        fake_client = _fake_redis_client(_card_news_json("other_news"))
        record_event_mock = AsyncMock()
        with (
            patch.object(cache, "get_redis_client", return_value=fake_client),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_summary("news_1", [])

        self.assertIsNone(result)
        fake_client.delete.assert_awaited_once()
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "miss")

    async def test_get_latest_summary_with_mismatched_news_id_is_deleted_and_returns_none(
        self,
    ):
        fake_client = _fake_redis_client(_card_news_json("other_news"))
        with (
            patch.object(cache, "get_redis_client", return_value=fake_client),
            patch.object(cache, "record_cache_event", new=AsyncMock()),
        ):
            result = await cache.get_latest_summary("news_1")

        self.assertIsNone(result)
        fake_client.delete.assert_awaited_once()

    async def test_get_latest_summary_delete_failure_does_not_break_the_lookup(self):
        fake_client = _fake_redis_client(_card_news_json("other_news"))
        fake_client.delete.side_effect = ConnectionError("delete failed")
        with (
            patch.object(cache, "get_redis_client", return_value=fake_client),
            patch.object(cache, "record_cache_event", new=AsyncMock()),
        ):
            result = await cache.get_latest_summary("news_1")

        self.assertIsNone(result)


class GetLatestSummaryTests(unittest.IsolatedAsyncioTestCase):
    """
    브리핑 생성마다 카드당 1번씩 실제로 호출되는 캐시 조회라, 여기도 get_summary처럼
    hit/miss/error가 기록돼야 Valkey 전체 효과(캐시 조회 건수·적중률)가 정확히 잡힌다.
    """

    async def test_records_miss_when_key_not_found(self):
        record_event_mock = AsyncMock()
        with (
            patch.object(
                cache, "get_redis_client", return_value=_fake_redis_client(None)
            ),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_latest_summary("news_1")

        self.assertIsNone(result)
        record_event_mock.assert_awaited_once()
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "miss")
        self.assertEqual(kwargs["agent_type"], "SUMMARY")
        self.assertEqual(kwargs["task_type"], "latest_news_summary")

    async def test_records_hit_when_news_id_matches(self):
        record_event_mock = AsyncMock()
        with (
            patch.object(
                cache,
                "get_redis_client",
                return_value=_fake_redis_client(_card_news_json("news_1")),
            ),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_latest_summary("news_1")

        self.assertIsNotNone(result)
        self.assertEqual(result.news_id, "news_1")
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "hit")

    async def test_records_error_when_redis_raises(self):
        record_event_mock = AsyncMock()
        with (
            patch.object(
                cache,
                "get_redis_client",
                return_value=_fake_redis_client(
                    get_side_effect=ConnectionError("down")
                ),
            ),
            patch.object(cache, "record_cache_event", record_event_mock),
        ):
            result = await cache.get_latest_summary("news_1")

        self.assertIsNone(result)
        _, kwargs = record_event_mock.call_args
        self.assertEqual(kwargs["cache_status"], "error")


if __name__ == "__main__":
    unittest.main()
