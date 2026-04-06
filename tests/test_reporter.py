from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
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
    TrialExecution,
)
from harness.reporter import compare_reports, print_comparison, print_summary
from harness.runner import BenchmarkRunner


def _report_payload(
    model: str,
    overall_score: float,
    capability_score: float,
    covered_weight: float,
    normalized_score_on_covered: float,
    *,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    unclassified_total_tokens: int = 0,
) -> dict:
    input_tokens = 10
    output_tokens = 5
    accounted_total_tokens = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    total_tokens = accounted_total_tokens + unclassified_total_tokens
    return {
        "model": model,
        "overall_score": overall_score,
        "capability_score": capability_score,
        "strict_pass_rate": 1.0,
        "avg_latency_ms": 1000.0,
        "cost_estimate_usd": 0.0,
        "total_tokens": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "accounted_total_tokens": accounted_total_tokens,
            "unclassified_total_tokens": unclassified_total_tokens,
            "total_tokens": total_tokens,
        },
        "aggregate_stats": {
            "time_s": {"min": 1.0, "max": 1.0},
        },
        "coverage": {
            "covered_weight": covered_weight,
            "normalized_score_on_covered": normalized_score_on_covered,
            "scenario_counts_by_execution_mode": {"replay": 1},
        },
        "summary": {
            "normalized_capability_score_on_covered": capability_score / covered_weight if covered_weight else capability_score,
            "reliability": {
                "weighted_pass_at_1": 1.0,
                "weighted_pass_at_k_any": 1.0,
                "weighted_pass_at_k_all": 1.0,
            },
        },
        "dimensions": {},
        "scenarios": [],
    }


