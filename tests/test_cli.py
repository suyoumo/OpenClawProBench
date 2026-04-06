from __future__ import annotations

import io
import json
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from harness.loader import load_scenarios
import run


class CliTests(unittest.TestCase):
    def test_inventory_command_prints_summary(self) -> None:
        args = run.build_parser().parse_args(["inventory", "--tag", "oib5-live-smoke", "--benchmark-status", "all"])

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = args.func(args)
        output = buffer.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertIn("scenarios: 3", output)
        self.assertIn("execution_modes: {'live': 3}", output)
        self.assertIn("difficulty_weight_mass:", output)
        self.assertIn("directory_weight_mass:", output)
        self.assertIn("benchmark_core:", output)
        self.assertIn("benchmark_statuses:", output)
        self.assertIn("tags:", output)

    def test_inventory_command_can_emit_json(self) -> None:
        args = run.build_parser().parse_args(["inventory", "--tag", "oib5", "--json"])

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = args.func(args)
        payload = json.loads(buffer.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["benchmark_profile"], "full")
        expected_oib5 = load_scenarios(tag="oib5")
        expected_count = len(expected_oib5)
        self.assertEqual(payload["count"], expected_count)
        self.assertEqual(payload["execution_modes"], {"live": expected_count})
        self.assertIn("difficulty_weight_mass", payload)
        self.assertIn("directory_weight_mass", payload)
        self.assertEqual(payload["tags"]["oib5"], expected_count)

    def test_inventory_command_can_filter_intelligence_profile(self) -> None:
        args = run.build_parser().parse_args(["inventory", "--benchmark-profile", "intelligence", "--json"])

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = args.func(args)
        payload = json.loads(buffer.getvalue())

        self.assertEqual(exit_code, 0)
        expected = load_scenarios(benchmark_group="intelligence")
        expected_signal_sources: dict[str, int] = {}
        for scenario in expected:
            expected_signal_sources[scenario.signal_source.value] = expected_signal_sources.get(scenario.signal_source.value, 0) + 1

        self.assertEqual(payload["benchmark_profile"], "intelligence")
        self.assertEqual(payload["count"], len(expected))
        self.assertEqual(payload["benchmark_groups"], {"intelligence": len(expected)})
        self.assertEqual(payload["signal_sources"], expected_signal_sources)

    def test_inventory_command_can_filter_core_suite(self) -> None:
        args = run.build_parser().parse_args(["inventory", "--benchmark-profile", "core", "--json"])

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = args.func(args)
        payload = json.loads(buffer.getvalue())

        self.assertEqual(exit_code, 0)
        expected = load_scenarios(benchmark_group="intelligence", benchmark_core=True)

        self.assertEqual(payload["benchmark_profile"], "core")
        self.assertEqual(payload["count"], len(expected))
        self.assertEqual(payload["benchmark_core"], {"core": len(expected)})

    def test_inventory_command_can_filter_native_slice(self) -> None:
        args = run.build_parser().parse_args(["inventory", "--benchmark-profile", "native", "--json"])

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = args.func(args)
        payload = json.loads(buffer.getvalue())

        self.assertEqual(exit_code, 0)
        expected = load_scenarios(signal_source="openclaw_native")

        self.assertEqual(payload["benchmark_profile"], "native")
        self.assertEqual(payload["count"], len(expected))
        self.assertEqual(payload["signal_sources"], {"openclaw_native": len(expected)})
        self.assertEqual(payload["benchmark_selection"]["signal_source"], "openclaw_native")

    def test_inventory_command_can_filter_live_core_suite(self) -> None:
        args = run.build_parser().parse_args(
            ["inventory", "--benchmark-profile", "core", "--execution-mode", "live", "--json"]
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = args.func(args)
        payload = json.loads(buffer.getvalue())

        self.assertEqual(exit_code, 0)
        expected = load_scenarios(benchmark_group="intelligence", benchmark_core=True, execution_mode="live")

        self.assertEqual(payload["count"], len(expected))
        self.assertEqual(payload["dimensions"], dict(Counter(s.dimension.value for s in expected)))
        self.assertEqual(payload["execution_modes"], {"live": len(expected)})

    def test_removed_test_command_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            run.build_parser().parse_args(["test"])

    def test_removed_deprecated_status_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            run.build_parser().parse_args(["inventory", "--benchmark-status", "deprecated"])

    def test_run_command_defaults_to_live_core(self) -> None:
        args = run.build_parser().parse_args(["run", "--model", "glm/GLM-5"])
        selection = run._benchmark_selection(args)
        filters = run._scenario_filters(args)

        self.assertEqual(selection["benchmark_profile"], "core")
        self.assertEqual(filters["benchmark_group"], "intelligence")
        self.assertEqual(filters["benchmark_core"], True)
        self.assertIsNone(filters["signal_source"])
        self.assertEqual(args.execution_mode, "live")

    def test_run_command_accepts_live_parallel_flags(self) -> None:
        args = run.build_parser().parse_args(
            ["run", "--model", "glm/GLM-5", "--parallel", "3", "--allow-live-parallelism", "--live-retries", "1"]
        )

        self.assertEqual(args.parallel, 3)
        self.assertTrue(args.allow_live_parallelism)
        self.assertEqual(args.live_retries, 1)

    def test_run_command_accepts_openclaw_isolation_flags(self) -> None:
        args = run.build_parser().parse_args(
            [
                "run",
                "--model",
                "glm/GLM-5",
                "--openclaw-profile",
                "bench-a",
                "--openclaw-state-dir",
                "/tmp/openclaw-bench-a",
                "--openclaw-config-path",
                "/tmp/openclaw-bench-a/openclaw.json",
                "--openclaw-gateway-port",
                "19011",
            ]
        )

        self.assertEqual(args.openclaw_profile, "bench-a")
        self.assertEqual(args.openclaw_state_dir, "/tmp/openclaw-bench-a")
        self.assertEqual(args.openclaw_config_path, "/tmp/openclaw-bench-a/openclaw.json")
        self.assertEqual(args.openclaw_gateway_port, 19011)

    def test_run_command_accepts_timeout_multiplier(self) -> None:
        args = run.build_parser().parse_args(
            ["run", "--model", "glm/GLM-5", "--scenario", "intel_h03_temporal_constraint_scheduling", "--timeout-multiplier", "2"]
        )

        self.assertEqual(args.timeout_multiplier, 2.0)

    def test_run_command_accepts_rerun_execution_failures_flag(self) -> None:
        args = run.build_parser().parse_args(
            ["run", "--model", "glm/GLM-5", "--continue", "--rerun-execution-failures"]
        )

        self.assertTrue(args.continue_run)
        self.assertTrue(args.rerun_execution_failures)

    def test_apply_timeout_multiplier_clones_scenarios_with_adjusted_timeout(self) -> None:
        scenario = load_scenarios(scenario_id="intel_h03_temporal_constraint_scheduling")[0]
        original_timeout = scenario.timeout_seconds

        adjusted = run._apply_timeout_multiplier([scenario], 2.0)

        self.assertEqual(scenario.timeout_seconds, original_timeout)
        self.assertEqual(adjusted[0].timeout_seconds, original_timeout * 2)
        self.assertIsNot(adjusted[0], scenario)

    def test_cmd_run_finishes_without_recursive_reentry(self) -> None:
        args = run.build_parser().parse_args(["run", "--model", "glm/GLM-5", "--scenario", "stub_case", "--trials", "1"])
        fake_result = mock.Mock()
        fake_result.summary = {"report_path": ""}

        with (
            mock.patch.object(run, "load_scenarios", return_value=[mock.sentinel.scenario]),
            mock.patch.object(run, "reserve_report_path", return_value=Path("results/fake.json")),
            mock.patch.object(run, "write_report", return_value=Path("results/fake.json")),
            mock.patch.object(run, "print_summary"),
            mock.patch.object(run, "BenchmarkRunner") as runner_cls,
        ):
            runner_cls.return_value.run_with_resume.return_value = fake_result
            exit_code = args.func(args)

        self.assertEqual(exit_code, 0)
        runner_cls.return_value.run_with_resume.assert_called_once()

    def test_cmd_run_passes_rerun_execution_failures_to_runner_and_resume_hint(self) -> None:
        args = run.build_parser().parse_args(
            ["run", "--model", "glm/GLM-5", "--scenario", "stub_case", "--trials", "1", "--rerun-execution-failures"]
        )
        fake_result = mock.Mock()
        fake_result.summary = {"report_path": ""}
        buffer = io.StringIO()

        with (
            redirect_stdout(buffer),
            mock.patch.object(run, "load_scenarios", return_value=[mock.sentinel.scenario]),
            mock.patch.object(run, "reserve_report_path", return_value=Path("results/fake.json")),
            mock.patch.object(run, "write_report", return_value=Path("results/fake.json")),
            mock.patch.object(run, "print_summary"),
            mock.patch.object(run, "BenchmarkRunner") as runner_cls,
        ):
            runner_cls.return_value.run_with_resume.return_value = fake_result
            exit_code = args.func(args)

        self.assertEqual(exit_code, 0)
        kwargs = runner_cls.return_value.run_with_resume.call_args.kwargs
        self.assertTrue(kwargs["rerun_execution_failures"])
        output = buffer.getvalue()
        self.assertIn("--rerun-execution-failures", output)
        self.assertIn("resume_policy:", output)

    def test_cmd_run_passes_openclaw_isolation_options_to_runner(self) -> None:
        args = run.build_parser().parse_args(
            [
                "run",
                "--model",
                "glm/GLM-5",
                "--scenario",
                "stub_case",
                "--trials",
                "1",
                "--openclaw-binary",
                "/tmp/openclaw.mjs",
                "--openclaw-profile",
                "bench-a",
                "--openclaw-state-dir",
                "/tmp/openclaw-bench-a",
                "--openclaw-config-path",
                "/tmp/openclaw-bench-a/openclaw.json",
                "--openclaw-gateway-port",
                "19011",
            ]
        )
        fake_result = mock.Mock()
        fake_result.summary = {"report_path": ""}
        buffer = io.StringIO()

        with (
            redirect_stdout(buffer),
            mock.patch.object(run, "load_scenarios", return_value=[mock.sentinel.scenario]),
            mock.patch.object(run, "reserve_report_path", return_value=Path("results/fake.json")),
            mock.patch.object(run, "write_report", return_value=Path("results/fake.json")),
            mock.patch.object(run, "print_summary"),
            mock.patch.object(run, "BenchmarkRunner") as runner_cls,
        ):
            runner_cls.return_value.run_with_resume.return_value = fake_result
            exit_code = args.func(args)

        self.assertEqual(exit_code, 0)
        runner_cls.assert_called_once()
        kwargs = runner_cls.call_args.kwargs
        self.assertEqual(kwargs["openclaw_binary"], "/tmp/openclaw.mjs")
        self.assertEqual(kwargs["openclaw_profile"], "bench-a")
        self.assertEqual(kwargs["openclaw_state_dir"], "/tmp/openclaw-bench-a")
        self.assertEqual(kwargs["openclaw_config_path"], "/tmp/openclaw-bench-a/openclaw.json")
        self.assertEqual(kwargs["openclaw_gateway_port"], 19011)
        output = buffer.getvalue()
        self.assertIn("--openclaw-profile bench-a", output)
        self.assertIn("--openclaw-state-dir /tmp/openclaw-bench-a", output)
        self.assertIn("--openclaw-gateway-port 19011", output)


if __name__ == "__main__":
    unittest.main()
