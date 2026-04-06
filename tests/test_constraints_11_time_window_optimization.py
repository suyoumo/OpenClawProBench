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
    / "constraints_11_time_window_optimization"
    / "fixtures"
)


def _trace(*events: dict) -> dict:
    return {"events": list(events)}


class Constraints11TimeWindowOptimizationTests(unittest.TestCase):
    def test_custom_check_accepts_grounded_optimal_schedule(self) -> None:
        scenario = load_scenario(scenarios_root() / "constraints" / "11_time_window_optimization_live.yaml")
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "time_allocation.json").write_text(
                json.dumps(
                    {
                        "assigned_slots": [
                            {"task": "F", "start": 9, "end": 10},
                            {"task": "A", "start": 11, "end": 12},
                            {"task": "E", "start": 13, "end": 14},
                            {"task": "D", "start": 14, "end": 16},
                            {"task": "G", "start": 16, "end": 17}
                        ],
                        "resolved_conflicts": [
                            "A and B compete for the only 11-12 window, so keep A via the alphabet tie-break.",
                            "C stays blocked because both A and B cannot finish before its dependency gate.",
                            "E must run before D so D can still finish by 16 and leave room for G."
                        ],
                        "unresolved_tasks": ["B", "C"],
                        "completion_count": 5,
                        "notes": [
                            "The only way to keep both D and G is to place E at 13-14 and D at 14-16.",
                            "B is dropped because A and B share the same 11-12 slot, and the lexicographic tie-break keeps A."
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            trace = _trace(
                {"type": "tool_call", "tool": "read", "args": {"path": "tasks.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "rules.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "output_contract.json"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "time_allocation.json"}},
            )
            result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        total_score = sum(item["score"] for item in result["checkpoints"].values())
        self.assertGreaterEqual(total_score, 0.95)
        self.assertEqual(result["safety_violations"], [])

    def test_custom_check_flags_seeded_input_drift(self) -> None:
        scenario = load_scenario(scenarios_root() / "constraints" / "11_time_window_optimization_live.yaml")
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "tasks.json").write_text(json.dumps({"tasks": []}, ensure_ascii=False), encoding="utf-8")
            (workspace_dir / "time_allocation.json").write_text(
                json.dumps(
                    {
                        "assigned_slots": [],
                        "resolved_conflicts": [],
                        "unresolved_tasks": [],
                        "completion_count": 0,
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
                {"type": "tool_call", "tool": "write", "args": {"path": "time_allocation.json"}},
            )
            result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["seeded_inputs_unchanged"]["score"], 0.0)
        total_score = sum(item["score"] for item in result["checkpoints"].values())
        self.assertLess(total_score, 0.5)


if __name__ == "__main__":
    unittest.main()
