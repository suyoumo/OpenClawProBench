"""Grounded scoring for constraints_11_time_window_optimization_live."""

from __future__ import annotations

from itertools import product
from pathlib import Path

from harness.custom_check_helpers import (
    file_exists_checkpoint,
    load_json_output,
    seeded_inputs_unchanged,
    skip_checkpoints,
    tool_arg_paths,
)


EXPECTED_INPUTS = [
    "tasks.json",
    "rules.json",
    "output_contract.json",
]
OUTPUT_NAME = "time_allocation.json"
SKIPPED_CHECKS = (
    ("top_level_contract_is_exact", 0.1),
    ("assigned_slots_are_optimal", 0.3),
    ("resolved_conflicts_cover_key_tradeoffs", 0.1),
    ("unresolved_tasks_are_correct", 0.1),
    ("completion_count_is_correct", 0.1),
    ("notes_capture_constraint_logic", 0.1),
)


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "constraints_11_time_window_optimization" / "fixtures"


def _fixture_json(name: str) -> dict:
    payload, error = load_json_output(_fixture_dir() / name)
    if payload is None:
        raise RuntimeError(f"Invalid fixture JSON for {name}: {error}")
    return payload


def _tasks_payload() -> dict:
    return _fixture_json("tasks.json")


def _rules_payload() -> dict:
    return _fixture_json("rules.json")


def _contract_payload() -> dict:
    return _fixture_json("output_contract.json")


def _task_map() -> dict[str, dict]:
    return {
        str(item["task"]): item
        for item in _tasks_payload().get("tasks", [])
        if isinstance(item, dict) and "task" in item
    }


def _required_top_level_keys() -> set[str]:
    return set(_contract_payload().get("required_top_level_keys", []))


def _required_slot_fields() -> list[str]:
    return list(_contract_payload().get("assigned_slots_contract", {}).get("required_fields", []))


def _resolved_conflict_requirements() -> dict:
    return dict(_contract_payload().get("resolved_conflict_requirements", {}))


def _notes_requirements() -> dict:
    return dict(_contract_payload().get("notes_requirements", {}))


def _priority_rank(priority: str) -> int:
    return int(str(priority).replace("P", ""))


def _candidate_starts(task: dict) -> list[int]:
    start_min = int(task["window_start"])
    end_max = int(task["window_end"])
    duration = int(task["duration"])
    return list(range(start_min, end_max - duration + 1))


def _topic_group_hits(text: str, groups: list[list[list[str]]]) -> int:
    lowered = text.lower()
    hits = 0
    for group in groups:
        matched = True
        for token_options in group:
            if not any(str(token).lower() in lowered for token in token_options):
                matched = False
                break
        if matched:
            hits += 1
    return hits


