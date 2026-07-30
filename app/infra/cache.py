"""
Redis 캐싱
공통 분석 - TTL 24h
카드뉴스 요약 - TTL 24h
개인화 레이어 코멘트 - TTL 다음 정산 시각(15:30 KST)까지
"""

import hashlib
import json
import logging
from datetime import datetime

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


# 카드뉴스 요약: summary:{news_id}:{exclude_terms 해시} — 전역 공유
def _summary_key(news_id: str, exclude_terms: list[str]) -> str:
    terms_json = json.dumps(sorted(exclude_terms), ensure_ascii=False)
    terms_hash = hashlib.sha256(terms_json.encode()).hexdigest()
    return f"summary:{news_id}:{terms_hash}"


# 카드뉴스 요약 최신본: summary:latest:{news_id} — exclude_terms 무관하게 조회 (브리핑 프롬프트 연동용)
def _summary_latest_key(news_id: str) -> str:
    return f"summary:latest:{news_id}"


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


async def set_personal(
    user_id: str, briefing_id: str, value: str, expires_at: datetime
) -> None:
    try:
        client = get_redis_client()
        await client.set(_personal_key(user_id, briefing_id), value, exat=expires_at)
    except Exception:
        _logger.exception("개인화 코멘트 캐시 저장 실패, 캐시 없이 진행합니다.")


async def get_summary(news_id: str, exclude_terms: list[str]) -> CardNewsResult | None:
    key = _summary_key(news_id, exclude_terms)
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


async def set_summary(
    news_id: str, exclude_terms: list[str], value: CardNewsResult
) -> None:
    try:
        client = get_redis_client()
        payload = value.model_dump_json()
        await client.set(
            _summary_key(news_id, exclude_terms), payload, ex=_TTL_SECONDS
        )
        await client.set(_summary_latest_key(news_id), payload, ex=_TTL_SECONDS)
    except Exception:
        _logger.exception("카드뉴스 요약 캐시 저장 실패, 캐시 없이 진행합니다.")


async def get_latest_summary(news_id: str) -> CardNewsResult | None:
    """
    exclude_terms와 무관하게 news_id 기준으로 가장 최근에 생성된 카드뉴스 요약을 조회한다.
    브리핑 프롬프트 생성 시 클라이언트가 보낸 headline/points 대신 사용한다.
    """
    key = _summary_latest_key(news_id)
    try:
        client = get_redis_client()
        raw = await client.get(key)
        if raw is None:
            return None
        return CardNewsResult.model_validate_json(raw)
    except ValidationError:
        _logger.exception(
            "카드뉴스 최신 캐시 값이 손상되어 삭제하고 캐시 미스로 처리합니다."
        )
        await _delete_key(key)
        return None
    except Exception:
        _logger.exception("카드뉴스 최신 캐시 조회 실패, 캐시 미스로 처리합니다.")
        return None


async def _delete_key(key: str) -> None:
    try:
        client = get_redis_client()
        await client.delete(key)
    except Exception:
        _logger.exception("손상된 캐시 키 삭제 실패")
