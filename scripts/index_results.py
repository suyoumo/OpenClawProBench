#!/usr/bin/env python3
"""Build a machine-readable index for benchmark result reports."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import glob
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.benchmark_profiles import benchmark_profile_choices, resolve_benchmark_selection
from harness.loader import load_scenarios

PARTIAL_COVERAGE_THRESHOLD = 0.9999
OFFICIAL_BENCHMARK_PROFILES = set(benchmark_profile_choices())
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


def _parse_timestamp(value: str) -> datetime:
    text = value.strip()
    if not text:
        return datetime.min
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.min


def _path_label(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _expand_report_paths(raw_paths: list[str] | None) -> list[Path]:
    patterns = raw_paths or ["results/result_*.json"]
    expanded: list[Path] = []
    for raw_path in patterns:
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
        deduped.append(path)
        seen.add(path)
    return deduped


def _int_dict(raw: dict[str, Any] | None) -> dict[str, int]:
    raw = raw or {}
    return {
        str(key): int(value or 0)
        for key, value in raw.items()
    }


def _detail_excerpt(detail: str, *, limit: int = 240) -> str:
    first_line = detail.strip().splitlines()[0] if detail.strip() else ""
    if len(first_line) <= limit:
        return first_line
    return f"{first_line[: limit - 3]}..."


def _extract_failure_markers(detail: str, *, status: str = "", preflight_failed: bool = False) -> list[str]:
    markers: set[str] = set()
    normalized_status = status.strip().lower()
    text = detail.lower()

    if normalized_status:
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


def _trial_count(raw: dict[str, Any], summary: dict[str, Any]) -> int:
    total_trials = int(summary.get("total_trials", 0) or 0)
    if total_trials > 0:
        return total_trials

    scenarios = raw.get("scenarios", []) or []
    count = 0
    for scenario in scenarios:
        scenario = scenario or {}
        scenario_trials = int(scenario.get("trial_count", 0) or 0)
        if scenario_trials > 0:
            count += scenario_trials
            continue
        count += len(scenario.get("trials", []) or [])
    return count


def _scenario_counts(raw: dict[str, Any], summary: dict[str, Any], selection: dict[str, Any], progress: dict[str, Any]) -> tuple[int, int, int]:
    scenario_rows = raw.get("scenarios", []) or []
    result_scenario_count = len(scenario_rows)
    report_total_scenarios = int(raw.get("total_scenarios", 0) or result_scenario_count)
    requested_scenario_count = int(
        progress.get(
            "requested_scenarios",
            selection.get("scenario_count", report_total_scenarios),
        )
        or report_total_scenarios
    )
    completed_scenario_count = int(
        progress.get("completed_scenarios", report_total_scenarios)
        or report_total_scenarios
    )
    return result_scenario_count, requested_scenario_count, completed_scenario_count


def _classify_integrity(execution_summary: dict[str, Any]) -> dict[str, Any]:
    failure_markers: set[str] = set()
    environment_markers: set[str] = set()
    failure_examples: list[dict[str, Any]] = []

    live_preflight = dict(execution_summary.get("live_preflight", {}) or {})
    live_preflight_ok = live_preflight.get("ok")
    if live_preflight_ok is False:
        detail = str(live_preflight.get("error_detail", ""))
        markers = _extract_failure_markers(detail, preflight_failed=True)
        failure_markers.update(markers)
        environment_markers.update(marker for marker in markers if marker in ENVIRONMENT_FAILURE_MARKERS)
        failure_examples.append(
            {
                "source": "live_preflight",
                "status": "error",
                "markers": markers,
                "detail_excerpt": _detail_excerpt(detail),
            }
        )

    for item in execution_summary.get("failure_examples", []) or []:
        detail = str(item.get("error_detail", ""))
        markers = _extract_failure_markers(detail, status=str(item.get("status", "")))
        failure_markers.update(markers)
        environment_markers.update(marker for marker in markers if marker in ENVIRONMENT_FAILURE_MARKERS)
        failure_examples.append(
            {
                "source": "trial_failure",
                "scenario_id": str(item.get("scenario_id", "")),
                "trial_id": int(item.get("trial_id", 0) or 0),
                "status": str(item.get("status", "")),
                "markers": markers,
                "detail_excerpt": _detail_excerpt(detail),
            }
        )

    failure_count = int(execution_summary.get("failure_count", 0) or 0)
    has_runtime_failures = failure_count > 0 or live_preflight_ok is False
    if environment_markers or live_preflight_ok is False:
        integrity_status = "environment_corrupted"
    elif has_runtime_failures:
        integrity_status = "runtime_failed"
    else:
        integrity_status = "clean"

    return {
        "integrity_status": integrity_status,
        "has_runtime_failures": has_runtime_failures,
        "has_live_preflight_failure": live_preflight_ok is False,
        "failure_count": failure_count,
        "trial_status_counts": _int_dict(execution_summary.get("trial_status_counts")),
        "scenario_status_counts": _int_dict(execution_summary.get("scenario_status_counts")),
        "runtime_failure_markers": sorted(failure_markers),
        "environment_failure_markers": sorted(environment_markers),
        "failure_examples": failure_examples,
        "live_preflight": {
            "ok": live_preflight_ok,
            "exit_code": int(live_preflight.get("exit_code", 0) or 0),
            "duration_seconds": float(live_preflight.get("duration_seconds", 0.0) or 0.0),
            "detail_excerpt": _detail_excerpt(str(live_preflight.get("error_detail", ""))),
        }
        if live_preflight
        else {},
    }


def _completion_status(
    progress: dict[str, Any],
    *,
    scenario_count: int,
    result_scenario_count: int,
) -> str:
    requested_scenarios = int(progress.get("requested_scenarios", 0) or 0)
    completed_scenarios = int(progress.get("completed_scenarios", 0) or 0)
    remaining_scenarios = int(progress.get("remaining_scenarios", 0) or 0)
    if requested_scenarios > 0:
        if remaining_scenarios > 0 or completed_scenarios < requested_scenarios:
            return "incomplete"
        return "complete"
    if scenario_count > 0 and result_scenario_count < scenario_count:
        return "incomplete"
    return "complete"


def _selection_kind(benchmark_profile: str) -> str:
    normalized = benchmark_profile.strip().lower()
    if normalized == "custom":
        return "custom_selection"
    if normalized in OFFICIAL_BENCHMARK_PROFILES:
        return "benchmark_profile"
    return "legacy_or_unknown"


def _partial_reason(coverage_scope: str, benchmark_profile: str, completion_status: str) -> str | None:
    normalized = benchmark_profile.strip().lower()
    if completion_status == "incomplete":
        return "incomplete_run"
    if coverage_scope != "partial":
        return None
    if normalized == "custom":
        return "custom_selection"
    if normalized in OFFICIAL_BENCHMARK_PROFILES and normalized != "full":
        return "benchmark_profile_subset"
    return "unknown_subset"


def _run_label(coverage_scope: str, integrity_status: str, partial_reason: str | None) -> str:
    if partial_reason == "incomplete_run":
        base_label = "incomplete"
    elif partial_reason == "custom_selection":
        base_label = "custom_subset"
    elif partial_reason == "benchmark_profile_subset":
        base_label = "profile_subset"
    elif coverage_scope == "partial":
        base_label = "partial"
    else:
        base_label = "full"

    if integrity_status == "environment_corrupted":
        return "corrupted" if base_label == "full" else f"{base_label}_corrupted"
    if integrity_status == "runtime_failed":
        return "full_runtime_failed" if base_label == "full" else f"{base_label}_runtime_failed"
    return base_label


def build_current_catalog_snapshot() -> dict[str, Any]:
    active_profile_counts: dict[str, int] = {}
    for profile_id in benchmark_profile_choices():
        selection = resolve_benchmark_selection(profile_id)
        active_profile_counts[profile_id] = len(
            load_scenarios(
                benchmark_group=selection["benchmark_group"],
                benchmark_core=selection["benchmark_core"],
                benchmark_status=selection["benchmark_status"],
                signal_source=selection["signal_source"],
            )
        )

    return {
        "active_count": len(load_scenarios(benchmark_status="active")),
        "all_status_count": len(load_scenarios(benchmark_status="all")),
        "active_profile_counts": active_profile_counts,
    }


def index_report(path: Path, *, current_catalog_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    summary = dict(raw.get("summary", {}) or {})
    selection = dict(summary.get("benchmark_selection", {}) or {})
    progress = dict(summary.get("progress", {}) or {})
    execution_summary = dict(summary.get("execution", {}) or {})
    coverage = dict(raw.get("coverage", {}) or {})

    covered_weight = float(coverage.get("covered_weight", 1.0) or 0.0)
    normalized_score_on_covered = float(coverage.get("normalized_score_on_covered", 0.0) or 0.0)
    normalized_capability_score_on_covered = float(summary.get("normalized_capability_score_on_covered", 0.0) or 0.0)
    coverage_scope = "partial" if covered_weight < PARTIAL_COVERAGE_THRESHOLD else "full"
    result_scenario_count, requested_scenario_count, completed_scenario_count = _scenario_counts(raw, summary, selection, progress)
    integrity = _classify_integrity(execution_summary)
    completion_status = _completion_status(
        progress,
        scenario_count=int(raw.get("total_scenarios", 0) or result_scenario_count),
        result_scenario_count=result_scenario_count,
    )
    runtime = dict(summary.get("openclaw_runtime", {}) or {})

    timestamp = str(raw.get("timestamp", ""))
    benchmark_profile = str(selection.get("profile", "custom") or "custom")
    selection_kind = _selection_kind(benchmark_profile)
    partial_reason = _partial_reason(coverage_scope, benchmark_profile, completion_status)
    scenario_count = int(raw.get("total_scenarios", 0) or result_scenario_count)
    active_profile_counts = dict((current_catalog_snapshot or {}).get("active_profile_counts", {}) or {})
    current_catalog_profile_count = active_profile_counts.get(benchmark_profile)
    current_catalog_count_delta = None
    current_catalog_matches_profile_count = None
    if current_catalog_profile_count is not None:
        current_catalog_count_delta = int(current_catalog_profile_count) - scenario_count
        current_catalog_matches_profile_count = current_catalog_count_delta == 0

    return {
        "report_path": _path_label(path),
        "report_file": path.name,
        "timestamp": timestamp,
        "model": str(raw.get("model", "")),
        "benchmark_profile": benchmark_profile,
        "selection_kind": selection_kind,
        "coverage_scope": coverage_scope,
        "completion_status": completion_status,
        "partial_reason": partial_reason,
        "integrity_status": integrity["integrity_status"],
        "run_label": _run_label(coverage_scope, integrity["integrity_status"], partial_reason),
        "is_partial_coverage": coverage_scope == "partial",
        "is_custom_selection": selection_kind == "custom_selection",
        "is_profile_subset": partial_reason == "benchmark_profile_subset",
        "is_incomplete": completion_status == "incomplete",
        "is_corrupted": integrity["integrity_status"] == "environment_corrupted",
        "has_runtime_failures": integrity["has_runtime_failures"],
        "has_live_preflight_failure": integrity["has_live_preflight_failure"],
        "scenario_count": scenario_count,
        "result_scenario_count": result_scenario_count,
        "requested_scenario_count": requested_scenario_count,
        "completed_scenario_count": completed_scenario_count,
        "trials_per_scenario": int(raw.get("trials_per_scenario", 0) or 0),
        "trial_count": _trial_count(raw, summary),
        "covered_weight": covered_weight,
        "coverage_ratio": covered_weight,
        "covered_dimension_count": int(coverage.get("covered_dimension_count", 0) or 0),
        "total_dimension_count": int(coverage.get("total_dimension_count", 0) or 0),
        "overall_score": float(raw.get("overall_score", 0.0) or 0.0),
        "capability_score": float(raw.get("capability_score", 0.0) or 0.0),
        "strict_pass_rate": float(raw.get("strict_pass_rate", 0.0) or 0.0),
        "normalized_score_on_covered": normalized_score_on_covered,
        "normalized_capability_score_on_covered": normalized_capability_score_on_covered,
        "runtime_failure_count": integrity["failure_count"],
        "trial_status_counts": integrity["trial_status_counts"],
        "scenario_status_counts": integrity["scenario_status_counts"],
        "runtime_failure_markers": integrity["runtime_failure_markers"],
        "environment_failure_markers": integrity["environment_failure_markers"],
        "failure_examples": integrity["failure_examples"],
        "live_preflight": integrity["live_preflight"],
        "openclaw_runtime_present": bool(runtime),
        "openclaw_runtime_commit": str(runtime.get("git_commit", "")),
        "openclaw_runtime_commit_short": str(runtime.get("git_commit_short", "")),
        "openclaw_runtime_dirty": bool(runtime.get("git_dirty", False)) if runtime else False,
        "openclaw_runtime_binary_realpath": str(runtime.get("binary_realpath", "")),
        "openclaw_runtime_binary_sha256": str(runtime.get("binary_sha256", "")),
        "openclaw_runtime_version_text": str(runtime.get("version_text", "")),
        "current_catalog_active_count": int((current_catalog_snapshot or {}).get("active_count", 0) or 0),
        "current_catalog_all_status_count": int((current_catalog_snapshot or {}).get("all_status_count", 0) or 0),
        "current_catalog_profile_count": current_catalog_profile_count,
        "current_catalog_count_delta": current_catalog_count_delta,
        "current_catalog_matches_profile_count": current_catalog_matches_profile_count,
    }


def build_results_index(
    raw_paths: list[str] | None = None,
    *,
    current_catalog_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_catalog_snapshot = current_catalog_snapshot or build_current_catalog_snapshot()
    reports = [
        index_report(path, current_catalog_snapshot=current_catalog_snapshot)
        for path in _expand_report_paths(raw_paths)
    ]
    reports.sort(
        key=lambda item: (
            _parse_timestamp(str(item.get("timestamp", ""))),
            str(item.get("report_path", "")),
        ),
        reverse=True,
    )

    compared_reports = [
        item
        for item in reports
        if item.get("current_catalog_profile_count") is not None
    ]
    summary = {
        "report_count": len(reports),
        "run_labels": dict(Counter(str(item["run_label"]) for item in reports)),
        "coverage_scopes": dict(Counter(str(item["coverage_scope"]) for item in reports)),
        "selection_kinds": dict(Counter(str(item["selection_kind"]) for item in reports)),
        "completion_statuses": dict(Counter(str(item["completion_status"]) for item in reports)),
        "partial_reasons": dict(Counter(str(item["partial_reason"]) for item in reports if item["partial_reason"])),
        "integrity_statuses": dict(Counter(str(item["integrity_status"]) for item in reports)),
        "benchmark_profiles": dict(Counter(str(item["benchmark_profile"]) for item in reports)),
        "current_catalog_comparison": {
            "matches": sum(1 for item in compared_reports if item["current_catalog_matches_profile_count"] is True),
            "drifted": sum(1 for item in compared_reports if item["current_catalog_matches_profile_count"] is False),
            "not_compared": len(reports) - len(compared_reports),
        },
    }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "current_catalog_snapshot": current_catalog_snapshot,
        "summary": summary,
        "reports": reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Result-report paths or globs. Defaults to results/result_*.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON file path for the generated index.",
    )
    args = parser.parse_args(argv)

    index = build_results_index(args.paths)
    payload = json.dumps(index, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        return 0

    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
