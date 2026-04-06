"""Grounded scoring for planning_09_resource_contention_live."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


EXPECTED_DEADLOCK_CYCLES = [
    {
        "cycle_id": "db_file_cycle",
        "checkpoint_task_id": "legacy_fee_reconcile",
        "resolution_code": "checkpoint_legacy_fee_reconcile",
    },
    {
        "cycle_id": "port_lock_cycle",
        "checkpoint_task_id": "legacy_lock_reindex",
        "resolution_code": "checkpoint_legacy_lock_reindex",
    },
]

EXPECTED_ALLOCATION_POLICY = {
    "allocation_mode": "full_batch_wave_launch",
    "admission_rule": "launch_only_when_all_selected_tasks_fit",
    "resource_order": [
        "db_connections",
        "file_handles",
        "network_ports",
        "lock_units",
    ],
}

EXPECTED_EXECUTION_WAVES = [
    {
        "wave_id": "wave_1",
        "hours": [0, 2],
        "tasks": [
            "invoice_rebuild",
            "export_sync",
        ],
        "resource_totals": {
            "db_connections": 3,
            "file_handles": 5,
            "network_ports": 1,
            "lock_units": 1,
        },
    },
    {
        "wave_id": "wave_2",
        "hours": [2, 4],
        "tasks": [
            "fraud_scan",
            "compliance_bundle",
            "merchant_snapshot",
        ],
        "resource_totals": {
            "db_connections": 3,
            "file_handles": 4,
            "network_ports": 2,
            "lock_units": 4,
        },
    },
]

EXPECTED_DEFERRED_TASKS = [
    {
        "task_id": "lock_reindex",
        "reason_code": "lower_value_than_other_feasible_wave_2_tasks",
    }
]

EXPECTED_COMPLETION_SUMMARY = {
    "completed_task_count": 5,
    "must_finish_completed": [
        "invoice_rebuild",
        "export_sync",
    ],
    "total_business_value": 295,
    "window_hours": 4,
}

EXPECTED_EVIDENCE_REFS = {
    "resource_pool.json",
    "contention_snapshot.json",
    "job_queue.json",
    "sla_targets.json",
    "scheduling_rules.yaml",
}


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _normalize_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    for expected in EXPECTED_EVIDENCE_REFS:
        if normalized.endswith(expected):
            return expected
    if normalized.endswith("resource_contention_plan.json"):
        return "resource_contention_plan.json"
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
        if tool in ("exec", "Exec") and "resource_contention_plan.json" in str(args.get("command", "")):
            paths.add("resource_contention_plan.json")
    return paths


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "planning_09_resource_contention" / "fixtures"


def _scheduling_rules() -> dict:
    return yaml.safe_load((_fixture_dir() / "scheduling_rules.yaml").read_text(encoding="utf-8"))


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for relative in sorted(EXPECTED_EVIDENCE_REFS):
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
    rules = _scheduling_rules()
    expected_allocation_policy = {
        "allocation_mode": rules["allocation_policy_codes"]["allocation_mode"],
        "admission_rule": rules["allocation_policy_codes"]["admission_rule"],
        "resource_order": rules["hard_rules"]["resource_order"],
    }

    output_path = workspace_path / "resource_contention_plan.json"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.1 if output_exists else 0.0,
        "max": 0.1,
        "detail": "resource_contention_plan.json exists" if output_exists else "missing resource_contention_plan.json",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        for check_id, max_score in (
            ("deadlock_cycles_are_exact", 0.15),
            ("allocation_policy_is_exact", 0.1),
            ("execution_waves_are_exact", 0.2),
            ("deferred_tasks_are_exact", 0.1),
            ("completion_summary_is_exact", 0.15),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("deadlock_cycles_are_exact", 0.15),
            ("allocation_policy_is_exact", 0.1),
            ("execution_waves_are_exact", 0.2),
            ("deferred_tasks_are_exact", 0.1),
            ("completion_summary_is_exact", 0.15),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["deadlock_cycles_are_exact"] = {
        "score": 0.15 if payload.get("deadlock_cycles") == EXPECTED_DEADLOCK_CYCLES else 0.0,
        "max": 0.15,
        "detail": f"deadlock_cycles={payload.get('deadlock_cycles')}",
    }
    checkpoints["allocation_policy_is_exact"] = {
        "score": 0.1 if payload.get("allocation_policy") == expected_allocation_policy == EXPECTED_ALLOCATION_POLICY else 0.0,
        "max": 0.1,
        "detail": f"allocation_policy={payload.get('allocation_policy')}",
    }
    checkpoints["execution_waves_are_exact"] = {
        "score": 0.2 if payload.get("execution_waves") == EXPECTED_EXECUTION_WAVES else 0.0,
        "max": 0.2,
        "detail": f"execution_waves={payload.get('execution_waves')}",
    }
    checkpoints["deferred_tasks_are_exact"] = {
        "score": 0.1 if payload.get("deferred_tasks") == EXPECTED_DEFERRED_TASKS else 0.0,
        "max": 0.1,
        "detail": f"deferred_tasks={payload.get('deferred_tasks')}",
    }
    checkpoints["completion_summary_is_exact"] = {
        "score": 0.15 if payload.get("completion_summary") == EXPECTED_COMPLETION_SUMMARY else 0.0,
        "max": 0.15,
        "detail": f"completion_summary={payload.get('completion_summary')}",
    }

    evidence_refs = payload.get("evidence_refs")
    evidence_set = set(evidence_refs) if isinstance(evidence_refs, list) else set()
    checkpoints["evidence_refs_are_complete"] = {
        "score": 0.1 if evidence_set == EXPECTED_EVIDENCE_REFS and len(evidence_refs) == 5 else 0.0,
        "max": 0.1,
        "detail": f"evidence_refs={evidence_refs}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _observed_reads(trace)
    write_paths = _observed_writes(trace)

    read_count = sum(1 for item in EXPECTED_EVIDENCE_REFS if item in read_paths)
    wrote_output = "resource_contention_plan.json" in write_paths

    if read_count == 5 and wrote_output:
        return 1.0
    if read_count >= 4 and wrote_output:
        return 0.85
    if read_count >= 3 and wrote_output:
        return 0.7
    if read_count >= 2 and wrote_output:
        return 0.55
    if read_count >= 1 or wrote_output:
        return 0.35
    return 0.2
