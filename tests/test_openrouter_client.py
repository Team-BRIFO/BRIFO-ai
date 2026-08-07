"""
openrouter_client.py의 max_tokens 지정 및 finish_reason=length 처리 테스트.
- 요청 payload에 max_tokens가 포함되는지
- finish_reason=length(응답 잘림)면 ValueError를 던져 fallback으로 재시도되는지
"""

import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.infra import openrouter_client
from app.infra.openrouter_client import (
    _MAX_OUTPUT_TOKENS,
    _try_model,
    _try_model_with_json_retry,
    call_llm,
)
from app.infra.pricing import calculate_estimated_cost_usd


def _choice(*, finish_reason: str = "stop", content: str = '{"ok": true}') -> dict:
    return {
        "model": "test-model",
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": content},
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _client_with_handler(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class TryModelMaxTokensTests(unittest.IsolatedAsyncioTestCase):
    async def test_payload_includes_max_tokens(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_choice())

        client = _client_with_handler(handler)
        await _try_model(client, "some-model", "prompt", require_json=True)

        self.assertEqual(captured["payload"]["max_tokens"], _MAX_OUTPUT_TOKENS)

    async def test_finish_reason_length_raises_value_error(self):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_choice(finish_reason="length"))

        client = _client_with_handler(handler)
        with self.assertRaises(ValueError):
            await _try_model(client, "some-model", "prompt", require_json=True)

    async def test_finish_reason_stop_succeeds(self):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_choice(finish_reason="stop"))

        client = _client_with_handler(handler)
        result = await _try_model(client, "some-model", "prompt", require_json=True)

        self.assertEqual(result["choices"][0]["message"]["content"], '{"ok": true}')


