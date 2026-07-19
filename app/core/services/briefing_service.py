"""
브리핑 생성 유스케이스
요청된 사원 유형(ROOKIE/TANKER/PRO)의 공통 분석과 개인화 코멘트를
asyncio.gather로 동시에 생성해 취합한다.
"""

import asyncio

from app.core.agents.briefing_api import generate_briefing, generate_personal_comment
from app.exceptions import InvalidRequest
from app.schemas.briefing import (
    AgentBriefing,
    AgentType,
    BriefingConclusion,
    BriefingGenerateRequest,
    BriefingResult,
    NewsInput,
    RecentDecision,
)


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
    """
    common = await generate_briefing(news_cards, agent_type, level_range)

    combined_card_id = ",".join(sorted(c.card_id for c in news_cards))   #캐시 키로 쓰일 카드 전체 조합 식별자
    briefing_id = f"{combined_card_id}:{agent_type}:{level_range}"
    conclusion = BriefingConclusion(
        headline=common.headline,
        direction=common.direction,
        confidenceRate=common.confidence_rate,
    )

    personal_comment = await generate_personal_comment(
        agent_type,
        user_id,
        briefing_id,
        conclusion,
        recent_decisions,
    )

    return AgentBriefing(
        **common.model_dump(),
        personal_comment=personal_comment,
        personal_cached=False,  # TODO: 개인화 캐시 연동 후 실제 히트 여부로 교체
    )