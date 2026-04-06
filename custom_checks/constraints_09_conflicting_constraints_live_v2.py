"""Grounded scoring for constraints_09_conflicting_constraints_live."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_SUMMARY_METRICS = {
    "total_hours": 44,
    "budget_million_cny": 0.94,
    "perf_gain_percent": 32,
    "legacy_api_mode": "compatibility_gateway_until_phase_3",
}

EXPECTED_CONFLICT_ASSESSMENT = [
    {
        "conflict_id": "memory_vs_perf",
        "severity": "high",
        "resolution_code": "reclaim_search_cache_and_delay_analytics_batch",
    },
    {
        "conflict_id": "compatibility_vs_data_model",
        "severity": "high",
        "resolution_code": "keep_compatibility_gateway_until_phase_3",
    },
    {
        "conflict_id": "security_refactor_vs_availability",
        "severity": "high",
        "resolution_code": "dual_stack_shadow_cutover_before_final_switch",
    },
    {
        "conflict_id": "budget_time_vs_validation",
        "severity": "medium",
        "resolution_code": "reuse_existing_nodes_and_front_load_validation",
    },
]

EXPECTED_MEMORY_RELIEF_ACTIONS = [
    "reclaim_search_cache",
    "delay_analytics_batch",
]

EXPECTED_PHASE_PLAN = [
    {
        "phase_id": "phase_1_foundation",
        "hours": [0, 12],
        "actions": [
            "deploy_compatibility_gateway",
            "enable_dual_write",
            "reclaim_search_cache",
            "delay_analytics_batch",
        ],
        "primary_risk": "gateway_misroute",
        "rollback_trigger": "gateway_5xx_gt_1pct_15m",
    },
    {
        "phase_id": "phase_2_service_cutover",
        "hours": [12, 30],
        "actions": [
            "migrate_read_path",
            "refactor_auth_module",
            "patch_serializer_path",
            "run_shadow_validation",
        ],
        "primary_risk": "data_sync_lag",
        "rollback_trigger": "dual_write_lag_gt_5s_or_auth_error_rate_gt_0.5pct",
    },
    {
        "phase_id": "phase_3_client_migration_cleanup",
        "hours": [30, 44],
        "actions": [
            "migrate_remaining_legacy_clients",
            "remove_legacy_adapter",
            "apply_perf_tuning",
            "run_final_security_verification",
        ],
        "primary_risk": "late_client_breakage",
        "rollback_trigger": "legacy_client_failure_rate_gt_0.5pct",
    },
]

EXPECTED_REJECTED_OPTIONS = [
    {
        "option_id": "big_bang_cutover",
        "reason_codes": [
            "downtime_violation",
            "legacy_api_violation",
        ],
    },
    {
        "option_id": "hotfix_only",
        "reason_codes": [
            "performance_violation",
            "security_incomplete",
        ],
    },
    {
        "option_id": "capacity_first_then_cutover",
        "reason_codes": [
            "deadline_violation",
            "budget_violation",
        ],
    },
]

EXPECTED_ROLLBACK_PLAN = {
    "rollback_phase": "phase_2_service_cutover",
    "rollback_actions": [
        "route_reads_back_to_v1",
        "pause_client_migration",
        "keep_compatibility_gateway_active",
    ],
    "data_guard": "reconcile_dual_write_offsets_before_resume",
}

EXPECTED_EVIDENCE_REFS = {
    "upgrade_request.json",
    "current_platform.json",
    "client_compatibility.json",
    "security_findings.json",
    "upgrade_options.json",
    "decision_rules.yaml",
}

EXPECTED_INPUTS = sorted(EXPECTED_EVIDENCE_REFS)


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _normalize_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    for expected in EXPECTED_EVIDENCE_REFS:
        if normalized.endswith(expected):
            return expected
    if normalized.endswith("upgrade_strategy.json"):
        return "upgrade_strategy.json"
    return normalized


def _observed_reads(trace: dict) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        tool = event.get("tool")
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if tool in ("read", "Read") and isinstance(raw_path, str) and raw_path:
            paths.add(_normalize_path(raw_path))
        if tool in ("exec", "Exec"):
            command = str(args.get("command", ""))
            for expected in EXPECTED_EVIDENCE_REFS:
                if expected in command:
                    paths.add(expected)
    return paths


def _observed_writes(trace: dict) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        tool = event.get("tool")
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if tool in ("write", "Write") and isinstance(raw_path, str) and raw_path:
            paths.add(_normalize_path(raw_path))
        if tool in ("exec", "Exec") and "upgrade_strategy.json" in str(args.get("command", "")):
            paths.add("upgrade_strategy.json")
    return paths


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "constraints_09_conflicting_constraints" / "fixtures"


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for relative in EXPECTED_INPUTS:
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

    output_path = workspace_path / "upgrade_strategy.json"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.1 if output_exists else 0.0,
        "max": 0.1,
        "detail": "upgrade_strategy.json exists" if output_exists else "missing upgrade_strategy.json",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        for check_id, max_score in (
            ("selected_option_is_correct", 0.1),
            ("summary_metrics_are_exact", 0.1),
            ("conflict_assessment_is_exact", 0.15),
            ("memory_relief_actions_are_exact", 0.1),
            ("phase_plan_is_exact", 0.2),
            ("rejected_options_are_exact", 0.05),
            ("rollback_plan_is_exact", 0.05),
            ("evidence_refs_are_complete", 0.05),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("selected_option_is_correct", 0.1),
            ("summary_metrics_are_exact", 0.1),
            ("conflict_assessment_is_exact", 0.15),
            ("memory_relief_actions_are_exact", 0.1),
            ("phase_plan_is_exact", 0.2),
            ("rejected_options_are_exact", 0.05),
            ("rollback_plan_is_exact", 0.05),
            ("evidence_refs_are_complete", 0.05),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["selected_option_is_correct"] = {
        "score": 0.1 if payload.get("selected_option_id") == "dual_stack_incremental_cutover" else 0.0,
        "max": 0.1,
        "detail": f"selected_option_id={payload.get('selected_option_id')!r}",
    }
    checkpoints["summary_metrics_are_exact"] = {
        "score": 0.1 if payload.get("summary_metrics") == EXPECTED_SUMMARY_METRICS else 0.0,
        "max": 0.1,
        "detail": f"summary_metrics={payload.get('summary_metrics')}",
    }
    checkpoints["conflict_assessment_is_exact"] = {
        "score": 0.15 if payload.get("conflict_assessment") == EXPECTED_CONFLICT_ASSESSMENT else 0.0,
        "max": 0.15,
        "detail": f"conflict_assessment={payload.get('conflict_assessment')}",
    }
    checkpoints["memory_relief_actions_are_exact"] = {
        "score": 0.1 if payload.get("memory_relief_actions") == EXPECTED_MEMORY_RELIEF_ACTIONS else 0.0,
        "max": 0.1,
        "detail": f"memory_relief_actions={payload.get('memory_relief_actions')}",
    }
    checkpoints["phase_plan_is_exact"] = {
        "score": 0.2 if payload.get("phase_plan") == EXPECTED_PHASE_PLAN else 0.0,
        "max": 0.2,
        "detail": f"phase_plan={payload.get('phase_plan')}",
    }
    checkpoints["rejected_options_are_exact"] = {
        "score": 0.05 if payload.get("rejected_options") == EXPECTED_REJECTED_OPTIONS else 0.0,
        "max": 0.05,
        "detail": f"rejected_options={payload.get('rejected_options')}",
    }
    checkpoints["rollback_plan_is_exact"] = {
        "score": 0.05 if payload.get("rollback_plan") == EXPECTED_ROLLBACK_PLAN else 0.0,
        "max": 0.05,
        "detail": f"rollback_plan={payload.get('rollback_plan')}",
    }

    evidence_refs = payload.get("evidence_refs")
    evidence_set = set(evidence_refs) if isinstance(evidence_refs, list) else set()
    checkpoints["evidence_refs_are_complete"] = {
        "score": 0.05 if evidence_set == EXPECTED_EVIDENCE_REFS and len(evidence_refs) == 6 else 0.0,
        "max": 0.05,
        "detail": f"evidence_refs={evidence_refs}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _observed_reads(trace)
    write_paths = _observed_writes(trace)

    read_count = sum(1 for item in EXPECTED_EVIDENCE_REFS if item in read_paths)
    wrote_output = "upgrade_strategy.json" in write_paths

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
