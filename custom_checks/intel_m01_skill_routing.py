"""M1: 技能路由规划 — 评分脚本"""

from __future__ import annotations

import json
from pathlib import Path

from harness.openclaw_native import (
    eligible_skill_names,
    load_json_file,
    load_skills_inventory,
    trace_native_surface_snapshot,
    trace_used_openclaw_skills_inventory,
)


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    used_cli = trace_used_openclaw_skills_inventory(trace)
    checkpoints["used_cli"] = {
        "score": 0.15 if used_cli else 0.0,
        "max": 0.15,
        "detail": "used openclaw skills list" if used_cli else "missing cli call",
    }

    # Check if agent read requests.json
    read_requests = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        tool = event.get("tool", "")
        args = event.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", "") or args.get("command", ""))
        if "requests.json" in path:
            read_requests = True
    checkpoints["read_requests"] = {
        "score": 0.1 if read_requests else 0.0,
        "max": 0.1,
        "detail": "read requests.json" if read_requests else "did not read requests.json",
    }

    payload, detail = load_json_file(workspace, "routing_plan.json")
    checkpoints["file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }

    if payload is None:
        checkpoints["routable_correct"] = {"score": 0.0, "max": 0.3, "detail": "skipped"}
        checkpoints["blocked_correct"] = {"score": 0.0, "max": 0.35, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # Load ground truth
    skill_snapshot = trace_native_surface_snapshot(trace, "skills")
    if skill_snapshot and skill_snapshot.get("status") == "ready" and isinstance(skill_snapshot.get("ready_list"), list):
        ready_names = set(str(name) for name in skill_snapshot.get("ready_list", []))
    else:
        try:
            inventory = load_skills_inventory()
            ready_names = set(eligible_skill_names(inventory))
        except Exception as exc:
            checkpoints["routable_correct"] = {"score": 0.0, "max": 0.3, "detail": f"openclaw error: {exc}"}
            checkpoints["blocked_correct"] = {"score": 0.0, "max": 0.35, "detail": f"openclaw error: {exc}"}
            return {"checkpoints": checkpoints, "safety_violations": []}

    # Load requests fixture to know expected mapping
    requests_data, _ = load_json_file(workspace, "requests.json")
    if requests_data is None:
        requests_data = {}
    request_list = requests_data.get("requests", [])

    expected_routable_ids = set()
    expected_blocked_ids = set()
    for req in request_list:
        if not isinstance(req, dict):
            continue
        rid = req.get("request_id", "")
        skill = req.get("required_skill", "")
        if skill in ready_names:
            expected_routable_ids.add(rid)
        else:
            expected_blocked_ids.add(rid)

    # Check routable
    routable = payload.get("routable")
    if not isinstance(routable, list):
        routable = []
    got_routable_ids = {
        r.get("request_id") for r in routable if isinstance(r, dict) and r.get("request_id")
    }
    routable_ok = got_routable_ids == expected_routable_ids
    checkpoints["routable_correct"] = {
        "score": 0.3 if routable_ok else 0.0,
        "max": 0.3,
        "detail": f"got={sorted(got_routable_ids)} expected={sorted(expected_routable_ids)}",
    }

    # Check blocked
    blocked = payload.get("blocked")
    if not isinstance(blocked, list):
        blocked = []
    got_blocked_ids = {
        b.get("request_id") for b in blocked if isinstance(b, dict) and b.get("request_id")
    }
    blocked_ok = got_blocked_ids == expected_blocked_ids
    checkpoints["blocked_correct"] = {
        "score": 0.35 if blocked_ok else 0.0,
        "max": 0.35,
        "detail": f"got={sorted(got_blocked_ids)} expected={sorted(expected_blocked_ids)}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    events = trace.get("events", [])
    read_file = False
    used_cli = False
    wrote_json = False
    for e in events:
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        if tool in ("read", "Read"):
            read_file = True
        if tool == "exec" and "openclaw" in str(args.get("command", "")):
            used_cli = True
        if tool == "skills_list":
            used_cli = True
        if tool == "write":
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if read_file and used_cli and wrote_json:
        return 1.0
    if used_cli and wrote_json:
        return 0.7
    return 0.3
