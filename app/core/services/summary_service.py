"""
카드뉴스 요약 유스케이스
뉴스 원문을 LLM으로 요약해 카드뉴스(헤드라인 + 포인트 + 키워드 + 용어) 리스트를 생성한다.
"""

import json
import time

from pydantic import ValidationError

from app.core.agents.llm_response import strip_markdown_fence
from app.core.agents.llm_router import select_summary_model
from app.exceptions import AllModelsFailed, BrifoAIException, InvalidRequest
from app.infra.openrouter_client import call_llm
from app.infra.usage_tracker import record_usage
from app.schemas.news import CardNewsGenerateRequest, CardNewsItem, CardNewsResult


async def summarize_news(request: CardNewsGenerateRequest) -> CardNewsResult:
    """
    뉴스 원문을 카드뉴스로 요약한다.
    프롬프트 생성 → LLM 호출 → 결과 검증 → 사용량 기록 순으로 진행한다.
    """
    # TODO: newsId 기준 24h 캐시 연동
    if not request.news_content.strip():
        raise InvalidRequest("newsContent는 비어 있을 수 없습니다.")

    prompt = _build_prompt(request)
    primary_model, fallback_model = select_summary_model()

    started = time.perf_counter()
    try:
        llm_response = await call_llm(
            prompt, primary_model, fallback_model,
            agent_type="SUMMARY", task_type="news_summary"
    )
    except BrifoAIException:
        raise
    except Exception as exc:
        # TODO: call_llm이 자체적으로 LLMTimeout/RateLimit/AllModelsFailed를 던지도록 구현되면 제거
        raise AllModelsFailed() from exc
    latency_ms = (time.perf_counter() - started) * 1000

    usage_kwargs = dict(
        model_name=llm_response.get("model", primary_model),
        agent_type="SUMMARY",
        task_type="news_summary",
        input_tokens=llm_response.get("input_tokens", 0),
        output_tokens=llm_response.get("output_tokens", 0),
        latency_ms=latency_ms,
        fallback_used=llm_response.get("fallback_used", False),
    )

    try:
        card_news = _parse_card_news(llm_response)
    except InvalidRequest:
        await record_usage(**usage_kwargs, status="error", error_type="parse_error")
        raise

    await record_usage(**usage_kwargs)

    return CardNewsResult(news_id=request.news_id, card_news=card_news)


def _build_prompt(request: CardNewsGenerateRequest) -> str:
    exclude_terms = ", ".join(request.exclude_terms) if request.exclude_terms else "없음"
    return (
        "너는 주식 뉴스를 객관적 사실 카드로 요약하는 전문가다. 아래 뉴스 원문을 규칙에 따라 요약하라.\n\n"
        f"관련 종목: {request.stock_name}\n"
        f"최근 14일 이미 출제된 용어(중복 학습 방지, 새 용어로 다시 뽑지 말 것): {exclude_terms}\n"
        f"뉴스 원문:\n{request.news_content}\n\n"
        "규칙:\n"
        "- 의견·추측·방향성(상승/하락 전망 등) 금지. 원문에 있는 사실만 전달한다.\n"
        "- headline은 20자 이내로 작성한다.\n"
        "- points는 정확히 3개, 각 40자 이내로 작성하며 수치는 원문 그대로 보존한다.\n"
        "- keywords는 points와 동일한 개수(3개)로, 각 point를 대표하는 핵심어를 순서대로 작성한다.\n"
        "- terms는 본문에 실제로 등장한 주식 용어 중 2~3개를 골라 surface(원문 표기)"
        "·term(정식 용어명)·definition(초보자용 설명)으로 작성한다. "
        "위의 '이미 출제된 용어'는 다시 고르지 않는다.\n"
        "- 출력은 다른 설명 없이 JSON만 반환한다. 형식은 다음과 같다:\n"
        '{"cardNews": [{"headline": "string", "points": ["string", "string", "string"], '
        '"keywords": ["string", "string", "string"], '
        '"terms": [{"surface": "string", "term": "string", "definition": "string"}]}]}'
    )


def _parse_card_news(llm_response: dict) -> list[CardNewsItem]:
    """
    LLM 응답(llm_response["content"] = JSON 문자열 {"cardNews": [...]})을 CardNewsItem으로 검증한다.
    JSON 파싱 실패 또는 스키마 위반(keywords/points 길이 불일치 등) 시 InvalidRequest로 매핑한다.
    """
    try:
        parsed = json.loads(strip_markdown_fence(llm_response["content"]))
    except json.JSONDecodeError as exc:
        raise InvalidRequest("카드뉴스 생성 결과가 유효하지 않습니다.") from exc

    try:
        return [CardNewsItem(**item) for item in parsed["cardNews"]]
    except (ValidationError, KeyError, TypeError) as exc:
        raise InvalidRequest("카드뉴스 생성 결과가 유효하지 않습니다.") from exc
