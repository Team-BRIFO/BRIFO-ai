"""
GET /ai/health — 서버 상태 확인
"""

from fastapi import APIRouter

router = APIRouter(prefix="/ai", tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    return {"isSuccess": True, "code": "COMMON200", "message": "OK", "result": None}
