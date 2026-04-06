#!/usr/bin/env python3
"""Audit scenario quality from existing benchmark result reports."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import glob
import json
from pathlib import Path
import statistics
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.benchmark_profiles import benchmark_profile_choices, resolve_benchmark_selection
from harness.loader import load_scenarios
from harness.models import BenchmarkResult, DIMENSION_WEIGHTS, Dimension, ScenarioResult


SATURATION_CAPABILITY_THRESHOLD = 0.90
SATURATION_STRICT_PASS_THRESHOLD = 0.90
SATURATION_STDDEV_THRESHOLD = 0.08
EFFICIENCY_DRAG_THRESHOLD = 0.08
INSTABILITY_STDDEV_THRESHOLD = 0.15
LOW_SEPARATION_RANGE_THRESHOLD = 0.12
HIGH_SEPARATION_RANGE_THRESHOLD = 0.25
PROMOTION_CAPABILITY_MIN = 0.25
PROMOTION_CAPABILITY_MAX = 0.85
DEFAULT_TARGET_CAPABILITY_MIN = 0.60
DEFAULT_TARGET_CAPABILITY_MAX = 0.70
ENVIRONMENT_FAILURE_MARKERS = {
    "gateway_agent_failure",
    "invalid_config",
    "live_preflight_failed",
    "missing_dependency",
    "node_version_mismatch",
    "plugin_load_failure",
    "plugin_path_missing",
    "provider_auth_missing",
    "unknown_agent_id",
}


@dataclass(frozen=True)
class ReportRecord:
    path: Path
    model: str
    profile: str
    timestamp: str
    covered_weight: float
    result: BenchmarkResult


@dataclass(frozen=True)
class ScenarioObservation:
    report: ReportRecord
    scenario: ScenarioResult


def _mean(values: list[float], *, decimals: int = 4) -> float:
    if not values:
        return 0.0
    return round(statistics.fmean(values), decimals)


def _stddev(values: list[float], *, decimals: int = 6) -> float:
    if len(values) <= 1:
        return 0.0
    return round(statistics.pstdev(values), decimals)


def _parse_timestamp(value: str) -> datetime:
    text = value.strip()
    if not text:
        return datetime.min
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.min


def _observation_sort_key(observation: ScenarioObservation) -> tuple[datetime, str]:
    return (_parse_timestamp(observation.report.timestamp), str(observation.report.path))


def _expand_report_paths(raw_paths: list[str]) -> list[Path]:
    if not raw_paths:
        raw_paths = ["results/result_*.json"]

    expanded: list[Path] = []
    for raw_path in raw_paths:
        matches = sorted(Path(path).resolve() for path in glob.glob(raw_path))
        if matches:
            expanded.extend(matches)
            continue
        path = Path(raw_path).resolve()
        if path.exists():
            expanded.append(path)
            continue
        raise FileNotFoundError(f"Report path not found: {raw_path}")

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in expanded:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _load_report(path: Path) -> ReportRecord:
    raw = json.loads(path.read_text(encoding="utf-8"))
    result = BenchmarkResult.from_dict(raw)
    summary = dict(raw.get("summary", {}))
    selection = dict(summary.get("benchmark_selection", {}))
    coverage = dict(raw.get("coverage", {}))
    profile = str(selection.get("profile", "custom"))
    covered_weight = float(coverage.get("covered_weight", 1.0) or 0.0)
    return ReportRecord(
        path=path,
        model=result.model,
        profile=profile,
        timestamp=str(raw.get("timestamp", "")),
        covered_weight=covered_weight,
        result=result,
    )


def _filter_reports(
    reports: list[ReportRecord],
    *,
    model_filters: list[str],
    report_profile: str | None,
    full_coverage_only: bool,
    latest_per_model_profile: bool,
) -> list[ReportRecord]:
    filtered = reports
    if model_filters:
        lowered = [item.lower() for item in model_filters]
        filtered = [
            report
            for report in filtered
            if any(fragment in report.model.lower() for fragment in lowered)
        ]
    if report_profile:
        filtered = [report for report in filtered if report.profile == report_profile]
    if full_coverage_only:
        filtered = [report for report in filtered if report.covered_weight >= 0.9999]
    if not latest_per_model_profile:
        return filtered

    latest: dict[tuple[str, str], ReportRecord] = {}
    for report in filtered:
        key = (report.model, report.profile)
        current = latest.get(key)
        if current is None:
            latest[key] = report
            continue
        if (_parse_timestamp(report.timestamp), str(report.path)) >= (_parse_timestamp(current.timestamp), str(current.path)):
            latest[key] = report
    return sorted(latest.values(), key=lambda item: (item.model, item.profile, _parse_timestamp(item.timestamp), str(item.path)))


def _selected_scenario_ids(benchmark_profile: str | None) -> tuple[set[str] | None, dict[str, Any]]:
    if not benchmark_profile:
        return None, {}

    selection = resolve_benchmark_selection(benchmark_profile)
    scenarios = load_scenarios(
        benchmark_group=selection["benchmark_group"],
        benchmark_core=selection["benchmark_core"],
        benchmark_status=selection["benchmark_status"],
        signal_source=selection["signal_source"],
    )
    return {scenario.scenario_id for scenario in scenarios}, selection


def _selected_catalog_scenarios(benchmark_profile: str | None) -> tuple[list[Any], dict[str, Any]]:
    if not benchmark_profile:
        return [], {}

    selection = resolve_benchmark_selection(benchmark_profile)
    scenarios = load_scenarios(
        benchmark_group=selection["benchmark_group"],
        benchmark_core=selection["benchmark_core"],
        benchmark_status=selection["benchmark_status"],
        signal_source=selection["signal_source"],
    )
    return scenarios, selection


def _scenario_catalog() -> dict[str, Any]:
    return {
        scenario.scenario_id: scenario
        for scenario in load_scenarios(benchmark_status="all")
    }


def _extract_failure_markers(detail: str, *, status: str = "", preflight_failed: bool = False) -> list[str]:
    markers: set[str] = set()
    normalized_status = status.strip().lower()
    text = detail.lower()

    if normalized_status and normalized_status != "success":
        markers.add(normalized_status)
    if preflight_failed:
        markers.add("live_preflight_failed")
    if "timed out" in text:
        markers.add("timeout")
    if "invalid config" in text or "config invalid" in text:
        markers.add("invalid_config")
    if "plugin path not found" in text:
        markers.add("plugin_path_missing")
    if "cannot find module" in text or "cannot find package" in text or "err_module_not_found" in text:
        markers.add("missing_dependency")
    if "node.js v" in text and "is required" in text:
        markers.add("node_version_mismatch")
    if "failed to load" in text and "plugin" in text:
        markers.add("plugin_load_failure")
    if "gateway agent failed" in text:
        markers.add("gateway_agent_failure")
    if "unknown agent id" in text:
        markers.add("unknown_agent_id")
    if "no api key for provider" in text or "no auth profiles found for providers" in text:
        markers.add("provider_auth_missing")

    return sorted(markers)


def _scenario_observation_integrity(observation: ScenarioObservation) -> dict[str, Any]:
    trial_status_counts: Counter[str] = Counter()
    failure_markers: set[str] = set()

    for trial in observation.scenario.trials:
        status = trial.execution.status.strip().lower() or "success"
        trial_status_counts[status] += 1
        failure_markers.update(
            _extract_failure_markers(
                str(trial.execution.error_detail or ""),
                status=status,
            )
        )

    clean = not trial_status_counts or set(trial_status_counts) <= {"success"}
    environment_corrupted = any(marker in ENVIRONMENT_FAILURE_MARKERS for marker in failure_markers)
    return {
        "clean": clean,
        "environment_corrupted": environment_corrupted,
        "trial_status_counts": dict(trial_status_counts),
        "failure_markers": sorted(failure_markers),
    }


def _catalog_proxy_weights(catalog_scenarios: list[Any]) -> dict[str, float]:
    by_dimension_weight_sum: dict[Dimension, float] = defaultdict(float)
    for scenario in catalog_scenarios:
        by_dimension_weight_sum[scenario.dimension] += scenario.difficulty_weight

    weights: dict[str, float] = {}
    for scenario in catalog_scenarios:
        dimension_total = by_dimension_weight_sum[scenario.dimension]
        difficulty_share = scenario.difficulty_weight / dimension_total if dimension_total > 0 else 0.0
        weights[scenario.scenario_id] = DIMENSION_WEIGHTS[scenario.dimension] * difficulty_share
    return weights


def _aggregate_selected_results(scenario_results: list[ScenarioResult]) -> dict[str, Any]:
    dimension_summaries: dict[str, dict[str, Any]] = {}
    overall_score = 0.0
    capability_score = 0.0

    for dimension_name in sorted({item.dimension for item in scenario_results}, key=lambda value: value.value):
        matching = [item for item in scenario_results if item.dimension == dimension_name]
        weighted = sum(item.avg_score * item.difficulty_weight for item in matching)
        capability_weighted = sum(item.capability_score * item.difficulty_weight for item in matching)
        weights = sum(item.difficulty_weight for item in matching)
        score = weighted / weights if weights else 0.0
        capability = capability_weighted / weights if weights else 0.0
        overall_score += score * DIMENSION_WEIGHTS[dimension_name]
        capability_score += capability * DIMENSION_WEIGHTS[dimension_name]
        dimension_summaries[dimension_name.value] = {
            "score": round(score, 4),
            "capability_score": round(capability, 4),
            "scenario_count": len(matching),
        }

    covered_dimensions = sorted({item.dimension.value for item in scenario_results})
    covered_weight = sum(DIMENSION_WEIGHTS[Dimension(name)] for name in covered_dimensions)
    return {
        "dimensions": dimension_summaries,
        "covered_dimensions": covered_dimensions,
        "covered_weight": round(covered_weight, 4),
        "overall_score": round(overall_score, 4),
        "capability_score": round(capability_score, 4),
        "normalized_score_on_covered": round(overall_score / covered_weight, 4) if covered_weight > 0 else 0.0,
        "normalized_capability_score_on_covered": round(capability_score / covered_weight, 4) if covered_weight > 0 else 0.0,
    }


def _aggregate_proxy_for_model(
    model: str,
    catalog_scenarios: list[Any],
    observations_by_scenario: dict[str, list[ScenarioObservation]],
) -> dict[str, Any]:
    catalog_by_id = {scenario.scenario_id: scenario for scenario in catalog_scenarios}
    catalog_weights = _catalog_proxy_weights(catalog_scenarios)
    selected_results: list[ScenarioResult] = []
    latest_nonclean_scenario_ids: list[str] = []
    latest_environment_corrupted_scenario_ids: list[str] = []
    clean_fallback_scenario_ids: list[str] = []
    missing_observation_scenario_ids: list[str] = []
    missing_clean_scenario_ids: list[str] = []
    selected_report_profiles: Counter[str] = Counter()
    top_score_contributors: list[dict[str, Any]] = []
    top_capability_contributors: list[dict[str, Any]] = []

    for scenario in catalog_scenarios:
        scenario_id = scenario.scenario_id
        model_observations = [
            item
            for item in observations_by_scenario.get(scenario_id, [])
            if item.report.model == model
        ]
        model_observations.sort(key=_observation_sort_key)
        if not model_observations:
            missing_observation_scenario_ids.append(scenario_id)
            missing_clean_scenario_ids.append(scenario_id)
            continue

        latest_observation = model_observations[-1]
        latest_integrity = _scenario_observation_integrity(latest_observation)
        if not latest_integrity["clean"]:
            latest_nonclean_scenario_ids.append(scenario_id)
        if latest_integrity["environment_corrupted"]:
            latest_environment_corrupted_scenario_ids.append(scenario_id)

        clean_observations = [
            item
            for item in model_observations
            if _scenario_observation_integrity(item)["clean"]
        ]
        if not clean_observations:
            missing_clean_scenario_ids.append(scenario_id)
            continue

        selected_observation = clean_observations[-1]
        if selected_observation is not latest_observation:
            clean_fallback_scenario_ids.append(scenario_id)

        selected_report_profiles[selected_observation.report.profile] += 1
        selected_scenario = selected_observation.scenario
        selected_results.append(
            ScenarioResult(
                scenario_id=scenario_id,
                name=scenario.name,
                dimension=scenario.dimension,
                difficulty=scenario.difficulty,
                benchmark_group=scenario.benchmark_group,
                benchmark_core=scenario.benchmark_core,
                trials=selected_scenario.trials,
                avg_score=selected_scenario.avg_score,
                max_score=selected_scenario.max_score,
                capability_score=selected_scenario.capability_score,
                pass_rate=selected_scenario.pass_rate,
                pass_at_k_any=selected_scenario.pass_at_k_any,
                pass_count=selected_scenario.pass_count,
                trial_count=selected_scenario.trial_count,
                strict_pass_k=selected_scenario.strict_pass_k,
                consistency=selected_scenario.consistency,
                avg_latency_ms=selected_scenario.avg_latency_ms,
                total_tokens=selected_scenario.total_tokens,
                cost_estimate_usd=selected_scenario.cost_estimate_usd,
                difficulty_weight=scenario.difficulty_weight,
                execution_mode=scenario.execution_mode,
                stats=selected_scenario.stats,
            )
        )

        catalog_weight = catalog_weights.get(scenario_id, 0.0)
        contributor_row = {
            "scenario_id": scenario_id,
            "dimension": scenario.dimension.value,
            "benchmark_group": scenario.benchmark_group.value,
            "benchmark_core": scenario.benchmark_core,
            "catalog_weight": round(catalog_weight, 6),
            "avg_score": round(selected_scenario.avg_score, 4),
            "capability_score": round(selected_scenario.capability_score, 4),
            "score_contribution": round(catalog_weight * selected_scenario.avg_score, 6),
            "capability_contribution": round(catalog_weight * selected_scenario.capability_score, 6),
            "source_report": str(selected_observation.report.path),
            "source_report_profile": selected_observation.report.profile,
            "source_timestamp": selected_observation.report.timestamp,
            "used_clean_fallback": selected_observation is not latest_observation,
        }
        top_score_contributors.append(contributor_row)
        top_capability_contributors.append(contributor_row)

    aggregated = _aggregate_selected_results(selected_results)
    catalog_weight_coverage = sum(catalog_weights[item.scenario_id] for item in selected_results)
    overall_score_lower_bound = sum(catalog_weights[item.scenario_id] * item.avg_score for item in selected_results)
    capability_score_lower_bound = sum(catalog_weights[item.scenario_id] * item.capability_score for item in selected_results)
    catalog_dimension_counts = Counter(scenario.dimension.value for scenario in catalog_scenarios)
    selected_dimension_counts = Counter(item.dimension.value for item in selected_results)

    top_score_contributors.sort(
        key=lambda item: (-item["score_contribution"], -item["catalog_weight"], item["scenario_id"])
    )
    top_capability_contributors.sort(
        key=lambda item: (-item["capability_contribution"], -item["catalog_weight"], item["scenario_id"])
    )

    return {
        "catalog_scenario_count": len(catalog_scenarios),
        "catalog_dimensions": sorted(catalog_dimension_counts),
        "catalog_dimension_counts": dict(catalog_dimension_counts),
        "observation_scenario_count": len(catalog_scenarios) - len(missing_observation_scenario_ids),
        "clean_observation_scenario_count": len(catalog_scenarios) - len(missing_clean_scenario_ids),
        "selected_clean_scenario_count": len(selected_results),
        "scenario_coverage_ratio": round(len(selected_results) / len(catalog_scenarios), 4) if catalog_scenarios else 0.0,
        "catalog_weight_coverage_ratio": round(catalog_weight_coverage, 4),
        "exact_catalog_proxy": len(selected_results) == len(catalog_scenarios),
        "missing_observation_scenario_ids": sorted(missing_observation_scenario_ids),
        "missing_clean_scenario_ids": sorted(missing_clean_scenario_ids),
        "latest_nonclean_scenario_ids": sorted(latest_nonclean_scenario_ids),
        "latest_environment_corrupted_scenario_ids": sorted(latest_environment_corrupted_scenario_ids),
        "clean_fallback_scenario_ids": sorted(clean_fallback_scenario_ids),
        "selected_report_profiles": dict(selected_report_profiles),
        "selected_dimension_counts": dict(selected_dimension_counts),
        "covered_dimensions": aggregated["covered_dimensions"],
        "covered_weight": aggregated["covered_weight"],
        "overall_score_proxy": aggregated["overall_score"],
        "capability_score_proxy": aggregated["capability_score"],
        "normalized_score_on_covered_proxy": aggregated["normalized_score_on_covered"],
        "normalized_capability_score_on_covered_proxy": aggregated["normalized_capability_score_on_covered"],
        "overall_score_lower_bound_missing_zero": round(overall_score_lower_bound, 4),
        "capability_score_lower_bound_missing_zero": round(capability_score_lower_bound, 4),
        "dimension_proxies": aggregated["dimensions"],
        "top_score_contributors": top_score_contributors[:10],
        "top_capability_contributors": top_capability_contributors[:10],
    }


def _build_row(
    scenario_id: str,
    observations: list[ScenarioObservation],
    catalog: dict[str, Any],
    *,
    target_capability_min: float,
    target_capability_max: float,
) -> dict[str, Any]:
    first = observations[0].scenario
    metadata = catalog.get(scenario_id)

    scores = [item.scenario.avg_score for item in observations]
    capabilities = [item.scenario.capability_score for item in observations]
    pass_rates = [item.scenario.pass_rate for item in observations]
    pass_any = [1.0 if item.scenario.pass_at_k_any else 0.0 for item in observations]
    strict_pass = [1.0 if item.scenario.strict_pass_k else 0.0 for item in observations]
    within_run_stddevs = [item.scenario.consistency for item in observations]
    latencies_s = [item.scenario.avg_latency_ms / 1000.0 for item in observations]
    total_tokens = [float(item.scenario.total_tokens.get("total_tokens", 0.0) or 0.0) for item in observations]
    costs = [float(item.scenario.cost_estimate_usd) for item in observations]
    efficiency_drags = [
        max(item.scenario.capability_score - item.scenario.avg_score, 0.0)
        for item in observations
    ]

    by_model_scores: dict[str, list[float]] = defaultdict(list)
    by_model_capabilities: dict[str, list[float]] = defaultdict(list)
    for item in observations:
        by_model_scores[item.report.model].append(item.scenario.avg_score)
        by_model_capabilities[item.report.model].append(item.scenario.capability_score)

    model_capability_means = {
        model: _mean(values, decimals=6)
        for model, values in by_model_capabilities.items()
    }
    cross_model_capability_range = None
    if len(model_capability_means) >= 2:
        cross_model_capability_range = round(
            max(model_capability_means.values()) - min(model_capability_means.values()),
            4,
        )

    same_model_score_stddev_max = 0.0
    same_model_capability_stddev_max = 0.0
    for model, values in by_model_scores.items():
        same_model_score_stddev_max = max(same_model_score_stddev_max, _stddev(values))
        same_model_capability_stddev_max = max(
            same_model_capability_stddev_max,
            _stddev(by_model_capabilities[model]),
        )

    row = {
        "scenario_id": scenario_id,
        "name": metadata.name if metadata else first.name,
        "dimension": metadata.dimension.value if metadata else first.dimension.value,
        "difficulty": metadata.difficulty.value if metadata else first.difficulty.value,
        "benchmark_group": metadata.benchmark_group.value if metadata else first.benchmark_group.value,
        "benchmark_core": metadata.benchmark_core if metadata else first.benchmark_core,
        "signal_source": metadata.signal_source.value if metadata else "unknown",
        "execution_mode": metadata.execution_mode if metadata else first.execution_mode,
        "openclaw_surfaces": list(metadata.openclaw_surfaces) if metadata else [],
        "custom_check": bool(getattr(metadata, "custom_check", None)) if metadata else False,
        "reports_seen": len({item.report.path for item in observations}),
        "observation_count": len(observations),
        "models_seen": sorted(by_model_scores),
        "model_count": len(by_model_scores),
        "avg_score": _mean(scores),
        "capability_score": _mean(capabilities),
        "avg_efficiency_drag": _mean(efficiency_drags),
        "pass_at_1": _mean(pass_rates),
        "pass_at_k_any": _mean(pass_any),
        "strict_pass_rate": _mean(strict_pass),
        "avg_within_run_score_stddev": _mean(within_run_stddevs, decimals=6),
        "observation_score_stddev": _stddev(scores),
        "same_model_score_stddev_max": round(same_model_score_stddev_max, 6),
        "same_model_capability_stddev_max": round(same_model_capability_stddev_max, 6),
        "cross_model_capability_range": cross_model_capability_range,
        "avg_latency_s": _mean(latencies_s),
        "avg_total_tokens": _mean(total_tokens, decimals=2),
        "avg_cost_usd": _mean(costs, decimals=8),
        "target_band_status": "",
        "flags": [],
    }

    saturated = (
        row["capability_score"] >= SATURATION_CAPABILITY_THRESHOLD
        and row["strict_pass_rate"] >= SATURATION_STRICT_PASS_THRESHOLD
        and row["same_model_score_stddev_max"] <= SATURATION_STDDEV_THRESHOLD
        and row["avg_within_run_score_stddev"] <= SATURATION_STDDEV_THRESHOLD
    )
    if saturated:
        row["flags"].append("saturated")

    if (
        row["cross_model_capability_range"] is not None
        and row["cross_model_capability_range"] <= LOW_SEPARATION_RANGE_THRESHOLD
        and row["capability_score"] >= 0.80
    ):
        row["flags"].append("low_separation")

    if (
        row["cross_model_capability_range"] is not None
        and row["cross_model_capability_range"] >= HIGH_SEPARATION_RANGE_THRESHOLD
        and PROMOTION_CAPABILITY_MIN <= row["capability_score"] <= PROMOTION_CAPABILITY_MAX
    ):
        row["flags"].append("high_separation")

    if row["avg_efficiency_drag"] >= EFFICIENCY_DRAG_THRESHOLD and row["capability_score"] >= 0.70:
        row["flags"].append("efficiency_drag")

    if (
        row["avg_within_run_score_stddev"] >= INSTABILITY_STDDEV_THRESHOLD
        or row["same_model_score_stddev_max"] >= INSTABILITY_STDDEV_THRESHOLD
        or row["same_model_capability_stddev_max"] >= INSTABILITY_STDDEV_THRESHOLD
    ):
        row["flags"].append("stability_review")

    if "saturated" in row["flags"] and row["benchmark_group"] == "intelligence":
        row["flags"].append("candidate_tighten")

    if row["benchmark_core"] and "candidate_tighten" in row["flags"] and "low_separation" in row["flags"]:
        row["flags"].append("candidate_demote_from_core")

    if (
        not row["benchmark_core"]
        and row["benchmark_group"] == "intelligence"
        and row["execution_mode"] == "live"
        and "high_separation" in row["flags"]
    ):
        row["flags"].append("candidate_core_promotion")

    if row["difficulty"] in {"hard", "expert"} and "saturated" in row["flags"]:
        row["flags"].append("difficulty_mismatch")

    if row["capability_score"] < target_capability_min:
        row["target_band_status"] = "below_target_band"
        row["flags"].append("below_target_band")
    elif row["capability_score"] > target_capability_max:
        row["target_band_status"] = "above_target_band"
        row["flags"].append("above_target_band")
    else:
        row["target_band_status"] = "within_target_band"

    if row["target_band_status"] == "above_target_band" and row["benchmark_group"] == "intelligence":
        row["flags"].append("calibration_tighten")

    if (
        row["target_band_status"] == "below_target_band"
        and row["benchmark_group"] == "intelligence"
        and "stability_review" not in row["flags"]
    ):
        row["flags"].append("calibration_review_hard")

    return row


def audit_scenario_quality(
    report_paths: list[str],
    *,
    model_filters: list[str] | None = None,
    report_profile: str | None = None,
    benchmark_profile: str | None = None,
    full_coverage_only: bool = False,
    latest_per_model_profile: bool = False,
    target_capability_min: float = DEFAULT_TARGET_CAPABILITY_MIN,
    target_capability_max: float = DEFAULT_TARGET_CAPABILITY_MAX,
) -> dict[str, Any]:
    model_filters = model_filters or []
    reports = [_load_report(path) for path in _expand_report_paths(report_paths)]
    reports = _filter_reports(
        reports,
        model_filters=model_filters,
        report_profile=report_profile,
        full_coverage_only=full_coverage_only,
        latest_per_model_profile=latest_per_model_profile,
    )
    if not reports:
        raise ValueError("No reports matched the requested filters")

    allowed_scenario_ids, selection = _selected_scenario_ids(benchmark_profile)
    selected_catalog_scenarios, aggregate_selection = _selected_catalog_scenarios(benchmark_profile)
    catalog = _scenario_catalog()
    observations_by_scenario: dict[str, list[ScenarioObservation]] = defaultdict(list)
    unknown_scenario_ids: set[str] = set()

    for report in reports:
        for scenario in report.result.scenarios:
            if allowed_scenario_ids is not None and scenario.scenario_id not in allowed_scenario_ids:
                continue
            if scenario.scenario_id not in catalog:
                unknown_scenario_ids.add(scenario.scenario_id)
            observations_by_scenario[scenario.scenario_id].append(
                ScenarioObservation(report=report, scenario=scenario)
            )

    rows = [
        _build_row(
            scenario_id,
            observations,
            catalog,
            target_capability_min=target_capability_min,
            target_capability_max=target_capability_max,
        )
        for scenario_id, observations in observations_by_scenario.items()
    ]
    rows.sort(key=lambda item: (item["dimension"], item["difficulty"], item["scenario_id"]))

    flag_counts = Counter(flag for row in rows for flag in row["flags"])
    target_band_counts = Counter(row["target_band_status"] for row in rows)
    dimension_counts = Counter(row["dimension"] for row in rows)
    benchmark_group_counts = Counter(row["benchmark_group"] for row in rows)
    report_profile_counts = Counter(report.profile for report in reports)

    def _top_rows(flag: str, *, limit: int = 10) -> list[dict[str, Any]]:
        tagged = [row for row in rows if flag in row["flags"]]
        if flag == "candidate_tighten":
            tagged.sort(key=lambda item: (-item["capability_score"], -item["strict_pass_rate"], item["scenario_id"]))
        elif flag == "candidate_core_promotion":
            tagged.sort(
                key=lambda item: (
                    -(item["cross_model_capability_range"] or 0.0),
                    item["capability_score"],
                    item["scenario_id"],
                )
            )
        elif flag == "stability_review":
            tagged.sort(
                key=lambda item: (
                    -max(item["avg_within_run_score_stddev"], item["same_model_score_stddev_max"]),
                    item["scenario_id"],
                )
            )
        elif flag == "efficiency_drag":
            tagged.sort(key=lambda item: (-item["avg_efficiency_drag"], -item["avg_total_tokens"], item["scenario_id"]))
        else:
            tagged.sort(key=lambda item: item["scenario_id"])
        return tagged[:limit]

    hardest = sorted(rows, key=lambda item: (item["capability_score"], item["scenario_id"]))[:10]
    most_expensive = sorted(rows, key=lambda item: (-item["avg_cost_usd"], -item["avg_total_tokens"], item["scenario_id"]))[:10]
    best_separation = sorted(
        [row for row in rows if row["cross_model_capability_range"] is not None],
        key=lambda item: (-(item["cross_model_capability_range"] or 0.0), item["scenario_id"]),
    )[:10]
    target_midpoint = (target_capability_min + target_capability_max) / 2.0
    target_band_examples = sorted(
        [row for row in rows if row["target_band_status"] == "within_target_band"],
        key=lambda item: (abs(item["capability_score"] - target_midpoint), item["scenario_id"]),
    )[:10]
    aggregate_proxy = {}
    if selected_catalog_scenarios:
        aggregate_proxy = {
            "benchmark_profile": benchmark_profile,
            "benchmark_selection": aggregate_selection,
            "models": {
                model: _aggregate_proxy_for_model(
                    model,
                    selected_catalog_scenarios,
                    observations_by_scenario,
                )
                for model in sorted({report.model for report in reports})
            },
        }

    return {
        "summary": {
            "report_count": len(reports),
            "partial_report_count": sum(1 for report in reports if report.covered_weight < 0.9999),
            "scenario_count": len(rows),
            "observation_count": sum(len(observations) for observations in observations_by_scenario.values()),
            "models": sorted({report.model for report in reports}),
            "report_profiles": dict(report_profile_counts),
            "dimensions": dict(dimension_counts),
            "benchmark_groups": dict(benchmark_group_counts),
            "flag_counts": dict(flag_counts),
            "target_capability_band": {
                "min": round(target_capability_min, 4),
                "max": round(target_capability_max, 4),
                "midpoint": round(target_midpoint, 4),
            },
            "target_band_counts": dict(target_band_counts),
            "cross_model_signal_available": len({report.model for report in reports}) >= 2,
            "benchmark_profile_filter": benchmark_profile,
            "benchmark_selection": selection,
            "full_coverage_only": full_coverage_only,
            "latest_per_model_profile": latest_per_model_profile,
            "unknown_scenarios": sorted(unknown_scenario_ids),
        },
        "aggregate_proxy": aggregate_proxy,
        "candidate_views": {
            "tighten": _top_rows("candidate_tighten"),
            "calibration_tighten": _top_rows("calibration_tighten"),
            "calibration_review_hard": _top_rows("calibration_review_hard"),
            "target_band_examples": target_band_examples,
            "demote_from_core": _top_rows("candidate_demote_from_core"),
            "core_promotion": _top_rows("candidate_core_promotion"),
            "stability_review": _top_rows("stability_review"),
            "efficiency_review": _top_rows("efficiency_drag"),
            "hardest": hardest,
            "most_expensive": most_expensive,
            "best_separation": best_separation,
        },
        "scenarios": rows,
    }


def _format_counter(values: dict[str, Any]) -> str:
    if not values:
        return "{}"
    return "{" + ", ".join(f"{key}={values[key]}" for key in sorted(values)) + "}"


def _print_row(row: dict[str, Any]) -> None:
    range_text = "n/a"
    if row["cross_model_capability_range"] is not None:
        range_text = f"{row['cross_model_capability_range']:.4f}"
    surfaces = ",".join(row["openclaw_surfaces"]) if row["openclaw_surfaces"] else row["signal_source"]
    flags = ",".join(row["flags"]) if row["flags"] else "-"
    print(
        f"  {row['scenario_id']}: "
        f"dim={row['dimension']} "
        f"diff={row['difficulty']} "
        f"cap={row['capability_score']:.4f} "
        f"score={row['avg_score']:.4f} "
        f"strict={row['strict_pass_rate']:.4f} "
        f"band={row['target_band_status']} "
        f"drag={row['avg_efficiency_drag']:.4f} "
        f"range={range_text} "
        f"same_model_std={row['same_model_score_stddev_max']:.6f} "
        f"reports={row['reports_seen']} "
        f"models={row['model_count']} "
        f"surface={surfaces} "
        f"flags={flags}"
    )


def print_human_summary(summary: dict[str, Any], *, top: int) -> None:
    meta = summary["summary"]
    print(f"reports: {meta['report_count']}")
    print(f"partial_reports: {meta['partial_report_count']}")
    print(f"models: {meta['models']}")
    print(f"report_profiles: {_format_counter(meta['report_profiles'])}")
    print(f"scenario_count: {meta['scenario_count']}")
    print(f"observation_count: {meta['observation_count']}")
    print(f"dimensions: {_format_counter(meta['dimensions'])}")
    print(f"benchmark_groups: {_format_counter(meta['benchmark_groups'])}")
    print(f"flags: {_format_counter(meta['flag_counts'])}")
    print(
        "target_capability_band: "
        f"{meta['target_capability_band']['min']:.4f}-"
        f"{meta['target_capability_band']['max']:.4f}"
    )
    print(f"target_band_counts: {_format_counter(meta['target_band_counts'])}")
    if meta["benchmark_profile_filter"]:
        print(f"benchmark_profile_filter: {meta['benchmark_profile_filter']}")
    if meta["unknown_scenarios"]:
        print(f"unknown_scenarios: {meta['unknown_scenarios']}")
    if not meta["cross_model_signal_available"]:
        print("cross_model_signal: unavailable (need at least 2 real models for separation analysis)")
    aggregate_proxy = summary.get("aggregate_proxy") or {}
    if aggregate_proxy:
        print("aggregate_proxy:")
        print(f"  benchmark_profile: {aggregate_proxy['benchmark_profile']}")
        for model, proxy in aggregate_proxy["models"].items():
            print(f"  model: {model}")
            print(
                "    "
                f"overall_proxy={proxy['overall_score_proxy']:.4f} "
                f"capability_proxy={proxy['capability_score_proxy']:.4f} "
                f"lower_bound={proxy['overall_score_lower_bound_missing_zero']:.4f} "
                f"catalog_weight_coverage={proxy['catalog_weight_coverage_ratio']:.4f}"
            )
            print(
                "    "
                f"selected_clean={proxy['selected_clean_scenario_count']}/"
                f"{proxy['catalog_scenario_count']} "
                f"clean_fallback={len(proxy['clean_fallback_scenario_ids'])} "
                f"latest_nonclean={len(proxy['latest_nonclean_scenario_ids'])} "
                f"env_corrupted={len(proxy['latest_environment_corrupted_scenario_ids'])}"
            )
            print("    top_score_contributors:")
            if not proxy["top_score_contributors"]:
                print("      none")
            else:
                for item in proxy["top_score_contributors"][:top]:
                    print(
                        "      "
                        f"{item['scenario_id']}: "
                        f"weight={item['catalog_weight']:.6f} "
                        f"score={item['avg_score']:.4f} "
                        f"contribution={item['score_contribution']:.6f} "
                        f"profile={item['source_report_profile']} "
                        f"fallback={item['used_clean_fallback']}"
                    )

    sections = [
        ("candidate_tighten", summary["candidate_views"]["tighten"]),
        ("calibration_tighten", summary["candidate_views"]["calibration_tighten"]),
        ("calibration_review_hard", summary["candidate_views"]["calibration_review_hard"]),
        ("target_band_examples", summary["candidate_views"]["target_band_examples"]),
        ("candidate_demote_from_core", summary["candidate_views"]["demote_from_core"]),
        ("candidate_core_promotion", summary["candidate_views"]["core_promotion"]),
        ("stability_review", summary["candidate_views"]["stability_review"]),
        ("efficiency_review", summary["candidate_views"]["efficiency_review"]),
        ("hardest_cases", summary["candidate_views"]["hardest"]),
        ("most_expensive_cases", summary["candidate_views"]["most_expensive"]),
    ]
    if meta["cross_model_signal_available"]:
        sections.append(("best_separation", summary["candidate_views"]["best_separation"]))

    for label, rows in sections:
        print(f"{label}:")
        if not rows:
            print("  none")
            continue
        for row in rows[:top]:
            _print_row(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_paths", nargs="*", help="Report JSON paths or globs. Defaults to results/result_*.json")
    parser.add_argument("--model", action="append", default=[], help="Case-insensitive model substring filter")
    parser.add_argument("--report-profile", help="Filter reports by the profile recorded in the report metadata")
    parser.add_argument("--benchmark-profile", choices=benchmark_profile_choices(), help="Filter scenarios by the current benchmark profile")
    parser.add_argument("--full-coverage-only", action="store_true", help="Ignore partial reports with covered_weight < 1.0")
    parser.add_argument("--latest-per-model-profile", action="store_true", help="Keep only the latest report for each (model, report profile) pair")
    parser.add_argument("--target-capability-min", type=float, default=DEFAULT_TARGET_CAPABILITY_MIN)
    parser.add_argument("--target-capability-max", type=float, default=DEFAULT_TARGET_CAPABILITY_MAX)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    summary = audit_scenario_quality(
        args.report_paths,
        model_filters=args.model,
        report_profile=args.report_profile,
        benchmark_profile=args.benchmark_profile,
        full_coverage_only=args.full_coverage_only,
        latest_per_model_profile=args.latest_per_model_profile,
        target_capability_min=args.target_capability_min,
        target_capability_max=args.target_capability_max,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_human_summary(summary, top=args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
