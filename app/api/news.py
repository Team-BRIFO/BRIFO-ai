"""
POST /ai/news/summarize — 카드뉴스 요약 요청 처리
요청/응답 검증만 담당하며, 비즈니스 로직은 core/services에 위임한다.
"""

from fastapi import APIRouter, Depends

from app.api.deps import verify_internal_api_key
from app.core.services.summary_service import summarize_news
from app.schemas.news import CardNewsGenerateRequest, CardNewsGenerateResponse

router = APIRouter(
    prefix="/ai/news", tags=["news"], dependencies=[Depends(verify_internal_api_key)]
)


@router.post("/summarize", response_model=CardNewsGenerateResponse)
async def summarize(request: CardNewsGenerateRequest) -> CardNewsGenerateResponse:
    result = await summarize_news(request)
    return CardNewsGenerateResponse(result=result)