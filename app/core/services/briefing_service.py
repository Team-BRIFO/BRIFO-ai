"""
브리핑 생성 유스케이스
요청된 사원 유형(ROOKIE/TANKER/PRO)의 공통 분석과 개인화 코멘트를
asyncio.gather로 동시에 생성해 취합한다.
"""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from app.core.agents.briefing_api import generate_briefing, generate_personal_comment
from app.exceptions import InvalidRequest
from app.infra.cache import get_briefing, get_personal, set_briefing, set_personal
from app.infra.redis_client import get_redis_client
from app.schemas.briefing import (
    AgentBriefing,
    AgentType,
    BriefingConclusion,
    BriefingGenerateRequest,
    BriefingResult,
    CommonBriefing,
    NewsInput,
    RecentDecision,
)

_CACHE_VERSION = "v1"
_LOCK_TTL_SECONDS = 30
_LOCK_WAIT_ATTEMPTS = 10
_LOCK_WAIT_INTERVAL = 0.5

_KST = ZoneInfo("Asia/Seoul")
_SETTLEMENT_TIME = dt_time(15, 30)  # 정산 시각


def _seconds_until_next_settlement() -> int:
    now = datetime.now(_KST)
    today_settlement = now.replace(
        hour=_SETTLEMENT_TIME.hour,
        minute=_SETTLEMENT_TIME.minute,
        second=0,
        microsecond=0,
    )
    next_settlement = (
        today_settlement
        if now < today_settlement
        else today_settlement + timedelta(days=1)
    )
    return max(1, int((next_settlement - now).total_seconds()))


async def generate_briefings(request: BriefingGenerateRequest) -> BriefingResult:
    """
    요청된 사원 유형별 브리핑(공통 분석 + 개인화 코멘트)을 asyncio.gather로 동시에 생성한다.
    """
    if not request.agent_types:
        raise InvalidRequest("agentTypes는 최소 1개 이상이어야 합니다.")
    if not request.news_card:
        raise InvalidRequest("newsCard는 최소 1개 이상이어야 합니다.")

    briefings = await asyncio.gather(
        *(
            _build_agent_briefing(
                news_cards=request.news_card,
                agent_type=agent_type,
                level_range=request.level_range,
                user_id=request.user_id,
                recent_decisions=request.recent_decisions,
            )
            for agent_type in request.agent_types
        )
    )

    return BriefingResult(briefings=list(briefings))


def build_briefing_cache_id(news_cards: list[NewsInput]) -> str:
    payload = [
        card.model_dump(by_alias=True, mode="json")
        for card in sorted(news_cards, key=lambda card: card.card_id)
    ]
    serialized = json.dumps(
        {"version": _CACHE_VERSION, "newsCards": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


async def _build_agent_briefing(
    *,
    news_cards: list[NewsInput],
    agent_type: AgentType,
    level_range: str,
    user_id: str,
    recent_decisions: list[RecentDecision],
) -> AgentBriefing:
    """
    사원 1명의 공통 분석과, 그 결론을 바탕으로 한 개인화 코멘트를 생성한다.
    캐시 확인 → LLM 호출 → 캐시 저장 순서로 진행한다.
    동시 요청이 겹치면 분산 락으로 LLM 중복 호출을 막는다.
    """
    cache_id = build_briefing_cache_id(news_cards)
    briefing_id = f"{cache_id}:{agent_type}:{level_range}"

    common = await get_briefing(cache_id, agent_type, level_range)
    if common is None:
        common = await _with_lock(
            lock_key=f"lock:briefing:{briefing_id}",
            get_cached=lambda: get_briefing(cache_id, agent_type, level_range),
            generate=lambda: _generate_and_cache_briefing(
                news_cards, agent_type, level_range, cache_id
            ),
        )
    else:
        common = common.model_copy(update={"cached": True})

    conclusion = BriefingConclusion(
        headline=common.headline,
        direction=common.direction,
        confidenceRate=common.confidence_rate,
    )

    personal_comment = await get_personal(user_id, briefing_id)
    personal_cached = personal_comment is not None
    if personal_comment is None:
        personal_comment = await _with_lock(
            lock_key=f"lock:personal:{user_id}:{briefing_id}",
            get_cached=lambda: get_personal(user_id, briefing_id),
            generate=lambda: _generate_and_cache_personal(
                agent_type, user_id, briefing_id, conclusion, recent_decisions
            ),
        )

    return AgentBriefing(
        **common.model_dump(),
        personal_comment=personal_comment,
        personal_cached=personal_cached,
    )


async def _generate_and_cache_briefing(
    news_cards: list[NewsInput], agent_type: AgentType, level_range: str, cache_id: str
) -> CommonBriefing:
    common = await generate_briefing(news_cards, agent_type, level_range)
    await set_briefing(cache_id, agent_type, level_range, common)
    return common


async def _generate_and_cache_personal(
    agent_type: AgentType,
    user_id: str,
    briefing_id: str,
    conclusion: BriefingConclusion,
    recent_decisions: list[RecentDecision],
) -> str:
    personal_comment = await generate_personal_comment(
        agent_type, user_id, briefing_id, conclusion, recent_decisions
    )
    await set_personal(
        user_id,
        briefing_id,
        personal_comment,
        ttl_seconds=_seconds_until_next_settlement(),
    )
    return personal_comment


async def _with_lock(*, lock_key: str, get_cached, generate):
    try:
        client = get_redis_client()
        acquired = await client.set(lock_key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
    except Exception:
        acquired = None

    if acquired:
        try:
            return await generate()
        finally:
            try:
                client = get_redis_client()
                await client.delete(lock_key)
            except Exception:
                pass

    for _ in range(_LOCK_WAIT_ATTEMPTS):
        await asyncio.sleep(_LOCK_WAIT_INTERVAL)
        cached = await get_cached()
        if cached is not None:
            return cached

    return await generate()
