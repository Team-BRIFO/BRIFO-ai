"""
프롬프트 조립

agent_profiles(사원 규칙) + 동적 입력(카드뉴스 여러 장, 최근 결정)을 받아
LLM에 보낼 최종 프롬프트 문자열을 만든다.

구조 원칙:
- 참조 데이터(카드뉴스)는 프롬프트 앞쪽에, 지시사항은 뒤쪽에 배치
- XML 태그로 역할/작업/규칙/출력형식을 구획
- 응답은 headline/summary/contentText/oneLiner/direction/confidenceRate를 하나의 JSON으로만 받는다
"""

from xml.sax.saxutils import escape

from app.core.agents.agent_profiles import get_agent_profile
from app.schemas.briefing import (
    AgentType,
    BriefingConclusion,
    NewsInput,
    RecentDecision,
)

_TASK = "카드뉴스를 종합해 하나의 주가 브리핑을 작성한다."

_LEVEL_TIERS = ["1-3", "4-6", "7-10"]

_COMMON_RULES = """\
- 카드뉴스의 사실관계는 변경하지 않고 정확히 반영한다. (요약 과정에서 문장을 압축하는 것은 가능하지만, 사실 자체를 바꾸거나 지어내지 않는다.)
- 수치는 두 종류로 구분한다: (1) 카드뉴스를 인용하는 수치(매출, 영업이익 등 원문에 실제로 나온 값)는 절대 바꾸거나 새로 만들지 않고 원문 그대로 정확히 반영한다. (2) 예측성 수치(방향에 대한 확신도, 하방 리스크 낙폭 등)는 아래 페르소나별 규칙이 명시적으로 요구하는 경우에만, 그 규칙이 정한 방식으로 만든다. 페르소나 규칙이 명시적으로 요구하지 않은 새로운 수치는 어떤 경우에도 지어내지 않는다.
- 카드뉴스에 전사/부문/사업 등 서로 다른 대상의 수치가 함께 나오면, 어떤 수치가 어느 대상의 것인지 정확히 구분해서 쓴다. 특정 대상의 수치를 다른 대상의 수치인 것처럼 섞어 쓰지 않는다.
- 배경 지식(과거 유사 사례, 시장 통념, 업계 일반 지식 등)을 최소 1개 포함해 카드뉴스 요약을 넘어서는 분석을 제공한다. 단, 구체적인 기업명·수치·사건은 카드뉴스에 있는 것만 사용하고 새로 지어내지 않는다. 실제로 널리 알려진 사례·통념만 사용하고, 근거 없는 낙관적·비관적 일반화를 그럴듯한 통념처럼 포장하지 않는다.
- 카드가 여러 장이면 카드별로 나열하지 말고 공통된 흐름 하나로 종합한다.
- 모든 출력 필드(headline/summary/contentText/oneLiner/direction/confidenceRate)는 같은 결론을 일관되게 반영한다.
- contentText에는 투자 유의사항 등 디스클레이머를 넣지 않는다 (서비스 화면에서 별도로 표기한다)."""

_OUTPUT_FORMAT_RULE = """\
아래 6개 필드를 모두 채운 JSON 하나만 출력한다. 그 외 설명이나 텍스트는 덧붙이지 않는다.
- headline: 접두어("상승 예측 확신 72%:" 등) 없이 순수한 한 줄 결론만 작성한다.
- direction: "UP" | "DOWN" | "NEUTRAL" 중 하나.
- confidenceRate: 0~100 사이의 정수. (아래 예시의 72는 형식 예시일 뿐, 실제 값은 분석 결과에 따라 정한다.)
  confidenceRate는 예상 수익률이 아니라 direction 판단에 대한 확신도를 의미한다.
  근거가 부족하거나 여러 근거가 서로 충돌할수록 낮게 설정한다.
  direction이 NEUTRAL이면 "관망이 맞다"는 판단 자체에 대한 확신도를 의미한다.
 
{
  "headline": "한 줄 결론",
  "summary": "짧은 요약",
  "contentText": "긴 분석 본문",
  "oneLiner": "마지막 한마디",
  "direction": "UP|DOWN|NEUTRAL",
  "confidenceRate": 72
}"""

_FINAL_CHECK = """\
출력하기 전에 다음을 스스로 확인한다:
- contentText가 글자수 제한을 지켰는가?
- 배경 지식을 최소 1개 포함했는가? 그 배경 지식이 구체적인 기업명·수치·사건을 새로 지어낸 것은 아닌가?
- direction/confidenceRate가 실제로 작성한 분석 내용과 일치하는가?
- 6개 필드를 모두 채웠는가?
- 출력이 파싱 가능한 유효한 JSON인가?"""


