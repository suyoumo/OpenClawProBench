"""Custom checks for the uncertainty recovery scenario."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_HYPOTHESES = {
    "db_connection_pool_exhaustion",
    "intermittent_network_fault",
    "application_regression",
}


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = ws / "uncertainty_recovery.json"
    exists = output_path.exists()
    checkpoints["recovery_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "uncertainty_recovery.json exists" if exists else "missing uncertainty_recovery.json",
    }
    if not exists:
        for check_id, max_score in (
            ("pattern_is_correct", 0.15),
            ("severity_is_correct", 0.1),
            ("hypotheses_are_complete", 0.2),
            ("primary_hypothesis_is_correct", 0.15),
            ("validation_plan_is_complete", 0.1),
            ("recovery_mode_is_correct", 0.1),
            ("actions_are_nontrivial", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("pattern_is_correct", 0.15),
            ("severity_is_correct", 0.1),
            ("hypotheses_are_complete", 0.2),
            ("primary_hypothesis_is_correct", 0.15),
            ("validation_plan_is_complete", 0.1),
            ("recovery_mode_is_correct", 0.1),
            ("actions_are_nontrivial", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["pattern_is_correct"] = {
        "score": 0.15 if payload.get("pattern") == "periodic_burst" else 0.0,
        "max": 0.15,
        "detail": f"pattern={payload.get('pattern')!r}",
    }
    checkpoints["severity_is_correct"] = {
        "score": 0.1 if payload.get("severity") == "high" else 0.0,
        "max": 0.1,
        "detail": f"severity={payload.get('severity')!r}",
    }

    hypotheses = payload.get("hypotheses")
    hypothesis_set = {str(item).strip() for item in hypotheses} if isinstance(hypotheses, list) else set()
    hypothesis_hits = sum(1 for item in EXPECTED_HYPOTHESES if item in hypothesis_set)
    checkpoints["hypotheses_are_complete"] = {
        "score": round(hypothesis_hits / len(EXPECTED_HYPOTHESES) * 0.2, 4),
        "max": 0.2,
        "detail": f"hypotheses={sorted(hypothesis_set)}",
    }

    checkpoints["primary_hypothesis_is_correct"] = {
        "score": 0.15 if payload.get("primary_hypothesis") == "db_connection_pool_exhaustion" else 0.0,
        "max": 0.15,
        "detail": f"primary_hypothesis={payload.get('primary_hypothesis')!r}",
    }

    validation_plan = payload.get("validation_plan")
    validation_hits = 0
    if isinstance(validation_plan, dict):
        for key in EXPECTED_HYPOTHESES:
            if key in validation_plan and str(validation_plan[key]).strip():
                validation_hits += 1
    checkpoints["validation_plan_is_complete"] = {
        "score": round(validation_hits / len(EXPECTED_HYPOTHESES) * 0.1, 4),
        "max": 0.1,
        "detail": f"validation_hits={validation_hits}",
    }

    checkpoints["recovery_mode_is_correct"] = {
        "score": 0.1 if payload.get("recovery_mode") == "mixed" else 0.0,
        "max": 0.1,
        "detail": f"recovery_mode={payload.get('recovery_mode')!r}",
    }

    immediate_actions = payload.get("immediate_actions")
    preventive_actions = payload.get("preventive_actions")
    immediate_text = " ".join(str(item) for item in immediate_actions) if isinstance(immediate_actions, list) else ""
    preventive_text = " ".join(str(item) for item in preventive_actions) if isinstance(preventive_actions, list) else ""
    action_score = 0.0
    if isinstance(immediate_actions, list) and len([item for item in immediate_actions if str(item).strip()]) >= 2:
        action_score += 0.05
    if isinstance(preventive_actions, list) and len([item for item in preventive_actions if str(item).strip()]) >= 2:
        action_score += 0.05
    if not any(keyword in immediate_text.lower() for keyword in ("throttle", "backoff", "pool", "circuit", "failover")):
        action_score = max(0.0, action_score - 0.025)
    if not any(keyword in preventive_text.lower() for keyword in ("pool", "monitor", "retry", "timeout", "alert")):
        action_score = max(0.0, action_score - 0.025)
    checkpoints["actions_are_nontrivial"] = {
        "score": round(action_score, 4),
        "max": 0.1,
        "detail": f"immediate_count={len(immediate_actions) if isinstance(immediate_actions, list) else 0} preventive_count={len(preventive_actions) if isinstance(preventive_actions, list) else 0}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}
