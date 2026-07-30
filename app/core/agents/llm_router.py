"""
LLM 모델 라우팅
- 브리핑: 사원별 차등 (루키<탱커<프로)
- 개인화: 최저가 저지연 모델
- 카드뉴스 요약: 최저가 저지연 모델
"""
 
from app.schemas.briefing import AgentType

_BRIEFING_MODELS: dict[AgentType, tuple[str, str]] = {
    "ROOKIE": ("google/gemini-3.5-flash", "anthropic/claude-haiku-4.5"),
    "TANKER": ("openai/gpt-5.3-chat", "anthropic/claude-sonnet-5"),
    "PRO": ("anthropic/claude-sonnet-5", "openai/gpt-5.3-chat"),
}
 
_PERSONAL_MODEL: tuple[str, str] = (
    "anthropic/claude-haiku-4.5",
    "google/gemini-3.5-flash-lite",
)

_SUMMARY_MODEL: tuple[str, str] = (
    "google/gemini-3.5-flash-lite",
    "anthropic/claude-haiku-4.5",
)
 
 
def select_briefing_model(agent_type: AgentType) -> tuple[str, str]:
    """
    브리핑용 모델 선택
    agent_type: "ROOKIE" | "TANKER" | "PRO"
    반환: (primary_model, fallback_model)
    """
    return _BRIEFING_MODELS[agent_type]
 
 
def select_personal_model() -> tuple[str, str]:
    """
    개인화용 모델 선택
    반환: (primary_model, fallback_model)
    """
    return _PERSONAL_MODEL
 
 

def select_summary_model() -> tuple[str, str]:
    """
    카드뉴스 요약용 모델 선택
    반환: (primary_model, fallback_model)
    """
    return _SUMMARY_MODEL
