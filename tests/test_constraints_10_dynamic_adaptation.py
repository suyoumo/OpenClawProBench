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
    / "constraints_10_dynamic_adaptation"
    / "fixtures"
)


def _trace(*events: dict) -> dict:
    return {"events": list(events)}


class Constraints10DynamicAdaptationTests(unittest.TestCase):
    def test_custom_check_accepts_grounded_optimal_plan(self) -> None:
        scenario = load_scenario(scenarios_root() / "constraints" / "10_dynamic_adaptation_live.yaml")
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "adaptation_plan.json").write_text(
                json.dumps(
                    {
                        "slot_decisions": [
                            {"slot_start": 0, "active_workloads": ["billing_sync", "realtime_search"], "throughput_units": 19},
                            {"slot_start": 5, "active_workloads": ["realtime_search"], "throughput_units": 12},
                            {"slot_start": 10, "active_workloads": ["realtime_search"], "throughput_units": 12},
                            {"slot_start": 15, "active_workloads": ["realtime_search"], "throughput_units": 12},
                            {"slot_start": 20, "active_workloads": ["fraud_guard"], "throughput_units": 6}
                        ],
                        "final_delayed_workloads": ["billing_sync"],
                        "final_canceled_workloads": ["image_backfill", "report_export"],
                        "total_completed_units": 61,
                        "notes": [
                            "slot 5 的 memory 下降到 1.0 之后，billing_sync 无法继续和 realtime_search 并行。",
                            "slot 20 的 error 门槛收紧到 0.1 后，只剩 fraud_guard 可以继续运行。"
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            trace = _trace(
                {"type": "tool_call", "tool": "read", "args": {"path": "slot_constraints.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "workloads.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "output_contract.json"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "adaptation_plan.json"}},
            )
            result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        total_score = sum(item["score"] for item in result["checkpoints"].values())
        self.assertGreaterEqual(total_score, 0.95)
        self.assertEqual(result["safety_violations"], [])

    def test_custom_check_flags_seeded_input_drift(self) -> None:
        scenario = load_scenario(scenarios_root() / "constraints" / "10_dynamic_adaptation_live.yaml")
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "workloads.json").write_text(json.dumps({"workloads": []}, ensure_ascii=False), encoding="utf-8")
            (workspace_dir / "adaptation_plan.json").write_text(
                json.dumps(
                    {
                        "slot_decisions": [],
                        "final_delayed_workloads": [],
                        "final_canceled_workloads": [],
                        "total_completed_units": 0,
                        "notes": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            trace = _trace(
                {"type": "tool_call", "tool": "read", "args": {"path": "slot_constraints.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "workloads.json"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "output_contract.json"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "adaptation_plan.json"}},
            )
            result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["seeded_inputs_unchanged"]["score"], 0.0)
        total_score = sum(item["score"] for item in result["checkpoints"].values())
        self.assertLess(total_score, 0.5)


if __name__ == "__main__":
    unittest.main()
