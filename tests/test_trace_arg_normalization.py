from __future__ import annotations

import unittest
from pathlib import Path

from harness.models import (
    BenchmarkGroup,
    BenchmarkStatus,
    CheckCategory,
    CheckSpec,
    Difficulty,
    Dimension,
    Scenario,
    SignalSource,
)
from harness.scoring import grade_scenario


class TraceArgNormalizationTests(unittest.TestCase):
    def test_generic_tool_arg_contains_accepts_file_alias(self) -> None:
        scenario = Scenario(
            scenario_id="synthetic_trace_alias_case",
            name="synthetic_trace_alias_case",
            dimension=Dimension.TOOL_USE,
            difficulty=Difficulty.EASY,
            benchmark_group=BenchmarkGroup.COVERAGE,
            benchmark_status=BenchmarkStatus.ACTIVE,
            signal_source=SignalSource.REPLAY,
            benchmark_core=False,
            weight=1.0,
            timeout_seconds=30,
            optimal_steps=1,
            prompt="Synthetic trace alias validation.",
            tools=["write"],
            checks=[
                CheckSpec(
                    check_id="write_path_detected",
                    check_type="tool_arg_contains",
                    points=1.0,
                    category=CheckCategory.CORRECTNESS,
                    config={"tool": "write", "path": "path", "pattern": "answer.json"},
                )
            ],
            source_path=Path(__file__),
            execution_mode="replay",
        )
        trace = {
            "events": [
                {
                    "type": "tool_call",
                    "tool": "write",
                    "args": {"file": "/tmp/answer.json", "content": "{}"},
                }
            ],
            "metrics": {"tool_calls": 1},
        }

        breakdown = grade_scenario(scenario, Path("."), trace)

        self.assertEqual(breakdown.correctness_score, 1.0)
        self.assertEqual(breakdown.process_score, 1.0)
        self.assertGreaterEqual(breakdown.final_score, 0.99)
