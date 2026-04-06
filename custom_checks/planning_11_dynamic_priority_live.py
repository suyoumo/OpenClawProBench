"""Custom checks for the dynamic priority planning scenario."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_ORDER = ["Z", "X", "A", "B", "C"]
EXPECTED_VALUES = [9, 16, 12, 11, 3]
EXPECTED_SLOTS = [0, 5, 10, 15, 20]


def _normalize_task(task: object) -> str:
    return str(task).strip().upper()


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = ws / "priority_plan.json"
    exists = output_path.exists()
    checkpoints["plan_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "priority_plan.json exists" if exists else "missing priority_plan.json",
    }
    if not exists:
        for check_id, max_score in (
            ("slot_timestamps_are_complete", 0.15),
            ("task_order_is_optimal", 0.3),
            ("values_match_dynamic_state", 0.15),
            ("total_value_is_correct", 0.15),
            ("events_are_accounted_for", 0.1),
            ("notes_explain_key_tradeoffs", 0.05),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("slot_timestamps_are_complete", 0.15),
            ("task_order_is_optimal", 0.3),
            ("values_match_dynamic_state", 0.15),
            ("total_value_is_correct", 0.15),
            ("events_are_accounted_for", 0.1),
            ("notes_explain_key_tradeoffs", 0.05),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    slot_plan = payload.get("slot_plan")
    if not isinstance(slot_plan, list):
        slot_plan = []

    slot_starts = [_coerce_int(item.get("slot_start")) if isinstance(item, dict) else None for item in slot_plan]
    slot_score = 0.15 if slot_starts == EXPECTED_SLOTS else 0.0
    checkpoints["slot_timestamps_are_complete"] = {
        "score": slot_score,
        "max": 0.15,
        "detail": f"slot_starts={slot_starts}",
    }

    actual_order = [_normalize_task(item.get("task")) for item in slot_plan if isinstance(item, dict)]
    matched_prefix = 0
    for expected, actual in zip(EXPECTED_ORDER, actual_order):
        if expected != actual:
            break
        matched_prefix += 1
    checkpoints["task_order_is_optimal"] = {
        "score": round(matched_prefix / len(EXPECTED_ORDER) * 0.3, 4),
        "max": 0.3,
        "detail": f"order={actual_order}",
    }

    actual_values = [_coerce_int(item.get("value_at_execution")) for item in slot_plan if isinstance(item, dict)]
    value_matches = sum(1 for expected, actual in zip(EXPECTED_VALUES, actual_values) if expected == actual)
    checkpoints["values_match_dynamic_state"] = {
        "score": round(value_matches / len(EXPECTED_VALUES) * 0.15, 4),
        "max": 0.15,
        "detail": f"values={actual_values}",
    }

    total_value = payload.get("total_value")
    total_score = 0.15 if _coerce_int(total_value) == 51 else 0.0
    checkpoints["total_value_is_correct"] = {
        "score": total_score,
        "max": 0.15,
        "detail": f"total_value={total_value}",
    }

    events = payload.get("events_considered")
    event_text = " ".join(str(item) for item in events) if isinstance(events, list) else ""
    lowered_events = event_text.lower()
    event_hits = 0
    for keyword_group in (
        ("t+5", "x", "16"),
        ("t+10", "a", "b", "c"),
        ("t+15", "y"),
        ("t+20", "z", "p2"),
    ):
        if all(token in lowered_events for token in keyword_group):
            event_hits += 1
    checkpoints["events_are_accounted_for"] = {
        "score": round(min(event_hits, 3) / 3 * 0.1, 4),
        "max": 0.1,
        "detail": f"event_hits={event_hits}",
    }

    notes = payload.get("notes")
    notes_text = " ".join(str(item) for item in notes) if isinstance(notes, list) else ""
    lowered_notes = notes_text.lower()
    has_z_before_x_reason = "z" in lowered_notes and ("x" in lowered_notes or "翻倍" in notes_text)
    has_y_skip_reason = "y" in lowered_notes and ("p0" in lowered_notes or "优先级" in notes_text)
    note_score = 0.0
    if isinstance(notes, list) and len([item for item in notes if str(item).strip()]) >= 2:
        note_score += 0.025
    if has_z_before_x_reason or has_y_skip_reason:
        note_score += 0.025
    checkpoints["notes_explain_key_tradeoffs"] = {
        "score": round(note_score, 4),
        "max": 0.05,
        "detail": f"notes_count={len(notes) if isinstance(notes, list) else 0}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}
