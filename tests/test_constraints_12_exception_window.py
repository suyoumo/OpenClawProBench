from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from shutil import copytree

from harness.custom_checks import run_custom_checks
from harness.loader import load_scenario, scenarios_root


FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "datasets"
    / "constraints_12_exception_window"
    / "fixtures"
)


def _trace(*events: dict) -> dict:
    return {"events": list(events)}


class Constraints12ExceptionWindowTests(unittest.TestCase):
    def test_custom_check_flags_seeded_input_drift(self) -> None:
        scenario = load_scenario(scenarios_root() / "constraints" / "12_exception_window_live.yaml")
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "tasks.json").write_text(json.dumps({"windows": []}, ensure_ascii=False), encoding="utf-8")
            (workspace_dir / "change_schedule.json").write_text(
                json.dumps(
                    {
                        "slot_plan": [],
                        "deferred_tasks": [],
                        "total_value": 0,
                        "triggered_rules": [],
                        "notes": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            trace = _trace(
                {"type": "tool_call", "tool": "read", "args": {"path": "tasks.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "rules.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "output_contract.json"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "change_schedule.json"}},
            )
            result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["seeded_inputs_unchanged"]["score"], 0.0)
        total_score = sum(item["score"] for item in result["checkpoints"].values())
        self.assertLess(total_score, 0.5)


if __name__ == "__main__":
    unittest.main()
