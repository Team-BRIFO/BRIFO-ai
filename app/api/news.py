"""
POST /ai/news/summarize — 카드뉴스 요약 요청 처리
요청/응답 검증만 담당하며, 비즈니스 로직은 core/services에 위임한다.
"""

from fastapi import APIRouter

from app.core.services.summary_service import summarize_news
from app.schemas.news import CardNewsGenerateRequest, CardNewsGenerateResponse

# TODO: AI_INTERNAL_API_KEY 인증 의존성(api/deps.py) 준비되면 router에 연결
router = APIRouter(prefix="/ai/news", tags=["news"])


@router.post("/summarize", response_model=CardNewsGenerateResponse)
async def summarize(request: CardNewsGenerateRequest) -> CardNewsGenerateResponse:
    result = await summarize_news(request)
    return CardNewsGenerateResponse(result=result)