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

        with (
            patch.object(
                openrouter_client, "get_openrouter_client", return_value=client
            ),
            patch.object(openrouter_client, "record_usage", new=AsyncMock()),
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


class TryModelWithJsonRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_once_when_response_is_not_json(self):
        # 요청 payload 전체(재질문 문구·response_format 포함)를 검증해야 해서
        # 모델명만 담는 다른 테스트의 calls와 달리 payloads로 구분해 둔다
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

        # primary: 최초 시도 + JSON 재질문 1회, 이후 fallback 모델로 전환
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


if __name__ == "__main__":
    unittest.main()
