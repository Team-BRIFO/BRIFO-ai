from typing import Literal

from pydantic import BaseModel, Field

AgentType = Literal["ROOKIE", "TANKER", "PRO"]
Direction = Literal["UP", "DOWN", "NEUTRAL"]


class RecentDecision(BaseModel):
    stock_name: str = Field(alias="stockName")
    direction: Direction
    confidence: int
    is_correct: bool | None = Field(alias="isCorrect")
    actual_change: float | None = Field(alias="actualChange")

    model_config = {"populate_by_name": True}


class BriefingGenerateRequest(BaseModel):
    news_id: str = Field(alias="newsId")
    user_id: str = Field(alias="userId")
    agent_types: list[AgentType] = Field(alias="agentTypes")
    level_range: str = Field(alias="levelRange")
    recent_decisions: list[RecentDecision] = Field(alias="recentDecisions")

    model_config = {"populate_by_name": True}


class CommonBriefing(BaseModel):
    agent_type: AgentType = Field(serialization_alias="agentType")
    direction: Direction
    probability: float
    headline: str
    summary: str
    common_analysis: str = Field(serialization_alias="commonAnalysis")
    closing_comment: str = Field(serialization_alias="closingComment")
    model_name: str = Field(serialization_alias="modelName")
    cached: bool

    model_config = {"populate_by_name": True}


class AgentBriefing(BaseModel):
    agent_type: AgentType = Field(serialization_alias="agentType")
    direction: Direction
    probability: float
    headline: str
    summary: str
    personal_intro: str = Field(serialization_alias="personalIntro")
    personal_outro: str | None = Field(
        serialization_alias="personalOutro", default=None
    )
    common_analysis: str = Field(serialization_alias="commonAnalysis")
    closing_comment: str = Field(serialization_alias="closingComment")
    model_name: str = Field(serialization_alias="modelName")
    cached: bool
    personal_cached: bool = Field(serialization_alias="personalCached")

    model_config = {"populate_by_name": True}


class BriefingResult(BaseModel):
    news_id: str = Field(serialization_alias="newsId")
    briefings: list[AgentBriefing]

    model_config = {"populate_by_name": True}


class BriefingGenerateResponse(BaseModel):
    is_success: bool = Field(serialization_alias="isSuccess", default=True)
    code: str = "COMMON200"
    message: str = "사원 브리핑 생성에 성공했습니다."
    result: BriefingResult

    model_config = {"populate_by_name": True}
