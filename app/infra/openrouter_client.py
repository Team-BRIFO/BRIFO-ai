"""
LLM 호출
primary 실패 시 fallback 으로 재시도.
"""


async def call_llm(prompt: str, primary_model: str, fallback_model: str) -> dict: ...
