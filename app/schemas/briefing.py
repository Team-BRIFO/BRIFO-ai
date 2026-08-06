from typing import Literal

from pydantic import BaseModel, Field

AgentType = Literal["ROOKIE", "TANKER", "PRO"]
Direction = Literal["UP", "DOWN", "NEUTRAL"]
LevelRange = Literal["1-3", "4-6", "7-10"]


class NewsInput(BaseModel):
    card_id: str = Field(alias="cardId")
    news_id: str = Field(alias="newsId")
    headline: str
    points: list[str]

    model_config = {"populate_by_name": True}


class RecentDecision(BaseModel):
    stock_name: str = Field(alias="stockName")
    direction: Direction
    confidence: int = Field(ge=1, le=5)
    is_correct: bool = Field(alias="isCorrect")
    actual_change: float = Field(alias="actualChange")

    model_config = {"populate_by_name": True}


class BriefingGenerateRequest(BaseModel):
    news_card: list[NewsInput] = Field(alias="newsCard")
    user_id: str = Field(alias="userId")
    agent_types: list[AgentType] = Field(alias="agentTypes")
    level_range: LevelRange = Field(alias="levelRange")
    recent_decisions: list[RecentDecision] = Field(alias="recentDecisions")

    model_config = {"populate_by_name": True}


class CommonBriefing(BaseModel):
    agent_type: AgentType = Field(serialization_alias="agentType")
    direction: Direction
    confidence_rate: int = Field(ge=0, le=100, serialization_alias="confidenceRate")
    headline: str
    summary: str
    content_text: str = Field(serialization_alias="contentText")
    one_liner: str = Field(serialization_alias="oneLiner")
    model_name: str = Field(serialization_alias="modelName")
    cached: bool

    model_config = {"populate_by_name": True}


class AgentBriefing(CommonBriefing):
    personal_comment: str | None = Field(
        serialization_alias="personalComment", default=None
    )
    personal_cached: bool = Field(serialization_alias="personalCached")


class BriefingConclusion(BaseModel):
    headline: str
    direction: Direction
    confidence_rate: int = Field(alias="confidenceRate")


class BriefingResult(BaseModel):
    briefings: list[AgentBriefing]

    model_config = {"populate_by_name": True}


class BriefingGenerateResponse(BaseModel):
    is_success: bool = Field(serialization_alias="isSuccess", default=True)
    code: str = "COMMON200"
    message: str = "사원 브리핑 생성에 성공했습니다."
    result: BriefingResult

    model_config = {"populate_by_name": True}