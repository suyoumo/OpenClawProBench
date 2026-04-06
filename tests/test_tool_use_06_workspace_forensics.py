from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from shutil import copytree

from harness.custom_checks import run_custom_checks
from harness.loader import load_scenario, scenarios_root


FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "datasets"
    / "frontier"
    / "tool_use_06_workspace_forensics_live"
    / "fixtures"
)


def _trace(*events: dict) -> dict:
    return {"events": list(events)}


class ToolUse06WorkspaceForensicsTests(unittest.TestCase):
    def test_custom_check_handles_non_object_summary_without_crashing(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "06_workspace_forensics_live.yaml")
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "incident_summary.json").write_text(
                '[{"incident_id": "INC-4821"}]\n',
                encoding="utf-8",
            )
            (workspace_dir / "evidence.txt").write_text(
                "2026-03-20T01:10:00Z | C104 | checkout | PAYMENT_TIMEOUT\n",
                encoding="utf-8",
            )
            trace = _trace(
                {"type": "tool_call", "tool": "read", "args": {"path": "ticket.md"}},
                {
                    "type": "tool_call",
                    "tool": "read",
                    "args": {"path": "logs/checkout/app-2026-03-20.log"},
                },
                {
                    "type": "tool_call",
                    "tool": "read",
                    "args": {"path": "logs/billing/alerts.log"},
                },
                {"type": "tool_call", "tool": "write", "args": {"path": "incident_summary.json"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "evidence.txt"}},
            )
            result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["summary_exists"]["score"], 0.08)
        self.assertEqual(result["checkpoints"]["evidence_exists"]["score"], 0.08)
        self.assertEqual(result["checkpoints"]["summary_content"]["score"], 0.0)
        self.assertEqual(result["checkpoints"]["source_files_are_correct"]["score"], 0.0)
        self.assertEqual(result["checkpoints"]["evidence_lines_match"]["score"], 0.0)
        self.assertEqual(result["checkpoints"]["counts_and_severity_are_correct"]["score"], 0.0)
        self.assertIn(
            "invalid summary structure",
            result["checkpoints"]["summary_content"]["detail"],
        )


if __name__ == "__main__":
    unittest.main()
