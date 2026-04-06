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
    / "error_recovery_19_recovery_guardrail_order"
    / "fixtures"
)


def _trace(*events: dict) -> dict:
    return {"events": list(events)}


class ErrorRecovery19RecoveryGuardrailOrderTests(unittest.TestCase):
    def test_custom_check_handles_trailing_json_without_crashing(self) -> None:
        scenario = load_scenario(
            scenarios_root() / "error_recovery" / "19_recovery_guardrail_order_live.yaml"
        )
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "recovery_guardrail_order.json").write_text(
                '{\n'
                '  "action_order": [\n'
                '    "freeze_writes",\n'
                '    "restore_last_clean_config",\n'
                '    "reopen_safe_traffic"\n'
                '  ],\n'
                '  "blocked_actions": [\n'
                '    {"action": "replay_backlog_immediately", "reason": "must_wait_until_config_is_restored"}\n'
                '  ],\n'
                '  "governing_guardrail": "stabilize_state_before_reintroducing_risk",\n'
                '  "why_this_order": [\n'
                '    "write_freeze_reduces_further_risk"\n'
                '  ],\n'
                '  "evidence_refs": [\n'
                '    "recovery_actions.json"\n'
                '  ]\n'
                '}\n'
                '{"extra": true}\n',
                encoding="utf-8",
            )
            trace = _trace(
                {"type": "tool_call", "tool": "read", "args": {"path": "recovery_actions.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "system_risks.md"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "guardrail_order.yaml"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "incident_goal.json"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "recovery_guardrail_order.json"}},
            )
            result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["file_exists"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["order"]["score"], 0.0)
        self.assertEqual(result["checkpoints"]["refs"]["score"], 0.0)
        self.assertIn("malformed_json", result["checkpoints"]["order"]["detail"])

    def test_custom_check_handles_non_object_json_without_crashing(self) -> None:
        scenario = load_scenario(
            scenarios_root() / "error_recovery" / "19_recovery_guardrail_order_live.yaml"
        )
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "recovery_guardrail_order.json").write_text(
                '[{"action_order": ["freeze_writes"]}]',
                encoding="utf-8",
            )
            result = run_custom_checks(scenario, workspace_dir, _trace(), [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["file_exists"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["order"]["score"], 0.0)
        self.assertIn(
            "invalid_json_structure:list",
            result["checkpoints"]["order"]["detail"],
        )


if __name__ == "__main__":
    unittest.main()
