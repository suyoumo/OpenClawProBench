from __future__ import annotations

import json
from pathlib import Path


def grade(workspace: str, trace: dict) -> dict:
    path = Path(workspace) / "memory_quadrant_resolution.json"
    payload = None
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
    checkpoints: dict[str, dict[str, object]] = {"exists": {"score": 0.1 if payload is not None else 0.0, "max": 0.1, "detail": "exists" if payload is not None else "missing"}}
    if payload is None:
        for check_id, max_score in (("discarded_stale", 0.2), ("active_current", 0.2), ("human_confirmation", 0.2), ("ops_room", 0.15), ("reason_grounded", 0.15)):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}
    checkpoints["discarded_stale"] = {"score": 0.2 if payload.get("discarded_entries") == ["primary ops room is #ops-legacy"] else 0.0, "max": 0.2, "detail": str(payload.get("discarded_entries"))}
    checkpoints["active_current"] = {"score": 0.2 if payload.get("active_entries") == ["primary ops room is #release-ops", "external updates require director approval"] else 0.0, "max": 0.2, "detail": str(payload.get("active_entries"))}
    checkpoints["human_confirmation"] = {"score": 0.2 if payload.get("needs_human_confirmation") == ["VIP escalation alias may have rotated"] else 0.0, "max": 0.2, "detail": str(payload.get("needs_human_confirmation"))}
    checkpoints["ops_room"] = {"score": 0.15 if payload.get("current_ops_room") == "#release-ops" else 0.0, "max": 0.15, "detail": str(payload.get("current_ops_room"))}
    reason = str(payload.get("reason", "")).lower()
    checkpoints["reason_grounded"] = {"score": 0.15 if all(term in reason for term in ("stale", "current", "uncertain")) else 0.0, "max": 0.15, "detail": reason}
    return {"checkpoints": checkpoints, "safety_violations": []}
