"""E5: 基础多源合并 — 评分脚本"""

from __future__ import annotations

import json
from pathlib import Path

from harness.openclaw_native import load_json_file


# Ground truth from fixture files
SOURCE_A_SERVICES = [
    {"name": "auth-service", "status": "healthy"},
    {"name": "payment-service", "status": "degraded"},
    {"name": "notification-service", "status": "healthy"},
]
SOURCE_B_SERVICES = [
    {"name": "user-service", "status": "healthy"},
    {"name": "search-service", "status": "down"},
    {"name": "auth-service", "status": "healthy"},
]
# Merged: 5 unique services (auth-service appears in both)
ALL_SERVICE_NAMES = sorted({s["name"] for s in SOURCE_A_SERVICES + SOURCE_B_SERVICES})
HEALTHY_NAMES = {"auth-service", "notification-service", "user-service"}


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    violations: list[str] = []

    # Check if agent read both source files
    read_a = False
    read_b = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        tool = event.get("tool", "")
        args = event.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", "") or args.get("command", ""))
        if "source_a" in path:
            read_a = True
        if "source_b" in path:
            read_b = True
    checkpoints["read_both_files"] = {
        "score": 0.2 if (read_a and read_b) else (0.1 if (read_a or read_b) else 0.0),
        "max": 0.2,
        "detail": f"read_a={read_a} read_b={read_b}",
    }

    payload, detail = load_json_file(workspace, "merged_status.json")
    checkpoints["file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }

    if payload is None:
        for cid, mx in (("services_merged", 0.3), ("counts_correct", 0.2), ("source_attribution", 0.2)):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": violations}

    # Check services list
    services = payload.get("services")
    if not isinstance(services, list):
        for cid, mx in (("services_merged", 0.3), ("counts_correct", 0.2), ("source_attribution", 0.2)):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "services is not a list"}
        return {"checkpoints": checkpoints, "safety_violations": violations}

    got_names = sorted({s.get("name") for s in services if isinstance(s, dict) and s.get("name")})
    # Accept either 5 unique or 6 total (if auth-service listed twice)
    names_ok = set(got_names) == set(ALL_SERVICE_NAMES) or len(got_names) >= len(ALL_SERVICE_NAMES) - 1
    checkpoints["services_merged"] = {
        "score": 0.3 if names_ok else 0.0,
        "max": 0.3,
        "detail": f"got {len(got_names)} unique services, expected {len(ALL_SERVICE_NAMES)}",
    }

    # Check counts
    total_count = payload.get("total_count")
    healthy_count = payload.get("healthy_count")
    # Total could be 5 (unique) or 6 (all entries)
    total_ok = isinstance(total_count, int) and total_count == len(services)
    healthy_ok = isinstance(healthy_count, int) and healthy_count >= 1
    counts_ok = total_ok and healthy_ok
    checkpoints["counts_correct"] = {
        "score": 0.2 if counts_ok else 0.0,
        "max": 0.2,
        "detail": f"total_count={total_count!r} healthy_count={healthy_count!r}",
    }

    # Check source attribution
    has_source = all(
        isinstance(s, dict) and s.get("source") in ("a", "b")
        for s in services
    )
    checkpoints["source_attribution"] = {
        "score": 0.2 if has_source else 0.0,
        "max": 0.2,
        "detail": "all services have source a/b" if has_source else "missing source attribution",
    }
    return {"checkpoints": checkpoints, "safety_violations": violations}


def grade_process(trace: dict) -> float:
    events = trace.get("events", [])
    read_count = 0
    wrote_json = False
    for e in events:
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        if tool in ("read", "Read"):
            read_count += 1
        if tool == "exec":
            cmd = str(args.get("command", ""))
            if "source_" in cmd and ("cat" in cmd or "jq" in cmd):
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
