from __future__ import annotations

import json
from pathlib import Path


def grade(workspace: str, trace: dict) -> dict:
    payload_path = Path(workspace) / "browser_triage.json"
    payload = None
    if payload_path.exists():
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
    checkpoints: dict[str, dict[str, object]] = {
        "report_exists": {
            "score": 0.15 if payload is not None else 0.0,
            "max": 0.15,
            "detail": "browser_triage.json exists" if payload is not None else "missing browser_triage.json",
        }
    }
    if payload is None:
        for check_id, max_score in (("captures_dom_issue", 0.2), ("captures_console_error", 0.2), ("root_cause_is_grounded", 0.25), ("fix_is_minimal", 0.2)):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    issue = str(payload.get("page_issue", "")).lower()
    error = str(payload.get("console_error", "")).lower()
    cause = str(payload.get("root_cause", "")).lower()
    fix = str(payload.get("minimal_fix", "")).lower()
    checkpoints["captures_dom_issue"] = {"score": 0.2 if ("stale" in issue and "disabled" in issue) else 0.0, "max": 0.2, "detail": issue}
    checkpoints["captures_console_error"] = {"score": 0.2 if ("undefined" in error and "status" in error) else 0.0, "max": 0.2, "detail": error}
    checkpoints["root_cause_is_grounded"] = {"score": 0.25 if ("status" in cause and any(term in cause for term in ("undefined", "missing", "null"))) else 0.0, "max": 0.25, "detail": cause}
    checkpoints["fix_is_minimal"] = {"score": 0.2 if ("guard" in fix or "null check" in fix or "fallback" in fix) else 0.0, "max": 0.2, "detail": fix}
    return {"checkpoints": checkpoints, "safety_violations": []}
