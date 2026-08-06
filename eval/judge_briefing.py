"""
브리핑 결과에 대해 정규식으로 못 잡는 내용 규칙을 LLM 판정으로 채점한다.

- 배경지식을 최소 1개 포함하되, 구체적 기업명·수치·사건을 새로 지어내지 않았는가
- 카드가 여러 장이면 나열이 아니라 하나의 흐름으로 종합했는가
- headline/summary/contentText/oneLiner/direction/confidenceRate가 같은 결론을 일관되게 반영하는가

평가 대상 모델과 다른 모델을 심판으로 써서 자기 자신을 스스로 채점하는 편향을 피한다.
"""

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import BaseModel

from app.infra.http_client import close_openrouter_client, init_openrouter_client
from app.infra.openrouter_client import call_llm

ROOT = Path(__file__).resolve().parent
RESULT_DIR = ROOT / "results" / "agent_baseline"
JUDGE_RESULT_DIR = ROOT / "results" / "agent_baseline_judge"

# 실제 생성 모델(briefing["modelName"])을 제외하고 남은 후보 중에서 primary/fallback을 고른다.
_JUDGE_POOL = (
    "anthropic/claude-sonnet-5",
    "openai/gpt-5.3-chat",
    "anthropic/claude-haiku-4.5",
)


class NewsCardIn(BaseModel):
    headline: str
    points: list[str]


class BriefingIn(BaseModel):
    agentType: str
    direction: str
    confidenceRate: int
    headline: str
    summary: str
    contentText: str
    oneLiner: str
    modelName: str


class BriefingJudgeInput(BaseModel):
    """eval/results/agent_baseline/*.json 하나(케이스 1개)의 필수 필드."""

    caseId: str
    newsCards: list[NewsCardIn]
    briefings: list[BriefingIn]


class BriefingJudgeVerdict(BaseModel):
    """심판 LLM이 반환해야 하는 JSON 형태. 필드 누락·타입 불일치를 여기서 막는다."""

    factsAccurate: bool
    hasGroundedBackground: bool
    isSynthesized: bool
    isConsistent: bool
    issues: list[str]


def _select_judge_models(generation_model: str) -> tuple[str, str]:
    candidates = [m for m in _JUDGE_POOL if m != generation_model]
    return candidates[0], candidates[1]


def _build_judge_prompt(news_cards: list[NewsCardIn], briefing: BriefingIn) -> str:
    cards_text = "\n\n".join(
        f"[카드 {i}] {c.headline}\n" + "\n".join(f"  - {p}" for p in c.points)
        for i, c in enumerate(news_cards, 1)
    )
    return (
        "너는 주가 브리핑의 품질을 검수하는 심사자다. "
        "아래 카드뉴스 원본과, 그것을 종합해 작성된 브리핑을 비교해 채점하라.\n\n"
        f"# 브리핑 작성 페르소나\n{briefing.agentType}\n\n"
        f"# 카드뉴스 원본\n{cards_text}\n\n"
        f"# 생성된 브리핑\n"
        f"headline: {briefing.headline}\n"
        f"summary: {briefing.summary}\n"
        f"contentText: {briefing.contentText}\n"
        f"oneLiner: {briefing.oneLiner}\n"
        f"direction: {briefing.direction}\n"
        f"confidenceRate: {briefing.confidenceRate}\n\n"
        "다음 4개 항목을 판정한다:\n"
        "- factsAccurate: headline/summary/contentText/oneLiner에 나오는 수치·사실이 카드뉴스 원본과 "
        "정확히 일치하면 true. 카드뉴스에 없는 수치를 지어냈거나, 있는 수치를 다른 대상(예: 전사 실적을 "
        "특정 부문 실적으로 착각)에 잘못 붙였거나 값을 바꿨다면 false. "
        "단, agentType이 TANKER(리스크 매니저 '탱커')인 경우 하방 시나리오에서 제시하는 예상 낙폭"
        "(예: '-8%', '-10%', '-15%' 등 'X%' 형식의 수치)은 카드뉴스에 없어도 위반이 아니다. "
        "TANKER 페르소나 규칙 자체가 근거가 부족하면 보수적으로 낙폭을 자체 추정해 제시하도록 "
        "요구하기 때문이다.\n"
        "- hasGroundedBackground: contentText에 카드뉴스를 넘어서는 배경지식(과거 유사 사례, 시장 통념, "
        "업계 일반 지식 등)이 최소 1개 있고, 그 배경지식이 구체적인 기업명·수치·사건을 새로 지어내지 "
        "않았으면 true. 배경지식이 없거나 지어낸 사실이 있으면 false.\n"
        "- isSynthesized: 카드가 2장 이상인데 contentText가 카드별로 나열하듯 쓰였다면 false. "
        "카드가 1장이거나, 여러 카드를 하나의 흐름으로 종합했다면 true.\n"
        "- isConsistent: headline/summary/contentText/oneLiner/direction이 서로 다른 결론을 "
        "암시하지 않고 일관되면 true. 예를 들어 contentText는 하락 근거가 우세한데 direction이 UP이면 false.\n\n"
        "출력은 다른 설명 없이 아래 JSON 형식만 반환한다:\n"
        '{"factsAccurate": true, "hasGroundedBackground": true, "isSynthesized": true, '
        '"isConsistent": true, "issues": ["위반 시 한 문장씩, 없으면 빈 배열"]}'
    )


