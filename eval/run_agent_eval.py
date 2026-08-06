"""선별된 카드뉴스로 3개 사원 브리핑의 기준 결과를 생성한다."""

import asyncio
import argparse
import json
from pathlib import Path

from app.core.agents.briefing_api import generate_briefing
from app.core.agents.llm_router import select_briefing_model
from app.infra.http_client import close_openrouter_client, init_openrouter_client
from app.schemas.briefing import AgentType, NewsInput


ROOT = Path(__file__).resolve().parent
CARD_NEWS_DIR = ROOT / "results" / "card_news_baseline"
AGENT_CASE_DIR = ROOT / "agent_cases"
RESULT_DIR = ROOT / "results" / "agent_baseline"
CASE_IDS = (
    "02-mixed-numeric",
    "04-positive-no-numeric",
    "05-negative-no-numeric",
)
AGENT_TYPES: tuple[AgentType, ...] = ("ROOKIE", "TANKER", "PRO")
LEVEL_RANGES = ("1-3", "4-6", "7-10")


def load_news_cards(case_id: str) -> list[NewsInput]:
    agent_case_path = AGENT_CASE_DIR / f"{case_id}.json"
    if agent_case_path.exists():
        data = json.loads(agent_case_path.read_text(encoding="utf-8"))
        return [NewsInput.model_validate(card) for card in data["newsCards"]]

    data = json.loads((CARD_NEWS_DIR / f"{case_id}.json").read_text(encoding="utf-8"))
    return [
        NewsInput(
            cardId=f"{case_id}-{index}",
            headline=card["headline"],
            points=card["points"],
        )
        for index, card in enumerate(data["cardNews"], 1)
    ]


async def run_case(
    case_id: str,
    agent_types: tuple[AgentType, ...] = AGENT_TYPES,
    level_range: str = "1-3",
) -> None:
    news_cards = load_news_cards(case_id)
    results = []
    for agent_type in agent_types:
        primary, fallback = select_briefing_model(agent_type)
        briefing = await generate_briefing(news_cards, agent_type, level_range)
        result = briefing.model_dump(by_alias=True, mode="json")
        result["primaryModel"] = primary
        result["fallbackModel"] = fallback
        result["fallbackUsed"] = briefing.model_name != primary
        results.append(result)
        print(
            f"PASS {case_id} {agent_type} level={level_range} ({briefing.model_name})"
        )

    suffix = "" if level_range == "1-3" else f"__level_{level_range}"
    out_path = RESULT_DIR / f"{case_id}{suffix}.json"

    existing_briefings = []
    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        run_agent_types = {r["agentType"] for r in results}
        existing_briefings = [
            b
            for b in existing.get("briefings", [])
            if b["agentType"] not in run_agent_types
        ]

    output = {
        "caseId": case_id,
        "levelRange": level_range,
        "newsCards": [
            card.model_dump(by_alias=True, mode="json") for card in news_cards
        ],
        "briefings": existing_briefings + results,
    }
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        choices=CASE_IDS
        + (
            "06-pro-financial-metrics",
            "07-two-cards-mixed",
            "08-tanker-compound-risk",
            "09-rookie-multi-comparison",
        ),
    )
    parser.add_argument("--agent", choices=AGENT_TYPES)
    parser.add_argument("--level", choices=LEVEL_RANGES, default="1-3")
    args = parser.parse_args()
    case_ids = (args.case,) if args.case else CASE_IDS
    agent_types = (args.agent,) if args.agent else AGENT_TYPES

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    init_openrouter_client()
    try:
        for case_id in case_ids:
            await run_case(case_id, agent_types, args.level)
    finally:
        await close_openrouter_client()


if __name__ == "__main__":
    asyncio.run(main())
