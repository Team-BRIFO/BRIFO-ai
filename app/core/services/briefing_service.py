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
    if not request.news.point:
        raise InvalidRequest("news.point는 최소 1개 이상이어야 합니다.")

    briefings = await asyncio.gather(
        *(
            _build_agent_briefing(
                news=request.news,
                agent_type=agent_type,
                level_range=request.level_range,
                user_id=request.user_id,
                recent_decisions=request.recent_decisions,
            )
            for agent_type in request.agent_types
        )
    )

    return BriefingResult(news_id=request.news.news_id, briefings=list(briefings))


async def _build_agent_briefing(
    *,
    news: NewsInput,
    agent_type: AgentType,
    level_range: str,
    user_id: str,
    recent_decisions: list[RecentDecision],
) -> AgentBriefing:
    """
    사원 1명의 공통 분석과, 그 결론을 바탕으로 한 개인화 코멘트를 생성한다.
    """
    common = await generate_briefing(news, agent_type, level_range)

    briefing_id = f"{news.news_id}:{agent_type}:{level_range}"
    conclusion = BriefingConclusion(
        headline=common.headline,
        direction=common.direction,
        probability=common.probability,
    )

    personal_intro, personal_outro = await generate_personal_comment(
        user_id=user_id,
        briefing_id=briefing_id,
        briefing_conclusion=conclusion,
        recent_decisions=recent_decisions,
    )

    return AgentBriefing(
        **common.model_dump(),
        personal_intro=personal_intro,
        personal_outro=personal_outro,
        personal_cached=False,  # TODO: 개인화 캐시 연동 후 실제 히트 여부로 교체
    )
