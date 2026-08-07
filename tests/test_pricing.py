"""
pricing.py의 모델 단가 기반 비용 계산 테스트.
"""

import unittest

from app.infra.pricing import calculate_estimated_cost_usd


class CalculateEstimatedCostUsdTests(unittest.TestCase):
    def test_computes_cost_for_known_model(self):
        cost = calculate_estimated_cost_usd(
            "anthropic/claude-haiku-4.5", input_tokens=1_000_000, output_tokens=1_000_000
        )
        self.assertAlmostEqual(cost, 1.00 + 5.00)

    def test_zero_tokens_is_zero_cost(self):
        cost = calculate_estimated_cost_usd("anthropic/claude-sonnet-4.6", 0, 0)
        self.assertEqual(cost, 0.0)

    def test_unknown_model_returns_none(self):
        cost = calculate_estimated_cost_usd("unknown/model", 1000, 1000)
        self.assertIsNone(cost)


if __name__ == "__main__":
    unittest.main()
