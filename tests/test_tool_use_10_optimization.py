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
    / "frontier"
    / "tool_use_10_tool_optimization_live"
    / "fixtures"
)
EXPECTED_INPUTS = [
    "scan_scope.json",
    "tool_steps.json",
    "validation_policy.md",
    "hit_manifest.json",
    "hit_001.summary",
    "hit_002.summary",
    "hit_003.summary",
    "hit_004.summary",
    "hit_005.summary",
    "hit_006.summary",
]


def _trace(*events: dict) -> dict:
    return {"events": list(events)}


class ToolUse10OptimizationTests(unittest.TestCase):
    def test_custom_check_scores_full_for_grounded_seeded_run(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "10_tool_optimization_live.yaml")
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "tool_strategy.json").write_text(
                json.dumps(
                    {
                        "selected_pipeline": [
                            "glob_py_js",
                            "exec_union_candidates",
                            "read_validate_hits",
                            "write_report",
                        ],
                        "estimated_total_seconds": 9,
                        "estimated_peak_memory_gb": 0.4,
                        "true_positive_files": [
                            "src/auth/session.py",
                            "src/config/local.py",
                            "src/payments/stripe.py",
                        ],
                        "false_positive_files": [
                            "src/api/client.js",
                            "src/helpers/request.js",
                            "src/internal/debug.js",
                        ],
                        "why_not_alternatives": {
                            "exec_serial_all_files": "It is far slower because it scans every file three times with no recall gain.",
                            "exec_union_all_files": "It wastes time and memory by scanning all files instead of the filtered candidates.",
                            "exec_batched_candidates": "It keeps recall but adds unnecessary batched scan overhead.",
                        },
                        "validation_rule": "Treat hardcoded secrets and token values written into logs as true positives, but exclude process.env reads, comments, and template strings.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            read_events = [
                {"type": "tool_call", "tool": "read", "args": {"path": name}}
                for name in EXPECTED_INPUTS
            ]
            trace = _trace(
                *read_events,
                {"type": "tool_call", "tool": "write", "args": {"path": "tool_strategy.json"}},
            )
            result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["strategy_file_exists"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["read_seeded_inputs"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["seeded_inputs_unchanged"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["pipeline_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["time_and_memory_are_correct"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["true_positive_split_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["false_positive_split_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["alternative_rationale_is_complete"]["score"], 0.075)
        self.assertAlmostEqual(result["checkpoints"]["validation_rule_is_correct"]["score"], 0.075, places=6)
        self.assertEqual(result["process_score"], 1.0)

    def test_custom_check_flags_seeded_input_drift(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "10_tool_optimization_live.yaml")
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            copytree(FIXTURE_DIR, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "hit_003.summary").write_text(
                'path: src/payments/stripe.py\nsnippet: logger.info("token=%s", "redacted")\nnotes: drifted\n',
                encoding="utf-8",
            )
            (workspace_dir / "tool_strategy.json").write_text(
                json.dumps(
                    {
                        "selected_pipeline": [
                            "glob_py_js",
                            "exec_union_candidates",
                            "read_validate_hits",
                            "write_report",
                        ],
                        "estimated_total_seconds": 9,
                        "estimated_peak_memory_gb": 0.4,
                        "true_positive_files": [],
                        "false_positive_files": [],
                        "why_not_alternatives": {},
                        "validation_rule": "",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            trace = _trace(
                {"type": "tool_call", "tool": "read", "args": {"path": "scan_scope.json"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "hit_003.summary"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "tool_strategy.json"}},
            )
            result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["seeded_inputs_unchanged"]["score"], 0.0)
        self.assertLess(result["process_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
