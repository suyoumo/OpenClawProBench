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
    / "constraints_16_compound_guardrail_selection"
    / "fixtures"
)


def _trace(*events: dict) -> dict:
    return {"events": list(events)}


class Constraints16CompoundGuardrailSelectionTests(unittest.TestCase):
    def test_custom_check_handles_malformed_json_without_crashing(self) -> None:
        scenario = load_scenario(scenarios_root() / "constraints" / "16_compound_guardrail_selection_live.yaml")
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "guardrail_selection.json").write_text(
                '{\n'
                '  "allowed_selection": ["item_a", "item_d"],\n'
                '  "blocked_items": [\n'
                '    {"item": "item_b", "reason": "fails_guardrail_region_limit"}\n'
                '  ],\n'
                '  "budget_used": 9,\n'
                '  "governing_guardrail": "only_budget_fit_items_passing_all_guardrails"\n'
                '}\n'
                '{"extra": true}\n',
                encoding="utf-8",
            )
            trace = _trace(
                {"type": "tool_call", "tool": "read", "args": {"path": "candidate_set.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "guardrails.md"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "eligibility_rules.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "selection_budget.txt"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "guardrail_selection.json"}},
            )
            result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["file_exists"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["allowed"]["score"], 0.0)
        self.assertEqual(result["checkpoints"]["refs"]["score"], 0.0)
        self.assertIn("malformed_json", result["checkpoints"]["allowed"]["detail"])


if __name__ == "__main__":
    unittest.main()