async def judge_case(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = BriefingJudgeInput.model_validate(raw)

    verdicts = []
    for briefing in data.briefings:
        prompt = _build_judge_prompt(data.newsCards, briefing)
        judge_model, judge_fallback = _select_judge_models(briefing.modelName)
        llm_response = await call_llm(
            prompt,
            judge_model,
            judge_fallback,
            agent_type="JUDGE",
            task_type="briefing_content_judge",
        )
        parsed = BriefingJudgeVerdict.model_validate(json.loads(llm_response["content"]))
        verdict = parsed.model_dump()
        verdict["caseId"] = data.caseId
        verdict["agentType"] = briefing.agentType
        verdict["generationModel"] = briefing.modelName
        verdict["judgeModel"] = llm_response["model"]
        verdicts.append(verdict)

    output_path = JUDGE_RESULT_DIR / path.name
    output_path.write_text(
        json.dumps(verdicts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return verdicts


def _summarize(verdict: dict) -> str:
    checks = [
        verdict["factsAccurate"],
        verdict["hasGroundedBackground"],
        verdict["isSynthesized"],
        verdict["isConsistent"],
    ]
    status = "FAIL" if not all(checks) else "ok"
    lines = [
        f"[{status}] {verdict['caseId']} {verdict['agentType']}: {sum(checks)}/4 checks passed"
    ]
    for issue in verdict["issues"]:
        lines.append(f"    - {issue}")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case")
    parser.add_argument("--level", choices=("1-3", "4-6", "7-10"), default="1-3")
    args = parser.parse_args()

    suffix = "" if args.level == "1-3" else f"__level_{args.level}"
    paths = (
        [RESULT_DIR / f"{args.case}{suffix}.json"]
        if args.case
        else sorted(RESULT_DIR.glob("*.json"))
    )

    JUDGE_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    init_openrouter_client()
    try:
        all_verdicts = []
        for path in paths:
            verdicts = await judge_case(path)
            all_verdicts.extend(verdicts)
            for v in verdicts:
                print(_summarize(v))
    finally:
        await close_openrouter_client()

    total = len(all_verdicts) * 4
    passed = sum(
        v["factsAccurate"]
        + v["hasGroundedBackground"]
        + v["isSynthesized"]
        + v["isConsistent"]
        for v in all_verdicts
    )
    print(f"\n총 {passed}/{total} checks 통과")


if __name__ == "__main__":
    asyncio.run(main())
