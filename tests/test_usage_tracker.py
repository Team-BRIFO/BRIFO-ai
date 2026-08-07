"""
usage_tracker.py의 동시 쓰기 안전성 테스트.
브리핑은 사원 3명을 asyncio.gather로 동시 호출하므로 record_usage/record_cache_event가
여러 스레드에서 동시에 _write_log를 실행할 수 있다.
"""

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.infra import usage_tracker


class ConcurrentWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_many_concurrent_writes_produce_valid_jsonl(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "usage.jsonl"
            with patch.object(usage_tracker, "LOG_PATH", log_path):
                calls = [
                    usage_tracker.record_usage(
                        model_name=f"model-{i}",
                        agent_type="ROOKIE",
                        task_type="briefing",
                        input_tokens=i,
                        output_tokens=i,
                        latency_ms=1.0,
                    )
                    for i in range(50)
                ] + [
                    usage_tracker.record_cache_event(
                        agent_type="TANKER",
                        task_type="briefing",
                        cache_status="hit",
                        lookup_ms=1.0,
                    )
                    for _ in range(50)
                ]
                await asyncio.gather(*calls)

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 100)
            for line in lines:
                json.loads(line)


if __name__ == "__main__":
    unittest.main()
