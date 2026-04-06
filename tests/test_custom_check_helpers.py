from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harness.custom_check_helpers import (
    file_exists_checkpoint,
    load_json_output,
    seeded_inputs_unchanged,
    skip_checkpoints,
    tool_arg_paths,
)


class CustomCheckHelpersTests(unittest.TestCase):
    def test_file_exists_checkpoint_and_skip_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "artifact.json"
            path.write_text("{}", encoding="utf-8")
            checkpoints: dict[str, dict[str, object]] = {}

            exists = file_exists_checkpoint(
                checkpoints,
                "artifact_exists",
                path,
                max_score=0.2,
            )
            skip_checkpoints(checkpoints, [("dependent", 0.4)])

        self.assertTrue(exists)
        self.assertEqual(checkpoints["artifact_exists"]["score"], 0.2)
        self.assertEqual(checkpoints["artifact_exists"]["detail"], "artifact.json exists")
        self.assertEqual(checkpoints["dependent"]["detail"], "skipped")

    def test_load_json_output_returns_detail_for_missing_invalid_and_valid_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "missing.json"
            invalid_path = Path(tmpdir) / "invalid.json"
            valid_path = Path(tmpdir) / "valid.json"
            invalid_path.write_text("{", encoding="utf-8")
            valid_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

            missing_payload, missing_detail = load_json_output(missing_path)
            invalid_payload, invalid_detail = load_json_output(invalid_path)
            valid_payload, valid_detail = load_json_output(valid_path)

        self.assertIsNone(missing_payload)
        self.assertIn("missing missing.json", missing_detail)
        self.assertIsNone(invalid_payload)
        self.assertIn("invalid JSON", invalid_detail)
        self.assertEqual(valid_payload, {"ok": True})
        self.assertEqual(valid_detail, "loaded valid.json")

    def test_tool_arg_paths_filters_and_can_return_basenames(self) -> None:
        trace = {
            "events": [
                {"type": "tool_call", "tool": "read", "args": {"path": "logs/system.log"}},
                {"type": "tool_call", "tool": "Read", "args": {"file_path": "data\\config.yaml"}},
                {"type": "tool_call", "tool": "read", "args": {"file": "docs/notes.txt"}},
                {"type": "tool_call", "tool": "write", "args": {"path": "outputs/result.json"}},
            ]
        }

        self.assertEqual(
            tool_arg_paths(trace, tool_name="read"),
            {"logs/system.log", "data/config.yaml", "docs/notes.txt"},
        )
        self.assertEqual(
            tool_arg_paths(trace, tool_name="write", basename=True),
            {"result.json"},
        )

    def test_seeded_inputs_unchanged_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixture_dir = root / "fixtures"
            workspace_dir = root / "workspace"
            fixture_dir.mkdir()
            workspace_dir.mkdir()
            (fixture_dir / "input.txt").write_text("expected", encoding="utf-8")
            (workspace_dir / "input.txt").write_text("expected", encoding="utf-8")

            ok, detail = seeded_inputs_unchanged(workspace_dir, fixture_dir, {"input.txt"})
            (workspace_dir / "input.txt").write_text("drifted", encoding="utf-8")
            drift_ok, drift_detail = seeded_inputs_unchanged(workspace_dir, fixture_dir, {"input.txt"})

        self.assertTrue(ok)
        self.assertEqual(detail, "seeded inputs are present and unchanged")
        self.assertFalse(drift_ok)
        self.assertIn("input.txt drifted from the seeded fixture", drift_detail)


if __name__ == "__main__":
    unittest.main()
