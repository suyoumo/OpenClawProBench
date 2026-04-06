"""H5: 多约束项目规划 — 评分脚本"""

from __future__ import annotations

import json
from pathlib import Path

from harness.openclaw_native import load_json_file

# Ground truth from fixtures:
# blocked_assignees: ["charlie"] -> tasks p03, p08, p12 are excluded
# priority_categories: ["security", "compliance"]
# budget_hours: 40
# max_parallel: 3
#
# After removing charlie's tasks (p03, p08, p12):
#   p01: security, alice, 8h, no deps
#   p02: compliance, bob, 6h, depends p01
#   p04: security, alice, 5h, depends p01
#   p05: engineering, dave, 4h, depends p03 -> BLOCKED (p03 excluded)
#   p06: security, bob, 10h, no deps
#   p07: design, eve, 15h, no deps
#   p09: engineering, dave, 6h, no deps
#   p10: security, alice, 7h, depends p04
#   p11: design, eve, 4h, depends p07
#
# Priority tasks (security+compliance): p01(8), p02(6), p04(5), p06(10), p10(7) = 36h
# Non-priority: p07(15), p09(6), p11(4)
# Budget = 40h. Priority tasks = 36h. Can fit all priority + p09(6) would exceed.
# So: select all priority tasks (36h) + maybe p09 (4h remaining? 36+6=42 > 40)
# Actually 40-36=4, so p11(4h) fits if p07 is done, but p07 is 15h.
# Best: all priority (36h) + nothing else within budget, or p09 partially.

BLOCKED_ASSIGNEES = {"charlie"}
PRIORITY_CATEGORIES = {"security", "compliance"}
BUDGET = 40

TASKS = {
    "p01": {"effort": 8, "assignee": "alice", "depends": [], "category": "security"},
    "p02": {"effort": 6, "assignee": "bob", "depends": ["p01"], "category": "compliance"},
    "p03": {"effort": 12, "assignee": "charlie", "depends": [], "category": "engineering"},
    "p04": {"effort": 5, "assignee": "alice", "depends": ["p01"], "category": "security"},
    "p05": {"effort": 4, "assignee": "dave", "depends": ["p03"], "category": "engineering"},
    "p06": {"effort": 10, "assignee": "bob", "depends": [], "category": "security"},
    "p07": {"effort": 15, "assignee": "eve", "depends": [], "category": "design"},
    "p08": {"effort": 3, "assignee": "charlie", "depends": ["p02"], "category": "compliance"},
    "p09": {"effort": 6, "assignee": "dave", "depends": [], "category": "engineering"},
    "p10": {"effort": 7, "assignee": "alice", "depends": ["p04"], "category": "security"},
    "p11": {"effort": 4, "assignee": "eve", "depends": ["p07"], "category": "design"},
    "p12": {"effort": 9, "assignee": "charlie", "depends": ["p03"], "category": "engineering"},
}

