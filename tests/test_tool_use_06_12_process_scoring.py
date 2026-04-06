from __future__ import annotations

import unittest

from custom_checks.tool_use_06_workspace_forensics_live import grade_process as grade_process_06
from custom_checks.tool_use_12_manifest_reconstruction_live import grade_process as grade_process_12


def _trace(*events: dict) -> dict:
    return {"events": list(events)}


class ToolUseProcessScoringTests(unittest.TestCase):
    def test_tool_use_06_accepts_file_and_file_path_args(self) -> None:
        trace = _trace(
            {"type": "tool_call", "tool": "read", "args": {"file_path": "/tmp/run/ticket.md"}},
            {
                "type": "tool_call",
                "tool": "read",
                "args": {"file": "/tmp/run/logs/checkout/app-2026-03-20.log"},
            },
            {
                "type": "tool_call",
                "tool": "read",
                "args": {"file": "/tmp/run/logs/billing/alerts.log"},
            },
        )
        self.assertEqual(grade_process_06(trace), 1.0)

    def test_tool_use_12_accepts_file_and_file_path_args(self) -> None:
        trace = _trace(
            {"type": "tool_call", "tool": "read", "args": {"file": "/tmp/run/brief.md"}},
            {
                "type": "tool_call",
                "tool": "read",
                "args": {"file_path": "/tmp/run/manifests/base_manifest.json"},
            },
            {"type": "tool_call", "tool": "read", "args": {"file": "/tmp/run/patches/patch_01.md"}},
            {"type": "tool_call", "tool": "read", "args": {"file": "/tmp/run/hotfixes.txt"}},
            {"type": "tool_call", "tool": "read", "args": {"file": "/tmp/run/rollback_notes.md"}},
        )
        self.assertEqual(grade_process_12(trace), 1.0)


if __name__ == "__main__":
    unittest.main()
