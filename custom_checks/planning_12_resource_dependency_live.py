"""Custom checks for the resource dependency scheduling scenario."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_SCHEDULE = [
    {"task": "A", "start": 0, "end": 2},
    {"task": "B", "start": 0, "end": 2},
    {"task": "C", "start": 2, "end": 5},
    {"task": "D", "start": 2, "end": 4},
    {"task": "F", "start": 4, "end": 7},
    {"task": "E", "start": 5, "end": 9},
    {"task": "G", "start": 9, "end": 14},
    {"task": "H", "start": 9, "end": 10},
    {"task": "I", "start": 14, "end": 16},
]
EXPECTED_PARALLEL_GROUPS = [["A", "B"], ["C", "D"], ["F"], ["E"], ["G", "H"], ["I"]]
EXPECTED_CRITICAL_PATH = ["A", "C", "E", "G", "I"]


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = ws / "resource_schedule.json"
    exists = output_path.exists()
    checkpoints["schedule_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "resource_schedule.json exists" if exists else "missing resource_schedule.json",
    }
    if not exists:
        for check_id, max_score in (
            ("schedule_is_correct", 0.35),
            ("parallel_groups_are_correct", 0.1),
            ("makespan_is_correct", 0.15),
            ("critical_path_is_correct", 0.2),
            ("notes_capture_reasoning", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("schedule_is_correct", 0.35),
            ("parallel_groups_are_correct", 0.1),
            ("makespan_is_correct", 0.15),
            ("critical_path_is_correct", 0.2),
            ("notes_capture_reasoning", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    schedule = payload.get("schedule")
    schedule_hits = 0
    if isinstance(schedule, list):
        for actual, expected in zip(schedule, EXPECTED_SCHEDULE):
            if actual == expected:
                schedule_hits += 1
    checkpoints["schedule_is_correct"] = {
        "score": round(schedule_hits / len(EXPECTED_SCHEDULE) * 0.35, 4),
        "max": 0.35,
        "detail": f"schedule_hits={schedule_hits}",
    }

    parallel_groups = payload.get("parallel_groups")
    checkpoints["parallel_groups_are_correct"] = {
        "score": 0.1 if parallel_groups == EXPECTED_PARALLEL_GROUPS else 0.0,
        "max": 0.1,
        "detail": f"parallel_groups={parallel_groups}",
    }

    makespan = payload.get("makespan")
    checkpoints["makespan_is_correct"] = {
        "score": 0.15 if makespan == 16 else 0.0,
        "max": 0.15,
        "detail": f"makespan={makespan}",
    }

    critical_path = payload.get("critical_path")
    checkpoints["critical_path_is_correct"] = {
        "score": 0.2 if critical_path == EXPECTED_CRITICAL_PATH else 0.0,
        "max": 0.2,
        "detail": f"critical_path={critical_path}",
    }

    notes = payload.get("notes")
    notes_text = " ".join(str(item) for item in notes) if isinstance(notes, list) else ""
    note_hits = 0
    for keywords in (
        ("critical", "关键路径"),
        ("resource", "资源"),
        ("E", "F", "G"),
    ):
        if any(keyword in notes_text.lower() or keyword in notes_text for keyword in keywords):
            note_hits += 1
    note_score = 0.0
    if isinstance(notes, list) and len([item for item in notes if str(item).strip()]) >= 2:
        note_score += 0.05
    if note_hits >= 2:
        note_score += 0.05
    checkpoints["notes_capture_reasoning"] = {
        "score": round(note_score, 4),
        "max": 0.1,
        "detail": f"notes={len(notes) if isinstance(notes, list) else 0} hits={note_hits}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}
