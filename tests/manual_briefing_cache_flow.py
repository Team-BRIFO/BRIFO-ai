"""
카드뉴스 요약 캐싱 -> 브리핑 프롬프트 연동을 실제 Redis + 실제 OpenRouter LLM 호출로 검증하는
수동 통합 테스트. `test_*.py`가 아니라서 `unittest discover`에는 잡히지 않는다 (자동 실행 시
실제 LLM 과금이 발생하는 걸 막기 위함).

사전 준비:
1. 로컬 Redis 실행 (.env의 REDIS_URL과 포트를 맞출 것):
   docker run --rm -d -p 6379:6379 redis:7-alpine
2. .env에 OPENROUTER_API_KEY / AI_INTERNAL_API_KEY가 유효하게 설정되어 있어야 한다.

실행:
    uv run python -m tests.manual_briefing_cache_flow

테스트 시나리오:
1. POST /ai/news/summarize 호출 -> 카드뉴스 생성 (Redis에 캐싱됨)
2. POST /ai/briefing/generate 호출 -> 브리핑 생성
3. 1에서 생성된 카드뉴스(headline/points)가 2번 브리핑 생성에 실제로 반영됐는지 확인
   (요청 body에는 일부러 다른 headline/points를 보내서, 캐시가 그걸 덮어쓰는지 확인한다)

주의: OpenRouter LLM을 실제로 2번(카드뉴스 요약 1회 + 브리핑 생성 3회, ROOKIE/TANKER/PRO) 호출하므로
비용이 발생한다.
"""

import asyncio
import json

from httpx import ASGITransport, AsyncClient

from app.config.settings import get_settings
from app.core.services import briefing_service
from app.main import app
from app.schemas.briefing import NewsInput

SUMMARIZE_REQUEST_BODY = {
    "newsId": "news_12345",
    "stockName": "삼성전자",
    "newsContent": (
        "삼성전자가 3분기 잠정 실적을 발표하며 매출 79조원, 영업이익 10조원을 기록했다고 "
        "밝혔다. 이는 시장 컨센서스를 상회하는 수치로, 메모리 반도체 가격 상승과 AI 서버향 "
        "수요 증가가 실적 개선을 견인한 것으로 분석된다. 회사 측은 4분기에도 이 같은 호조세가 "
        "이어질 것으로 전망했다."
    ),
    "excludeTerms": ["공매도", "PER"],
}

BRIEFING_REQUEST_BODY = {
    "newsCard": [
        {
            "cardId": "card_20250721",
            "newsId": "news_12345",
            "headline": "삼성전자, 3분기 반도체 실적 시장 예상치 상회",
            "points": [
                "메모리 반도체 가격 상승세가 실적 개선을 견인",
                "AI 서버향 수요 증가로 4분기 전망도 긍정적",
                "외국인 투자자 순매수 전환 조짐",
            ],
        }
    ],
    "userId": "user_789",
    "agentTypes": ["ROOKIE", "TANKER", "PRO"],
    "levelRange": "1-3",
    "recentDecisions": [
        {
            "stockName": "SK하이닉스",
            "direction": "NEUTRAL",
            "confidence": 3,
            "isCorrect": True,
            "actualChange": -1.2,
        },
        {
            "stockName": "카카오",
            "direction": "UP",
            "confidence": 4,
            "isCorrect": False,
            "actualChange": -3.5,
        },
        {
            "stockName": "네이버",
            "direction": "DOWN",
            "confidence": 2,
            "isCorrect": True,
            "actualChange": -1.2,
        },
    ],
}


def _print_json(title: str, payload: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


async def main() -> None:
    settings = get_settings()
    headers = {"AI_INTERNAL_API_KEY": settings.internal_api_key}

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. 카드뉴스 요약 생성 -> summary:{newsId}:* 및 summary:latest:{newsId}에 캐싱됨
            summarize_res = await client.post(
                "/ai/news/summarize", json=SUMMARIZE_REQUEST_BODY, headers=headers
            )
            _print_json(
                f"1. POST /ai/news/summarize ({summarize_res.status_code})",
                summarize_res.json(),
            )
            summarize_res.raise_for_status()

            cached_card = summarize_res.json()["result"]["cardNews"][0]
            print(f"\n[캐시에 저장된 headline] {cached_card['headline']!r}")
            print(f"[캐시에 저장된 points]   {cached_card['points']!r}")

            # 2. 브리핑 생성 API 호출 (요청 body의 headline/points는 위 캐시 내용과 다름)
            briefing_res = await client.post(
                "/ai/briefing/generate", json=BRIEFING_REQUEST_BODY, headers=headers
            )
            _print_json(
                f"2. POST /ai/briefing/generate ({briefing_res.status_code})",
                briefing_res.json(),
            )
            briefing_res.raise_for_status()

            # 3. 캐시 연동 로직(_resolve_news_card)을 직접 호출해서, 요청 body의 headline/points가
            #    아니라 1번에서 캐싱된 headline/points가 브리핑 프롬프트에 반영됐는지 결정적으로 확인
            request_card = NewsInput(**BRIEFING_REQUEST_BODY["newsCard"][0])
            resolved = await briefing_service._resolve_news_card(request_card)
            _print_json(
                "3. _resolve_news_card() 직접 호출 결과 (요청 body 값 vs 캐시 반영 값 비교)",
                {
                    "요청_body_headline": request_card.headline,
                    "요청_body_points": request_card.points,
                    "브리핑_프롬프트에_실제_반영된_headline": resolved.headline,
                    "브리핑_프롬프트에_실제_반영된_points": resolved.points,
                },
            )

            if resolved.headline == cached_card["headline"]:
                print(
                    "\n[OK] 브리핑 프롬프트에 1번에서 생성된 카드뉴스 캐시가 정상 반영되었습니다."
                )
            else:
                print(
                    "\n[FAIL] 브리핑 프롬프트가 캐시가 아니라 요청 body 값을 그대로 사용했습니다."
                )


if __name__ == "__main__":
    asyncio.run(main())
