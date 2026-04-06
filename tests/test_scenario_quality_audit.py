from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harness.loader import load_scenarios
from harness.models import DIMENSION_WEIGHTS
from scripts.audit_scenario_quality import audit_scenario_quality


def _trial_payload(
    *,
    trial_id: int = 1,
    score: float,
    capability_score: float,
    status: str = "success",
    error_detail: str = "",
) -> dict:
    return {
        "trial_id": trial_id,
        "score": score,
        "capability_score": capability_score,
        "passed": score >= 0.6,
        "safety_passed": True,
        "checks": [],
        "process_score": capability_score,
        "efficiency_score": score,
        "efficiency_penalty": 0.0,
        "latency_ms": 1000.0,
        "token_usage": {"total_tokens": 1000},
        "transcript": [],
        "tool_calls": [],
        "audit_state": {},
        "execution": {
            "mode": "live",
            "status": status,
            "exit_code": 0 if status == "success" else -1,
            "error_detail": error_detail,
        },
        "safety_failures": [],
        "workspace_path": None,
    }


def _scenario_payload(
    scenario_id: str,
    *,
    avg_score: float,
    capability_score: float,
    pass_rate: float,
    strict_pass_k: bool,
    trials: list[dict] | None = None,
) -> dict:
    scenario = next(item for item in load_scenarios(benchmark_status="all") if item.scenario_id == scenario_id)
    return {
        "scenario_id": scenario.scenario_id,
        "name": scenario.name,
        "dimension": scenario.dimension.value,
        "difficulty": scenario.difficulty.value,
        "benchmark_group": scenario.benchmark_group.value,
        "benchmark_core": scenario.benchmark_core,
        "avg_score": avg_score,
        "capability_score": capability_score,
        "pass_rate": pass_rate,
        "pass_at_k_any": pass_rate > 0.0,
        "pass_count": int(pass_rate > 0.0),
        "trial_count": 1,
        "strict_pass_k": strict_pass_k,
        "consistency": 0.0,
        "avg_latency_ms": 1000.0,
        "total_tokens": {"total_tokens": 1000},
        "cost_estimate_usd": 0.02,
        "difficulty_weight": scenario.difficulty_weight,
        "execution_mode": scenario.execution_mode,
        "stats": {},
        "trials": list(trials or []),
    }


def _report_payload(
    model: str,
    profile: str,
    scenarios: list[dict],
    *,
    covered_weight: float = 1.0,
    timestamp: str = "2026-03-22T00:00:00+00:00",
) -> dict:
    return {
        "model": model,
        "overall_score": 0.5,
        "capability_score": 0.5,
        "efficiency_score": 0.5,
        "total_scenarios": len(scenarios),
        "passed_scenarios": sum(1 for item in scenarios if item["strict_pass_k"]),
        "strict_pass_rate": 0.5,
        "avg_latency_ms": 1000.0,
        "total_tokens": {"total_tokens": 1000},
        "cost_estimate_usd": 0.02,
        "timestamp": timestamp,
        "trials_per_scenario": 1,
        "coverage": {"covered_weight": covered_weight},
        "summary": {"benchmark_selection": {"profile": profile}},
        "dimensions": {},
        "scenarios": scenarios,
    }


