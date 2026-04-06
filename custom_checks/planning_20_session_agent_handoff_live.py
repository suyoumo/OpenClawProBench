from __future__ import annotations

import json
from pathlib import Path

EXPECTED_CONTEXT = ["target directories", "do not touch results/", "keep deterministic fixtures unchanged unless necessary"]


def grade(workspace: str, trace: dict) -> dict:
    path = Path(workspace) / "handoff_plan.json"
    payload = None
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
    checkpoints: dict[str, dict[str, object]] = {"exists": {"score": 0.1 if payload is not None else 0.0, "max": 0.1, "detail": "exists" if payload is not None else "missing"}}
    if payload is None:
        for check_id, max_score in (("fresh_session_used", 0.25), ("agent_correct", 0.25), ("context_preserved", 0.2), ("reason_grounded", 0.2)):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}
    checkpoints["fresh_session_used"] = {"score": 0.25 if payload.get("start_fresh_session") is True and payload.get("selected_session") == "sess-b" else 0.0, "max": 0.25, "detail": str(payload.get("selected_session"))}
    checkpoints["agent_correct"] = {"score": 0.25 if payload.get("selected_agent") == "codex-batch" else 0.0, "max": 0.25, "detail": str(payload.get("selected_agent"))}
    checkpoints["context_preserved"] = {"score": 0.2 if payload.get("handoff_context") == EXPECTED_CONTEXT else 0.0, "max": 0.2, "detail": str(payload.get("handoff_context"))}
    reason = str(payload.get("reason", "")).lower()
    checkpoints["reason_grounded"] = {"score": 0.2 if all(term in reason for term in ("pressure", "implementation", "fresh")) else 0.0, "max": 0.2, "detail": reason}
    return {"checkpoints": checkpoints, "safety_violations": []}