def _synthetic_replay_scenario(
    root: Path,
    *,
    scenario_id: str,
    dimension: Dimension,
    difficulty: Difficulty,
    wall_time_s: float,
    benchmark_group: BenchmarkGroup = BenchmarkGroup.COVERAGE,
) -> Scenario:
    scenario_path = root / f"{scenario_id}.yaml"
    trace_path = root / f"{scenario_id}.json"
    response_text = f"{scenario_id} ok"
    scenario_path.write_text("# synthetic replay scenario\n", encoding="utf-8")
    trace_path.write_text(
        json.dumps(
            {
                "events": [
                    {"type": "assistant_message", "text": response_text},
                ],
                "metrics": {
                    "wall_time_s": wall_time_s,
                    "duration_seconds": wall_time_s,
                    "tool_calls": 0,
                    "total_tokens": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    return Scenario(
        scenario_id=scenario_id,
        name=scenario_id,
        dimension=dimension,
        difficulty=difficulty,
        benchmark_group=benchmark_group,
        benchmark_status=BenchmarkStatus.ACTIVE,
        signal_source=SignalSource.REPLAY,
        benchmark_core=False,
        weight=1.0,
        timeout_seconds=30,
        optimal_steps=1,
        prompt="Synthetic replay validation scenario.",
        tools=[],
        checks=[
            CheckSpec(
                check_id="response_ok",
                check_type="response_contains",
                points=1.0,
                category=CheckCategory.CORRECTNESS,
                config={"pattern": response_text},
            )
        ],
        source_path=scenario_path,
        replay_traces={"default": trace_path},
        execution_mode="replay",
    )


class ReporterTests(unittest.TestCase):
    def test_compare_reports_sorts_full_coverage_before_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            full_path = Path(tmpdir) / "full.json"
            partial_path = Path(tmpdir) / "partial.json"
            full_path.write_text(
                json.dumps(_report_payload("full-model", overall_score=0.61, capability_score=0.66, covered_weight=1.0, normalized_score_on_covered=0.61)),
                encoding="utf-8",
            )
            partial_path.write_text(
                json.dumps(_report_payload("partial-model", overall_score=0.2, capability_score=0.2, covered_weight=0.2, normalized_score_on_covered=1.0)),
                encoding="utf-8",
            )

            rows = compare_reports([partial_path, full_path])

        self.assertEqual([row["model"] for row in rows], ["full-model", "partial-model"])
        self.assertFalse(rows[0]["is_partial_coverage"])
        self.assertTrue(rows[1]["is_partial_coverage"])

    def test_print_comparison_warns_on_mixed_coverage(self) -> None:
        rows = [
            {
                "model": "full-model",
                "overall_score": 0.61,
                "capability_score": 0.66,
                "normalized_capability_on_covered": 0.66,
                "normalized_score_on_covered": 0.61,
                "covered_weight": 1.0,
                "is_partial_coverage": False,
                "strict_pass_rate": 1.0,
                "weighted_pass_at_1": 1.0,
                "weighted_pass_at_k_any": 1.0,
                "weighted_pass_at_k_all": 1.0,
                "avg_latency_ms": 1000.0,
                "time_min_s": 1.0,
                "time_max_s": 1.0,
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "accounted_total_tokens": 15,
                "unclassified_total_tokens": 0,
                "total_tokens": 15,
                "cost_estimate_usd": 0.0,
            },
            {
                "model": "partial-model",
                "overall_score": 0.2,
                "capability_score": 0.2,
                "normalized_capability_on_covered": 1.0,
                "normalized_score_on_covered": 1.0,
                "covered_weight": 0.2,
                "is_partial_coverage": True,
                "strict_pass_rate": 1.0,
                "weighted_pass_at_1": 1.0,
                "weighted_pass_at_k_any": 1.0,
                "weighted_pass_at_k_all": 1.0,
                "avg_latency_ms": 1000.0,
                "time_min_s": 1.0,
                "time_max_s": 1.0,
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_tokens": 4,
                "cache_write_tokens": 0,
                "accounted_total_tokens": 19,
                "unclassified_total_tokens": 6,
                "total_tokens": 25,
                "cost_estimate_usd": 0.0,
            },
        ]

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            print_comparison(rows)
        output = buffer.getvalue()

        self.assertIn("mixed coverage detected", output)
        self.assertIn("scope=full", output)
        self.assertIn("scope=partial", output)
        self.assertIn("capability=", output)
        self.assertIn("pass@1=", output)

    def test_compare_reports_preserves_token_breakdown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "with-cache.json"
            report_path.write_text(
                json.dumps(
                    _report_payload(
                        "cache-model",
                        overall_score=0.7,
                        capability_score=0.75,
                        covered_weight=1.0,
                        normalized_score_on_covered=0.7,
                        cache_read_tokens=4,
                        cache_write_tokens=3,
                        unclassified_total_tokens=2,
                    )
                ),
                encoding="utf-8",
            )

            rows = compare_reports([report_path])

        self.assertEqual(rows[0]["cache_read_tokens"], 4)
        self.assertEqual(rows[0]["cache_write_tokens"], 3)
        self.assertEqual(rows[0]["accounted_total_tokens"], 22)
        self.assertEqual(rows[0]["unclassified_total_tokens"], 2)
        self.assertEqual(rows[0]["total_tokens"], 24)

    def test_compare_reports_falls_back_to_trial_cache_tokens(self) -> None:
        raw = _report_payload(
            "trial-cache-model",
            overall_score=0.8,
            capability_score=0.85,
            covered_weight=0.2,
            normalized_score_on_covered=1.0,
        )
        raw["total_tokens"] = {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 40,
        }
        raw["scenarios"] = [
            {
                "trials": [
                    {
                        "token_usage": {
                            "cache_read_tokens": 7,
                            "cache_write_tokens": 2,
                        }
                    }
                ]
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "trial-cache.json"
            report_path.write_text(json.dumps(raw), encoding="utf-8")
            rows = compare_reports([report_path])

        self.assertEqual(rows[0]["cache_read_tokens"], 7)
        self.assertEqual(rows[0]["cache_write_tokens"], 2)
        self.assertEqual(rows[0]["accounted_total_tokens"], 24)
        self.assertEqual(rows[0]["unclassified_total_tokens"], 16)

    def test_print_summary_shows_p95_difficulty_summary_and_top5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="reporter_constraints_easy",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                    wall_time_s=0.01,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="reporter_planning_hard",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.HARD,
                    wall_time_s=0.03,
                    benchmark_group=BenchmarkGroup.INTELLIGENCE,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="reporter_tool_use_expert",
                    dimension=Dimension.TOOL_USE,
                    difficulty=Difficulty.EXPERT,
                    wall_time_s=0.05,
                    benchmark_group=BenchmarkGroup.INTELLIGENCE,
                ),
            ]
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay")
            result = runner.run(model="mock/default", scenarios=scenarios, trials=1)
        result.cost_efficiency["cost_top5"] = [
            {
                "scenario_id": "synthetic_cost_case",
                "difficulty": "hard",
                "cost_usd": 0.125,
                "tokens": 3210,
            }
        ]
        result.summary["parallel"] = {
            "requested_workers": 3,
            "replay_workers": 3,
            "live_workers": 2,
            "live_final_workers": 1,
            "live_parallelism_enabled": True,
            "live_retry_attempts": 1,
            "live_pressure_rerun_count": 2,
            "replay_scenarios": 3,
            "live_scenarios": 0,
            "live_backoff_count": 1,
            "live_backoff_events": [{"scenario_id": "x", "from_workers": 2, "to_workers": 1, "reason": "retry_pressure"}],
        }
        result.summary["openclaw_runtime"] = {
            "binary_realpath": "/tmp/openclaw.mjs",
            "git_commit_short": "deadbeefcafe",
            "git_dirty": True,
            "version_text": "OpenClaw 0.1.0\nextra",
        }
        result.summary["openclaw_isolation"] = {
            "profile": "bench-a",
            "state_dir": "/tmp/openclaw-bench-a",
            "config_path": "/tmp/openclaw-bench-a/openclaw.json",
            "gateway_port": 19011,
        }

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            print_summary(result)
        output = buffer.getvalue()

        self.assertIn("capability_score:", output)
        self.assertIn("score_views:", output)
        self.assertIn("reliability:", output)
        self.assertIn("pass_histogram:", output)
        self.assertIn("p95=", output)
        self.assertIn("difficulty_summary:", output)
        self.assertIn("duration_top5:", output)
        self.assertIn("cost_top5:", output)
        self.assertIn("live_final_workers=1", output)
        self.assertIn("live_pressure_reruns=2", output)
        self.assertIn("live_backoff:", output)
        self.assertIn("openclaw_runtime:", output)
        self.assertIn("openclaw_isolation:", output)
        self.assertIn("best=", output)
        self.assertIn("deadbeefcafe", output)

    def test_print_summary_shows_execution_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="reporter_failure_case",
                    dimension=Dimension.SAFETY,
                    difficulty=Difficulty.MEDIUM,
                    wall_time_s=0.01,
                    benchmark_group=BenchmarkGroup.INTELLIGENCE,
                )
            ]
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay")
            result = runner.run(model="mock/default", scenarios=scenarios, trials=1)
        trial = result.scenarios[0].trials[0]
        trial.execution = TrialExecution(mode="live", status="error", exit_code=-1, error_detail="agent add failed")
        result.scenarios[0].stats["execution_status_counts"] = {"error": 1}
        result.summary["execution"] = {
            "trial_status_counts": {"error": 1},
            "scenario_status_counts": {"execution_failure": 1},
            "failure_count": 1,
            "live_preflight": {
                "ok": False,
                "exit_code": 1,
                "duration_seconds": 0.4,
                "error_detail": "missing gaxios",
            },
            "failure_examples": [
                {
                    "scenario_id": result.scenarios[0].scenario_id,
                    "trial_id": 1,
                    "mode": "live",
                    "status": "error",
                    "exit_code": -1,
                    "error_detail": "agent add failed",
                }
            ],
        }
        result.summary["outcomes"] = {
            "scenario_outcome_counts": {"execution_failure": 1},
            "trial_outcome_counts": {"execution_failure": 1},
            "threshold_miss_count": 0,
            "threshold_miss_examples": [],
        }

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            print_summary(result)
        output = buffer.getvalue()

        self.assertIn("execution:", output)
        self.assertIn("live_preflight:", output)
        self.assertIn("execution_failures:", output)
        self.assertIn("outcomes:", output)
        self.assertIn("agent add failed", output)
        self.assertIn("missing gaxios", output)
        self.assertIn("status={error=1}", output)


if __name__ == "__main__":
    unittest.main()
