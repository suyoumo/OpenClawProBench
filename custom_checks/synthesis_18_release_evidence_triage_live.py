"""Custom checks for synthesis_18_release_evidence_triage_live."""

from __future__ import annotations

import json
from pathlib import Path

EXPECTED_SUPPORTING = [
    "bug_tracker:P0_checkout_null_pointer_open",
    "ci_summary:checkout_e2e_failed_after_hotfix",
    "launch_plan:no_P0_or_failing_release_gates_allowed",
]
EXPECTED_EVIDENCE_REFS = [
    "bug_tracker.json",
    "ci_summary.json",
    "ops_incidents.json",
    "launch_plan.md",
]


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}
    output_path = ws / "release_triage.json"
    exists = output_path.exists()
    checkpoints["triage_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "release_triage.json exists" if exists else "missing release_triage.json",
    }
    if not exists:
        for check_id, max_score in (
            ("launch_decision_is_correct", 0.2),
            ("primary_blocker_is_correct", 0.2),
            ("blocker_class_is_correct", 0.1),
            ("supporting_evidence_is_exact", 0.15),
            ("next_action_is_correct", 0.15),
            ("confidence_and_refs_are_correct", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("launch_decision_is_correct", 0.2),
            ("primary_blocker_is_correct", 0.2),
            ("blocker_class_is_correct", 0.1),
            ("supporting_evidence_is_exact", 0.15),
            ("next_action_is_correct", 0.15),
            ("confidence_and_refs_are_correct", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["launch_decision_is_correct"] = {
        "score": 0.2 if payload.get("launch_decision") == "hold" else 0.0,
        "max": 0.2,
        "detail": f"launch_decision={payload.get('launch_decision')!r}",
    }
    checkpoints["primary_blocker_is_correct"] = {
        "score": 0.2 if payload.get("primary_blocker") == "P0_checkout_null_pointer_open" else 0.0,
        "max": 0.2,
        "detail": f"primary_blocker={payload.get('primary_blocker')!r}",
    }
    checkpoints["blocker_class_is_correct"] = {
        "score": 0.1 if payload.get("blocker_class") == "code_regression" else 0.0,
        "max": 0.1,
        "detail": f"blocker_class={payload.get('blocker_class')!r}",
    }
    checkpoints["supporting_evidence_is_exact"] = {
        "score": 0.15 if payload.get("supporting_evidence") == EXPECTED_SUPPORTING else 0.0,
        "max": 0.15,
        "detail": f"supporting_evidence={payload.get('supporting_evidence')}",
    }
    checkpoints["next_action_is_correct"] = {
        "score": 0.15 if payload.get("recommended_next_action") == "fix_checkout_null_pointer_and_rerun_release_gate" else 0.0,
        "max": 0.15,
        "detail": f"recommended_next_action={payload.get('recommended_next_action')!r}",
    }
    refs_ok = payload.get("confidence") == "high" and payload.get("evidence_refs") == EXPECTED_EVIDENCE_REFS
    checkpoints["confidence_and_refs_are_correct"] = {
        "score": 0.1 if refs_ok else 0.0,
        "max": 0.1,
        "detail": f"confidence={payload.get('confidence')!r} evidence_refs={payload.get('evidence_refs')}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_count = 0
    wrote_output = False
    for event in _tool_calls(trace):
        tool = str(event.get("tool", "")).lower()
        args = event.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", ""))
        if tool == "read" and any(name in path for name in EXPECTED_EVIDENCE_REFS):
            read_count += 1
        if tool == "write" and path.endswith("release_triage.json"):
            wrote_output = True
    if read_count >= 4 and wrote_output:
        return 1.0
    if read_count >= 2 and wrote_output:
        return 0.7
    if wrote_output:
        return 0.45
    return 0.2
