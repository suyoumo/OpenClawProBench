"""Grounded scoring for constraints_12_exception_window_live."""

from __future__ import annotations

from itertools import permutations
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
OUTPUT_NAME = "change_schedule.json"
SKIPPED_CHECKS = (
    ("top_level_contract_is_exact", 0.1),
    ("slot_plan_is_optimal", 0.3),
    ("deferred_tasks_are_correct", 0.15),
    ("total_value_is_correct", 0.15),
    ("triggered_rules_are_complete", 0.1),
    ("notes_are_nontrivial", 0.1),
)


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "constraints_12_exception_window" / "fixtures"


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
    return {str(item["task"]): item for item in _tasks_payload().get("tasks", []) if isinstance(item, dict) and "task" in item}


def _required_hours() -> list[int]:
    return [int(item) for item in _contract_payload().get("slot_plan_contract", {}).get("required_hours", [])]


def _required_slot_fields() -> list[str]:
    return list(_contract_payload().get("slot_plan_contract", {}).get("required_fields", []))


def _triggered_rule_groups() -> list[list[str]]:
    return list(_contract_payload().get("triggered_rule_requirements", {}).get("required_keyword_groups", []))


def _triggered_rule_min_items() -> int:
    return int(_contract_payload().get("triggered_rule_requirements", {}).get("min_items", 3))


def _note_keyword_groups() -> list[list[str]]:
    return list(_contract_payload().get("notes_requirements", {}).get("required_keyword_groups", []))


def _note_min_items() -> int:
    return int(_contract_payload().get("notes_requirements", {}).get("min_items", 2))


def _required_top_level_keys() -> set[str]:
    return set(_contract_payload().get("required_top_level_keys", []))


def _task_allowed_at_hour(task: dict, hour: int) -> bool:
    earliest_start = task.get("earliest_start")
    if earliest_start is not None and hour < int(earliest_start):
        return False
    must_start_before = task.get("must_start_before")
    if must_start_before is not None and hour >= int(must_start_before):
        return False
    freeze_hours = set(int(item) for item in _rules_payload().get("external_freeze_windows", []))
    if str(task.get("scope", "")) == "external" and hour in freeze_hours:
        return False
    return True


def _value_at_execution(task_name: str, assigned: dict[int, str], hour: int) -> int:
    task = _task_map()[task_name]
    base_value = int(task.get("value", 0))
    dependency = task.get("depends_on")
    if dependency:
        dependency_hour = None
        for slot_hour, slot_task in assigned.items():
            if slot_task == dependency:
                dependency_hour = slot_hour
                break
        if dependency_hour is None or dependency_hour >= hour:
            return int(task.get("value_if_dependency_missing", 0))
    return base_value


def _schedule_score(task_sequence: tuple[str, ...]) -> tuple[int, list[dict], list[str]]:
    hours = _required_hours()
    assigned = {hour: task for hour, task in zip(hours, task_sequence)}
    slot_plan: list[dict] = []
    total_value = 0
    for hour in hours:
        task_name = assigned[hour]
        value = _value_at_execution(task_name, assigned, hour)
        slot_plan.append({"hour": hour, "task": task_name, "value_at_execution": value})
        total_value += value
    deferred = sorted(task_name for task_name in _task_map() if task_name not in assigned.values())
    return total_value, slot_plan, deferred


def _best_plan() -> tuple[list[dict], list[str], int]:
    tasks = list(_task_map())
    hours = _required_hours()
    best: tuple[int, list[dict], list[str]] | None = None
    for task_sequence in permutations(tasks, len(hours)):
        feasible = True
        for hour, task_name in zip(hours, task_sequence):
            if not _task_allowed_at_hour(_task_map()[task_name], hour):
                feasible = False
                break
        if not feasible:
            continue
        total_value, slot_plan, deferred = _schedule_score(task_sequence)
        candidate = (total_value, slot_plan, deferred)
        if best is None:
            best = candidate
            continue
        if candidate[0] > best[0]:
            best = candidate
            continue
        if candidate[0] == best[0]:
            candidate_key = tuple(item["task"] for item in candidate[1])
            best_key = tuple(item["task"] for item in best[1])
            if candidate_key < best_key:
                best = candidate
    if best is None:
        raise RuntimeError("No feasible plan found for constraints_12 fixtures")
    return best[1], best[2], best[0]


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


def _keyword_group_hits(text: str, groups: list[list[str]]) -> int:
    lowered = text.lower()
    hits = 0
    for group in groups:
        if all(str(keyword).lower() in lowered for keyword in group):
            hits += 1
    return hits


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = workspace_path / OUTPUT_NAME
    output_exists = file_exists_checkpoint(checkpoints, "schedule_file_exists", output_path, max_score=0.1)

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

    expected_slot_plan, expected_deferred, expected_total_value = _best_plan()
    slot_plan = payload.get("slot_plan")
    slot_plan_exact = slot_plan == expected_slot_plan
    slot_plan_shape_ok = False
    if isinstance(slot_plan, list) and len(slot_plan) == len(_required_hours()):
        slot_plan_shape_ok = True
        for row, expected_hour in zip(slot_plan, _required_hours()):
            if not isinstance(row, dict):
                slot_plan_shape_ok = False
                break
            if row.get("hour") != expected_hour:
                slot_plan_shape_ok = False
                break
            row_keys = set(row.keys())
            if not set(_required_slot_fields()).issubset(row_keys):
                slot_plan_shape_ok = False
                break
    checkpoints["slot_plan_is_optimal"] = {
        "score": 0.3 if slot_plan_exact else 0.15 if slot_plan_shape_ok else 0.0,
        "max": 0.3,
        "detail": f"slot_plan={slot_plan}",
    }

    deferred = payload.get("deferred_tasks")
    checkpoints["deferred_tasks_are_correct"] = {
        "score": 0.15 if deferred == expected_deferred else 0.0,
        "max": 0.15,
        "detail": f"deferred_tasks={deferred}",
    }

    checkpoints["total_value_is_correct"] = {
        "score": 0.15 if payload.get("total_value") == expected_total_value else 0.0,
        "max": 0.15,
        "detail": f"total_value={payload.get('total_value')!r}",
    }

    triggered_rules = payload.get("triggered_rules")
    triggered_text = " ".join(str(item) for item in triggered_rules) if isinstance(triggered_rules, list) else ""
    triggered_hits = _keyword_group_hits(triggered_text, _triggered_rule_groups())
    triggered_score = 0.0
    if isinstance(triggered_rules, list) and len(triggered_rules) >= _triggered_rule_min_items():
        triggered_score = min(triggered_hits / max(len(_triggered_rule_groups()), 1), 1.0)
    checkpoints["triggered_rules_are_complete"] = {
        "score": round(0.1 * triggered_score, 4),
        "max": 0.1,
        "detail": f"triggered_count={len(triggered_rules) if isinstance(triggered_rules, list) else 0} hits={triggered_hits}",
    }

    notes = payload.get("notes")
    notes_text = " ".join(str(item) for item in notes) if isinstance(notes, list) else ""
    note_hits = _keyword_group_hits(notes_text, _note_keyword_groups())
    note_score = 0.0
    if isinstance(notes, list) and len(notes) >= _note_min_items():
        note_score = min(note_hits / max(len(_note_keyword_groups()), 1), 1.0)
    checkpoints["notes_are_nontrivial"] = {
        "score": round(0.1 * note_score, 4),
        "max": 0.1,
        "detail": f"notes_count={len(notes) if isinstance(notes, list) else 0} hits={note_hits}",
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
