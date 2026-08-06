"""
카드뉴스 결과에 대해 정규식으로 못 잡는 내용 규칙을 LLM 판정으로 채점한다.

- 원문의 가능성/전망 표현을 확정 사실로 바꾸지 않았는가
- 원문에 긍정·부정 사실이 함께 있으면 point에서 한쪽을 누락하지 않았는가
- 수치·사실이 원문과 일치하는가 (지어내거나 왜곡하지 않았는가)

평가 대상 모델과 다른 모델을 심판으로 써서 자기 자신을 스스로 채점하는 편향을 피한다.
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.infra.http_client import close_openrouter_client, init_openrouter_client
from app.infra.openrouter_client import call_llm
from eval.run_card_news_eval import parse_source

ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "news_sources"
RESULT_DIR = ROOT / "results" / "card_news_baseline"
JUDGE_RESULT_DIR = ROOT / "results" / "card_news_judge"

_JUDGE_MODEL = "anthropic/claude-sonnet-5"
_JUDGE_FALLBACK = "openai/gpt-5.3-chat"


def _build_judge_prompt(article_title: str, article_body: str, card_news: list[dict]) -> str:
    cards_text = "\n\n".join(
        f"[카드 {i}] headline: {c['headline']}\n"
        + "\n".join(f"  - point {j}: {p}" for j, p in enumerate(c["points"], 1))
        for i, c in enumerate(card_news, 1)
    )
    return (
        "너는 주식 뉴스 요약 카드의 품질을 검수하는 심사자다. "
        "아래 뉴스 원문과, 그 원문을 요약한 카드뉴스 point들을 비교해 각 point를 채점하라.\n\n"
        f"# 뉴스 원문\n{article_title}\n\n{article_body}\n\n"
        f"# 생성된 카드뉴스\n{cards_text}\n\n"
        "각 point마다 다음 3개 항목을 판정한다:\n"
        "- factsAccurate: point의 수치·사실이 원문과 일치하고 지어내거나 왜곡한 내용이 없으면 true.\n"
        "- uncertaintyPreserved: 원문이 가능성·전망·관측으로 표현한 내용을 point가 확정된 사실처럼 "
        "단정해버렸다면 false. 원문 자체가 확정 사실이었다면 true.\n"
        "- factCoverageOk: point는 정확히 3개뿐이라 원문의 사소한 뉘앙스까지 다 담을 필요는 없다. "
        "다만 카드뉴스 전체를 봤을 때 원문의 전반적인 논조(긍정 우세/부정 우세/혼재)와 반대로 "
        "보이거나, 원문에서 가장 비중 있게 다뤄진 핵심 사실(수치로 뒷받침되는 실적처럼 기사 도입부에 "
        "명시된 사실)이 통째로 빠졌다면 false. 비중이 작은 부연 설명이나 후반부의 짧은 반대 언급 "
        "정도가 빠진 것은 false로 잡지 않는다.\n\n"
        "출력은 다른 설명 없이 아래 JSON 형식만 반환한다:\n"
        '{"points": [{"index": 1, "factsAccurate": true, "uncertaintyPreserved": true, '
        '"factCoverageOk": true, "issue": "위반 시 한 문장 설명, 없으면 빈 문자열"}], '
        '"overallNote": "전체에 대한 한 문장 코멘트"}'
    )


async def judge_case(path: Path) -> dict:
    article_title, article_body = "", ""
    md_path = SOURCE_DIR / f"{path.stem}.md"
    _, article_title, article_body = parse_source(md_path)

    data = json.loads(path.read_text(encoding="utf-8"))
    prompt = _build_judge_prompt(article_title, article_body, data["cardNews"])

    llm_response = await call_llm(
        prompt,
        _JUDGE_MODEL,
        _JUDGE_FALLBACK,
        agent_type="JUDGE",
        task_type="card_news_content_judge",
    )
    verdict = json.loads(llm_response["content"])
    verdict["caseId"] = path.stem
    verdict["judgeModel"] = llm_response["model"]

    output_path = JUDGE_RESULT_DIR / f"{path.stem}.json"
    output_path.write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return verdict


def _summarize(verdict: dict) -> str:
    total = len(verdict["points"])
    fails = [
        p
        for p in verdict["points"]
        if not (p["factsAccurate"] and p["uncertaintyPreserved"] and p["factCoverageOk"])
    ]
    status = "FAIL" if fails else "ok"
    lines = [f"[{status}] {verdict['caseId']}: {total - len(fails)}/{total} points clean"]
    for p in fails:
        lines.append(f"    point {p['index']}: {p['issue']}")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case")
    args = parser.parse_args()

    paths = (
        [RESULT_DIR / f"{args.case}.json"]
        if args.case
        else sorted(RESULT_DIR.glob("*.json"))
    )

    JUDGE_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    init_openrouter_client()
    try:
        verdicts = []
        for path in paths:
            verdict = await judge_case(path)
            verdicts.append(verdict)
            print(_summarize(verdict))
    finally:
        await close_openrouter_client()

    total_points = sum(len(v["points"]) for v in verdicts)
    clean_points = sum(
        1
        for v in verdicts
        for p in v["points"]
        if p["factsAccurate"] and p["uncertaintyPreserved"] and p["factCoverageOk"]
    )
    print(f"\n총 {clean_points}/{total_points} points가 3개 항목 모두 통과")


if __name__ == "__main__":
    asyncio.run(main())
