"""
POST /ai/briefing/generate — ROOKIE, TANKER, PRO 브리핑 생성 요청 처리
요청/응답 검증만 담당하며, 비즈니스 로직은 core/services에 위임한다.
"""

from fastapi import APIRouter

from app.core.services.briefing_service import generate_briefings
from app.schemas.briefing import BriefingGenerateRequest, BriefingGenerateResponse

# TODO: AI_INTERNAL_API_KEY 인증 의존성(api/deps.py) 준비되면 router에 연결
router = APIRouter(prefix="/ai/briefing", tags=["briefing"])


@router.post("/generate", response_model=BriefingGenerateResponse)
async def generate_briefing(request: BriefingGenerateRequest) -> BriefingGenerateResponse:
    result = await generate_briefings(request)
    return BriefingGenerateResponse(result=result)