class ScenarioQualityAuditTests(unittest.TestCase):
    def test_audit_flags_tighten_promotion_and_efficiency_candidates(self) -> None:
        active = load_scenarios(benchmark_status="active")
        core_id = next(item.scenario_id for item in active if item.benchmark_core)
        non_core_ids = [item.scenario_id for item in active if not item.benchmark_core and item.benchmark_group.value == "intelligence"]
        promotion_id = non_core_ids[0]
        efficiency_id = non_core_ids[1]

        report_a = _report_payload(
            "model/a",
            "full",
            [
                _scenario_payload(core_id, avg_score=0.94, capability_score=0.96, pass_rate=1.0, strict_pass_k=True),
                _scenario_payload(promotion_id, avg_score=0.35, capability_score=0.35, pass_rate=0.0, strict_pass_k=False),
                _scenario_payload(efficiency_id, avg_score=0.72, capability_score=0.88, pass_rate=1.0, strict_pass_k=True),
            ],
        )
        report_b = _report_payload(
            "model/b",
            "full",
            [
                _scenario_payload(core_id, avg_score=0.93, capability_score=0.95, pass_rate=1.0, strict_pass_k=True),
                _scenario_payload(promotion_id, avg_score=0.75, capability_score=0.75, pass_rate=1.0, strict_pass_k=True),
                _scenario_payload(efficiency_id, avg_score=0.70, capability_score=0.86, pass_rate=1.0, strict_pass_k=True),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path_a = Path(tmpdir) / "a.json"
            path_b = Path(tmpdir) / "b.json"
            path_a.write_text(json.dumps(report_a), encoding="utf-8")
            path_b.write_text(json.dumps(report_b), encoding="utf-8")

            summary = audit_scenario_quality([str(path_a), str(path_b)])

        rows = {row["scenario_id"]: row for row in summary["scenarios"]}
        self.assertIn("candidate_tighten", rows[core_id]["flags"])
        self.assertIn("low_separation", rows[core_id]["flags"])
        self.assertIn("candidate_demote_from_core", rows[core_id]["flags"])
        self.assertIn("candidate_core_promotion", rows[promotion_id]["flags"])
        self.assertIn("high_separation", rows[promotion_id]["flags"])
        self.assertIn("efficiency_drag", rows[efficiency_id]["flags"])
        self.assertIn(efficiency_id, [item["scenario_id"] for item in summary["candidate_views"]["efficiency_review"]])

    def test_audit_tracks_target_capability_band_and_calibration_views(self) -> None:
        active = load_scenarios(benchmark_status="active")
        core_id = next(item.scenario_id for item in active if item.benchmark_core)
        below_id = next(
            item.scenario_id
            for item in active
            if item.benchmark_group.value == "intelligence" and not item.benchmark_core
        )
        within_id = next(
            item.scenario_id
            for item in active
            if item.scenario_id not in {core_id, below_id}
        )

        report = _report_payload(
            "model/a",
            "full",
            [
                _scenario_payload(core_id, avg_score=0.95, capability_score=0.95, pass_rate=1.0, strict_pass_k=True),
                _scenario_payload(below_id, avg_score=0.45, capability_score=0.45, pass_rate=0.0, strict_pass_k=False),
                _scenario_payload(within_id, avg_score=0.65, capability_score=0.65, pass_rate=1.0, strict_pass_k=True),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.json"
            path.write_text(json.dumps(report), encoding="utf-8")

            summary = audit_scenario_quality(
                [str(path)],
                target_capability_min=0.6,
                target_capability_max=0.7,
            )

        rows = {row["scenario_id"]: row for row in summary["scenarios"]}
        self.assertEqual(rows[core_id]["target_band_status"], "above_target_band")
        self.assertIn("calibration_tighten", rows[core_id]["flags"])
        self.assertEqual(rows[below_id]["target_band_status"], "below_target_band")
        self.assertIn("calibration_review_hard", rows[below_id]["flags"])
        self.assertEqual(rows[within_id]["target_band_status"], "within_target_band")
        self.assertEqual(summary["summary"]["target_band_counts"]["above_target_band"], 1)
        self.assertEqual(summary["summary"]["target_band_counts"]["below_target_band"], 1)
        self.assertEqual(summary["summary"]["target_band_counts"]["within_target_band"], 1)
        self.assertIn(core_id, [item["scenario_id"] for item in summary["candidate_views"]["calibration_tighten"]])
        self.assertIn(below_id, [item["scenario_id"] for item in summary["candidate_views"]["calibration_review_hard"]])
        self.assertIn(within_id, [item["scenario_id"] for item in summary["candidate_views"]["target_band_examples"]])

    def test_audit_can_filter_by_current_benchmark_profile(self) -> None:
        active = load_scenarios(benchmark_status="active")
        core_id = next(item.scenario_id for item in active if item.benchmark_core)
        extended_id = next(item.scenario_id for item in active if not item.benchmark_core)

        report = _report_payload(
            "model/a",
            "full",
            [
                _scenario_payload(core_id, avg_score=0.8, capability_score=0.8, pass_rate=1.0, strict_pass_k=True),
                _scenario_payload(extended_id, avg_score=0.5, capability_score=0.5, pass_rate=0.0, strict_pass_k=False),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.json"
            path.write_text(json.dumps(report), encoding="utf-8")

            summary = audit_scenario_quality([str(path)], benchmark_profile="core")

        scenario_ids = {row["scenario_id"] for row in summary["scenarios"]}
        self.assertIn(core_id, scenario_ids)
        self.assertNotIn(extended_id, scenario_ids)

    def test_audit_builds_aggregate_proxy_with_clean_fallbacks(self) -> None:
        active = load_scenarios(benchmark_status="active")
        tool_scenario = next(item for item in active if item.dimension.value == "tool_use")
        planning_scenario = next(item for item in active if item.dimension.value == "planning")
        catalog = load_scenarios(benchmark_status="active")
        by_dimension_total = {}
        for item in catalog:
            by_dimension_total[item.dimension] = by_dimension_total.get(item.dimension, 0.0) + item.difficulty_weight

        tool_weight = DIMENSION_WEIGHTS[tool_scenario.dimension] * (
            tool_scenario.difficulty_weight / by_dimension_total[tool_scenario.dimension]
        )
        planning_weight = DIMENSION_WEIGHTS[planning_scenario.dimension] * (
            planning_scenario.difficulty_weight / by_dimension_total[planning_scenario.dimension]
        )

        clean_report = _report_payload(
            "model/a",
            "full",
            [
                _scenario_payload(
                    tool_scenario.scenario_id,
                    avg_score=0.8,
                    capability_score=0.82,
                    pass_rate=1.0,
                    strict_pass_k=True,
                    trials=[_trial_payload(score=0.8, capability_score=0.82)],
                ),
                _scenario_payload(
                    planning_scenario.scenario_id,
                    avg_score=0.6,
                    capability_score=0.65,
                    pass_rate=1.0,
                    strict_pass_k=True,
                    trials=[_trial_payload(score=0.6, capability_score=0.65)],
                ),
            ],
            timestamp="2026-03-22T00:00:00+00:00",
        )
        corrupted_report = _report_payload(
            "model/a",
            "full",
            [
                _scenario_payload(
                    tool_scenario.scenario_id,
                    avg_score=0.1,
                    capability_score=0.1,
                    pass_rate=0.0,
                    strict_pass_k=False,
                    trials=[
                        _trial_payload(
                            score=0.1,
                            capability_score=0.1,
                            status="error",
                            error_detail="Invalid config at ~/.openclaw/openclaw.json: plugins.entries.cccontrol.service",
                        )
                    ],
                ),
            ],
            timestamp="2026-03-23T00:00:00+00:00",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            clean_path = Path(tmpdir) / "clean.json"
            corrupted_path = Path(tmpdir) / "corrupted.json"
            clean_path.write_text(json.dumps(clean_report), encoding="utf-8")
            corrupted_path.write_text(json.dumps(corrupted_report), encoding="utf-8")

            summary = audit_scenario_quality(
                [str(clean_path), str(corrupted_path)],
                model_filters=["model/a"],
                benchmark_profile="full",
            )

        proxy = summary["aggregate_proxy"]["models"]["model/a"]
        self.assertIn(tool_scenario.scenario_id, proxy["clean_fallback_scenario_ids"])
        self.assertIn(tool_scenario.scenario_id, proxy["latest_nonclean_scenario_ids"])
        self.assertIn(tool_scenario.scenario_id, proxy["latest_environment_corrupted_scenario_ids"])
        self.assertEqual(proxy["selected_clean_scenario_count"], 2)
        self.assertAlmostEqual(proxy["overall_score_proxy"], 0.28, places=4)
        self.assertAlmostEqual(proxy["capability_score_proxy"], 0.294, places=4)
        self.assertAlmostEqual(proxy["normalized_score_on_covered_proxy"], 0.7, places=4)
        self.assertAlmostEqual(
            proxy["overall_score_lower_bound_missing_zero"],
            round((tool_weight * 0.8) + (planning_weight * 0.6), 4),
            places=4,
        )
        self.assertAlmostEqual(
            proxy["catalog_weight_coverage_ratio"],
            round(tool_weight + planning_weight, 4),
            places=4,
        )


if __name__ == "__main__":
    unittest.main()
