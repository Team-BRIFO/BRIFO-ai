"""
POST /ai/briefing/generate — ROOKIE, TANKER, PRO 브리핑 생성 요청 처리
요청/응답 검증만 담당하며, 비즈니스 로직은 core/services에 위임한다.
"""

from fastapi import APIRouter, Depends

from app.api.deps import verify_internal_api_key
from app.core.services.briefing_service import generate_briefings
from app.schemas.briefing import BriefingGenerateRequest, BriefingGenerateResponse

router = APIRouter(
    prefix="/ai/briefing", tags=["briefing"], dependencies=[Depends(verify_internal_api_key)]
)


@router.post("/generate", response_model=BriefingGenerateResponse)
async def generate_briefing(request: BriefingGenerateRequest) -> BriefingGenerateResponse:
    result = await generate_briefings(request)
    return BriefingGenerateResponse(result=result)