def _best_plan() -> tuple[list[dict], list[str], int]:
    task_map = _task_map()
    task_names = sorted(task_map)
    options = [[None, *_candidate_starts(task_map[name])] for name in task_names]
    worker_count = int(_rules_payload().get("worker_count", 1))
    if worker_count != 1:
        raise RuntimeError("constraints_11 scorer currently expects worker_count=1")

    best_key: tuple[int, tuple[int, ...], tuple[tuple[int, str, int], ...]] | None = None
    best_slots: list[dict] | None = None
    best_unresolved: list[str] | None = None

    for values in product(*options):
        assignment = dict(zip(task_names, values))
        scheduled: list[tuple[int, str, int, str | None]] = []
        valid = True
        for task_name in task_names:
            start = assignment[task_name]
            if start is None:
                continue

            task = task_map[task_name]
            duration = int(task["duration"])
            end = int(start) + duration

            for dep in task.get("deps", []):
                dep_start = assignment.get(str(dep))
                if dep_start is None:
                    valid = False
                    break
                dep_end = int(dep_start) + int(task_map[str(dep)]["duration"])
                if dep_end > int(start):
                    valid = False
                    break
            if not valid:
                break

            resource = task.get("resource")
            for other_start, other_name, other_end, other_resource in scheduled:
                overlaps = not (end <= other_start or int(start) >= other_end)
                if overlaps:
                    valid = False
                    break
                if resource and other_resource and resource == other_resource and overlaps:
                    valid = False
                    break
            if not valid:
                break

            scheduled.append((int(start), task_name, end, str(resource) if resource is not None else None))

        if not valid:
            continue

        scheduled.sort(key=lambda item: (item[0], item[1]))
        completion_count = len(scheduled)
        priority_counts = tuple(
            sum(1 for _, task_name, _, _ in scheduled if _priority_rank(str(task_map[task_name]["priority"])) == rank)
            for rank in range(3)
        )
        slot_key = tuple((start, task_name, end) for start, task_name, end, _ in scheduled)

        if best_key is None or completion_count > best_key[0]:
            best_key = (completion_count, priority_counts, slot_key)
        elif completion_count == best_key[0]:
            if priority_counts > best_key[1]:
                best_key = (completion_count, priority_counts, slot_key)
            elif priority_counts == best_key[1] and slot_key < best_key[2]:
                best_key = (completion_count, priority_counts, slot_key)
            else:
                continue
        else:
            continue

        best_slots = [
            {"task": task_name, "start": start, "end": end}
            for start, task_name, end, _ in scheduled
        ]
        best_unresolved = sorted(task_name for task_name in task_names if assignment[task_name] is None)

    if best_key is None or best_slots is None or best_unresolved is None:
        raise RuntimeError("No feasible plan found for constraints_11 fixtures")
    return best_slots, best_unresolved, best_key[0]


def _observed_reads(trace: dict) -> set[str]:
    paths = tool_arg_paths(trace, tool_name="read", basename=True)
    for event in trace.get("events", []):
        if event.get("type") != "tool_call" or str(event.get("tool", "")).lower() != "exec":
            continue
        command = str((event.get("args") or {}).get("command", ""))
        for name in EXPECTED_INPUTS:
            if name in command:
                paths.add(name)
    return paths


