"""
공유 의존성 주입
- Spring Boot 백엔드 인증(AI_INTERNAL_API_KEY 헤더) 검증
- 설정(Settings) 주입
"""

from fastapi import Depends, Header

from app.config.settings import Settings, get_settings
from app.exceptions import Unauthorized


async def verify_internal_api_key(
    ai_internal_api_key: str | None = Header(default=None, alias="AI_INTERNAL_API_KEY"),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    AI_INTERNAL_API_KEY 헤더가 설정된 내부 API 키와 일치하는지 검증한다.
    """
    if ai_internal_api_key != settings.internal_api_key:
        raise Unauthorized()