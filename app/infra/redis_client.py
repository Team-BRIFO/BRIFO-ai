"""
Redis 전용 공유 클라이언트

redis.asyncio.Redis를 요청마다 새로 만들지 않고, 서버 lifespan에서 하나만 만들어 재사용한다
"""

import redis.asyncio as redis

from app.config.settings import get_settings

_client: redis.Redis | None = None


def init_redis_client() -> None:
    """
    서버 시작 시 공유 Redis 클라이언트를 생성한다.
    """
    global _client
    if _client is not None:
        raise RuntimeError("Redis client가 이미 초기화되어 있습니다.")
    settings = get_settings()
    _client = redis.from_url(settings.redis_url, decode_responses=True)


async def close_redis_client() -> None:
    """서버 종료 시 공유 클라이언트를 정리한다."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_redis_client() -> redis.Redis:
    """
    공유 클라이언트를 반환한다.
    init_redis_client()가 먼저 호출되지 않았으면 즉시 에러를 던진다.
    """
    if _client is None:
        raise RuntimeError(
            "Redis client가 초기화되지 않았습니다. "
            "main.py의 lifespan에서 init_redis_client()를 호출했는지 확인하세요."
        )
    return _client
