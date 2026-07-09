"""
사원 페르소나 정의
"""

from typing import TypedDict

from app.schemas.briefing import AgentType


class AgentProfile(TypedDict):
    personality: str
    analysis_frame: str
    writing_rules: list[str]
    level_effects: dict[str, str]


def get_agent_profile(agent_type: AgentType) -> AgentProfile:
    """
    사원 프로필을 반환한다
    (성향, 분석프레임, 작성 규칙, 레벨 효과)
    모델 정보는 model_policy가 관리한다.
    """
    ...
