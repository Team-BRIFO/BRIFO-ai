"""
LLM 모델 라우팅
- 브리핑: 사원별 차등 (루키<탱커<프로)
- 개인화: 최저가 저지연 모델
- 카드뉴스 요약: 최저가 저지연 모델
"""

from app.schemas.briefing import AgentType


def select_briefing_model(agent_type: AgentType) -> tuple[str, str]:
    """
    브리핑용 모델 선택
    agent_type: "ROOKIE" | "TANKER" | "PRO"
    반환: (primary_model, fallback_model)
    """
    ...


def select_personal_model() -> tuple[str, str]:
    """
    개인화용 모델 선택
    반환: (primary_model, fallback_model)
    """
    ...


def select_summary_model() -> tuple[str, str]:
    """
    카드뉴스 요약용 모델 선택
    반환: (primary_model, fallback_model)
    """
    ...
