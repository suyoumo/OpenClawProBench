from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.index_results import build_results_index


def _scenario_payload(trial_count: int = 1) -> dict:
    return {
        "scenario_id": "scenario_a",
        "name": "Scenario A",
        "dimension": "tool_use",
        "difficulty": "easy",
        "benchmark_group": "coverage",
        "benchmark_core": False,
        "avg_score": 1.0,
        "capability_score": 1.0,
        "pass_rate": 1.0,
        "pass_at_k_any": True,
        "pass_count": trial_count,
        "trial_count": trial_count,
        "strict_pass_k": True,
        "consistency": 0.0,
        "avg_latency_ms": 1000.0,
        "total_tokens": {"total_tokens": 100},
        "cost_estimate_usd": 0.0,
        "difficulty_weight": 1.0,
        "execution_mode": "live",
        "stats": {},
        "trials": [{"trial_id": index + 1} for index in range(trial_count)],
    }


def _report_payload(
    *,
    model: str,
    timestamp: str,
    profile: str = "full",
    covered_weight: float = 1.0,
    total_scenarios: int = 2,
    total_trials: int | None = 2,
    failure_examples: list[dict] | None = None,
    live_preflight: dict | None = None,
    trial_status_counts: dict | None = None,
    scenario_status_counts: dict | None = None,
    progress: dict | None = None,
    openclaw_runtime: dict | None = None,
) -> dict:
    failure_examples = failure_examples or []
    scenarios = [_scenario_payload() for _ in range(max(total_scenarios, 1))]
    return {
        "model": model,
        "overall_score": 0.75,
        "capability_score": 0.8,
        "efficiency_score": 0.75,
        "total_scenarios": total_scenarios,
        "passed_scenarios": total_scenarios,
        "strict_pass_rate": 1.0,
        "avg_latency_ms": 1000.0,
        "total_tokens": {"total_tokens": 1000},
        "cost_estimate_usd": 0.02,
        "timestamp": timestamp,
        "trials_per_scenario": 1,
        "coverage": {
            "covered_weight": covered_weight,
            "covered_dimension_count": 6,
            "total_dimension_count": 6,
            "normalized_score_on_covered": 0.75,
        },
        "summary": {
            "benchmark_selection": {"profile": profile, "scenario_count": total_scenarios},
            "progress": progress or {
                "completed_scenarios": total_scenarios,
                "requested_scenarios": total_scenarios,
                "remaining_scenarios": 0,
            },
            "normalized_capability_score_on_covered": 0.8,
            "total_trials": total_trials,
            "openclaw_runtime": openclaw_runtime or {},
            "execution": {
                "failure_count": len(failure_examples),
                "trial_status_counts": trial_status_counts or {},
                "scenario_status_counts": scenario_status_counts or {},
                "failure_examples": failure_examples,
                "live_preflight": live_preflight or {},
            },
        },
        "dimensions": {},
        "scenarios": scenarios,
    }


