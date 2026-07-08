"""
Redis 캐싱
공통 분석 + 개인화 레이어 코멘트 - TTL 24h
"""


# 공통 분석: briefing:{news_id}:{agent_type}:{level_range} — 전역 공유
async def get_briefing(
    news_id: str, agent_type: str, level_range: str
) -> dict | None: ...


async def set_briefing(
    news_id: str, agent_type: str, level_range: str, value: dict
) -> None: ...


# 개인화 레이어: briefing:personal:{user_id}:{briefing_id} — 유저별
async def get_personal(user_id: str, briefing_id: str) -> str | None: ...


async def set_personal(user_id: str, briefing_id: str, value: str) -> None: ...