def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    # --- checkpoint: read_both (0.1) ---
    read_project = read_constraints = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        args = event.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", "") or args.get("command", ""))
        if "project.json" in path:
            read_project = True
        if "constraints.json" in path:
            read_constraints = True
    checkpoints["read_both"] = {
        "score": 0.1 if (read_project and read_constraints) else 0.05 if (read_project or read_constraints) else 0.0,
        "max": 0.1,
        "detail": f"project={read_project} constraints={read_constraints}",
    }

    # --- checkpoint: file_exists (0.05) ---
    payload, detail = load_json_file(workspace, "plan.json")
    checkpoints["file_exists"] = {
        "score": 0.05 if payload is not None else 0.0,
        "max": 0.05,
        "detail": detail,
    }

    if payload is None:
        for cid, mx in (
            ("no_blocked_assignees", 0.1),
            ("dependencies_respected", 0.1),
            ("within_budget", 0.2),
            ("total_effort_accurate", 0.1),
            ("priority_first", 0.05),
            ("max_parallel_respected", 0.05),
            ("dependency_order_respected", 0.1),
            ("deferred_tasks_correct", 0.1),
            ("transitive_block_detected", 0.05),
        ):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    selected = payload.get("selected_tasks", [])
    if not isinstance(selected, list):
        selected = []
    selected_ids = [s.get("id") for s in selected if isinstance(s, dict) and s.get("id")]

    # --- checkpoint: no_blocked_assignees (0.15) ---
    has_blocked = any(
        TASKS.get(tid, {}).get("assignee") in BLOCKED_ASSIGNEES
        for tid in selected_ids
    )
    checkpoints["no_blocked_assignees"] = {
        "score": 0.1 if not has_blocked else 0.0,
        "max": 0.1,
        "detail": f"blocked_assignee_in_plan={has_blocked}",
    }

    # --- checkpoint: dependencies_respected (0.15) ---
    selected_set = set(selected_ids)
    deps_ok = True
    for tid in selected_ids:
        task = TASKS.get(tid)
        if not task:
            continue
        for dep in task["depends"]:
            if dep not in selected_set and dep not in BLOCKED_ASSIGNEES:
                dep_task = TASKS.get(dep)
                if dep_task and dep_task["assignee"] not in BLOCKED_ASSIGNEES:
                    deps_ok = False
    checkpoints["dependencies_respected"] = {
        "score": 0.1 if deps_ok else 0.0,
        "max": 0.1,
        "detail": f"deps_respected={deps_ok}",
    }

    # --- checkpoint: within_budget (0.25) ---
    total_effort = sum(TASKS.get(tid, {}).get("effort", 0) for tid in selected_ids)
    got_within = payload.get("within_budget")
    budget_ok = total_effort <= BUDGET
    report_ok = got_within is True if budget_ok else got_within is False
    checkpoints["within_budget"] = {
        "score": 0.2 if (budget_ok and report_ok) else 0.08 if budget_ok else 0.0,
        "max": 0.2,
        "detail": f"total={total_effort}/{BUDGET} within={budget_ok} reported={got_within}",
    }

    # --- checkpoint: total_effort_accurate (0.1) ---
    got_total = payload.get("total_effort_hours")
    effort_accurate = got_total == total_effort
    checkpoints["total_effort_accurate"] = {
        "score": 0.1 if effort_accurate else 0.0,
        "max": 0.1,
        "detail": f"reported_total={got_total} actual_total={total_effort}",
    }

    # --- checkpoint: priority_first (0.1) ---
    priority_selected = [tid for tid in selected_ids if TASKS.get(tid, {}).get("category") in PRIORITY_CATEGORIES]
    eligible_priority = [
        tid for tid, t in TASKS.items()
        if t["category"] in PRIORITY_CATEGORIES and t["assignee"] not in BLOCKED_ASSIGNEES
    ]
    priority_ratio = len(priority_selected) / max(len(eligible_priority), 1)
    got_priority_count = payload.get("priority_tasks_scheduled")
    checkpoints["priority_first"] = {
        "score": round(0.05 * priority_ratio, 4),
        "max": 0.05,
        "detail": f"priority_selected={len(priority_selected)}/{len(eligible_priority)} reported={got_priority_count}",
    }

    # --- checkpoint: max_parallel_respected (0.05) ---
    from collections import Counter
    day_counts = Counter()
    start_days = {}
    for s in selected:
        if isinstance(s, dict) and s.get("start_day") is not None:
            day_counts[s["start_day"]] += 1
            if s.get("id"):
                start_days[s["id"]] = s["start_day"]
    max_concurrent = max(day_counts.values()) if day_counts else 0
    parallel_ok = max_concurrent <= 3
    violations = payload.get("constraint_violations", [])
    checkpoints["max_parallel_respected"] = {
        "score": 0.05 if parallel_ok else 0.0,
        "max": 0.05,
        "detail": f"max_concurrent={max_concurrent} violations={len(violations)}",
    }

    # --- checkpoint: dependency_order_respected (0.1) ---
    # For selected tasks, verify start_day respects dependency chains.
    # p02 depends on p01, p04 depends on p01, p10 depends on p04.
    dep_order_ok = True
    dep_violations = []
    if start_days:
        for tid in selected_ids:
            task = TASKS.get(tid)
            if not task:
                continue
            for dep in task["depends"]:
                if dep in start_days and tid in start_days:
                    if start_days[tid] <= start_days[dep]:
                        dep_order_ok = False
                        dep_violations.append(f"{tid}(day={start_days[tid]}) must be after {dep}(day={start_days[dep]})")
    else:
        # No start_days provided at all
        dep_order_ok = False
        dep_violations.append("no start_day values provided")
    checkpoints["dependency_order_respected"] = {
        "score": 0.1 if dep_order_ok else 0.0,
        "max": 0.1,
        "detail": f"dep_order_ok={dep_order_ok} violations={dep_violations[:3]}",
    }

    # --- checkpoint: deferred_tasks_correct (0.1) ---
    # Expected deferred: p03/p08/p12 (blocked assignee), p05 (transitive dep block),
    # p07/p09/p11 (budget or non-priority)
    deferred = payload.get("deferred_tasks", [])
    if not isinstance(deferred, list):
        deferred = []
    deferred_ids = set()
    for d in deferred:
        if isinstance(d, dict) and d.get("id"):
            deferred_ids.add(d["id"])
    # Must include blocked-assignee tasks and transitively blocked p05
    must_defer = {"p03", "p08", "p12", "p05"}
    deferred_hits = len(must_defer & deferred_ids)
    checkpoints["deferred_tasks_correct"] = {
        "score": round(0.1 * deferred_hits / len(must_defer), 4),
        "max": 0.1,
        "detail": f"deferred_ids={sorted(deferred_ids)} must_defer={sorted(must_defer)} hits={deferred_hits}/{len(must_defer)}",
    }

    # --- checkpoint: transitive_block_detected (0.05) ---
    # p05 depends on p03 (charlie's task). Agent must recognize p05 is blocked
    # even though p05's own assignee (dave) is not blocked.
    p05_deferred = "p05" in deferred_ids
    p05_reason_ok = False
    for d in deferred:
        if isinstance(d, dict) and d.get("id") == "p05":
            reason = str(d.get("reason", "")).lower()
            if any(kw in reason for kw in ("p03", "depend", "依赖", "blocked", "charlie")):
                p05_reason_ok = True
    checkpoints["transitive_block_detected"] = {
        "score": 0.05 if (p05_deferred and p05_reason_ok) else 0.0,
        "max": 0.05,
        "detail": f"p05_deferred={p05_deferred} p05_reason_ok={p05_reason_ok}",
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
        if tool == "exec":
            cmd = str(args.get("command", ""))
            if "project.json" in cmd or "constraints.json" in cmd:
                read_count += 1
        if tool == "write":
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if read_count >= 2 and wrote_json:
        return 1.0
    if read_count >= 1 and wrote_json:
        return 0.7
    return 0.3
