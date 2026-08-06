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
from app.infra.openrouter_client import _MAX_OUTPUT_TOKENS, _try_model, call_llm


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
            patch.object(openrouter_client, "get_openrouter_client", return_value=client),
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


if __name__ == "__main__":
    unittest.main()