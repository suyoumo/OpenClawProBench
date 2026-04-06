from __future__ import annotations

import unittest

from harness.trace import normalize_trace


class TraceTests(unittest.TestCase):
    def test_normalize_trace_classifies_live_usage_cache_fields(self) -> None:
        trace = normalize_trace(
            [
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "usage": {
                            "input": 100,
                            "output": 20,
                            "cacheRead": 300,
                            "cacheWrite": 40,
                            "totalTokens": 460,
                            "cost": {"total": 1.25},
                        },
                        "content": [{"type": "text", "text": "done"}],
                    },
                }
            ]
        )

        self.assertEqual(trace["metrics"]["assistant_turns"], 1)
        self.assertEqual(trace["metrics"]["input_tokens"], 100)
        self.assertEqual(trace["metrics"]["output_tokens"], 20)
        self.assertEqual(trace["metrics"]["cache_read_tokens"], 300)
        self.assertEqual(trace["metrics"]["cache_write_tokens"], 40)
        self.assertEqual(trace["metrics"]["total_tokens"], 460)
        self.assertEqual(trace["metrics"]["cost_usd"], 1.25)
    def test_normalize_trace_accepts_openai_style_usage_and_string_values(self) -> None:
        trace = normalize_trace(
            [
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "usage": {
                            "prompt_tokens": "120",
                            "completion_tokens": "30",
                            "cache_creation_input_tokens": "10",
                            "cached_tokens": "5",
                        },
                        "content": [{"type": "text", "text": "done"}],
                    },
                }
            ]
        )

        self.assertEqual(trace["metrics"]["input_tokens"], 120)
        self.assertEqual(trace["metrics"]["output_tokens"], 30)
        self.assertEqual(trace["metrics"]["cache_read_tokens"], 5)
        self.assertEqual(trace["metrics"]["cache_write_tokens"], 10)
        self.assertEqual(trace["metrics"]["total_tokens"], 165)

    def test_normalize_trace_accepts_flat_message_entries(self) -> None:
        trace = normalize_trace(
            [
                {
                    "role": "assistant",
                    "usage": {"input": 12, "output": 8, "total": 20},
                    "content": [{"type": "text", "text": "ok"}],
                }
            ]
        )

        self.assertEqual(trace["metrics"]["assistant_turns"], 1)
        self.assertEqual(trace["metrics"]["input_tokens"], 12)
        self.assertEqual(trace["metrics"]["output_tokens"], 8)
        self.assertEqual(trace["metrics"]["total_tokens"], 20)

    def test_normalize_trace_estimates_usage_when_provider_usage_is_all_zero(self) -> None:
        trace = normalize_trace(
            [
                {
                    "type": "message",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "请检查 release_request.md 并给出结论。"}],
                    },
                },
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0},
                        "content": [
                            {"type": "thinking", "thinking": "先列目录确认相关文件。"},
                            {"type": "toolCall", "name": "exec", "arguments": {"command": "ls -la"}},
                        ],
                    },
                },
                {
                    "type": "message",
                    "message": {
                        "role": "toolResult",
                        "toolName": "exec",
                        "content": [{"type": "text", "text": "release_request.md\napprovals.json\n"}],
                    },
                },
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0},
                        "content": [{"type": "text", "text": "已确认文件，接下来读取 release_request.md。"}],
                    },
                },
            ],
            session_metadata={"systemPromptReport": {"systemPrompt": {"chars": 1200}}},
        )

        self.assertEqual(trace["metrics"]["assistant_turns"], 2)
        self.assertGreater(trace["metrics"]["input_tokens"], 0)
        self.assertGreater(trace["metrics"]["output_tokens"], 0)
        self.assertGreater(trace["metrics"]["cache_read_tokens"], 0)
        self.assertEqual(
            trace["metrics"]["total_tokens"],
            trace["metrics"]["input_tokens"]
            + trace["metrics"]["output_tokens"]
            + trace["metrics"]["cache_read_tokens"],
        )
        self.assertEqual(trace["audit_state"]["usage_fallback"]["mode"], "transcript_estimate")
        self.assertEqual(trace["audit_state"]["usage_fallback"]["reason"], "provider_usage_all_zero")


if __name__ == "__main__":
    unittest.main()
