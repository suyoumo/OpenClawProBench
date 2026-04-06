"""M7: 依赖链规划 — 评分脚本"""

from __future__ import annotations

import json
from pathlib import Path

from harness.openclaw_native import load_json_file

# Ground truth computed from fixtures/tasks.json:
# t1 (30m) -> t2 (20m), t3 (25m)
# t2 -> t4 (15m), t6 (10m)
# t3 -> t4
# t4 -> t5 (40m)
#
# Topological orders (valid): t1 must be first; t2,t3 can be in any order;
# t6 can come after t2; t4 after both t2,t3; t5 last.
# Valid orders include: [t1, t2, t3, t6, t4, t5], [t1, t3, t2, t6, t4, t5], etc.
#
# Critical path: t1(30) -> t3(25) -> t4(15) -> t5(40) = 110 min
#   or t1(30) -> t2(20) -> t4(15) -> t5(40) = 105 min
# So critical path = 110 minutes
#
# Parallel groups:
#   Group 0: [t1]
#   Group 1: [t2, t3]
#   Group 2: [t4, t6]  (t6 depends only on t2, t4 depends on t2+t3)
#   Group 3: [t5]

CRITICAL_PATH_MINUTES = 110
CRITICAL_PATH_TASK_IDS = ["t1", "t3", "t4", "t5"]
HAS_CYCLE = False
EXPECTED_PARALLEL_GROUPS = [["t1"], ["t2", "t3"], ["t4", "t6"], ["t5"]]
EXPECTED_EARLIEST_START = {"t1": 0, "t2": 30, "t3": 30, "t4": 55, "t5": 70, "t6": 50}

TASKS = {
    "t1": {"depends_on": [], "duration": 30},
    "t2": {"depends_on": ["t1"], "duration": 20},
    "t3": {"depends_on": ["t1"], "duration": 25},
    "t4": {"depends_on": ["t2", "t3"], "duration": 15},
    "t5": {"depends_on": ["t4"], "duration": 40},
    "t6": {"depends_on": ["t2"], "duration": 10},
}


def _is_valid_topo_order(order: list[str]) -> bool:
    """Check if the given order is a valid topological sort."""
    if set(order) != set(TASKS.keys()):
        return False
    seen: set[str] = set()
    for tid in order:
        deps = TASKS.get(tid, {}).get("depends_on", [])
        if not all(d in seen for d in deps):
            return False
        seen.add(tid)
    return True


def _validate_parallel_groups(groups: list) -> bool:
    """Check parallel groups are valid: no intra-group dependencies, all deps in prior groups."""
    if not isinstance(groups, list):
        return False
    seen: set[str] = set()
    all_ids: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            return False
        for tid in group:
            if tid not in TASKS:
                return False
            all_ids.add(tid)
            deps = TASKS[tid]["depends_on"]
            # All deps must be in previously seen groups
            if not all(d in seen for d in deps):
                return False
            # No intra-group dependency
            if any(d in group for d in deps):
                return False
        seen.update(group)
    return all_ids == set(TASKS.keys())


