"""
사원 페르소나 정의
"""

from app.schemas.briefing import AgentType


def get_agent_profile(agent_type: AgentType) -> dict:
    """
    사원 프로필을 반환한다
    (성향, 분석프레임, 작성 규칙, 레벨 효과)
    모델 정보는 model_policy가 관리한다.
    """
    ...
