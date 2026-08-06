"""카드뉴스 요약 프롬프트의 수동 평가 세트를 실행한다."""

import asyncio
import json
import re
from pathlib import Path

from app.core.agents.llm_router import select_summary_model
from app.core.services.summary_service import _build_prompt, _parse_card_news
from app.infra.http_client import close_openrouter_client, init_openrouter_client
from app.infra.openrouter_client import call_llm
from app.schemas.news import CardNewsGenerateRequest


ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "news_sources"
RESULT_DIR = ROOT / "results" / "card_news_baseline"


def parse_source(path: Path) -> tuple[str, str, str]:
    text = path.read_text(encoding="utf-8")
    stock_match = re.search(r"^- 종목명:\s*(.+)$", text, re.MULTILINE)
    title_match = re.search(
        r"^# 기사 제목\s*\n+(.+?)\n+(?=^# 뉴스 원문)", text, re.MULTILINE | re.DOTALL
    )
    content_match = re.search(
        r"^# 뉴스 원문\s*\n+(.+)\Z", text, re.MULTILINE | re.DOTALL
    )
    if not (stock_match and title_match and content_match):
        raise ValueError(f"지원하지 않는 테스트 파일 형식: {path.name}")

    return (
        stock_match.group(1).strip(),
        title_match.group(1).strip(),
        content_match.group(1).strip(),
    )


async def run_case(path: Path) -> None:
    stock_name, article_title, article_body = parse_source(path)
    request = CardNewsGenerateRequest(
        newsId=path.stem,
        stockName=stock_name,
        newsContent=f"{article_title}\n\n{article_body}",
        excludeTerms=[],
    )
    primary, fallback = select_summary_model()
    llm_response = await call_llm(
        _build_prompt(request),
        primary,
        fallback,
        agent_type="SUMMARY",
        task_type="news_summary_eval",
    )
    parsed = _parse_card_news(llm_response)
    result = {
        "caseId": path.stem,
        "stockName": stock_name,
        "primaryModel": primary,
        "fallbackModel": fallback,
        "usedModel": llm_response["model"],
        "fallbackUsed": llm_response["fallback_used"],
        "cardNews": [item.model_dump(mode="json") for item in parsed],
    }
    output_path = RESULT_DIR / f"{path.stem}.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"PASS {path.name} -> {output_path.name} ({llm_response['model']})")


async def main() -> None:
    paths = sorted(SOURCE_DIR.glob("*.md"))
    if not paths:
        raise RuntimeError(f"테스트 파일이 없습니다: {SOURCE_DIR}")

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    init_openrouter_client()
    try:
        for path in paths:
            await run_case(path)
    finally:
        await close_openrouter_client()


if __name__ == "__main__":
    asyncio.run(main())
