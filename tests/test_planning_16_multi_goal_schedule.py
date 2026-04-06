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
    / "planning_16_multi_goal_schedule"
    / "fixtures"
)


def _trace(*events: dict) -> dict:
    return {"events": list(events)}


class Planning16MultiGoalScheduleTests(unittest.TestCase):
    def test_custom_check_handles_malformed_json_without_crashing(self) -> None:
        scenario = load_scenario(scenarios_root() / "planning" / "16_multi_goal_schedule_live.yaml")
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "multi_goal_schedule.json").write_text(
                '{\n'
                '  "selected_plan": ["plan_beta", "plan_gamma", "plan_alpha"],\n'
                '  "rejected_plans": [\n'
                '    {"plan": "plan_delta", "reason": "misses_top_objective_customer_commitment"}\n'
                '  ],\n'
                '  "resource_allocation": [\n'
                '    {"window": "w1", "task": "customer_fix"}\n'
                '  ],\n'
                '  "governing_objective" "protect_customer_commitment_before_secondary_revenue_gain"\n'
                '}\n',
                encoding="utf-8",
            )
            trace = _trace(
                {"type": "tool_call", "tool": "read", "args": {"path": "work_items.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "resource_limits.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "business_objectives.md"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "planning_contract.json"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "multi_goal_schedule.json"}},
            )
            result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["file_exists"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["selected"]["score"], 0.0)
        self.assertEqual(result["checkpoints"]["refs"]["score"], 0.0)
        self.assertIn("malformed_json", result["checkpoints"]["selected"]["detail"])


if __name__ == "__main__":
    unittest.main()
