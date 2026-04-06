from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.custom_checks import run_custom_checks
from harness.loader import load_scenario, scenarios_root


class ToolUse20StrategyProofTests(unittest.TestCase):
    def test_custom_check_handles_malformed_json_without_crashing(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "20_strategy_proof_live.yaml")
        with tempfile.TemporaryDirectory() as workspace_tmpdir:
            workspace_dir = Path(workspace_tmpdir)
            (workspace_dir / "strategy_proof.json").write_text(
                '{\n  "chosen_strategy": "strategy_a"\n  "proof_skeleton": []\n}\n',
                encoding="utf-8",
            )

            result = run_custom_checks(scenario, workspace_dir, {"events": []}, [])

        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["file_exists"]["score"], 0.0)
        self.assertIn("invalid JSON", result["checkpoints"]["file_exists"]["detail"])
        self.assertEqual(result["checkpoints"]["chosen"]["score"], 0.0)
        self.assertEqual(result["checkpoints"]["dom"]["detail"], "skipped")


if __name__ == "__main__":
    unittest.main()
