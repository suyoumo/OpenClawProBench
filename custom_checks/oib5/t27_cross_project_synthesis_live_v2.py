"""Grounded scoring for oib5_t27_cross_project_synthesis_live."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_EVIDENCE_REFS = {
    "project_alpha/README.md",
    "project_alpha/performance_report.md",
    "project_beta/README.md",
    "project_beta/issues.md",
    "project_gamma/README.md",
    "project_gamma/migration_lessons.md",
}
EXPECTED_ALPHA = {
    "database": "PostgreSQL 14.2",
    "peak_tps": 12500,
    "pooled_stable_tps": 8000,
    "direct_connection_limit": 500,
}
EXPECTED_BETA = {
    "database": "MongoDB 6.0",
    "inconsistent_records": 3420,
    "transaction_latency_penalty": "3-5x",
    "decision": "reject_for_financial_core",
}
EXPECTED_GAMMA = {
    "database": "MySQL 8.0",
    "concurrent_sessions": 200000,
    "write_contention_threshold": 6000,
    "decision": "secondary_option_not_primary",
}
EXPECTED_RISKS = [
    {
        "risk": "connection_pooling_required",
        "mitigation": "pgbouncer_and_limit_direct_connections_to_500",
    },
    {
        "risk": "large_table_maintenance",
        "mitigation": "partition_large_tables_early_and_monitor_vacuum",
    },
    {
        "risk": "future_write_scale_beyond_single_node",
        "mitigation": "vertical_scale_first_then_plan_sharding",
    },
]
EXPECTED_PERFORMANCE = {
    "steady_state_tps": 4800,
    "pooled_peak_tps": 8000,
    "p99_latency_ms": 50,
}
EXPECTED_REJECTIONS = [
    {
        "database": "MongoDB 6.0",
        "reason": "network_partition_inconsistency_and_3_to_5x_transaction_latency_penalty",
    },
    {
        "database": "MySQL 8.0",
        "reason": "row_level_lock_contention_above_6000_concurrent_writes",
    },
]
REQUIRED_READS = tuple(sorted(EXPECTED_EVIDENCE_REFS))


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _normalize_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    for expected in EXPECTED_EVIDENCE_REFS:
        if normalized.endswith(expected):
            return expected
    if normalized.endswith("database_recommendation.json"):
        return "database_recommendation.json"
    return normalized


def _normalized_paths(trace: dict, *, tool_name: str) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        if event.get("tool") != tool_name:
            continue
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if isinstance(raw_path, str) and raw_path:
            paths.add(_normalize_path(raw_path))
    return paths


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "datasets" / "oib5" / "t27_cross_project_synthesis_live" / "fixtures"


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for relative in REQUIRED_READS:
        seeded = fixture_dir / relative
        current = workspace_path / relative
        if not seeded.exists() or not current.exists():
            return False, f"missing required input file {relative}"
        if current.read_text(encoding="utf-8") != seeded.read_text(encoding="utf-8"):
            return False, f"{relative} drifted from the seeded fixture"
    return True, "seeded inputs are present and unchanged"


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = workspace_path / "database_recommendation.json"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.05 if output_exists else 0.0,
        "max": 0.05,
        "detail": "database_recommendation.json exists" if output_exists else "missing database_recommendation.json",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        for check_id, max_score in (
            ("recommendation_is_correct", 0.1),
            ("project_findings_are_exact", 0.25),
            ("risks_are_exact", 0.15),
            ("performance_expectation_is_exact", 0.1),
            ("rejected_options_are_exact", 0.15),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("recommendation_is_correct", 0.1),
            ("project_findings_are_exact", 0.25),
            ("risks_are_exact", 0.15),
            ("performance_expectation_is_exact", 0.1),
            ("rejected_options_are_exact", 0.15),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    recommendation_ok = (
        payload.get("recommended_database") == "PostgreSQL"
        and payload.get("recommended_version") == "14.2"
        and payload.get("primary_rationale")
        == "postgresql_best_matches_financial_acid_workload_with_proven_transaction_performance"
    )
    checkpoints["recommendation_is_correct"] = {
        "score": 0.1 if recommendation_ok else 0.0,
        "max": 0.1,
        "detail": (
            f"recommended_database={payload.get('recommended_database')!r} "
            f"recommended_version={payload.get('recommended_version')!r} "
            f"primary_rationale={payload.get('primary_rationale')!r}"
        ),
    }

    findings = payload.get("project_findings") if isinstance(payload.get("project_findings"), dict) else {}
    finding_hits = 0
    if findings.get("project_alpha") == EXPECTED_ALPHA:
        finding_hits += 1
    if findings.get("project_beta") == EXPECTED_BETA:
        finding_hits += 1
    if findings.get("project_gamma") == EXPECTED_GAMMA:
        finding_hits += 1
    checkpoints["project_findings_are_exact"] = {
        "score": round((finding_hits / 3) * 0.25, 4),
        "max": 0.25,
        "detail": f"exact_project_findings={finding_hits}/3",
    }

    checkpoints["risks_are_exact"] = {
        "score": 0.15 if payload.get("risks") == EXPECTED_RISKS else 0.0,
        "max": 0.15,
        "detail": f"risks={payload.get('risks')}",
    }
    checkpoints["performance_expectation_is_exact"] = {
        "score": 0.1 if payload.get("performance_expectation") == EXPECTED_PERFORMANCE else 0.0,
        "max": 0.1,
        "detail": f"performance_expectation={payload.get('performance_expectation')}",
    }
    checkpoints["rejected_options_are_exact"] = {
        "score": 0.15 if payload.get("rejected_options") == EXPECTED_REJECTIONS else 0.0,
        "max": 0.15,
        "detail": f"rejected_options={payload.get('rejected_options')}",
    }

    evidence_refs = payload.get("evidence_refs")
    evidence_set = set(evidence_refs) if isinstance(evidence_refs, list) else set()
    checkpoints["evidence_refs_are_complete"] = {
        "score": 0.1 if evidence_set == EXPECTED_EVIDENCE_REFS and len(evidence_refs) == 6 else 0.0,
        "max": 0.1,
        "detail": f"evidence_refs={evidence_refs}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _normalized_paths(trace, tool_name="read")
    write_paths = _normalized_paths(trace, tool_name="write")

    read_count = sum(1 for path in REQUIRED_READS if path in read_paths)
    wrote_output = "database_recommendation.json" in write_paths

    if read_count == 6 and wrote_output:
        return 1.0
    if read_count >= 5 and wrote_output:
        return 0.85
    if read_count >= 4 and wrote_output:
        return 0.7
    if read_count >= 3 and wrote_output:
        return 0.55
    if read_count >= 2 or wrote_output:
        return 0.35
    return 0.2
