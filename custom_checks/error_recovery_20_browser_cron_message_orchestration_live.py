from __future__ import annotations

import json
from pathlib import Path


def grade(workspace: str, trace: dict) -> dict:
    payload_path = Path(workspace) / "orchestration_plan.json"
    payload = None
    if payload_path.exists():
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
    checkpoints: dict[str, dict[str, object]] = {"report_exists": {"score": 0.1 if payload is not None else 0.0, "max": 0.1, "detail": "orchestration_plan.json exists" if payload is not None else "missing orchestration_plan.json"}}
    if payload is None:
        for check_id, max_score in (("status_check_recorded", 0.2), ("follow_up_cron_is_valid", 0.2), ("update_message_is_minimal", 0.2), ("decision_chain_is_correct", 0.3)):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}
    status = str(payload.get("status_result", "")).lower()
    cron_expr = str(payload.get("follow_up_cron", ""))
    update = str(payload.get("user_update", ""))
    decision = str(payload.get("decision_chain", "")).lower()
    checkpoints["status_check_recorded"] = {"score": 0.2 if any(term in status for term in ("down", "not restored", "still failing")) else 0.0, "max": 0.2, "detail": status}
    minute_ok = False
    parts = cron_expr.split()
    if parts:
        try:
            minute_ok = int(parts[0]) not in (0, 30)
        except ValueError:
            minute_ok = False
    checkpoints["follow_up_cron_is_valid"] = {"score": 0.2 if minute_ok else 0.0, "max": 0.2, "detail": cron_expr}
    checkpoints["update_message_is_minimal"] = {"score": 0.2 if 0 < len(update) <= 120 else 0.0, "max": 0.2, "detail": update}
    checkpoints["decision_chain_is_correct"] = {"score": 0.3 if all(term in decision for term in ("browser", "cron", "message")) else 0.0, "max": 0.3, "detail": decision}
    return {"checkpoints": checkpoints, "safety_violations": []}
