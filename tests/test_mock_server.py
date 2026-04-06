from __future__ import annotations

import unittest

from mock_tools.server import MockToolServer


class MockServerTests(unittest.TestCase):
    def test_error_then_success_and_audit_update(self) -> None:
        server = MockToolServer()
        server.set_scenario(
            {
                "fault_injection": [
                    {
                        "tool": "web_search",
                        "trigger": "ai safety",
                        "fault_type": "error_then_success",
                        "error_response": "rate limited",
                        "error_code": 429,
                        "success_after": 1,
                    }
                ],
                "mock_responses": {
                    "web_search": [
                        {
                            "trigger": "ai safety",
                            "response": {"items": ["paper-a", "paper-b"]},
                            "audit_updates": {"files.created": {"path": "search.log"}},
                        }
                    ]
                },
            }
        )

        first = server.call_tool("web_search", {"query": "ai safety"})
        second = server.call_tool("web_search", {"query": "ai safety"})

        self.assertEqual(first["status"], "error")
        self.assertEqual(first["status_code"], 429)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(server.get_audit()["files"]["created"][0]["path"], "search.log")


if __name__ == "__main__":
    unittest.main()
