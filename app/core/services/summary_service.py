"""
카드뉴스 요약 유스케이스
뉴스 원문을 LLM으로 요약해 카드뉴스(헤드라인 + 포인트 + 키워드 + 용어) 리스트를 생성한다.
"""

import json
import logging

from pydantic import ValidationError

from app.core.agents.llm_response import strip_markdown_fence
from app.core.agents.llm_router import select_summary_model
from app.exceptions import InvalidLLMResponse, InvalidRequest
from app.infra.cache import get_summary, set_summary
from app.infra.openrouter_client import call_llm
from app.infra.usage_tracker import record_usage
from app.schemas.news import CardNewsGenerateRequest, CardNewsItem, CardNewsResult

_logger = logging.getLogger(__name__)


async def summarize_news(request: CardNewsGenerateRequest) -> CardNewsResult:
    """
    뉴스 원문을 카드뉴스로 요약한다.
    캐시 확인 → 없으면 프롬프트 생성 → LLM 호출 → 결과 검증 → 캐시 저장 순으로 진행한다.
    LLM 호출 성공/실패 usage는 call_llm 내부에서 이미 기록하므로 여기서는 중복 기록하지 않는다.
    """
    if not request.news_content.strip():
        raise InvalidRequest("newsContent는 비어 있을 수 없습니다.")

    cached = await get_summary(request.news_id, request.exclude_terms)
    if cached is not None:
        return cached

    prompt = _build_prompt(request)
    primary_model, fallback_model = select_summary_model()

    llm_response = await call_llm(
        prompt, primary_model, fallback_model,
        agent_type="SUMMARY", task_type="news_summary"
    )

    try:
        card_news = _parse_card_news(llm_response)
        result = CardNewsResult(news_id=request.news_id, card_news=card_news)
    except InvalidLLMResponse:
        await _record_parse_failure(llm_response)
        raise
    except ValidationError as exc:
        await _record_parse_failure(llm_response)
        raise InvalidLLMResponse("카드뉴스 생성 결과가 유효하지 않습니다.") from exc

    await set_summary(request.news_id, request.exclude_terms, result)
    return result


