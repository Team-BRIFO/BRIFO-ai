from app.schemas.briefing import AgentType, RecentDecision


def build_briefing_prompt(agent_type: AgentType, news: dict, level_range: str) -> str:
    """
    공통 규칙에 따른 기본 프롬프트 생성
    (고정 프롬프트+뉴스)
    """
    ...


def build_personal_prompt(
    briefing_conclusion: dict, recent_decisions: list[RecentDecision]
) -> str:
    """
    개인화 코멘트용 프롬프트 생성
    (공통 분석 결과 + 최근 결정 3건)
    """
    ...