def _groups_match_exact(groups: list) -> bool:
    if not isinstance(groups, list) or len(groups) != len(EXPECTED_PARALLEL_GROUPS):
        return False
    normalized = []
    for group in groups:
        if not isinstance(group, list):
            return False
        normalized.append(sorted(group))
    expected = [sorted(group) for group in EXPECTED_PARALLEL_GROUPS]
    return normalized == expected


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    # --- checkpoint: read_tasks (0.08) ---
    read_tasks = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        args = event.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", "") or args.get("command", ""))
        if "tasks.json" in path:
            read_tasks = True
    checkpoints["read_tasks"] = {
        "score": 0.08 if read_tasks else 0.0,
        "max": 0.08,
        "detail": "read tasks.json" if read_tasks else "did not read tasks.json",
    }

    # --- checkpoint: file_exists (0.07) ---
    payload, detail = load_json_file(workspace, "execution_plan.json")
    checkpoints["file_exists"] = {
        "score": 0.07 if payload is not None else 0.0,
        "max": 0.07,
        "detail": detail,
    }

    if payload is None:
        for cid, mx in (
            ("order_valid", 0.15),
            ("critical_path_minutes_correct", 0.15),
            ("critical_path_chain_correct", 0.2),
            ("parallel_groups_correct", 0.25),
            ("earliest_start_correct", 0.1),
        ):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # --- checkpoint: order_valid (0.15) ---
    got_order = payload.get("execution_order", [])
    if not isinstance(got_order, list):
        got_order = []
    order_ok = _is_valid_topo_order(got_order)
    # Also check has_cycle
    got_cycle = payload.get("has_cycle")
    cycle_ok = got_cycle is False or got_cycle == HAS_CYCLE
    order_score = 0.0
    if order_ok:
        order_score += 0.1
    if cycle_ok:
        order_score += 0.05
    checkpoints["order_valid"] = {
        "score": round(order_score, 4),
        "max": 0.15,
        "detail": f"topo_valid={order_ok} has_cycle={got_cycle} (expected {HAS_CYCLE})",
    }

    # --- checkpoint: critical_path_minutes_correct (0.15) ---
    got_cp = payload.get("critical_path_minutes")
    cp_ok = got_cp == CRITICAL_PATH_MINUTES
    checkpoints["critical_path_minutes_correct"] = {
        "score": 0.15 if cp_ok else 0.0,
        "max": 0.15,
        "detail": f"got={got_cp} expected={CRITICAL_PATH_MINUTES}",
    }

    # --- checkpoint: critical_path_chain_correct (0.2) ---
    got_chain = payload.get("critical_path_task_ids", [])
    chain_ok = got_chain == CRITICAL_PATH_TASK_IDS
    checkpoints["critical_path_chain_correct"] = {
        "score": 0.2 if chain_ok else 0.0,
        "max": 0.2,
        "detail": f"got={got_chain} expected={CRITICAL_PATH_TASK_IDS}",
    }

    # --- checkpoint: parallel_groups_correct (0.25) ---
    got_groups = payload.get("parallel_groups", [])
    groups_ok = _validate_parallel_groups(got_groups)
    exact_groups = _groups_match_exact(got_groups)
    groups_score = 0.0
    if groups_ok:
        groups_score += 0.1
    if exact_groups:
        groups_score += 0.15
    checkpoints["parallel_groups_correct"] = {
        "score": round(groups_score, 4),
        "max": 0.25,
        "detail": f"valid_groups={groups_ok} exact_groups={exact_groups} groups={got_groups}",
    }

    # --- checkpoint: earliest_start_correct (0.1) ---
    got_earliest = payload.get("earliest_start_minutes", {})
    if not isinstance(got_earliest, dict):
        got_earliest = {}
    # Coerce values to int for comparison
    correct_starts = 0
    for tid, expected_min in EXPECTED_EARLIEST_START.items():
        got_val = got_earliest.get(tid)
        if got_val is not None:
            try:
                if int(got_val) == expected_min:
                    correct_starts += 1
            except (TypeError, ValueError):
                pass
    earliest_score = round(correct_starts / len(EXPECTED_EARLIEST_START) * 0.1, 4)
    checkpoints["earliest_start_correct"] = {
        "score": earliest_score,
        "max": 0.1,
        "detail": f"{correct_starts}/{len(EXPECTED_EARLIEST_START)} earliest start times correct got={got_earliest}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_file = False
    wrote_json = False
    for e in trace.get("events", []):
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", ""))
        if tool in ("read", "Read"):
            read_file = True
            if "execution_plan.json" in path:
                wrote_json = True
        if tool == "exec":
            cmd = str(args.get("command", ""))
            if "tasks.json" in cmd:
                read_file = True
            if "execution_plan.json" in cmd:
                wrote_json = True
        if tool == "write":
            if path.endswith(".json"):
                wrote_json = True
    if read_file and wrote_json:
        return 1.0
    if wrote_json:
        return 0.5
    return 0.2
