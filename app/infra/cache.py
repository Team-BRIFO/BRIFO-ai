"""
Redis 캐싱
공통 분석 + 개인화 레이어 코멘트 - TTL 24h
카드뉴스 요약 - TTL 24h
"""

import logging

from pydantic import ValidationError

from app.infra.redis_client import get_redis_client
from app.schemas.briefing import CommonBriefing
from app.schemas.news import CardNewsResult

_logger = logging.getLogger(__name__)

_TTL_SECONDS = 24 * 60 * 60


# 공통 분석: briefing:{news_id}:{agent_type}:{level_range} — 전역 공유
def _briefing_key(news_id: str, agent_type: str, level_range: str) -> str:
    return f"briefing:{news_id}:{agent_type}:{level_range}"


# 개인화 레이어: briefing:personal:{user_id}:{briefing_id} — 유저별
def _personal_key(user_id: str, briefing_id: str) -> str:
    return f"briefing:personal:{user_id}:{briefing_id}"


# 카드뉴스 요약: summary:{news_id} — 전역 공유
def _summary_key(news_id: str) -> str:
    return f"summary:{news_id}"


async def get_briefing(
    news_id: str, agent_type: str, level_range: str
) -> CommonBriefing | None:
    key = _briefing_key(news_id, agent_type, level_range)
    try:
        client = get_redis_client()
        raw = await client.get(key)
        if raw is None:
            return None
        return CommonBriefing.model_validate_json(raw)
    except ValidationError:
        _logger.exception(
            "공통 분석 캐시 값이 손상되어 삭제하고 캐시 미스로 처리합니다."
        )
        await _delete_key(key)
        return None
    except Exception:
        _logger.exception("공통 분석 캐시 조회 실패, 캐시 미스로 처리합니다.")
        return None


async def set_briefing(
    news_id: str, agent_type: str, level_range: str, value: CommonBriefing
) -> None:
    try:
        client = get_redis_client()
        await client.set(
            _briefing_key(news_id, agent_type, level_range),
            value.model_dump_json(),
            ex=_TTL_SECONDS,
        )
    except Exception:
        _logger.exception("공통 분석 캐시 저장 실패, 캐시 없이 진행합니다.")


async def get_personal(user_id: str, briefing_id: str) -> str | None:
    try:
        client = get_redis_client()
        return await client.get(_personal_key(user_id, briefing_id))
    except Exception:
        _logger.exception("개인화 코멘트 캐시 조회 실패, 캐시 미스로 처리합니다.")
        return None


async def set_personal(user_id: str, briefing_id: str, value: str) -> None:
    try:
        client = get_redis_client()
        await client.set(_personal_key(user_id, briefing_id), value, ex=_TTL_SECONDS)
    except Exception:
        _logger.exception("개인화 코멘트 캐시 저장 실패, 캐시 없이 진행합니다.")


async def get_summary(news_id: str) -> CardNewsResult | None:
    key = _summary_key(news_id)
    try:
        client = get_redis_client()
        raw = await client.get(key)
        if raw is None:
            return None
        return CardNewsResult.model_validate_json(raw)
    except ValidationError:
        _logger.exception(
            "카드뉴스 요약 캐시 값이 손상되어 삭제하고 캐시 미스로 처리합니다."
        )
        await _delete_key(key)
        return None
    except Exception:
        _logger.exception("카드뉴스 요약 캐시 조회 실패, 캐시 미스로 처리합니다.")
        return None


async def set_summary(news_id: str, value: CardNewsResult) -> None:
    try:
        client = get_redis_client()
        await client.set(
            _summary_key(news_id), value.model_dump_json(), ex=_TTL_SECONDS
        )
    except Exception:
        _logger.exception("카드뉴스 요약 캐시 저장 실패, 캐시 없이 진행합니다.")


async def _delete_key(key: str) -> None:
    try:
        client = get_redis_client()
        await client.delete(key)
    except Exception:
        _logger.exception("손상된 캐시 키 삭제 실패")
