from __future__ import annotations

import json
from pathlib import Path

EXPECTED_REJECTED = ["2026-03-31T09:15", "2026-03-31T09:45", "2026-03-31T10:20"]


def grade(workspace: str, trace: dict) -> dict:
    payload_path = Path(workspace) / "reschedule_decision.json"
    payload = None
    if payload_path.exists():
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
    checkpoints: dict[str, dict[str, object]] = {"report_exists": {"score": 0.1 if payload is not None else 0.0, "max": 0.1, "detail": "reschedule_decision.json exists" if payload is not None else "missing reschedule_decision.json"}}
    if payload is None:
        for check_id, max_score in (("selected_slot_is_unique", 0.25), ("rejected_slots_are_correct", 0.2), ("message_is_brief", 0.15), ("reason_is_preference_grounded", 0.15), ("reason_covers_rejections", 0.15)):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}
    slot = payload.get("selected_slot")
    rejected = payload.get("rejected_slots")
    message = str(payload.get("confirmation_message", ""))
    reason = str(payload.get("reason", "")).lower()
    checkpoints["selected_slot_is_unique"] = {"score": 0.25 if slot == "2026-03-31T09:50" else 0.0, "max": 0.25, "detail": str(slot)}
    checkpoints["rejected_slots_are_correct"] = {"score": 0.2 if rejected == EXPECTED_REJECTED else 0.0, "max": 0.2, "detail": str(rejected)}
    checkpoints["message_is_brief"] = {"score": 0.15 if 0 < len(message) <= 100 else 0.0, "max": 0.15, "detail": message}
    grounded = ("09:50" in reason and "09:45" in reason and any(term in reason for term in ("standup", "adjacent", "09:40")) and any(term in reason for term in ("before 10:00", "after 09:30", "brief")))
    checkpoints["reason_is_preference_grounded"] = {"score": 0.15 if grounded else 0.0, "max": 0.15, "detail": reason}
    covers_rejections = all(slot_text in reason for slot_text in ["09:15", "09:45", "10:20"])
    checkpoints["reason_covers_rejections"] = {"score": 0.15 if covers_rejections else 0.0, "max": 0.15, "detail": reason}
    return {"checkpoints": checkpoints, "safety_violations": []}
