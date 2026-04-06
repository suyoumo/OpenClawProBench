"""Grounded scoring for intel_h03_temporal_constraint_scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import permutations
from typing import Any, NamedTuple

from harness.openclaw_native import (
    eligible_skill_names,
    load_json_file,
    load_skills_inventory,
    trace_native_surface_snapshot,
    trace_used_openclaw_skills_inventory,
)


class Task(NamedTuple):
    task_id: str
    duration_hours: int
    earliest_start: datetime
    deadline: datetime
    requires_skill: str


def _parse_iso(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _load_tasks(workspace: str) -> dict[str, Task]:
    payload, _ = load_json_file(workspace, "schedule_input.json")
    tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
    task_map: dict[str, Task] = {}
    for raw in tasks:
        if not isinstance(raw, dict):
            continue
        task_id = str(raw.get("id", "")).strip()
        start = _parse_iso(raw.get("earliest_start"))
        deadline = _parse_iso(raw.get("deadline"))
        duration = raw.get("duration_hours")
        skill = str(raw.get("requires_skill", "")).strip()
        if not task_id or not start or not deadline or not isinstance(duration, int) or duration <= 0 or not skill:
            continue
        task_map[task_id] = Task(
            task_id=task_id,
            duration_hours=duration,
            earliest_start=start,
            deadline=deadline,
            requires_skill=skill,
        )
    return task_map


def _reason_if_unschedulable(task: Task) -> str:
    if task.earliest_start + timedelta(hours=task.duration_hours) > task.deadline:
        return "deadline_exceeded"
    return "time_conflict"


def _schedule_order(tasks: tuple[Task, ...]) -> list[dict[str, Any]] | None:
    current_end: datetime | None = None
    scheduled: list[dict[str, Any]] = []
    for task in tasks:
        start = task.earliest_start if current_end is None else max(task.earliest_start, current_end)
        end = start + timedelta(hours=task.duration_hours)
        if end > task.deadline:
            return None
        scheduled.append(
            {
                "task_id": task.task_id,
                "start": start,
                "end": end,
            }
        )
        current_end = end
    return scheduled


def _derive_expected(task_map: dict[str, Task], ready_skills: set[str]) -> dict[str, Any]:
    blocked_rows = sorted(
        [
            {
                "task_id": task.task_id,
                "reason": "skill_unavailable",
                "required_skill": task.requires_skill,
            }
            for task in task_map.values()
            if task.requires_skill not in ready_skills
        ],
        key=lambda item: item["task_id"],
    )
    available_tasks = tuple(sorted(
        (task for task in task_map.values() if task.requires_skill in ready_skills),
        key=lambda item: item.task_id,
    ))

    best_key = (-1, -1)
    optimal_plans: dict[tuple[str, ...], dict[str, Any]] = {}
    for size in range(len(available_tasks) + 1):
        for order in permutations(available_tasks, size):
            scheduled = _schedule_order(order)
            if scheduled is None:
                continue
            total_hours = sum(task.duration_hours for task in order)
            key = (total_hours, len(order))
            unscheduled_rows = sorted(
                [
                    {
                        "task_id": task.task_id,
                        "reason": _reason_if_unschedulable(task),
                    }
                    for task in available_tasks
                    if task not in order
                ],
                key=lambda item: item["task_id"],
            )
            plan_key = tuple(task.task_id for task in order)
            if key > best_key:
                best_key = key
                optimal_plans = {}
            if key == best_key and plan_key not in optimal_plans:
                optimal_plans[plan_key] = {
                    "scheduled": scheduled,
                    "unschedulable": unscheduled_rows,
                    "total_hours": total_hours,
                }

    if best_key == (-1, -1):
        best_key = (0, 0)
        optimal_plans[()] = {
            "scheduled": [],
            "unschedulable": [],
            "total_hours": 0,
        }

    return {
        "blocked": blocked_rows,
        "optimal_total_hours": best_key[0],
        "optimal_plans": optimal_plans,
    }


def _validate_scheduled_rows(
    scheduled_rows: object,
    task_map: dict[str, Task],
    ready_skills: set[str],
) -> tuple[bool, str, tuple[str, ...], int]:
    if not isinstance(scheduled_rows, list):
        return False, "scheduled is not a list", (), 0

    previous_end: datetime | None = None
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    total_hours = 0
    for row in scheduled_rows:
        if not isinstance(row, dict):
            return False, "scheduled row is not an object", (), 0
        task_id = str(row.get("task_id", "")).strip()
        task = task_map.get(task_id)
        if task is None:
            return False, f"unknown task_id={task_id!r}", (), 0
        if task_id in seen_ids:
            return False, f"duplicate task_id={task_id}", (), 0
        if task.requires_skill not in ready_skills:
            return False, f"blocked task scheduled: {task_id}", (), 0
        start = _parse_iso(row.get("start"))
        end = _parse_iso(row.get("end"))
        if start is None or end is None:
            return False, f"invalid start/end for {task_id}", (), 0
        if end - start != timedelta(hours=task.duration_hours):
            return False, f"duration mismatch for {task_id}", (), 0
        if start < task.earliest_start or end > task.deadline:
            return False, f"window violation for {task_id}", (), 0
        if previous_end is not None and start < previous_end:
            return False, f"time overlap at {task_id}", (), 0
        previous_end = end
        ordered_ids.append(task_id)
        seen_ids.add(task_id)
        total_hours += task.duration_hours

    return True, f"scheduled_ids={ordered_ids}", tuple(ordered_ids), total_hours


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    used_cli = trace_used_openclaw_skills_inventory(trace)
    checkpoints["used_skills_cli"] = {
        "score": 0.1 if used_cli else 0.0,
        "max": 0.1,
        "detail": "used skills cli" if used_cli else "missing",
    }

    read_input = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        args = event.get("args") or {}
        target = str(args.get("path", "") or args.get("file_path", "") or args.get("command", ""))
        if "schedule_input.json" in target:
            read_input = True
            break
    checkpoints["read_input"] = {
        "score": 0.1 if read_input else 0.0,
        "max": 0.1,
        "detail": "read schedule_input.json" if read_input else "did not read input",
    }

    payload, detail = load_json_file(workspace, "schedule.json")
    checkpoints["file_exists"] = {
        "score": 0.05 if payload is not None else 0.0,
        "max": 0.05,
        "detail": detail,
    }

    if payload is None:
        for cid, mx in (
            ("blocked_correct", 0.2),
            ("schedule_is_feasible", 0.2),
            ("optimal_schedule_selected", 0.2),
            ("unschedulable_is_correct", 0.1),
            ("total_hours_is_optimal", 0.1),
        ):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    skill_snapshot = trace_native_surface_snapshot(trace, "skills")
    if skill_snapshot and skill_snapshot.get("status") == "ready" and isinstance(skill_snapshot.get("ready_list"), list):
        ready_skills = {str(name) for name in skill_snapshot.get("ready_list", [])}
    else:
        try:
            inventory = load_skills_inventory()
            ready_skills = set(eligible_skill_names(inventory))
        except Exception as exc:
            for cid, mx in (
                ("blocked_correct", 0.2),
                ("schedule_is_feasible", 0.2),
                ("optimal_schedule_selected", 0.2),
                ("unschedulable_is_correct", 0.1),
                ("total_hours_is_optimal", 0.1),
            ):
                checkpoints[cid] = {"score": 0.0, "max": mx, "detail": f"openclaw error: {exc}"}
            return {"checkpoints": checkpoints, "safety_violations": []}

    task_map = _load_tasks(workspace)
    expected = _derive_expected(task_map, ready_skills)

    blocked_rows = payload.get("blocked", [])
    if not isinstance(blocked_rows, list):
        blocked_rows = []
    blocked_ok = blocked_rows == expected["blocked"]
    checkpoints["blocked_correct"] = {
        "score": 0.2 if blocked_ok else 0.0,
        "max": 0.2,
        "detail": f"blocked={blocked_rows}",
    }

    feasible, feasible_detail, ordered_ids, actual_total_hours = _validate_scheduled_rows(
        payload.get("scheduled", []),
        task_map,
        ready_skills,
    )
    checkpoints["schedule_is_feasible"] = {
        "score": 0.2 if feasible else 0.0,
        "max": 0.2,
        "detail": feasible_detail,
    }

    optimal_plans = expected["optimal_plans"]
    is_optimal = feasible and ordered_ids in optimal_plans
    checkpoints["optimal_schedule_selected"] = {
        "score": 0.2 if is_optimal else 0.0,
        "max": 0.2,
        "detail": (
            f"scheduled_ids={list(ordered_ids)}"
            if feasible
            else feasible_detail
        ),
    }

    expected_unschedulable = optimal_plans.get(ordered_ids, {}).get("unschedulable", [])
    unschedulable_rows = payload.get("unschedulable", [])
    if not isinstance(unschedulable_rows, list):
        unschedulable_rows = []
    unschedulable_ok = is_optimal and unschedulable_rows == expected_unschedulable
    checkpoints["unschedulable_is_correct"] = {
        "score": 0.1 if unschedulable_ok else 0.0,
        "max": 0.1,
        "detail": f"unschedulable={unschedulable_rows}",
    }

    reported_total_hours = payload.get("total_scheduled_hours")
    total_hours_ok = (
        is_optimal
        and isinstance(reported_total_hours, int)
        and reported_total_hours == actual_total_hours == expected["optimal_total_hours"]
    )
    checkpoints["total_hours_is_optimal"] = {
        "score": 0.1 if total_hours_ok else 0.0,
        "max": 0.1,
        "detail": (
            f"reported={reported_total_hours} actual={actual_total_hours} optimal={expected['optimal_total_hours']}"
        ),
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_input = False
    used_cli = trace_used_openclaw_skills_inventory(trace)
    wrote_schedule = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        tool = str(event.get("tool", "")).lower()
        args = event.get("args") or {}
        target = str(args.get("path", "") or args.get("file_path", "") or args.get("command", ""))
        if "schedule_input.json" in target:
            read_input = True
        if tool == "write" and str(args.get("path", "") or args.get("file_path", "")).endswith("schedule.json"):
            wrote_schedule = True
    if read_input and used_cli:
        return 1.0
    if used_cli and wrote_schedule:
        return 0.8
    if read_input and wrote_schedule:
        return 0.6
    if wrote_schedule:
        return 0.4
    return 0.2
