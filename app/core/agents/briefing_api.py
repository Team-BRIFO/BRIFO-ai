"""
브리핑 생성 기능의 외부 연동 인터페이스
"""

from app.schemas.briefing import (
    AgentType,
    BriefingConclusion,
    CommonBriefing,
    NewsInput,
    RecentDecision,
)


async def generate_briefing(
    news: NewsInput,  # BE가 전달한 카드뉴스
    agent_type: AgentType,  # "ROOKIE" | "TANKER" | "PRO"
    level_range: str,  # "1-3" | "4-6" | "7-10"
) -> CommonBriefing:
    """
    사원 1명의 공통 분석 브리핑을 생성한다.

    공통 분석 캐시 확인 → 프롬프트 생성 → 모델 선택 → LLM 호출 → 캐시 저장
    """
    ...


async def generate_personal_comment(
    user_id: str,
    briefing_id: str,
    briefing_conclusion: BriefingConclusion,
    recent_decisions: list[RecentDecision],
) -> tuple[str, str | None]:  # (personal_intro, personal_outro)
    """
    개인화 코멘트를 생성한다.

    개인화 캐시 확인 → 개인화 프롬프트 생성 → LLM 호출 → 캐시 저장.
    """
    ...
