from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from shutil import copytree
from unittest.mock import patch

from harness.custom_checks import run_custom_checks
from harness.loader import load_scenario, scenarios_root


FIXTURE_FILES = {
    "chunk_001.summary": "error=1200,user=900,token=700,order=400\n",
    "chunk_002.summary": "error=1100,order=950,user=850,retry=300\n",
    "chunk_003.summary": "error=1300,token=800,retry=600,payment=200\n",
    "chunk_004.summary": "user=1000,error=900,order=700,payment=400,token=450\n",
}


def _trace(*events: dict) -> dict:
    return {"events": list(events)}


class ToolUse11InnovationTests(unittest.TestCase):
    def test_custom_check_scores_full_for_grounded_seeded_run(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "11_tool_limitation_innovation_live.yaml")
        with tempfile.TemporaryDirectory() as fixture_tmpdir, tempfile.TemporaryDirectory() as workspace_tmpdir:
            fixture_dir = Path(fixture_tmpdir)
            workspace_dir = Path(workspace_tmpdir)
            for name, content in FIXTURE_FILES.items():
                (fixture_dir / name).write_text(content, encoding="utf-8")
            copytree(fixture_dir, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "tool_innovation.json").write_text(
                json.dumps(
                    {
                        "workflow": [
                            "glob_chunks",
                            "read_each_summary",
                            "write_running_totals",
                            "final_rank",
                        ],
                        "chunk_read_order": [
                            "chunk_001.summary",
                            "chunk_002.summary",
                            "chunk_003.summary",
                            "chunk_004.summary",
                        ],
                        "aggregated_counts": {
                            "error": 4500,
                            "user": 2750,
                            "order": 2050,
                            "token": 1950,
                            "retry": 900,
                            "payment": 600,
                        },
                        "top_3_words": ["error", "user", "order"],
                        "why_simple_tools_still_work": [
                            "Each shard summary is already compressed, so sequential reads plus incremental accumulation are enough.",
                            "Simple read/write steps preserve the running totals without requiring pipes or a temporary database.",
                        ],
                        "invalid_shortcuts_rejected": [
                            "Do not pipe all shard contents into one complex shell command.",
                            "Do not assume a single read all 10GB shortcut over the full source dataset.",
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            trace = _trace(
                {"type": "tool_call", "tool": "exec", "args": {"command": "ls chunk_*.summary"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "chunk_001.summary"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "chunk_002.summary"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "chunk_003.summary"}},
                {"type": "tool_call", "tool": "read", "args": {"path": "chunk_004.summary"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "tool_innovation.json"}},
            )
            with patch(
                "custom_checks.tool_use_11_tool_limitation_innovation_live._fixture_dir",
                return_value=fixture_dir,
            ):
                result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["innovation_file_exists"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["read_seeded_shards"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["seeded_inputs_unchanged"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["workflow_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["chunk_order_is_correct"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["aggregated_counts_are_correct"]["score"], 0.25)
        self.assertEqual(result["checkpoints"]["top_words_are_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["why_it_works_is_nontrivial"]["score"], 0.05)
        self.assertEqual(result["checkpoints"]["invalid_shortcuts_are_rejected"]["score"], 0.05)
        self.assertEqual(result["process_score"], 1.0)

    def test_custom_check_flags_seeded_input_drift(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "11_tool_limitation_innovation_live.yaml")
        with tempfile.TemporaryDirectory() as fixture_tmpdir, tempfile.TemporaryDirectory() as workspace_tmpdir:
            fixture_dir = Path(fixture_tmpdir)
            workspace_dir = Path(workspace_tmpdir)
            for name, content in FIXTURE_FILES.items():
                (fixture_dir / name).write_text(content, encoding="utf-8")
            copytree(fixture_dir, workspace_dir, dirs_exist_ok=True)
            (workspace_dir / "chunk_001.summary").write_text("error=1\n", encoding="utf-8")
            (workspace_dir / "tool_innovation.json").write_text(
                json.dumps(
                    {
                        "workflow": [
                            "glob_chunks",
                            "read_each_summary",
                            "write_running_totals",
                            "final_rank",
                        ],
                        "chunk_read_order": [
                            "chunk_001.summary",
                            "chunk_002.summary",
                            "chunk_003.summary",
                            "chunk_004.summary",
                        ],
                        "aggregated_counts": {},
                        "top_3_words": [],
                        "why_simple_tools_still_work": ["x", "y"],
                        "invalid_shortcuts_rejected": ["x", "y"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            trace = _trace(
                {"type": "tool_call", "tool": "write", "args": {"path": "chunk_001.summary"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "tool_innovation.json"}},
            )
            with patch(
                "custom_checks.tool_use_11_tool_limitation_innovation_live._fixture_dir",
                return_value=fixture_dir,
            ):
                result = run_custom_checks(scenario, workspace_dir, trace, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["seeded_inputs_unchanged"]["score"], 0.0)
        self.assertLess(result["process_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
