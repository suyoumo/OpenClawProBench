"""Grounded scoring for planning_07_dynamic_resource_allocation_live."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


EXPECTED_BASELINE_SERVICE = {
    "service_id": "api_guardrail",
    "resource_reservation": {
        "cpu": 2,
        "ram_gb": 4,
    },
}

EXPECTED_WINDOW_ALLOCATIONS = [
    {
        "window_id": "window_1",
        "minutes": [0, 5],
        "tasks": [
            "stream_restore",
            "feature_backfill_a",
            "feature_backfill_b",
            "ingestion_repair",
        ],
        "resource_totals": {
            "cpu": 14,
            "ram_gb": 28,
        },
    },
    {
        "window_id": "window_2",
        "minutes": [5, 10],
        "tasks": [
            "analytics_rollup",
        ],
        "resource_totals": {
            "cpu": 7,
            "ram_gb": 14,
        },
    },
    {
        "window_id": "window_3",
        "minutes": [10, 15],
        "tasks": [
            "analytics_rollup",
        ],
        "resource_totals": {
            "cpu": 7,
            "ram_gb": 14,
        },
    },
    {
        "window_id": "window_4",
        "minutes": [15, 20],
        "tasks": [
            "cache_rebuild",
        ],
        "resource_totals": {
            "cpu": 4,
            "ram_gb": 8,
        },
    },
]

EXPECTED_REALLOCATION_EVENTS = [
    {
        "at_minute": 5,
        "action_code": "launch_analytics_rollup_at_5_after_ingestion_repair",
    },
    {
        "at_minute": 15,
        "action_code": "launch_cache_rebuild_at_15_after_analytics_rollup",
    },
]

EXPECTED_DEFERRED_TASKS = [
    {
        "task_id": "model_refresh",
        "reason_code": "lower_completed_task_count_than_analytics_path",
    }
]

EXPECTED_COMPLETION_SUMMARY = {
    "deadline_met_task_ids": [
        "stream_restore",
        "feature_backfill_a",
        "feature_backfill_b",
        "ingestion_repair",
        "analytics_rollup",
        "cache_rebuild",
    ],
    "completed_task_count": 6,
    "total_business_value": 275,
}

EXPECTED_EVIDENCE_REFS = {
    "resource_windows.json",
    "task_catalog.json",
    "baseline_service.json",
    "scheduler_objectives.json",
    "allocation_rules.yaml",
}


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _normalize_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    for expected in EXPECTED_EVIDENCE_REFS:
        if normalized.endswith(expected):
            return expected
    if normalized.endswith("dynamic_allocation_plan.json"):
        return "dynamic_allocation_plan.json"
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
        if tool in ("exec", "Exec") and "dynamic_allocation_plan.json" in str(args.get("command", "")):
            paths.add("dynamic_allocation_plan.json")
    return paths


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "planning_07_dynamic_resource_allocation" / "fixtures"


def _allocation_rules() -> dict:
    return yaml.safe_load((_fixture_dir() / "allocation_rules.yaml").read_text(encoding="utf-8"))


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
    rules = _allocation_rules()
    expected_baseline_service = rules.get("baseline_output", EXPECTED_BASELINE_SERVICE)

    output_path = workspace_path / "dynamic_allocation_plan.json"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.1 if output_exists else 0.0,
        "max": 0.1,
        "detail": "dynamic_allocation_plan.json exists" if output_exists else "missing dynamic_allocation_plan.json",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        for check_id, max_score in (
            ("baseline_service_is_exact", 0.1),
            ("window_allocations_are_exact", 0.2),
            ("reallocation_events_are_exact", 0.1),
            ("deferred_tasks_are_exact", 0.1),
            ("completion_summary_is_exact", 0.2),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("baseline_service_is_exact", 0.1),
            ("window_allocations_are_exact", 0.2),
            ("reallocation_events_are_exact", 0.1),
            ("deferred_tasks_are_exact", 0.1),
            ("completion_summary_is_exact", 0.2),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["baseline_service_is_exact"] = {
        "score": 0.1 if payload.get("baseline_service") == expected_baseline_service == EXPECTED_BASELINE_SERVICE else 0.0,
        "max": 0.1,
        "detail": f"baseline_service={payload.get('baseline_service')}",
    }
    checkpoints["window_allocations_are_exact"] = {
        "score": 0.2 if payload.get("window_allocations") == EXPECTED_WINDOW_ALLOCATIONS else 0.0,
        "max": 0.2,
        "detail": f"window_allocations={payload.get('window_allocations')}",
    }
    checkpoints["reallocation_events_are_exact"] = {
        "score": 0.1 if payload.get("reallocation_events") == EXPECTED_REALLOCATION_EVENTS else 0.0,
        "max": 0.1,
        "detail": f"reallocation_events={payload.get('reallocation_events')}",
    }
    checkpoints["deferred_tasks_are_exact"] = {
        "score": 0.1 if payload.get("deferred_tasks") == EXPECTED_DEFERRED_TASKS else 0.0,
        "max": 0.1,
        "detail": f"deferred_tasks={payload.get('deferred_tasks')}",
    }
    got_summary = payload.get("completion_summary")
    if isinstance(got_summary, dict):
        # Compare deadline_met_task_ids as a set (order not specified in prompt)
        got_ids = got_summary.get("deadline_met_task_ids", [])
        expected_ids = EXPECTED_COMPLETION_SUMMARY["deadline_met_task_ids"]
        ids_match = isinstance(got_ids, list) and set(got_ids) == set(expected_ids) and len(got_ids) == len(expected_ids)
        count_match = got_summary.get("completed_task_count") == EXPECTED_COMPLETION_SUMMARY["completed_task_count"]
        value_match = got_summary.get("total_business_value") == EXPECTED_COMPLETION_SUMMARY["total_business_value"]
        summary_ok = ids_match and count_match and value_match
    else:
        summary_ok = False
    checkpoints["completion_summary_is_exact"] = {
        "score": 0.2 if summary_ok else 0.0,
        "max": 0.2,
        "detail": f"completion_summary={got_summary}",
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
    wrote_output = "dynamic_allocation_plan.json" in write_paths

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
