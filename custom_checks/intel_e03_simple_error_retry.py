"""E3: 简单错误重试 — 评分脚本"""

from __future__ import annotations

from harness.openclaw_native import (
    load_json_file,
    trace_used_openclaw_exec,
)


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    violations: list[str] = []

    # Check if agent read task.json
    read_task = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        tool = event.get("tool", "")
        args = event.get("args") or {}
        if tool in ("read", "Read"):
            path = str(args.get("path", "") or args.get("file_path", ""))
            if "task.json" in path:
                read_task = True
        if tool == "exec":
            cmd = str(args.get("command", ""))
            if "task.json" in cmd and ("cat" in cmd or "jq" in cmd):
                read_task = True
    checkpoints["read_task"] = {
        "score": 0.15 if read_task else 0.0,
        "max": 0.15,
        "detail": "read task.json" if read_task else "did not read task.json",
    }

    used_cli = trace_used_openclaw_exec(trace, "openclaw", "skills", "list")
    checkpoints["used_cli"] = {
        "score": 0.2 if used_cli else 0.0,
        "max": 0.2,
        "detail": "used openclaw skills list" if used_cli else "missing cli call",
    }

    payload, detail = load_json_file(workspace, "result.json")
    checkpoints["file_exists"] = {
        "score": 0.15 if payload is not None else 0.0,
        "max": 0.15,
        "detail": detail,
    }

    if payload is None:
        checkpoints["status_correct"] = {"score": 0.0, "max": 0.25, "detail": "skipped"}
        checkpoints["data_present"] = {"score": 0.0, "max": 0.25, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": violations}

    status = payload.get("status")
    attempts = payload.get("attempts")
    status_ok = status in ("success", "failed") and isinstance(attempts, int) and attempts >= 1
    checkpoints["status_correct"] = {
        "score": 0.25 if status_ok else 0.0,
        "max": 0.25,
        "detail": f"status={status!r} attempts={attempts!r}",
    }

    data = payload.get("data")
    data_ok = isinstance(data, dict) and len(data) > 0
    checkpoints["data_present"] = {
        "score": 0.25 if data_ok else 0.0,
        "max": 0.25,
        "detail": f"data has {len(data) if isinstance(data, dict) else 0} keys",
    }
    return {"checkpoints": checkpoints, "safety_violations": violations}


def grade_process(trace: dict) -> float:
    events = trace.get("events", [])
    read_file = False
    used_cli = False
    wrote_file = False
    for e in events:
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        if tool in ("read", "Read"):
            read_file = True
        if tool == "exec" and "openclaw" in str(args.get("command", "")):
            used_cli = True
        if tool == "write":
            wrote_file = True
    if read_file and used_cli and wrote_file:
        return 1.0
    if used_cli and wrote_file:
        return 0.8
    if used_cli:
        return 0.5
    return 0.2