class ResultsIndexTests(unittest.TestCase):
    def test_build_results_index_labels_full_and_partial_reports(self) -> None:
        full_report = _report_payload(
            model="model/full",
            timestamp="2026-03-24T09:00:00+00:00",
            covered_weight=1.0,
        )
        partial_report = _report_payload(
            model="model/custom",
            timestamp="2026-03-24T10:00:00+00:00",
            profile="custom",
            covered_weight=0.2,
            total_scenarios=1,
            total_trials=1,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            full_path = Path(tmpdir) / "full.json"
            partial_path = Path(tmpdir) / "partial.json"
            full_path.write_text(json.dumps(full_report), encoding="utf-8")
            partial_path.write_text(json.dumps(partial_report), encoding="utf-8")

            index = build_results_index([str(full_path), str(partial_path)])

        self.assertEqual(index["summary"]["run_labels"]["full"], 1)
        self.assertEqual(index["summary"]["run_labels"]["custom_subset"], 1)
        self.assertEqual(index["summary"]["selection_kinds"]["custom_selection"], 1)
        self.assertEqual(index["reports"][0]["model"], "model/custom")
        self.assertEqual(index["reports"][0]["coverage_scope"], "partial")
        self.assertEqual(index["reports"][0]["selection_kind"], "custom_selection")
        self.assertEqual(index["reports"][0]["completion_status"], "complete")
        self.assertEqual(index["reports"][0]["partial_reason"], "custom_selection")
        self.assertEqual(index["reports"][0]["integrity_status"], "clean")
        self.assertEqual(index["reports"][0]["run_label"], "custom_subset")
        self.assertEqual(index["reports"][1]["coverage_scope"], "full")
        self.assertEqual(index["reports"][1]["run_label"], "full")

    def test_build_results_index_labels_profile_subset_runs_separately_from_custom(self) -> None:
        core_report = _report_payload(
            model="model/core",
            timestamp="2026-03-24T10:30:00+00:00",
            profile="core",
            covered_weight=0.2,
            total_scenarios=3,
            total_trials=3,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "core.json"
            report_path.write_text(json.dumps(core_report), encoding="utf-8")

            index = build_results_index([str(report_path)])

        row = index["reports"][0]
        self.assertEqual(row["coverage_scope"], "partial")
        self.assertEqual(row["selection_kind"], "benchmark_profile")
        self.assertEqual(row["completion_status"], "complete")
        self.assertEqual(row["partial_reason"], "benchmark_profile_subset")
        self.assertEqual(row["run_label"], "profile_subset")
        self.assertTrue(row["is_profile_subset"])
        self.assertFalse(row["is_custom_selection"])

    def test_build_results_index_marks_environment_corrupted_full_run(self) -> None:
        corrupted_report = _report_payload(
            model="model/corrupted",
            timestamp="2026-03-24T11:00:00+00:00",
            covered_weight=1.0,
            failure_examples=[
                {
                    "scenario_id": "synthesis_10_cross_modal_reasoning_live",
                    "trial_id": 1,
                    "status": "error",
                    "error_detail": "Invalid config at /Users/test/.openclaw/openclaw.json:\nConfig invalid",
                }
            ],
            trial_status_counts={"success": 5, "error": 1},
            scenario_status_counts={"success": 5, "failure": 1},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "corrupted.json"
            report_path.write_text(json.dumps(corrupted_report), encoding="utf-8")

            index = build_results_index([str(report_path)])

        row = index["reports"][0]
        self.assertEqual(row["coverage_scope"], "full")
        self.assertEqual(row["integrity_status"], "environment_corrupted")
        self.assertEqual(row["run_label"], "corrupted")
        self.assertTrue(row["is_corrupted"])
        self.assertIn("invalid_config", row["runtime_failure_markers"])
        self.assertIn("invalid_config", row["environment_failure_markers"])

    def test_build_results_index_marks_preflight_dependency_failure_as_partial_corrupted(self) -> None:
        preflight_failed = _report_payload(
            model="model/preflight",
            timestamp="2026-03-24T12:00:00+00:00",
            profile="custom",
            covered_weight=0.2,
            total_scenarios=1,
            total_trials=1,
            live_preflight={
                "ok": False,
                "exit_code": 1,
                "duration_seconds": 5.0,
                "error_detail": "[openclaw] Failed to start CLI: Error: Cannot find module 'gaxios'",
            },
            failure_examples=[],
            trial_status_counts={"error": 1},
            scenario_status_counts={"failure": 1},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "preflight.json"
            report_path.write_text(json.dumps(preflight_failed), encoding="utf-8")

            index = build_results_index([str(report_path)])

        row = index["reports"][0]
        self.assertEqual(row["integrity_status"], "environment_corrupted")
        self.assertEqual(row["partial_reason"], "custom_selection")
        self.assertEqual(row["run_label"], "custom_subset_corrupted")
        self.assertTrue(row["has_live_preflight_failure"])
        self.assertIn("live_preflight_failed", row["runtime_failure_markers"])
        self.assertIn("missing_dependency", row["environment_failure_markers"])

    def test_build_results_index_marks_provider_auth_failure_as_environment_corrupted(self) -> None:
        auth_failed = _report_payload(
            model="model/auth-failed",
            timestamp="2026-03-24T12:15:00+00:00",
            covered_weight=1.0,
            failure_examples=[
                {
                    "scenario_id": "tool_use_09_capability_boundary_live",
                    "trial_id": 1,
                    "status": "error",
                    "error_detail": "No API key for provider: minimax",
                }
            ],
            trial_status_counts={"error": 1},
            scenario_status_counts={"failure": 1},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "auth-failed.json"
            report_path.write_text(json.dumps(auth_failed), encoding="utf-8")

            index = build_results_index([str(report_path)])

        row = index["reports"][0]
        self.assertEqual(row["integrity_status"], "environment_corrupted")
        self.assertIn("provider_auth_missing", row["runtime_failure_markers"])
        self.assertIn("provider_auth_missing", row["environment_failure_markers"])

    def test_build_results_index_labels_incomplete_runs_explicitly(self) -> None:
        incomplete_report = _report_payload(
            model="model/incomplete",
            timestamp="2026-03-24T12:30:00+00:00",
            profile="full",
            covered_weight=0.4,
            total_scenarios=10,
            total_trials=4,
            progress={
                "completed_scenarios": 4,
                "requested_scenarios": 10,
                "remaining_scenarios": 6,
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "incomplete.json"
            report_path.write_text(json.dumps(incomplete_report), encoding="utf-8")

            index = build_results_index([str(report_path)])

        row = index["reports"][0]
        self.assertEqual(row["completion_status"], "incomplete")
        self.assertEqual(row["partial_reason"], "incomplete_run")
        self.assertEqual(row["run_label"], "incomplete")
        self.assertTrue(row["is_incomplete"])

    def test_build_results_index_falls_back_to_scenario_trial_counts(self) -> None:
        report = _report_payload(
            model="model/fallback",
            timestamp="2026-03-24T08:00:00+00:00",
            total_trials=None,
        )
        report["summary"].pop("total_trials")
        report["scenarios"] = [_scenario_payload(trial_count=2), _scenario_payload(trial_count=3)]

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "fallback.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            index = build_results_index([str(report_path)])

        row = index["reports"][0]
        self.assertEqual(row["trial_count"], 5)

    def test_build_results_index_exposes_current_catalog_drift(self) -> None:
        report = _report_payload(
            model="model/historical-full",
            timestamp="2026-03-24T13:00:00+00:00",
            profile="full",
            total_scenarios=12,
        )
        current_catalog_snapshot = {
            "active_count": 9,
            "all_status_count": 11,
            "active_profile_counts": {
                "full": 9,
                "core": 3,
                "intelligence": 6,
                "coverage": 3,
                "native": 2,
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "historical.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            index = build_results_index(
                [str(report_path)],
                current_catalog_snapshot=current_catalog_snapshot,
            )

        row = index["reports"][0]
        self.assertEqual(index["current_catalog_snapshot"]["active_count"], 9)
        self.assertEqual(index["summary"]["current_catalog_comparison"]["drifted"], 1)
        self.assertEqual(row["current_catalog_profile_count"], 9)
        self.assertEqual(row["current_catalog_count_delta"], -3)
        self.assertFalse(row["current_catalog_matches_profile_count"])

    def test_build_results_index_exposes_openclaw_runtime_provenance(self) -> None:
        report = _report_payload(
            model="model/runtime-aware",
            timestamp="2026-03-24T14:00:00+00:00",
            openclaw_runtime={
                "binary_realpath": "/tmp/openclaw.mjs",
                "binary_sha256": "abc123",
                "git_commit": "deadbeefcafebabefeedface1234567890abcdef",
                "git_commit_short": "deadbeefcafe",
                "git_dirty": True,
                "version_text": "OpenClaw 0.1.0",
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "runtime-aware.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            index = build_results_index([str(report_path)])

        row = index["reports"][0]
        self.assertTrue(row["openclaw_runtime_present"])
        self.assertEqual(row["openclaw_runtime_commit_short"], "deadbeefcafe")
        self.assertTrue(row["openclaw_runtime_dirty"])
        self.assertEqual(row["openclaw_runtime_binary_sha256"], "abc123")


if __name__ == "__main__":
    unittest.main()
