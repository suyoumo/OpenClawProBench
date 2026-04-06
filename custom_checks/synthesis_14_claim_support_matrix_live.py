"""Custom checks for the claim support matrix scenario."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_CLAIMS = [
    {"claim_id": "C1", "status": "contradicted", "evidence": ["E1"]},
    {"claim_id": "C2", "status": "contradicted", "evidence": ["E2"]},
    {"claim_id": "C3", "status": "supported", "evidence": ["E3"]},
    {"claim_id": "C4", "status": "contradicted", "evidence": ["E4"]},
    {"claim_id": "C5", "status": "supported", "evidence": ["E1", "E4"]},
]


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}
    output_path = ws / "claim_matrix.json"
    exists = output_path.exists()
    checkpoints["matrix_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "claim_matrix.json exists" if exists else "missing claim_matrix.json",
    }
    if not exists:
        for check_id, max_score in (
            ("claim_assessments_are_correct", 0.40),
            ("primary_driver_is_correct", 0.25),
            ("recommended_action_is_correct", 0.15),
            ("notes_are_nontrivial", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("claim_assessments_are_correct", 0.40),
            ("primary_driver_is_correct", 0.25),
            ("recommended_action_is_correct", 0.15),
            ("notes_are_nontrivial", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    claim_assessments = payload.get("claim_assessments")
    checkpoints["claim_assessments_are_correct"] = {
        "score": 0.40 if claim_assessments == EXPECTED_CLAIMS else 0.0,
        "max": 0.40,
        "detail": f"claim_assessments={claim_assessments}",
    }
    checkpoints["primary_driver_is_correct"] = {
        "score": 0.25 if payload.get("primary_incident_driver") == "deploy_regression_before_vendor_degradation" else 0.0,
        "max": 0.25,
        "detail": f"primary_incident_driver={payload.get('primary_incident_driver')!r}",
    }
    checkpoints["recommended_action_is_correct"] = {
        "score": 0.15 if payload.get("recommended_action") == "treat_vendor_degradation_as_secondary_factor" else 0.0,
        "max": 0.15,
        "detail": f"recommended_action={payload.get('recommended_action')!r}",
    }

    notes = payload.get("notes")
    notes_text = " ".join(str(item) for item in notes) if isinstance(notes, list) else ""
    note_hits = 0
    for keyword_group in (
        ("rollback", "回滚"),
        ("vendor", "供应商"),
        ("deploy", "发布"),
    ):
        if any(keyword in notes_text.lower() or keyword in notes_text for keyword in keyword_group):
            note_hits += 1
    checkpoints["notes_are_nontrivial"] = {
        "score": 0.1 if isinstance(notes, list) and len(notes) >= 2 and note_hits >= 2 else 0.0,
        "max": 0.1,
        "detail": f"notes_count={len(notes) if isinstance(notes, list) else 0} hits={note_hits}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_count = 0
    wrote_json = False
    for e in trace.get("events", []):
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        if tool in ("read", "Read"):
            read_count += 1
        if tool in ("write", "Write"):
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if read_count >= 3 and wrote_json:
        return 1.0
    if read_count >= 1 and wrote_json:
        return 0.7
    return 0.3
