from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _cron_events(trace: dict) -> list[dict]:
    return [
        event for event in trace.get("events", [])
        if event.get("type") == "tool_call" and event.get("tool") == "cron"
    ]


def _extract_cron_from_trace(trace: dict) -> str:
    for event in _cron_events(trace):
        args = event.get("args") or {}
        cron = args.get("cron")
        if isinstance(cron, str) and cron.strip():
            return cron.strip()
    return ""


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    payload = _load_json(workspace_path / "cron_monitor_plan.json")
    request = _load_json(workspace_path / "request.json")
    checkpoints: dict[str, dict[str, object]] = {}

    checkpoints["report_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": "cron_monitor_plan.json exists" if payload is not None else "missing or invalid cron_monitor_plan.json",
    }

    cron_calls = _cron_events(trace)
    recurring_used = any((event.get("args") or {}).get("recurring") is True for event in cron_calls)
    checkpoints["used_recurring_cron"] = {
        "score": 0.15 if recurring_used else 0.0,
        "max": 0.15,
        "detail": "used recurring cron" if recurring_used else "missing recurring=true cron call",
    }

    if payload is None or request is None:
        for check_id, max_score in (("cron_is_hourly", 0.15), ("minute_choice_is_valid", 0.15), ("rejected_minutes_are_exact", 0.15), ("expiry_notice_is_present", 0.15), ("explanation_is_grounded", 0.15)):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    trace_cron = _extract_cron_from_trace(trace)
    cron_expr = str(payload.get("cron", ""))
    parts = cron_expr.split()
    hourly = len(parts) == 5 and parts[1:] == ["*", "*", "*", "*"]
    checkpoints["cron_is_hourly"] = {
        "score": 0.15 if hourly and payload.get("recurring") is True and cron_expr == trace_cron else 0.0,
        "max": 0.15,
        "detail": f"cron={cron_expr!r} trace_cron={trace_cron!r} recurring={payload.get('recurring')!r}",
    }

    minute_ok = False
    selected_minute = payload.get("selected_minute")
    if parts:
        try:
            minute = int(parts[0])
            minute_ok = minute not in set(request.get("forbidden_minutes", [])) and minute in set(request.get("suggested_minutes", [])) and selected_minute == minute
        except ValueError:
            minute_ok = False
    checkpoints["minute_choice_is_valid"] = {
        "score": 0.15 if minute_ok else 0.0,
        "max": 0.15,
        "detail": f"cron={cron_expr!r} selected_minute={selected_minute!r}",
    }

    checkpoints["rejected_minutes_are_exact"] = {
        "score": 0.15 if payload.get("rejected_minutes") == [0, 30] else 0.0,
        "max": 0.15,
        "detail": f"rejected_minutes={payload.get('rejected_minutes')!r}",
    }

    explanation = str(payload.get("explanation", "")).lower()
    expiry_notice = payload.get("mentions_auto_expire_days") == 7 and "7" in explanation and any(term in explanation for term in ("expire", "过期"))
    checkpoints["expiry_notice_is_present"] = {
        "score": 0.15 if expiry_notice else 0.0,
        "max": 0.15,
        "detail": f"explanation={payload.get('explanation')!r} mentions_auto_expire_days={payload.get('mentions_auto_expire_days')!r}",
    }

    grounded = (
        any(term in explanation for term in (":00", "00", ":30", "30"))
        and any(term in explanation for term in ("peak", "拥挤", "avoid", "避开"))
        and any(str(minute) in explanation for minute in request.get("suggested_minutes", []))
    )
    checkpoints["explanation_is_grounded"] = {
        "score": 0.15 if grounded else 0.0,
        "max": 0.15,
        "detail": f"explanation={payload.get('explanation')!r}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    cron_calls = _cron_events(trace)
    write_json = any(
        event.get("type") == "tool_call"
        and event.get("tool") == "write"
        and str((event.get("args") or {}).get("file_path", "")).endswith("cron_monitor_plan.json")
        for event in trace.get("events", [])
    )
    if cron_calls and write_json:
        return 1.0
    if cron_calls:
        return 0.6
    if write_json:
        return 0.4
    return 0.2
