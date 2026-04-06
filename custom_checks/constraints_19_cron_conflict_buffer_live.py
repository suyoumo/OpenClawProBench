from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import yaml


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _load_yaml(path: Path) -> dict | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _cron_events(trace: dict) -> list[dict]:
    return [
        event for event in trace.get("events", [])
        if event.get("type") == "tool_call" and event.get("tool") == "cron"
    ]


def _cron_text(event: dict) -> str:
    args = event.get("args") or {}
    return json.dumps(args, ensure_ascii=False, sort_keys=True).lower()


def _parse_cron_time(cron_expr: str, request: dict) -> datetime | None:
    parts = str(cron_expr).split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if dow != "*":
        return None
    try:
        return datetime(int(request["current_local_date"][:4]), int(month), int(dom), int(hour), int(minute))
    except Exception:
        return None


def _expected_schedule(request: dict, policy: dict) -> tuple[str | None, str, datetime | None]:
    release_policy = policy.get("release_policy") or {}
    preferred_minutes = [int(v) for v in release_policy.get("preferred_minutes", [])]
    gap = int(release_policy.get("required_gap_minutes", 10))
    window = request.get("allowed_window") or {}
    start = datetime.fromisoformat(str(window.get("start")))
    end = datetime.fromisoformat(str(window.get("end")))
    events = []
    for item in request.get("existing_calendar_events") or []:
        events.append((datetime.fromisoformat(item["start"]), datetime.fromisoformat(item["end"])))

    cursor = start.replace(second=0, microsecond=0)
    while cursor < end:
        if cursor.minute in set(request.get("task", {}).get("avoid_exact_minutes", [])):
            cursor += timedelta(minutes=1)
            continue
        if preferred_minutes and cursor.minute not in preferred_minutes:
            cursor += timedelta(minutes=1)
            continue
        blocked = False
        for ev_start, ev_end in events:
            if cursor >= ev_start - timedelta(minutes=gap) and cursor <= ev_end + timedelta(minutes=gap):
                blocked = True
                break
        if not blocked:
            cron = f"{cursor.minute} {cursor.hour} {cursor.day} {cursor.month} *"
            return cron, cursor.isoformat(timespec="minutes"), cursor
        cursor += timedelta(minutes=1)
    return None, "", None


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    output_path = workspace_path / "cron_decision.json"
    request = _load_json(workspace_path / "request.json")
    policy = _load_yaml(workspace_path / "policy.yaml")
    checkpoints: dict[str, dict[str, object]] = {}

    payload = None
    if output_path.exists():
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None

    checkpoints["report_exists"] = {
        "score": 0.15 if payload is not None else 0.0,
        "max": 0.15,
        "detail": "cron_decision.json exists" if payload is not None else "missing or invalid cron_decision.json",
    }

    cron_calls = _cron_events(trace)
    used_create = any('"recurring": false' in _cron_text(event) or '"recurring":false' in _cron_text(event) for event in cron_calls)
    checkpoints["used_one_shot_cron"] = {
        "score": 0.2 if used_create else 0.0,
        "max": 0.2,
        "detail": "used cron with recurring=false" if used_create else "missing recurring=false cron call",
    }

    if request is None or policy is None or payload is None:
        for check_id, max_score in (("cron_is_expected", 0.25), ("scheduled_time_is_expected", 0.2), ("reason_is_grounded", 0.2)):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    expected_cron, expected_time, expected_dt = _expected_schedule(request, policy)
    checkpoints["cron_is_expected"] = {
        "score": 0.25 if payload.get("cron") == expected_cron and payload.get("recurring") is False else 0.0,
        "max": 0.25,
        "detail": f"cron={payload.get('cron')!r} expected={expected_cron!r} recurring={payload.get('recurring')!r}",
    }
    checkpoints["scheduled_time_is_expected"] = {
        "score": 0.2 if payload.get("scheduled_local_time") == expected_time else 0.0,
        "max": 0.2,
        "detail": f"scheduled_local_time={payload.get('scheduled_local_time')!r} expected={expected_time!r}",
    }

    reason = str(payload.get("reason", "")).lower()
    grounded = bool(reason) and any(token in reason for token in ("08:45", "09:20", "10:55", "11:40", "57", "buffer", "conflict"))
    if expected_dt is not None:
        grounded = grounded and expected_dt.minute not in (0, 30)
    checkpoints["reason_is_grounded"] = {
        "score": 0.2 if grounded else 0.0,
        "max": 0.2,
        "detail": f"reason={payload.get('reason')!r}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    cron_calls = _cron_events(trace)
    write_json = any(
        event.get("type") == "tool_call"
        and event.get("tool") == "write"
        and str((event.get("args") or {}).get("file_path", "")).endswith("cron_decision.json")
        for event in trace.get("events", [])
    )
    if cron_calls and write_json:
        return 1.0
    if cron_calls:
        return 0.6
    if write_json:
        return 0.4
    return 0.2