class CallLlmFallbackOnLengthTests(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_when_primary_response_is_truncated(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            calls.append(payload["model"])
            if payload["model"] == "primary-model":
                return httpx.Response(200, json=_choice(finish_reason="length"))
            return httpx.Response(200, json=_choice(finish_reason="stop"))

        client = _client_with_handler(handler)
        record_usage_mock = AsyncMock()

        with (
            patch.object(
                openrouter_client, "get_openrouter_client", return_value=client
            ),
            patch.object(openrouter_client, "record_usage", record_usage_mock),
        ):
            result = await call_llm(
                "prompt",
                "primary-model",
                "fallback-model",
                agent_type="ROOKIE",
                task_type="briefing",
            )

        self.assertEqual(calls, ["primary-model", "fallback-model"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["content"], '{"ok": true}')

        # 회귀 테스트: finish_reason=length로 잘린 primary 호출에서도 실제 소모된
        # 토큰(prompt=10, completion=5)이 유실되지 않고 fallback 토큰과 함께 누적돼야 함
        self.assertEqual(result["input_tokens"], 20)
        self.assertEqual(result["output_tokens"], 10)
        record_usage_mock.assert_awaited_once()
        _, record_kwargs = record_usage_mock.call_args
        self.assertEqual(record_kwargs["input_tokens"], 20)
        self.assertEqual(record_kwargs["output_tokens"], 10)
        self.assertEqual(record_kwargs["finish_reason"], "stop")


class TryModelWithJsonRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_once_when_response_is_not_json(self):
        payloads = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            payloads.append(payload)
            if len(payloads) == 1:
                return httpx.Response(
                    200, json=_choice(content="이것은 JSON이 아닙니다.")
                )
            return httpx.Response(200, json=_choice(content='{"ok": true}'))

        client = _client_with_handler(handler)
        attempt = await _try_model_with_json_retry(
            client, "some-model", "prompt", require_json=True
        )

        self.assertEqual(len(payloads), 2)
        self.assertEqual(
            payloads[1]["messages"][0]["content"],
            "prompt" + openrouter_client._JSON_RETRY_SUFFIX,
        )
        self.assertEqual(payloads[1]["response_format"], {"type": "json_object"})
        self.assertEqual(
            attempt.result["choices"][0]["message"]["content"], '{"ok": true}'
        )
        # 첫 시도(실패)와 재질문(성공) 두 응답의 토큰이 모두 누적돼야함
        self.assertEqual(attempt.prompt_tokens, 20)
        self.assertEqual(attempt.completion_tokens, 10)

    async def test_retries_when_response_is_json_array(self):
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            if request_count == 1:
                return httpx.Response(200, json=_choice(content="[]"))
            return httpx.Response(200, json=_choice(content='{"ok": true}'))

        client = _client_with_handler(handler)
        attempt = await _try_model_with_json_retry(
            client, "some-model", "prompt", require_json=True
        )

        self.assertEqual(request_count, 2)
        self.assertEqual(
            attempt.result["choices"][0]["message"]["content"], '{"ok": true}'
        )

    async def test_scalar_json_values_are_rejected(self):
        for content in ('"hello"', "123", "null", "true"):
            with self.subTest(content=content):
                self.assertFalse(openrouter_client._is_valid_json_object(content))

    async def test_raises_value_error_when_still_not_json_after_retry(self):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_choice(content="이것은 JSON이 아닙니다."))

        client = _client_with_handler(handler)
        with self.assertRaises(ValueError) as ctx:
            await _try_model_with_json_retry(
                client, "some-model", "prompt", require_json=True
            )

        # 실패했더라도 두 번의 호출에서 소모된 토큰은 예외에 담겨 있어야함
        self.assertEqual(ctx.exception.prompt_tokens, 20)
        self.assertEqual(ctx.exception.completion_tokens, 10)

    async def test_raises_value_error_when_retry_call_itself_raises(self):
        request_count = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            if request_count == 1:
                return httpx.Response(
                    200, json=_choice(content="이것은 JSON이 아닙니다.")
                )
            return httpx.Response(200, json=_choice(finish_reason="length"))

        client = _client_with_handler(handler)
        with self.assertRaises(ValueError) as ctx:
            await _try_model_with_json_retry(
                client, "some-model", "prompt", require_json=True
            )

        self.assertEqual(request_count, 2)
        # 회귀 테스트: 재질문 호출 자체가 예외를 던져도 첫 호출(10/5)의 토큰이
        # 유실되지 않고 재질문에서 소모된 토큰(10/5)과 합쳐져야 함
        self.assertEqual(ctx.exception.prompt_tokens, 20)
        self.assertEqual(ctx.exception.completion_tokens, 10)

    async def test_preserves_first_usage_when_json_retry_has_http_error(self):
        request_count = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            if request_count == 1:
                return httpx.Response(
                    200, json=_choice(content="이것은 JSON이 아닙니다.")
                )
            return httpx.Response(500, json={"error": "internal server error"})

        client = _client_with_handler(handler)
        with self.assertRaises(ValueError) as ctx:
            await _try_model_with_json_retry(
                client, "some-model", "prompt", require_json=True
            )

        self.assertEqual(request_count, 2)
        self.assertEqual(ctx.exception.prompt_tokens, 10)
        self.assertEqual(ctx.exception.completion_tokens, 5)

    async def test_does_not_retry_when_require_json_is_false(self):
        request_count = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(200, json=_choice(content="이것은 JSON이 아닙니다."))

        client = _client_with_handler(handler)
        attempt = await _try_model_with_json_retry(
            client, "some-model", "prompt", require_json=False
        )

        self.assertEqual(request_count, 1)
        self.assertEqual(
            attempt.result["choices"][0]["message"]["content"],
            "이것은 JSON이 아닙니다.",
        )

    async def test_no_retry_when_first_response_is_valid_json(self):
        request_count = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(200, json=_choice(content='{"ok": true}'))

        client = _client_with_handler(handler)
        await _try_model_with_json_retry(
            client, "some-model", "prompt", require_json=True
        )

        self.assertEqual(request_count, 1)


class CallLlmFallbackOnInvalidJsonTests(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_when_primary_never_returns_json(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            calls.append(payload["model"])
            if payload["model"] == "primary-model":
                return httpx.Response(
                    200, json=_choice(content="이것은 JSON이 아닙니다.")
                )
            return httpx.Response(200, json=_choice(content='{"ok": true}'))

        client = _client_with_handler(handler)
        record_usage_mock = AsyncMock()

        with (
            patch.object(
                openrouter_client, "get_openrouter_client", return_value=client
            ),
            patch.object(openrouter_client, "record_usage", record_usage_mock),
        ):
            result = await call_llm(
                "prompt",
                "primary-model",
                "fallback-model",
                agent_type="ROOKIE",
                task_type="briefing",
            )

        self.assertEqual(calls, ["primary-model", "primary-model", "fallback-model"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["content"], '{"ok": true}')

        # primary에서 낭비된 2번의 호출 + fallback 1번 호출이
        # 모두 최종 기록에 누적돼야함
        self.assertEqual(result["input_tokens"], 30)
        self.assertEqual(result["output_tokens"], 15)
        record_usage_mock.assert_awaited_once()
        _, record_kwargs = record_usage_mock.call_args
        self.assertEqual(record_kwargs["input_tokens"], 30)
        self.assertEqual(record_kwargs["output_tokens"], 15)
        self.assertEqual(record_kwargs["status"], "success")


class CallLlmFallbackOnBothFailingTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_wasted_usage_when_both_models_fail(self):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_choice(content="이것은 JSON이 아닙니다."))

        client = _client_with_handler(handler)
        record_usage_mock = AsyncMock()

        with (
            patch.object(
                openrouter_client, "get_openrouter_client", return_value=client
            ),
            patch.object(openrouter_client, "record_usage", record_usage_mock),
        ):
            with self.assertRaises(openrouter_client.AllModelsFailed):
                await call_llm(
                    "prompt",
                    "primary-model",
                    "fallback-model",
                    agent_type="ROOKIE",
                    task_type="briefing",
                )

        # 소모된 토큰은 에러 기록에도 누적돼야함
        record_usage_mock.assert_awaited_once()
        _, record_kwargs = record_usage_mock.call_args
        self.assertEqual(record_kwargs["input_tokens"], 40)
        self.assertEqual(record_kwargs["output_tokens"], 20)
        self.assertEqual(record_kwargs["status"], "error")


class MixedModelCostCalculationTests(unittest.IsolatedAsyncioTestCase):
    """
    primary와 fallback의 단가가 다를 때, 각 모델에서 실제로 소모된 토큰에
    그 모델의 단가를 각각 적용해 합산하는지 검증한다.
    """

    _PRIMARY_MODEL = "anthropic/claude-opus-4.8"
    _FALLBACK_MODEL = "google/gemini-3.1-pro-preview"

    def _expected_combined_cost(self) -> float:
        primary_cost = calculate_estimated_cost_usd(self._PRIMARY_MODEL, 10, 5)
        fallback_cost = calculate_estimated_cost_usd(self._FALLBACK_MODEL, 10, 5)
        return primary_cost + fallback_cost

    async def test_success_after_fallback_prices_each_model_separately(self):
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            model = payload["model"]
            if model == self._PRIMARY_MODEL:
                body = _choice(finish_reason="length")
            else:
                body = _choice(finish_reason="stop")
            body["model"] = model
            return httpx.Response(200, json=body)

        client = _client_with_handler(handler)
        record_usage_mock = AsyncMock()

        with (
            patch.object(
                openrouter_client, "get_openrouter_client", return_value=client
            ),
            patch.object(openrouter_client, "record_usage", record_usage_mock),
        ):
            await call_llm(
                "prompt",
                self._PRIMARY_MODEL,
                self._FALLBACK_MODEL,
                agent_type="TANKER",
                task_type="briefing",
            )

        record_usage_mock.assert_awaited_once()
        _, record_kwargs = record_usage_mock.call_args
        expected_cost = self._expected_combined_cost()
        # 전체 토큰(20/10)에 fallback 단가만 적용한 값과는 달라야 한다
        wrong_cost = calculate_estimated_cost_usd(self._FALLBACK_MODEL, 20, 10)
        self.assertNotAlmostEqual(record_kwargs["estimated_cost_usd"], wrong_cost)
        self.assertAlmostEqual(record_kwargs["estimated_cost_usd"], expected_cost)

    async def test_both_models_fail_prices_each_model_separately(self):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_choice(finish_reason="length"))

        client = _client_with_handler(handler)
        record_usage_mock = AsyncMock()

        with (
            patch.object(
                openrouter_client, "get_openrouter_client", return_value=client
            ),
            patch.object(openrouter_client, "record_usage", record_usage_mock),
        ):
            with self.assertRaises(openrouter_client.AllModelsFailed):
                await call_llm(
                    "prompt",
                    self._PRIMARY_MODEL,
                    self._FALLBACK_MODEL,
                    agent_type="TANKER",
                    task_type="briefing",
                )

        record_usage_mock.assert_awaited_once()
        _, record_kwargs = record_usage_mock.call_args
        expected_cost = self._expected_combined_cost()
        wrong_cost = calculate_estimated_cost_usd(self._FALLBACK_MODEL, 20, 10)
        self.assertNotAlmostEqual(record_kwargs["estimated_cost_usd"], wrong_cost)
        self.assertAlmostEqual(record_kwargs["estimated_cost_usd"], expected_cost)


if __name__ == "__main__":
    unittest.main()