def build_briefing_prompt(
    agent_type: AgentType, news_cards: list[NewsInput], level_range: str
) -> str:
    """
    공통 규칙에 따른 기본 프롬프트 생성 (카드뉴스 + 페르소나 규칙).
    level_range가 정의되지 않은 값이면 예외를 던진다.
    """
    if not news_cards:
        raise ValueError("news_cards는 한 장 이상이어야 합니다.")

    profile = get_agent_profile(agent_type)
    news_section = "\n\n".join(
        _format_news_card(i, card) for i, card in enumerate(news_cards, 1)
    )
    summary_rules = "\n".join(f"- {r}" for r in profile["summary_rules"])
    content_rules = "\n".join(f"- {r}" for r in profile["content_rules"])
    one_liner_rules = "\n".join(f"- {r}" for r in profile["one_liner_rules"])
    examples_section = "\n".join(_format_example(ex) for ex in profile["examples"])

    try:
        tier_index = _LEVEL_TIERS.index(level_range)
    except ValueError as exc:
        raise ValueError(f"지원하지 않는 level_range: {level_range!r}") from exc

    level_effect = "\n".join(
        f"- {profile['level_effects'][tier]}" for tier in _LEVEL_TIERS[: tier_index + 1]
    )

    return f"""\
<news_cards>
{news_section}
</news_cards>
 
<role>
{profile["role_intro"]}
</role>
 
<task>
{_TASK}
</task>
 
<rules>
<common_rules>
{_COMMON_RULES}
</common_rules>
 
<summary_rules>
{summary_rules}
</summary_rules>
 
<content_rules>
{content_rules}
</content_rules>
 
<level_effect>
현재 레벨 구간: {level_range} (contentText에 적용)
{level_effect}
</level_effect>

<one_liner_rules>
{one_liner_rules}
</one_liner_rules>
</rules>

<examples>
아래는 톤과 형식만 참고할 예시다. 예시의 수치, 종목명, 구체적 사실은 그대로 베끼지 말고
반드시 위 <news_cards>의 내용을 기반으로 새로 작성한다. 예시는 서로 다른 상황을 보여주기 위한
것으로, 특정 방향(상승/하락)을 암시하지 않는다.
{examples_section}
</examples>

<output_format>
{_OUTPUT_FORMAT_RULE}
</output_format>

<final_check>
{_FINAL_CHECK}
</final_check>"""


def build_personal_prompt(
    agent_type: AgentType,
    briefing_conclusion: BriefingConclusion,
    recent_decisions: list[RecentDecision],
) -> str:
    """
    개인화 코멘트용 프롬프트 생성 (공통 분석 결과 + 최근 결정 3건)
    공통 분석 중 결론(headline/direction/confidenceRate)만 사용해 가볍게 유지하고, 같은 페르소나 말투를 유지한다
    """
    profile = get_agent_profile(agent_type)

    if recent_decisions:
        decisions_text = "\n".join(_format_decision(d) for d in recent_decisions)
    else:
        decisions_text = "- 최근 결정 기록이 없습니다."

    return f"""\
<recent_decisions>
{decisions_text}
</recent_decisions>
 
<briefing_conclusion>
- 방향: {briefing_conclusion.direction}
- 확신도: {briefing_conclusion.confidence_rate}%
- 헤드라인: {escape(str(briefing_conclusion.headline))}
</briefing_conclusion>
 
<role>
{profile["role_intro"]}
</role>
 
<task>
당신은 방금 위 role의 페르소나로 위 결론의 브리핑을 작성했다. 같은 말투를 유지하며
사용자에게 1~2문장의 짧은 개인화 코멘트를 작성한다.
</task>
 
<rules>
- 사용자의 과거 결정 패턴(적중/실패/경향)을 짚어주되, 매수·매도를 직접 지시하지 않는다.
- 1~2문장, 짧고 자연스럽게 작성한다.
- 최근 결정 기록이 없으면 과거 언급 없이 이번 분석에 대한 짧은 코멘트만 작성한다.
- 다른 설명 없이 코멘트 문장만 출력한다.
</rules>"""


def _format_example(example: dict[str, str]) -> str:
    return f"""\
<example>
  <summary>{example["summary"]}</summary>
  <content_text>{example["content_text"]}</content_text>
  <one_liner>{example["one_liner"]}</one_liner>
</example>"""


def _format_news_card(index: int, card: NewsInput) -> str:
    points = "\n".join(f"  - {escape(str(p))}" for p in card.points)
    return f"[카드 {index}] {escape(str(card.headline))}\n{points}"


def _format_decision(decision: RecentDecision) -> str:
    result = "적중" if decision.is_correct else "실패"
    return (
        f"- {escape(str(decision.stock_name))}: {decision.direction} 예측"
        f" (확신도 {decision.confidence}/5점, {result})"
    )