def _observed_writes(trace: dict) -> set[str]:
    paths = tool_arg_paths(trace, tool_name="write", basename=True)
    for event in trace.get("events", []):
        if event.get("type") != "tool_call" or str(event.get("tool", "")).lower() != "exec":
            continue
        command = str((event.get("args") or {}).get("command", ""))
        if OUTPUT_NAME in command:
            paths.add(OUTPUT_NAME)
    return paths


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = workspace_path / OUTPUT_NAME
    output_exists = file_exists_checkpoint(checkpoints, "allocation_file_exists", output_path, max_score=0.1)

    observed_reads = _observed_reads(trace)
    read_count = sum(1 for name in EXPECTED_INPUTS if name in observed_reads)
    checkpoints["read_required_inputs"] = {
        "score": round((read_count / len(EXPECTED_INPUTS)) * 0.1, 4),
        "max": 0.1,
        "detail": f"read_count={read_count}/{len(EXPECTED_INPUTS)}",
    }

    inputs_ok, inputs_detail = seeded_inputs_unchanged(workspace_path, _fixture_dir(), EXPECTED_INPUTS)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        skip_checkpoints(checkpoints, SKIPPED_CHECKS)
        return {"checkpoints": checkpoints, "safety_violations": []}

    payload, error = load_json_output(output_path)
    if payload is None:
        skip_checkpoints(checkpoints, SKIPPED_CHECKS, detail=error)
        return {"checkpoints": checkpoints, "safety_violations": []}

    actual_keys = set(payload.keys()) if isinstance(payload, dict) else set()
    required_keys = _required_top_level_keys()
    top_level_score = 1.0 if actual_keys == required_keys else 0.5 if actual_keys.issuperset(required_keys) else 0.0
    checkpoints["top_level_contract_is_exact"] = {
        "score": round(0.1 * top_level_score, 4),
        "max": 0.1,
        "detail": f"keys={sorted(actual_keys)}",
    }

    expected_slots, expected_unresolved, expected_completion = _best_plan()
    assigned_slots = payload.get("assigned_slots")
    slots_exact = assigned_slots == expected_slots
    slots_shape_ok = False
    if isinstance(assigned_slots, list) and len(assigned_slots) == len(expected_slots):
        slots_shape_ok = True
        prior: tuple[int, str] | None = None
        for row in assigned_slots:
            if not isinstance(row, dict):
                slots_shape_ok = False
                break
            if not set(_required_slot_fields()).issubset(row.keys()):
                slots_shape_ok = False
                break
            current = (int(row.get("start", -999)), str(row.get("task", "")))
            if prior is not None and current < prior:
                slots_shape_ok = False
                break
            prior = current
    checkpoints["assigned_slots_are_optimal"] = {
        "score": 0.3 if slots_exact else 0.15 if slots_shape_ok else 0.0,
        "max": 0.3,
        "detail": f"assigned_slots={assigned_slots}",
    }

    conflict_requirements = _resolved_conflict_requirements()
    resolved_conflicts = payload.get("resolved_conflicts")
    resolved_text = " ".join(str(item) for item in resolved_conflicts) if isinstance(resolved_conflicts, list) else ""
    resolved_hits = _topic_group_hits(resolved_text, conflict_requirements.get("required_topic_groups", []))
    resolved_count = len(resolved_conflicts) if isinstance(resolved_conflicts, list) else 0
    resolved_target = max(int(conflict_requirements.get("min_topic_hits", 2)), 1)
    resolved_score = 0.0
    if resolved_count >= int(conflict_requirements.get("min_items", 2)):
        resolved_score = min(resolved_hits / resolved_target, 1.0)
    checkpoints["resolved_conflicts_cover_key_tradeoffs"] = {
        "score": round(0.1 * resolved_score, 4),
        "max": 0.1,
        "detail": f"resolved_count={resolved_count} hits={resolved_hits}",
    }

    unresolved_tasks = payload.get("unresolved_tasks")
    checkpoints["unresolved_tasks_are_correct"] = {
        "score": 0.1 if unresolved_tasks == expected_unresolved else 0.0,
        "max": 0.1,
        "detail": f"unresolved_tasks={unresolved_tasks}",
    }

    checkpoints["completion_count_is_correct"] = {
        "score": 0.1 if payload.get("completion_count") == expected_completion else 0.0,
        "max": 0.1,
        "detail": f"completion_count={payload.get('completion_count')!r}",
    }

    notes_requirements = _notes_requirements()
    notes = payload.get("notes")
    notes_text = " ".join(str(item) for item in notes) if isinstance(notes, list) else ""
    note_hits = _topic_group_hits(notes_text, notes_requirements.get("required_topic_groups", []))
    notes_count = len(notes) if isinstance(notes, list) else 0
    note_target = max(int(notes_requirements.get("min_topic_hits", 2)), 1)
    note_score = 0.0
    if notes_count >= int(notes_requirements.get("min_items", 2)):
        note_score = min(note_hits / note_target, 1.0)
    checkpoints["notes_capture_constraint_logic"] = {
        "score": round(0.1 * note_score, 4),
        "max": 0.1,
        "detail": f"notes_count={notes_count} hits={note_hits}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _observed_reads(trace)
    write_paths = _observed_writes(trace)

    read_count = sum(1 for name in EXPECTED_INPUTS if name in read_paths)
    wrote_output = OUTPUT_NAME in write_paths
    rewrote_inputs = any(name in write_paths for name in EXPECTED_INPUTS)

    if read_count == len(EXPECTED_INPUTS) and wrote_output and not rewrote_inputs:
        return 1.0
    if read_count >= 2 and wrote_output and not rewrote_inputs:
        return 0.8
    if read_count >= 1 and wrote_output:
        return 0.6
    if read_count >= 1 or wrote_output:
        return 0.35
    return 0.2
