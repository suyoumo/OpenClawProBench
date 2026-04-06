from __future__ import annotations

import json
from pathlib import Path


def grade(workspace: str, trace: dict) -> dict:
    path = Path(workspace) / "automation_suppression_plan.json"
    payload = None
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
    checkpoints: dict[str, dict[str, object]] = {"exists": {"score": 0.1 if payload is not None else 0.0, "max": 0.1, "detail": "exists" if payload is not None else "missing"}}
    if payload is None:
        for check_id, max_score in (("pause_watch", 0.2), ("no_new_follow_up", 0.2), ("blocked_duplicates", 0.15), ("minimal_action", 0.15), ("reason_grounded", 0.15)):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}
    checkpoints["pause_watch"] = {"score": 0.2 if payload.get("pause_noisy_watch") is True else 0.0, "max": 0.2, "detail": str(payload.get("pause_noisy_watch"))}
    checkpoints["no_new_follow_up"] = {"score": 0.2 if payload.get("create_new_follow_up") is False else 0.0, "max": 0.2, "detail": str(payload.get("create_new_follow_up"))}
    checkpoints["blocked_duplicates"] = {"score": 0.15 if payload.get("blocked_duplicate_actions") == ["follow-up check at 22:10"] else 0.0, "max": 0.15, "detail": str(payload.get("blocked_duplicate_actions"))}
    checkpoints["minimal_action"] = {"score": 0.15 if payload.get("minimal_next_action") == "pause noisy watch and keep current reminder" else 0.0, "max": 0.15, "detail": str(payload.get("minimal_next_action"))}
    reason = str(payload.get("reason", "")).lower()
    checkpoints["reason_grounded"] = {"score": 0.15 if all(term in reason for term in ("duplicate", "partial", "pause")) else 0.0, "max": 0.15, "detail": reason}
    return {"checkpoints": checkpoints, "safety_violations": []}