def _build_prompt(request: CardNewsGenerateRequest) -> str:
    exclude_terms = ", ".join(request.exclude_terms) if request.exclude_terms else "없음"
    return (
        "너는 주식 뉴스를 객관적 사실 카드로 요약하는 전문가다. 아래 뉴스 원문을 규칙에 따라 요약하라.\n\n"
        f"관련 종목: {request.stock_name}\n"
        f"최근 14일 이미 출제된 용어(중복 학습 방지, 새 용어로 다시 뽑지 말 것): {exclude_terms}\n"
        f"뉴스 원문:\n{request.news_content}\n\n"
        "규칙:\n"
        "- 의견·추측·방향성(상승/하락 전망 등) 금지. 원문에 있는 사실만 전달한다.\n"
        "- points 3개는 원문에서 가장 중요한 사실 3가지를 우선순위로 골라 담는다. 원문에 긍정적 "
        "사실과 부정적 사실이 함께 있으면 가능한 한 양쪽이 드러나게 균형을 맞추되, 셋 다 중요도가 "
        "높은 한쪽 성격의 사실이라면 억지로 반대쪽을 끼워 넣지 않는다. 단, 방향성이 실제와 반대로 "
        "보일 정도로 한쪽만 골라 담지는 않는다.\n"
        "- 원문이 '~것으로 분석된다/추정된다/전망된다/보인다'처럼 가능성·전망·관측으로 표현한 내용은 "
        "'~했다/~였다' 같은 확정 서술어로 바꾸지 않는다. 문장을 압축하더라도 원문과 같은 강도의 "
        "추정 표현('~것으로 보인다' 등)을 point 끝에 그대로 유지한다.\n"
        "- headline은 20자 이내로 작성한다.\n"
        "- points는 정확히 3개이며 각 point에는 핵심 사실 하나만 담는다. "
        "공백과 문장부호를 포함해 40자 내외로 간결하게 쓰되, 사실을 누락하거나 어색하게 "
        "축약하면서까지 글자 수를 맞추려 하지 않는다. 수치는 원문 그대로 보존한다.\n"
        "- keywords는 뉴스 원문에 실제로 등장한 어려운 주식 용어 중 1~3개를 원문 표기 그대로 골라 "
        "작성한다. keywords는 절대 빈 배열일 수 없으므로 최소 1개는 반드시 포함한다. 가능하면 2개 "
        "이상을 목표로 하되, 후보가 3개보다 많으면 이 기사를 이해하는 데 가장 중요한 용어부터 "
        "우선 선택한다. "
        f"단, 다음 용어는 최근 14일 내 이미 출제되었으므로 다시 고르지 않는다: {exclude_terms}. "
        "이 용어들을 제외하고 남은 용어 중에서 고르되, 제외하고 나면 후보가 하나도 남지 않는 "
        "경우에만 예외적으로 제외 목록 중 원문에서 가장 중요하게 다뤄진 용어를 다시 사용한다.\n"
        "- terms는 keywords 각각에 대해 순서대로 surface(keywords와 동일한 원문 표기)"
        "·term(정식 용어명)·definition(초보자용 설명)을 작성한다. keywords와 terms는 개수가 "
        "정확히 같아야 한다.\n"
        "- cardNews 배열에는 카드를 정확히 1개만 담는다. 뉴스 원문에 다룰 내용이 여러 개여도 "
        "하나의 카드로 종합한다.\n"
        "- 출력 직전에 points가 3개인지, 가장 중요한 사실 위주로 골랐는지, 방향성이 원문과 반대로 "
        "왜곡되지 않았는지, 원문의 추정 표현을 확정 서술어로 바꾼 곳은 없는지, keywords에 이미 "
        "출제된 용어가 섞이지 않았는지 확인한다.\n"
        "- 출력은 다른 설명 없이 JSON만 반환한다. 형식은 다음과 같다:\n"
        '{"cardNews": [{"headline": "string", "points": ["string", "string", "string"], '
        '"keywords": ["string", "string"], '
        '"terms": [{"surface": "string", "term": "string", "definition": "string"}, '
        '{"surface": "string", "term": "string", "definition": "string"}]}]}'
    )


def _parse_card_news(llm_response: dict) -> list[CardNewsItem]:
    """
    LLM 응답(llm_response["content"] = JSON 문자열 {"cardNews": [...]})을 CardNewsItem으로 검증한다.
    JSON 파싱 실패 또는 스키마 위반(keywords/points 길이 불일치 등) 시 InvalidLLMResponse로 매핑한다.
    카드 개수(정확히 1개)는 CardNewsResult.card_news의 min_length/max_length 제약으로
    별도 강제되며, 그 검증은 호출부(summarize_news)에서 CardNewsResult 생성 시 이루어진다.
    """
    try:
        parsed = json.loads(strip_markdown_fence(llm_response["content"]))
    except json.JSONDecodeError as exc:
        raise InvalidLLMResponse("카드뉴스 생성 결과가 유효하지 않습니다.") from exc

    try:
        return [CardNewsItem(**item) for item in parsed["cardNews"]]
    except (ValidationError, KeyError, TypeError) as exc:
        raise InvalidLLMResponse("카드뉴스 생성 결과가 유효하지 않습니다.") from exc


async def _record_parse_failure(llm_response: dict) -> None:
    """
    호출은 성공했으나 파싱/검증에 실패했을 때 실패 이벤트만 별도로 기록한다.
    call_llm이 이미 성공 usage를 기록했으므로 토큰은 2배로 집계되지 않도록 0으로 기록한다.
    """
    try:
        await record_usage(
            event_type="llm_validation_error",
            model_name=llm_response.get("model", "unknown"),
            agent_type="SUMMARY",
            task_type="news_summary",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0.0,
            fallback_used=llm_response.get("fallback_used", False),
            status="error",
            error_type="parse_error",
        )
    except Exception:
        _logger.exception("파싱 실패 usage 기록 실패 (InvalidLLMResponse 발생에는 영향 X)")
