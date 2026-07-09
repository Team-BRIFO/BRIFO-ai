from pydantic import BaseModel

from .briefing import AgentType, RecentDecision


class PersonalCommentRequest(BaseModel):
    user_id: str
    agent_type: AgentType
    level_range: str
    recent_decisions: list[RecentDecision]


class PersonalCommentResult(BaseModel):
    comment: str
    cached: bool