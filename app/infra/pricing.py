"""
모델별 단가 기반 비용 추정
OpenRouter 모델 페이지 기준 1M 토큰당 USD 단가.
"""

# Pricing updated: 2026-08-07 (OpenRouter 모델 페이지 기준)
MODEL_PRICING_VERSION = "2026-08-07"

MODEL_PRICING: dict[str, dict[str, float]] = {
    "anthropic/claude-haiku-4.5": {
        "input_per_million_usd": 1.00,
        "output_per_million_usd": 5.00,
    },
    "anthropic/claude-sonnet-5": {
        "input_per_million_usd": 2.00,
        "output_per_million_usd": 10.00,
    },
    "openai/gpt-5.3-chat": {
        "input_per_million_usd": 1.75,
        "output_per_million_usd": 14.00,
    },
    "google/gemini-3.5-flash": {
        "input_per_million_usd": 1.50,
        "output_per_million_usd": 9.00,
    },
    "google/gemini-3.5-flash-lite": {
        "input_per_million_usd": 0.30,
        "output_per_million_usd": 2.50,
    },
    # 과거 로그(모델 교체 이전)의 비용 계산을 위해 유지. llm_router.py에서는 더 이상 쓰지 않음.
    "anthropic/claude-sonnet-4.6": {
        "input_per_million_usd": 3.00,
        "output_per_million_usd": 15.00,
    },
    "anthropic/claude-opus-4.8": {
        "input_per_million_usd": 5.00,
        "output_per_million_usd": 25.00,
    },
    "google/gemini-3-flash-preview": {
        "input_per_million_usd": 0.50,
        "output_per_million_usd": 3.00,
    },
    "google/gemini-3.1-pro-preview": {
        "input_per_million_usd": 2.00,
        "output_per_million_usd": 12.00,
    },
}


def calculate_estimated_cost_usd(
    model: str, input_tokens: int, output_tokens: int
) -> float | None:
    """
    단가표 기준 예상 비용(USD)을 계산한다.
    단가표에 없는 모델이면 계산할 수 없으므로 None을 반환한다.
    """
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        return None

    input_cost = input_tokens / 1_000_000 * pricing["input_per_million_usd"]
    output_cost = output_tokens / 1_000_000 * pricing["output_per_million_usd"]
    return input_cost + output_cost
