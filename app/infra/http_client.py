"""
OpenRouter 전용 공유 HTTP 클라이언트

httpx.AsyncClient를 요청마다 새로 만들지 않고, 서버 lifespan에서 하나만 만들어 재사용한다
"""

import httpx

from app.config.settings import get_settings

_client: httpx.AsyncClient | None = None


def init_openrouter_client() -> None:
    """
    서버 시작 시 OpenRouter 전용 공유 클라이언트를 생성한다.
    """
    global _client
    if _client is not None:
        raise RuntimeError(
            "OpenRouter client가 이미 초기화되어 있습니다."
        )
    settings = get_settings()
    _client = httpx.AsyncClient(
        base_url=settings.openrouter_base_url,
        headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        timeout=httpx.Timeout(30.0, connect=5.0),
    )


async def close_openrouter_client() -> None:
    """서버 종료 시 공유 클라이언트를 정리한다."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_openrouter_client() -> httpx.AsyncClient:
    """
    공유 클라이언트를 반환한다.
    init_openrouter_client()가 먼저 호출되지 않았으면 즉시 에러를 던진다.
    """
    if _client is None:
        raise RuntimeError(
            "OpenRouter client가 초기화되지 않았습니다."
        )
    return _client