"""
브리핑 생성 기능의 외부 연동 인터페이스
"""

import json
import logging

from pydantic import ValidationError

from app.core.agents.llm_router import select_briefing_model, select_personal_model
from app.core.agents.prompt_builder import build_briefing_prompt, build_personal_prompt
from app.exceptions import InvalidLLMResponse
from app.infra.openrouter_client import call_llm
from app.infra.usage_tracker import record_usage
from app.schemas.briefing import (
    AgentType,
    BriefingConclusion,
    CommonBriefing,
    NewsInput,
    RecentDecision,
)

_logger = logging.getLogger(__name__)


async def generate_briefing(
    news_cards: list[NewsInput],
    agent_type: AgentType,
    level_range: str,
) -> CommonBriefing:
    """
    사원 1명의 공통 분석 브리핑을 생성한다.

    프롬프트 생성 → 모델 선택 → LLM 호출 →
    응답 JSON 파싱 → CommonBriefing 검증
    """
    prompt = build_briefing_prompt(agent_type, news_cards, level_range)
    primary_model, fallback_model = select_briefing_model(agent_type)

    llm_response = await call_llm(
        prompt,
        primary_model,
        fallback_model,
        agent_type=agent_type,
        task_type="briefing",
    )

    try:
        parsed = json.loads(llm_response["content"])
    except json.JSONDecodeError as exc:
        await _record_parse_failure(llm_response, agent_type)
        raise InvalidLLMResponse("AI 응답을 JSON으로 해석할 수 없습니다.") from exc

    try:
        return CommonBriefing(
            agent_type=agent_type,
            direction=parsed["direction"],
            confidence_rate=parsed["confidenceRate"],
            headline=parsed["headline"],
            summary=parsed["summary"],
            content_text=parsed["contentText"],
            one_liner=parsed["oneLiner"],
            model_name=llm_response["model"],
            cached=False,
        )
    except (KeyError, TypeError, ValidationError) as exc:
        await _record_parse_failure(llm_response, agent_type)
        raise InvalidLLMResponse("AI 응답이 정해진 형식과 다릅니다.") from exc


async def _record_parse_failure(llm_response: dict, agent_type: AgentType) -> None:
    """
    호출은 성공했으나 파싱/검증에 실패했을 때
    실패 이벤트만 별도로 남긴다
    토큰은 2배로 집계되지 않도록 0으로 기록한다 
    """
    try:
        await record_usage(
            model_name=llm_response.get("model", "unknown"),
            agent_type=agent_type,
            task_type="briefing",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0.0,
            fallback_used=llm_response.get("fallback_used", False),
            status="error",
            error_type="parse_error",
        )
    except Exception:
        _logger.exception("파싱 실패 usage 기록 실패 (InvalidLLMResponse 발생에는 영향 X)")


async def generate_personal_comment(
    agent_type: AgentType,
    user_id: str,
    briefing_id: str,
    briefing_conclusion: BriefingConclusion,
    recent_decisions: list[RecentDecision],
) -> str:
    """
    개인화 코멘트(personalComment)를 생성한다.

    개인화 프롬프트 → 모델 선택 → LLM 호출 → 반환
    """
    prompt = build_personal_prompt(agent_type, briefing_conclusion, recent_decisions)
    primary_model, fallback_model = select_personal_model()

    llm_response = await call_llm(
        prompt,
        primary_model,
        fallback_model,
        agent_type=agent_type,
        task_type="personal",
        require_json=False,
    )

    return llm_response["content"].strip()