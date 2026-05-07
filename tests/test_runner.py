from __future__ import annotations

import json
from collections import Counter
from itertools import count
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from harness.live_harness import LivePreflightResult, LiveRunResult
from harness.loader import load_scenarios
from harness.models import (
    BenchmarkGroup,
    BenchmarkResult,
    BenchmarkStatus,
    CheckCategory,
    CheckSpec,
    Difficulty,
    Dimension,
    Scenario,
    SignalSource,
    ScenarioResult,
    TrialExecution,
    TrialResult,
)
from harness.reporter import save_report
from harness import runner as runner_module
from harness.runner import BenchmarkRunner


def _synthetic_replay_scenario(
    root: Path,
    *,
    scenario_id: str,
    dimension: Dimension,
    difficulty: Difficulty,
    wall_time_s: float,
    benchmark_group: BenchmarkGroup = BenchmarkGroup.COVERAGE,
    benchmark_core: bool = False,
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
        benchmark_core=benchmark_core,
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


def _synthetic_live_scenario(
    root: Path,
    *,
    scenario_id: str,
    dimension: Dimension,
    difficulty: Difficulty,
    benchmark_group: BenchmarkGroup = BenchmarkGroup.COVERAGE,
    benchmark_core: bool = False,
    signal_source: SignalSource = SignalSource.WORKSPACE_LIVE,
    openclaw_surfaces: list[str] | None = None,
) -> Scenario:
    scenario_path = root / f"{scenario_id}.yaml"
    response_text = f"{scenario_id} ok"
    scenario_path.write_text("# synthetic live scenario\n", encoding="utf-8")
    return Scenario(
        scenario_id=scenario_id,
        name=scenario_id,
        dimension=dimension,
        difficulty=difficulty,
        benchmark_group=benchmark_group,
        benchmark_status=BenchmarkStatus.ACTIVE,
        signal_source=signal_source,
        benchmark_core=benchmark_core,
        weight=1.0,
        timeout_seconds=30,
        optimal_steps=1,
        prompt="Synthetic live validation scenario.",
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
        openclaw_surfaces=list(openclaw_surfaces or []),
        execution_mode="live",
    )


class RunnerTests(unittest.TestCase):
    def _fake_trial_result(
        self,
        trial_id: int,
        latency_ms: float,
        execution_mode: str = "replay",
        *,
        score: float = 1.0,
        capability_score: float | None = None,
        passed: bool = True,
    ) -> TrialResult:
        return TrialResult(
            trial_id=trial_id,
            score=score,
            capability_score=score if capability_score is None else capability_score,
            passed=passed,
            safety_passed=True,
            checks=[],
            process_score=1.0,
            efficiency_score=1.0,
            efficiency_penalty=0.0,
            latency_ms=latency_ms,
            token_usage={
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "tool_calls": 0,
                "input_cost_usd": 0.0,
                "output_cost_usd": 0.0,
                "cache_read_cost_usd": 0.0,
                "cache_write_cost_usd": 0.0,
                "total_cost_usd": 0.0,
                "cost_estimate_usd": 0.0,
            },
            transcript=[],
            tool_calls=[],
            audit_state={},
            execution=TrialExecution(mode=execution_mode, status="success", exit_code=0),
        )

    def test_runner_builds_summary_and_cost_metrics_for_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="replay_constraints_easy",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                    wall_time_s=0.01,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="replay_error_medium",
                    dimension=Dimension.ERROR_RECOVERY,
                    difficulty=Difficulty.MEDIUM,
                    wall_time_s=0.02,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="replay_planning_hard",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.HARD,
                    wall_time_s=0.03,
                    benchmark_group=BenchmarkGroup.INTELLIGENCE,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="replay_synthesis_hard",
                    dimension=Dimension.SYNTHESIS,
                    difficulty=Difficulty.HARD,
                    wall_time_s=0.04,
                    benchmark_group=BenchmarkGroup.INTELLIGENCE,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="replay_tool_use_medium",
                    dimension=Dimension.TOOL_USE,
                    difficulty=Difficulty.MEDIUM,
                    wall_time_s=0.05,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="replay_safety_expert",
                    dimension=Dimension.SAFETY,
                    difficulty=Difficulty.EXPERT,
                    wall_time_s=0.06,
                    benchmark_group=BenchmarkGroup.INTELLIGENCE,
                    benchmark_core=True,
                ),
            ]
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", show_progress=False)
            result = runner.run(model="mock/default", scenarios=scenarios, trials=1)
        self.assertEqual(result.total_scenarios, 6)
        self.assertEqual(result.summary["total_trials"], 6)
        self.assertIn("time_s", result.aggregate_stats)
        self.assertIn("cost_breakdown", result.summary)
        self.assertIn("progress", result.summary)
        self.assertIn("difficulty_summary", result.summary)
        self.assertEqual(
            set(result.summary["difficulty_summary"].keys()),
            {"easy", "medium", "hard", "expert"},
        )
        self.assertEqual(result.summary["difficulty_summary"]["expert"]["scenario_count"], 1)
        self.assertEqual(result.summary["progress"]["completed_scenarios"], 6)
        self.assertEqual(result.summary["progress"]["remaining_scenarios"], 0)
        self.assertEqual(result.coverage["covered_weight"], 1.0)
        self.assertEqual(result.coverage["scenario_counts_by_execution_mode"], {"replay": 6})
        self.assertEqual(result.summary["slowest_scenario"], "replay_safety_expert")
        self.assertGreater(result.dimensions["tool_use"].score, 0.8)
        self.assertGreaterEqual(result.capability_score, result.overall_score)
        self.assertIn("reliability", result.summary)
        self.assertAlmostEqual(result.cost_estimate_usd, 0.0, places=8)
        self.assertEqual(result.total_tokens["cache_read_tokens"], 0)
        self.assertEqual(result.total_tokens["cache_write_tokens"], 0)
        self.assertEqual(result.total_tokens["accounted_total_tokens"], result.total_tokens["total_tokens"])
        self.assertEqual(result.total_tokens["unclassified_total_tokens"], 0)

    def test_runner_tracks_capability_and_pass_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", show_progress=False)
            scenario = _synthetic_replay_scenario(
                Path(tmpdir),
                scenario_id="replay_profile_case",
                dimension=Dimension.TOOL_USE,
                difficulty=Difficulty.MEDIUM,
                wall_time_s=0.1,
            )
            trials = [
                self._fake_trial_result(trial_id=1, latency_ms=100.0, score=0.80, capability_score=0.90, passed=True),
                self._fake_trial_result(trial_id=2, latency_ms=200.0, score=0.20, capability_score=0.60, passed=False),
                self._fake_trial_result(trial_id=3, latency_ms=300.0, score=0.70, capability_score=0.85, passed=True),
            ]

            scenario_result = runner._build_scenario_result(scenario, trials)
            benchmark = runner._build_benchmark_result(
                model="mock/default",
                scenario_results=[scenario_result],
                trials=3,
            )

        self.assertEqual(scenario_result.pass_count, 2)
        self.assertEqual(scenario_result.trial_count, 3)
        self.assertAlmostEqual(scenario_result.pass_rate, 0.6667, places=4)
        self.assertAlmostEqual(scenario_result.max_score, 0.8, places=4)
        self.assertTrue(scenario_result.pass_at_k_any)
        self.assertFalse(scenario_result.strict_pass_k)
        self.assertAlmostEqual(scenario_result.capability_score, 0.7833, places=4)
        self.assertAlmostEqual(benchmark.summary["normalized_capability_score_on_covered"], 0.7833, places=4)
        self.assertAlmostEqual(benchmark.summary["normalized_score_on_covered"], 0.5667, places=4)
        self.assertEqual(benchmark.summary["reliability"]["pass_count_histogram"], {"2/3": 1})
        self.assertAlmostEqual(benchmark.summary["reliability"]["weighted_pass_at_1"], 0.6667, places=4)
        self.assertAlmostEqual(benchmark.summary["reliability"]["weighted_pass_at_k_any"], 1.0, places=4)
        self.assertAlmostEqual(benchmark.summary["reliability"]["weighted_pass_at_k_all"], 0.0, places=4)
        self.assertEqual(benchmark.summary["outcomes"]["trial_outcome_counts"], {"pass": 2, "threshold_miss": 1})
        self.assertEqual(benchmark.summary["outcomes"]["scenario_outcome_counts"], {"threshold_miss": 1})

    def test_auto_mode_can_include_live_scenarios_in_inventory(self) -> None:
        scenarios = load_scenarios()
        runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="auto", show_progress=False)
        live = [scenario for scenario in scenarios if runner._resolve_execution_mode(scenario) == "live"]
        self.assertGreaterEqual(len(live), 4)

    def test_runner_can_resume_from_existing_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="resume_case_one",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                    wall_time_s=0.01,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="resume_case_two",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.MEDIUM,
                    wall_time_s=0.02,
                    benchmark_group=BenchmarkGroup.INTELLIGENCE,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="resume_case_three",
                    dimension=Dimension.SAFETY,
                    difficulty=Difficulty.HARD,
                    wall_time_s=0.03,
                    benchmark_group=BenchmarkGroup.INTELLIGENCE,
                ),
            ]
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", show_progress=False)
            first = runner.run(model="mock/default", scenarios=scenarios, trials=1)

            with tempfile.TemporaryDirectory() as report_tmpdir:
                path = save_report(first, Path(report_tmpdir))
                existing = BenchmarkResult.from_dict(json.loads(path.read_text(encoding="utf-8")))
                existing.summary["report_path"] = str(path)
                resumed = runner.run_with_resume(
                    model="mock/default",
                    scenarios=scenarios,
                    trials=1,
                    existing_result=existing,
                )

        self.assertTrue(resumed.resume["resumed"])
        self.assertEqual(resumed.resume["reused_scenarios"], 3)
        self.assertEqual(resumed.resume["new_scenarios"], 0)
        self.assertAlmostEqual(resumed.overall_score, first.overall_score, places=4)
        self.assertEqual(resumed.coverage["covered_weight"], 0.5)

    def test_runner_writes_checkpoint_report_during_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="checkpoint_one",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                    wall_time_s=0.01,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="checkpoint_two",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.MEDIUM,
                    wall_time_s=0.02,
                    benchmark_group=BenchmarkGroup.INTELLIGENCE,
                ),
            ]
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", show_progress=False)
            checkpoint_path = Path(tmpdir) / "checkpoint.json"
            result = runner.run_with_resume(
                model="mock/default",
                scenarios=scenarios,
                trials=1,
                checkpoint_path=checkpoint_path,
                benchmark_profile="core",
            )

            self.assertTrue(checkpoint_path.exists())
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["summary"]["progress"]["completed_scenarios"], 2)
        self.assertEqual(payload["summary"]["progress"]["remaining_scenarios"], 0)
        self.assertEqual(payload["summary"]["progress"]["checkpoint_path"], str(checkpoint_path))
        self.assertEqual(result.summary["progress"]["completed_scenarios"], 2)

    def test_save_report_uses_unique_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="save_report_case",
                    dimension=Dimension.TOOL_USE,
                    difficulty=Difficulty.MEDIUM,
                    wall_time_s=0.01,
                )
            ]
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", show_progress=False)
            result = runner.run(model="mock/default", scenarios=scenarios, trials=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            first_path = save_report(result, Path(tmpdir))
            second_path = save_report(result, Path(tmpdir))
            self.assertNotEqual(first_path, second_path)
            self.assertTrue(first_path.exists())
            self.assertTrue(second_path.exists())

    def test_parallel_replay_preserves_input_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="parallel_order_one",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                    wall_time_s=0.01,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="parallel_order_two",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.MEDIUM,
                    wall_time_s=0.01,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="parallel_order_three",
                    dimension=Dimension.TOOL_USE,
                    difficulty=Difficulty.HARD,
                    wall_time_s=0.01,
                ),
            ]
            delay_by_id = {
                scenarios[0].scenario_id: 0.05,
                scenarios[1].scenario_id: 0.0,
                scenarios[2].scenario_id: 0.02,
            }
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", parallelism=3, show_progress=False)

            def fake_run_trial(
                _runner: BenchmarkRunner,
                model: str,
                scenario,
                trial_id: int,
                pricing,
            ) -> TrialResult:
                time.sleep(delay_by_id[scenario.scenario_id])
                return self._fake_trial_result(trial_id=trial_id, latency_ms=delay_by_id[scenario.scenario_id] * 1000.0)

            with mock.patch.object(BenchmarkRunner, "_run_trial", autospec=True, side_effect=fake_run_trial):
                result = runner.run(model="mock/default", scenarios=scenarios, trials=1)

        self.assertEqual([item.scenario_id for item in result.scenarios], [scenario.scenario_id for scenario in scenarios])
        self.assertEqual(result.summary["parallel"]["requested_workers"], 3)
        self.assertEqual(result.summary["parallel"]["replay_workers"], 3)
        self.assertEqual(result.summary["parallel"]["live_workers"], 0)

    def test_parallel_resume_only_executes_pending_replay_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="parallel_resume_one",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                    wall_time_s=0.01,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="parallel_resume_two",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.MEDIUM,
                    wall_time_s=0.01,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="parallel_resume_three",
                    dimension=Dimension.TOOL_USE,
                    difficulty=Difficulty.HARD,
                    wall_time_s=0.01,
                ),
            ]
            cached_runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", show_progress=False)
            existing = cached_runner.run(model="mock/default", scenarios=scenarios[:1], trials=1)
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", parallelism=4, show_progress=False)
            called_ids: list[str] = []
            delay_by_id = {
                scenarios[1].scenario_id: 0.03,
                scenarios[2].scenario_id: 0.0,
            }

            def fake_run_trial(
                _runner: BenchmarkRunner,
                model: str,
                scenario,
                trial_id: int,
                pricing,
            ) -> TrialResult:
                called_ids.append(scenario.scenario_id)
                time.sleep(delay_by_id.get(scenario.scenario_id, 0.0))
                return self._fake_trial_result(trial_id=trial_id, latency_ms=10.0)

            with mock.patch.object(BenchmarkRunner, "_run_trial", autospec=True, side_effect=fake_run_trial):
                resumed = runner.run_with_resume(
                    model="mock/default",
                    scenarios=scenarios,
                    trials=1,
                    existing_result=existing,
                )

        self.assertEqual(resumed.resume["reused_scenarios"], 1)
        self.assertEqual(resumed.resume["new_scenarios"], 2)
        self.assertEqual([item.scenario_id for item in resumed.scenarios], [scenario.scenario_id for scenario in scenarios])
        self.assertEqual(called_ids.count(scenarios[0].scenario_id), 0)
        self.assertCountEqual(called_ids, [scenarios[1].scenario_id, scenarios[2].scenario_id])
        self.assertEqual(resumed.summary["parallel"]["replay_workers"], 2)

    def test_resume_still_reuses_execution_failures_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="resume_keep_success",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                    wall_time_s=0.01,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="resume_keep_execution_failure",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.MEDIUM,
                    wall_time_s=0.01,
                ),
            ]
            cached_runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", show_progress=False)

            def fake_initial_run(
                _runner: BenchmarkRunner,
                model: str,
                scenario: Scenario,
                trial_id: int,
                pricing: dict[str, float],
            ) -> TrialResult:
                del model, pricing
                if scenario.scenario_id == "resume_keep_execution_failure":
                    trial = self._fake_trial_result(trial_id=trial_id, latency_ms=10.0, passed=False, score=0.0)
                    trial.execution = TrialExecution(
                        mode="replay",
                        status="error",
                        exit_code=1,
                        error_detail="provider quota",
                    )
                    return trial
                return self._fake_trial_result(trial_id=trial_id, latency_ms=10.0)

            with mock.patch.object(BenchmarkRunner, "_run_trial", autospec=True, side_effect=fake_initial_run):
                existing = cached_runner.run(model="mock/default", scenarios=scenarios, trials=1)

            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", parallelism=2, show_progress=False)
            called_ids: list[str] = []

            def fake_resume_run(
                _runner: BenchmarkRunner,
                model: str,
                scenario: Scenario,
                trial_id: int,
                pricing: dict[str, float],
            ) -> TrialResult:
                del model, trial_id, pricing
                called_ids.append(scenario.scenario_id)
                return self._fake_trial_result(trial_id=1, latency_ms=10.0)

            with mock.patch.object(BenchmarkRunner, "_run_trial", autospec=True, side_effect=fake_resume_run):
                resumed = runner.run_with_resume(
                    model="mock/default",
                    scenarios=scenarios,
                    trials=1,
                    existing_result=existing,
                )

        self.assertEqual(resumed.resume["reused_scenarios"], 2)
        self.assertEqual(resumed.resume["new_scenarios"], 0)
        self.assertEqual(called_ids, [])

    def test_resume_can_rerun_execution_failures_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="resume_clean_success",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                    wall_time_s=0.01,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="resume_rerun_execution_failure",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.MEDIUM,
                    wall_time_s=0.01,
                ),
            ]
            cached_runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", show_progress=False)

            def fake_initial_run(
                _runner: BenchmarkRunner,
                model: str,
                scenario: Scenario,
                trial_id: int,
                pricing: dict[str, float],
            ) -> TrialResult:
                del model, pricing
                if scenario.scenario_id == "resume_rerun_execution_failure":
                    trial = self._fake_trial_result(trial_id=trial_id, latency_ms=10.0, passed=False, score=0.0)
                    trial.execution = TrialExecution(
                        mode="replay",
                        status="timeout",
                        exit_code=124,
                        error_detail="timed out",
                    )
                    return trial
                return self._fake_trial_result(trial_id=trial_id, latency_ms=10.0)

            with mock.patch.object(BenchmarkRunner, "_run_trial", autospec=True, side_effect=fake_initial_run):
                existing = cached_runner.run(model="mock/default", scenarios=scenarios, trials=1)

            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", parallelism=2, show_progress=False)
            called_ids: list[str] = []

            def fake_resume_run(
                _runner: BenchmarkRunner,
                model: str,
                scenario: Scenario,
                trial_id: int,
                pricing: dict[str, float],
            ) -> TrialResult:
                del model, pricing
                called_ids.append(scenario.scenario_id)
                return self._fake_trial_result(trial_id=trial_id, latency_ms=10.0)

            with mock.patch.object(BenchmarkRunner, "_run_trial", autospec=True, side_effect=fake_resume_run):
                resumed = runner.run_with_resume(
                    model="mock/default",
                    scenarios=scenarios,
                    trials=1,
                    existing_result=existing,
                    rerun_execution_failures=True,
                )

        self.assertEqual(resumed.resume["reused_scenarios"], 1)
        self.assertEqual(resumed.resume["new_scenarios"], 1)
        self.assertTrue(resumed.resume["rerun_execution_failures"])
        self.assertEqual(resumed.resume["rerun_execution_failure_scenarios"], 1)
        self.assertEqual(called_ids, ["resume_rerun_execution_failure"])
        rerun_result = next(item for item in resumed.scenarios if item.scenario_id == "resume_rerun_execution_failure")
        self.assertEqual(rerun_result.stats["execution_status_counts"], {"success": 1})

    def test_resume_reuses_siliconflow_pro_alias_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="resume_alias_case_one",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                    wall_time_s=0.01,
                ),
                _synthetic_replay_scenario(
                    Path(tmpdir),
                    scenario_id="resume_alias_case_two",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.MEDIUM,
                    wall_time_s=0.01,
                ),
            ]
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="replay", show_progress=False)
            existing = runner.run(model="siliconflow/deepseek-ai/DeepSeek-V3.2", scenarios=scenarios, trials=1)

            resumed = runner.run_with_resume(
                model="siliconflow/Pro/deepseek-ai/DeepSeek-V3.2",
                scenarios=scenarios,
                trials=1,
                existing_result=existing,
            )

        self.assertTrue(resumed.resume["resumed"])
        self.assertEqual(resumed.resume["reused_scenarios"], 2)
        self.assertEqual(resumed.resume["new_scenarios"], 0)

    def test_live_parallel_run_uses_probed_worker_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_live_scenario(
                    Path(tmpdir),
                    scenario_id="live_parallel_one",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                ),
                _synthetic_live_scenario(
                    Path(tmpdir),
                    scenario_id="live_parallel_two",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.MEDIUM,
                ),
                _synthetic_live_scenario(
                    Path(tmpdir),
                    scenario_id="live_parallel_three",
                    dimension=Dimension.TOOL_USE,
                    difficulty=Difficulty.HARD,
                ),
            ]
            runner = BenchmarkRunner(
                results_dir=Path("results"),
                execution_mode="live",
                parallelism=3,
                allow_live_parallelism=True,
                show_progress=False,
            )
            preflight = LivePreflightResult(ok=True, exit_code=0, duration_seconds=0.1)

            def fake_run_trial(
                _runner: BenchmarkRunner,
                model: str,
                scenario: Scenario,
                trial_id: int,
                pricing: dict[str, float],
            ) -> TrialResult:
                del model, pricing
                time.sleep(0.01)
                return self._fake_trial_result(trial_id=trial_id, latency_ms=10.0, execution_mode="live")

            with (
                mock.patch.object(runner.live_harness, "preflight", return_value=preflight),
                mock.patch.object(BenchmarkRunner, "_run_trial", autospec=True, side_effect=fake_run_trial),
            ):
                result = runner.run(model="mock/default", scenarios=scenarios, trials=1)

        self.assertEqual([item.scenario_id for item in result.scenarios], [scenario.scenario_id for scenario in scenarios])
        self.assertEqual(result.summary["parallel"]["requested_workers"], 3)
        self.assertEqual(result.summary["parallel"]["live_workers"], 3)
        self.assertEqual(result.summary["parallel"]["live_initial_workers"], 3)
        self.assertEqual(result.summary["parallel"]["live_final_workers"], 3)
        self.assertTrue(result.summary["parallel"]["live_parallelism_enabled"])
        self.assertEqual(result.summary["parallel"]["live_backoff_count"], 0)
        self.assertEqual(result.summary["parallel"]["live_pressure_rerun_count"], 0)
        self.assertFalse(result.summary["parallel"]["live_execution_serialized"])

    def test_live_parallel_run_backs_off_after_retry_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_live_scenario(
                    Path(tmpdir),
                    scenario_id="live_backoff_one",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                ),
                _synthetic_live_scenario(
                    Path(tmpdir),
                    scenario_id="live_backoff_two",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.MEDIUM,
                ),
                _synthetic_live_scenario(
                    Path(tmpdir),
                    scenario_id="live_backoff_three",
                    dimension=Dimension.TOOL_USE,
                    difficulty=Difficulty.HARD,
                ),
                _synthetic_live_scenario(
                    Path(tmpdir),
                    scenario_id="live_backoff_four",
                    dimension=Dimension.SAFETY,
                    difficulty=Difficulty.HARD,
                ),
            ]
            runner = BenchmarkRunner(
                results_dir=Path("results"),
                execution_mode="live",
                parallelism=2,
                allow_live_parallelism=True,
                live_retry_attempts=1,
                show_progress=False,
            )
            preflight = LivePreflightResult(ok=True, exit_code=0, duration_seconds=0.1)

            def fake_run_scenario(
                _runner: BenchmarkRunner,
                model: str,
                scenario: Scenario,
                trials: int,
                pricing: dict[str, float],
            ) -> ScenarioResult:
                del model, trials, pricing
                time.sleep(0.01)
                trial = self._fake_trial_result(trial_id=1, latency_ms=10.0, execution_mode="live")
                if scenario.scenario_id in {"live_backoff_one", "live_backoff_two"}:
                    trial.audit_state = {
                        "live_retry": {
                            "enabled": True,
                            "max_attempts": 2,
                            "attempt_count": 2,
                            "retries_used": 1,
                            "exhausted": False,
                            "attempts": [],
                        }
                    }
                return runner._build_scenario_result(scenario, [trial])

            with (
                mock.patch.object(runner.live_harness, "preflight", return_value=preflight),
                mock.patch.object(BenchmarkRunner, "_run_scenario", autospec=True, side_effect=fake_run_scenario),
            ):
                result = runner.run(model="mock/default", scenarios=scenarios, trials=1)

        self.assertEqual(result.summary["parallel"]["live_workers"], 2)
        self.assertEqual(result.summary["parallel"]["live_initial_workers"], 2)
        self.assertEqual(result.summary["parallel"]["live_final_workers"], 1)
        self.assertEqual(result.summary["parallel"]["live_backoff_count"], 1)
        self.assertEqual(result.summary["parallel"]["live_pressure_rerun_count"], 0)
        self.assertEqual(result.summary["parallel"]["live_backoff_events"][0]["reason"], "retry_pressure")
        self.assertEqual(result.summary["parallel"]["live_backoff_events"][0]["to_workers"], 1)

    def test_live_parallel_run_reruns_failed_scenarios_after_backoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenarios = [
                _synthetic_live_scenario(
                    Path(tmpdir),
                    scenario_id="live_rerun_one",
                    dimension=Dimension.CONSTRAINTS,
                    difficulty=Difficulty.EASY,
                ),
                _synthetic_live_scenario(
                    Path(tmpdir),
                    scenario_id="live_rerun_two",
                    dimension=Dimension.PLANNING,
                    difficulty=Difficulty.MEDIUM,
                ),
                _synthetic_live_scenario(
                    Path(tmpdir),
                    scenario_id="live_rerun_three",
                    dimension=Dimension.TOOL_USE,
                    difficulty=Difficulty.HARD,
                ),
            ]
            runner = BenchmarkRunner(
                results_dir=Path("results"),
                execution_mode="live",
                parallelism=2,
                allow_live_parallelism=True,
                live_retry_attempts=1,
                show_progress=False,
            )
            preflight = LivePreflightResult(ok=True, exit_code=0, duration_seconds=0.1)
            call_counts = Counter()

            def fake_run_scenario(
                _runner: BenchmarkRunner,
                model: str,
                scenario: Scenario,
                trials: int,
                pricing: dict[str, float],
            ) -> ScenarioResult:
                del model, trials, pricing
                call_counts[scenario.scenario_id] += 1
                trial = self._fake_trial_result(trial_id=1, latency_ms=10.0, execution_mode="live")
                if scenario.scenario_id in {"live_rerun_one", "live_rerun_two"} and call_counts[scenario.scenario_id] == 1:
                    trial.score = 0.1
                    trial.capability_score = 0.1
                    trial.passed = False
                    trial.execution = TrialExecution(mode="live", status="error", exit_code=1, error_detail="parallel pressure")
                return runner._build_scenario_result(scenario, [trial])

            with (
                mock.patch.object(runner.live_harness, "preflight", return_value=preflight),
                mock.patch.object(BenchmarkRunner, "_run_scenario", autospec=True, side_effect=fake_run_scenario),
            ):
                result = runner.run(model="mock/default", scenarios=scenarios, trials=1)

        self.assertEqual(call_counts["live_rerun_one"], 2)
        self.assertEqual(call_counts["live_rerun_two"], 2)
        self.assertEqual(call_counts["live_rerun_three"], 1)
        self.assertEqual(result.summary["parallel"]["live_initial_workers"], 2)
        self.assertEqual(result.summary["parallel"]["live_final_workers"], 1)
        self.assertEqual(result.summary["parallel"]["live_backoff_count"], 1)
        self.assertEqual(result.summary["parallel"]["live_pressure_rerun_count"], 2)
        self.assertTrue(all(item.strict_pass_k for item in result.scenarios))
        rerun_trial = next(item for item in result.scenarios if item.scenario_id == "live_rerun_one").trials[0]
        self.assertEqual(rerun_trial.audit_state["live_parallel_rerun"]["count"], 1)
        self.assertEqual(rerun_trial.audit_state["live_parallel_rerun"]["history"][0]["status_counts"], {"error": 1})

    def test_live_retry_retries_only_execution_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenario = _synthetic_live_scenario(
                Path(tmpdir),
                scenario_id="live_retry_case",
                dimension=Dimension.CONSTRAINTS,
                difficulty=Difficulty.EASY,
            )
            runner = BenchmarkRunner(
                results_dir=Path("results"),
                execution_mode="live",
                live_retry_attempts=1,
                show_progress=False,
            )
            pricing = {
                "input_per_million_usd": 0.0,
                "output_per_million_usd": 0.0,
                "cache_read_per_million_usd": 0.0,
                "cache_write_per_million_usd": 0.0,
            }
            failed = LiveRunResult(
                status="timeout",
                exit_code=-1,
                error_detail="OpenClaw agent timed out",
                trace={"events": [], "metrics": {"wall_time_s": 0.1, "duration_seconds": 0.1}},
                duration_seconds=0.1,
                agent_id="agent-timeout",
                session_id="session-timeout",
            )
            succeeded = LiveRunResult(
                status="success",
                exit_code=0,
                error_detail="",
                trace={
                    "events": [{"type": "assistant_message", "text": "live_retry_case ok"}],
                    "metrics": {"wall_time_s": 0.2, "duration_seconds": 0.2},
                    "audit_state": {},
                },
                duration_seconds=0.2,
                agent_id="agent-success",
                session_id="session-success",
            )

            with mock.patch.object(runner.live_harness, "execute_turn", side_effect=[failed, succeeded]) as execute_turn:
                trial = runner._run_trial(model="mock/default", scenario=scenario, trial_id=1, pricing=pricing)

        self.assertEqual(execute_turn.call_count, 2)
        self.assertTrue(trial.passed)
        self.assertEqual(trial.execution.status, "success")
        self.assertEqual(trial.audit_state["live_retry"]["attempt_count"], 2)
        self.assertEqual(trial.audit_state["live_retry"]["retries_used"], 1)
        self.assertFalse(trial.audit_state["live_retry"]["exhausted"])

    def test_live_trial_records_execution_metadata_in_summary(self) -> None:
        runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="live", show_progress=False)
        scenario = next(item for item in load_scenarios() if item.execution_mode == "live")
        pricing = {
            "input_per_million_usd": 0.0,
            "output_per_million_usd": 0.0,
            "cache_read_per_million_usd": 0.0,
            "cache_write_per_million_usd": 0.0,
        }
        live_result = LiveRunResult(
            status="error",
            exit_code=-1,
            error_detail="agent add failed",
            trace={"events": [], "metrics": {"wall_time_s": 0.2, "duration_seconds": 0.2}},
            duration_seconds=0.2,
            agent_id="agent-123",
            session_id="",
        )

        with mock.patch.object(runner.live_harness, "execute_turn", return_value=live_result):
            trial = runner._run_trial(model="mock/default", scenario=scenario, trial_id=1, pricing=pricing)
            scenario_result = runner._build_scenario_result(scenario, [trial])
            benchmark = runner._build_benchmark_result(
                model="mock/default",
                scenario_results=[scenario_result],
                trials=1,
            )

        self.assertEqual(trial.execution.mode, "live")
        self.assertEqual(trial.execution.status, "error")
        self.assertEqual(trial.execution.exit_code, -1)
        self.assertEqual(trial.execution.error_detail, "agent add failed")
        self.assertEqual(benchmark.summary["execution"]["trial_status_counts"], {"error": 1})
        self.assertEqual(benchmark.summary["execution"]["scenario_status_counts"], {"execution_failure": 1})
        self.assertEqual(benchmark.summary["execution"]["failure_examples"][0]["error_detail"], "agent add failed")
        self.assertEqual(benchmark.summary["outcomes"]["trial_outcome_counts"], {"execution_failure": 1})
        self.assertEqual(benchmark.summary["outcomes"]["scenario_outcome_counts"], {"execution_failure": 1})

    def test_live_trial_passes_prepared_workspace_manifest_and_restore_callback(self) -> None:
        runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="live", show_progress=False)
        scenario = next(item for item in load_scenarios() if item.scenario_id == "intel_e04_safety_no_delete")
        pricing = {
            "input_per_million_usd": 0.0,
            "output_per_million_usd": 0.0,
            "cache_read_per_million_usd": 0.0,
            "cache_write_per_million_usd": 0.0,
        }
        live_result = LiveRunResult(
            status="error",
            exit_code=-1,
            error_detail="agent add failed",
            trace={"events": [], "metrics": {"wall_time_s": 0.2, "duration_seconds": 0.2}, "audit_state": {}},
            duration_seconds=0.2,
            agent_id="agent-123",
            session_id="",
        )

        with mock.patch.object(runner.live_harness, "execute_turn", return_value=live_result) as execute_turn:
            runner._run_trial(model="mock/default", scenario=scenario, trial_id=1, pricing=pricing)

        kwargs = execute_turn.call_args.kwargs
        self.assertEqual(
            set(kwargs["expected_workspace_files"]),
            {"config.json", "request.json", "safety_policy.json", "output_contract.json"},
        )
        self.assertTrue(callable(kwargs["repair_workspace"]))
        self.assertTrue(kwargs["use_local_agent"])

    def test_live_trial_keeps_non_workspace_live_scenarios_on_default_agent_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenario = _synthetic_live_scenario(
                Path(tmpdir),
                scenario_id="native_live_case",
                dimension=Dimension.TOOL_USE,
                difficulty=Difficulty.EASY,
                signal_source=SignalSource.OPENCLAW_NATIVE,
            )
            scenario.workspace_files = [{"path": "seed.json", "content": "{}\n"}]
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="live", show_progress=False)
            pricing = {
                "input_per_million_usd": 0.0,
                "output_per_million_usd": 0.0,
                "cache_read_per_million_usd": 0.0,
                "cache_write_per_million_usd": 0.0,
            }
            live_result = LiveRunResult(
                status="success",
                exit_code=0,
                error_detail="",
                trace={
                    "events": [{"type": "assistant_message", "text": "native_live_case ok"}],
                    "metrics": {"wall_time_s": 0.2, "duration_seconds": 0.2},
                    "audit_state": {},
                },
                duration_seconds=0.2,
                agent_id="agent-123",
                session_id="session-123",
            )

            with mock.patch.object(runner.live_harness, "execute_turn", return_value=live_result) as execute_turn:
                runner._run_trial(model="mock/default", scenario=scenario, trial_id=1, pricing=pricing)

        self.assertFalse(execute_turn.call_args.kwargs["use_local_agent"])

    def test_live_preflight_failure_short_circuits_live_turn_execution(self) -> None:
        runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="live", show_progress=False)
        scenario = next(item for item in load_scenarios() if item.execution_mode == "live")
        preflight = LivePreflightResult(
            ok=False,
            exit_code=1,
            error_detail="missing gaxios",
            duration_seconds=0.4,
        )

        with (
            mock.patch.object(runner.live_harness, "preflight", return_value=preflight),
            mock.patch.object(runner.live_harness, "execute_turn") as execute_turn,
        ):
            result = runner.run(model="mock/default", scenarios=[scenario], trials=1)

        execute_turn.assert_not_called()
        trial = result.scenarios[0].trials[0]
        self.assertEqual(trial.execution.status, "error")
        self.assertEqual(trial.execution.error_detail, "missing gaxios")
        self.assertEqual(result.summary["execution"]["live_preflight"]["ok"], False)
        self.assertEqual(result.summary["execution"]["live_preflight"]["error_detail"], "missing gaxios")

    def test_native_live_trial_records_environment_fingerprint_in_audit_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenario = _synthetic_live_scenario(
                Path(tmpdir),
                scenario_id="native_fingerprint_case",
                dimension=Dimension.TOOL_USE,
                difficulty=Difficulty.EASY,
                signal_source=SignalSource.OPENCLAW_NATIVE,
                openclaw_surfaces=["skills"],
            )
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="live", show_progress=False)
            pricing = {
                "input_per_million_usd": 0.0,
                "output_per_million_usd": 0.0,
                "cache_read_per_million_usd": 0.0,
                "cache_write_per_million_usd": 0.0,
            }
            live_result = LiveRunResult(
                status="success",
                exit_code=0,
                error_detail="",
                trace={
                    "events": [{"type": "assistant_message", "text": "native_fingerprint_case ok"}],
                    "metrics": {"wall_time_s": 0.2, "duration_seconds": 0.2},
                    "audit_state": {},
                },
                duration_seconds=0.2,
                agent_id="native-agent",
                session_id="native-session",
            )
            fingerprint = {"version": 1, "surfaces": ["skills"], "skills": {"status": "ready", "ready_count": 3}}

            with (
                mock.patch.object(runner.live_harness, "execute_turn", return_value=live_result),
                mock.patch(
                    "harness.runner.collect_native_environment_snapshot",
                    return_value=fingerprint,
                ) as collect_native_environment_snapshot,
            ):
                trial = runner._run_trial(model="mock/default", scenario=scenario, trial_id=1, pricing=pricing)

        self.assertEqual(trial.audit_state["native_environment"], fingerprint)
        collect_native_environment_snapshot.assert_called_once_with(
            scenario.openclaw_surfaces,
            openclaw_bin=runner.live_harness.openclaw_bin,
            env=runner.live_harness.command_env,
        )

    def test_live_benchmark_result_records_openclaw_runtime_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(results_dir=Path("results"), execution_mode="live", show_progress=False)
            scenario = _synthetic_live_scenario(
                Path(tmpdir),
                scenario_id="runtime_provenance_case",
                dimension=Dimension.TOOL_USE,
                difficulty=Difficulty.EASY,
            )
            scenario_result = runner._build_scenario_result(
                scenario,
                [self._fake_trial_result(trial_id=1, latency_ms=10.0, execution_mode="live")],
            )
            provenance = {
                "configured_binary": "openclaw",
                "binary_realpath": "/tmp/openclaw.mjs",
                "git_commit_short": "deadbeefcafe",
                "git_dirty": True,
                "version_text": "OpenClaw 0.1.0",
            }

            with mock.patch("harness.runner._collect_openclaw_runtime_provenance", return_value=provenance):
                benchmark = runner._build_benchmark_result(
                    model="mock/default",
                    scenario_results=[scenario_result],
                    trials=1,
                )

        self.assertEqual(benchmark.summary["openclaw_runtime"], provenance)
        self.assertEqual(benchmark.summary["openclaw_isolation"], runner.live_harness.isolation_metadata())

    def test_openclaw_runtime_provenance_tolerates_binary_hash_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            binary = Path(tmpdir) / "openclaw.mjs"
            binary.write_text("console.log('openclaw')\n", encoding="utf-8")

            with mock.patch("harness.runner._binary_sha256", side_effect=PermissionError("blocked")):
                provenance = runner_module._collect_openclaw_runtime_provenance(str(binary))

        self.assertTrue(provenance["binary_exists"])
        self.assertEqual(provenance["binary_sha256"], "")
        self.assertGreater(provenance["binary_size_bytes"], 0)
        self.assertIn("PermissionError", provenance["binary_read_error"])

    def test_scenario_result_from_dict_falls_back_to_avg_score_when_max_score_missing(self) -> None:
        parsed = ScenarioResult.from_dict(
            {
                "scenario_id": "legacy-case",
                "name": "legacy-case",
                "dimension": "tool_use",
                "difficulty": "medium",
                "benchmark_group": "coverage",
                "benchmark_core": False,
                "avg_score": 0.42,
                "capability_score": 0.5,
                "pass_rate": 0.0,
                "pass_at_k_any": False,
                "pass_count": 0,
                "trial_count": 1,
                "strict_pass_k": False,
                "consistency": 0.0,
                "avg_latency_ms": 10.0,
                "total_tokens": {"total_tokens": 0},
                "cost_estimate_usd": 0.0,
                "difficulty_weight": 1.0,
                "execution_mode": "replay",
                "stats": {},
                "trials": [],
            }
        )

        self.assertAlmostEqual(parsed.avg_score, 0.42, places=4)
        self.assertAlmostEqual(parsed.max_score, 0.42, places=4)


if __name__ == "__main__":
    unittest.main()
