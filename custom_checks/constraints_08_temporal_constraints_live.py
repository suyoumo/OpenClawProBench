"""Grounded scoring for constraints_08_temporal_constraints_live."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_SCHEDULE = [
    {"slot": 0, "transaction_id": "tx101"},
    {"slot": 1, "transaction_id": "tx103"},
    {"slot": 2, "transaction_id": "tx102"},
    {"slot": 3, "transaction_id": "tx105"},
    {"slot": 4, "transaction_id": "tx104"},
    {"slot": 5, "transaction_id": "tx106"},
    {"slot": 6, "transaction_id": "tx100"},
]

EXPECTED_REJECTED = [
    {"transaction_id": "tx107", "reason": "dependency_cycle"},
    {"transaction_id": "tx108", "reason": "dependency_cycle"},
]

EXPECTED_NOTES = [
    "tx103_before_tx100_due_large_before_small_rule",
    "tx102_waited_until_slot_2_due_same_user_order_and_side_gap_after_tx101",
    "tx105_took_slot_3_due_earliest_latest_start",
    "tx104_before_tx106_due_dependency",
    "tx107_and_tx108_rejected_due_dependency_cycle",
]

EXPECTED_EVIDENCE = [
    "transactions.json:tx101",
    "transactions.json:tx102",
    "transactions.json:tx104",
    "transactions.json:tx105",
    "transactions.json:tx106",
    "transactions.json:tx107",
    "transactions.json:tx108",
    "policy.json:hard_rules",
]


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _basename_set(trace: dict, *, tool_name: str) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        if event.get("tool") != tool_name:
            continue
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if isinstance(raw_path, str) and raw_path:
            paths.add(Path(raw_path).name)
    return paths


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "constraints_08_temporal_constraints" / "fixtures"


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for filename in ("transactions.json", "policy.json"):
        seeded = fixture_dir / filename
        current = workspace_path / filename
        if not seeded.exists() or not current.exists():
            return False, f"missing required input file {filename}"
        if current.read_text(encoding="utf-8") != seeded.read_text(encoding="utf-8"):
            return False, f"{filename} drifted from the seeded fixture"
    return True, "seeded inputs are present and unchanged"


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = workspace_path / "execution_schedule.json"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.1 if output_exists else 0.0,
        "max": 0.1,
        "detail": "execution_schedule.json exists" if output_exists else "missing execution_schedule.json",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        for check_id, max_score in (
            ("scheduled_order_is_exact", 0.35),
            ("rejected_transactions_are_exact", 0.15),
            ("total_completion_is_correct", 0.1),
            ("resolution_notes_are_exact", 0.1),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("scheduled_order_is_exact", 0.35),
            ("rejected_transactions_are_exact", 0.15),
            ("total_completion_is_correct", 0.1),
            ("resolution_notes_are_exact", 0.1),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["scheduled_order_is_exact"] = {
        "score": 0.35 if payload.get("scheduled_order") == EXPECTED_SCHEDULE else 0.0,
        "max": 0.35,
        "detail": f"scheduled_order={payload.get('scheduled_order')}",
    }
    checkpoints["rejected_transactions_are_exact"] = {
        "score": 0.15 if payload.get("rejected_transactions") == EXPECTED_REJECTED else 0.0,
        "max": 0.15,
        "detail": f"rejected_transactions={payload.get('rejected_transactions')}",
    }
    checkpoints["total_completion_is_correct"] = {
        "score": 0.1 if payload.get("total_completion_seconds") == 7 else 0.0,
        "max": 0.1,
        "detail": f"total_completion_seconds={payload.get('total_completion_seconds')!r}",
    }
    checkpoints["resolution_notes_are_exact"] = {
        "score": 0.1 if payload.get("resolution_notes") == EXPECTED_NOTES else 0.0,
        "max": 0.1,
        "detail": f"resolution_notes={payload.get('resolution_notes')}",
    }
    checkpoints["evidence_refs_are_complete"] = {
        "score": 0.1 if payload.get("evidence_refs") == EXPECTED_EVIDENCE else 0.0,
        "max": 0.1,
        "detail": f"evidence_refs={payload.get('evidence_refs')}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _basename_set(trace, tool_name="read")
    write_paths = _basename_set(trace, tool_name="write")

    found_reads = sum(1 for item in ("transactions.json", "policy.json") if item in read_paths)
    wrote_output = "execution_schedule.json" in write_paths

    if found_reads == 2 and wrote_output:
        return 1.0
    if found_reads == 2:
        return 0.75
    if found_reads == 1 and wrote_output:
        return 0.65
    if found_reads == 1 or wrote_output:
        return 0.4
    return 0.2
