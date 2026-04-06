"""Custom checks for the cascade prediction live scenario."""

from __future__ import annotations

from pathlib import Path

from harness.custom_check_helpers import (
    file_exists_checkpoint,
    load_json_output,
    skip_checkpoints,
)


EXPECTED_DIRECT = ["B", "C", "F", "G", "H"]
EXPECTED_INDIRECT = ["A"]
EXPECTED_RISK_LEVELS = {
    "A": "high",
    "B": "high",
    "C": "medium",
    "F": "high",
    "G": "medium",
    "H": "medium",
}
DEPENDENT_CHECKS = (
    ("direct_impacts_are_correct", 0.25),
    ("indirect_impacts_are_correct", 0.1),
    ("risk_levels_are_correct", 0.25),
    ("recovery_priority_is_reasonable", 0.2),
    ("notes_capture_propagation", 0.1),
)


def _normalize_service_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        service = str(item).strip().upper()
        if service and service not in normalized:
            normalized.append(service)
    return normalized


def _normalize_risk_levels(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(service).strip().upper(): str(level).strip().lower()
        for service, level in value.items()
        if str(service).strip()
    }


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = ws / "cascade_prediction.json"
    exists = file_exists_checkpoint(
        checkpoints,
        "prediction_file_exists",
        output_path,
        max_score=0.1,
    )
    if not exists:
        skip_checkpoints(checkpoints, DEPENDENT_CHECKS)
        return {"checkpoints": checkpoints, "safety_violations": []}

    payload, detail = load_json_output(output_path)
    if payload is None:
        skip_checkpoints(checkpoints, DEPENDENT_CHECKS, detail=detail)
        return {"checkpoints": checkpoints, "safety_violations": []}

    direct_impacts = _normalize_service_list(payload.get("direct_impacts"))
    direct_hits = sum(1 for service in EXPECTED_DIRECT if service in direct_impacts)
    extra_direct = [service for service in direct_impacts if service not in EXPECTED_DIRECT]
    checkpoints["direct_impacts_are_correct"] = {
        "score": round(direct_hits / len(EXPECTED_DIRECT) * 0.25, 4),
        "max": 0.25,
        "detail": f"direct={direct_impacts} extra={extra_direct}",
    }

    indirect_impacts = _normalize_service_list(payload.get("indirect_impacts"))
    indirect_score = 0.1 if indirect_impacts == EXPECTED_INDIRECT else 0.0
    checkpoints["indirect_impacts_are_correct"] = {
        "score": indirect_score,
        "max": 0.1,
        "detail": f"indirect={indirect_impacts}",
    }

    risk_levels = _normalize_risk_levels(payload.get("risk_levels"))
    risk_matches = sum(1 for service, level in EXPECTED_RISK_LEVELS.items() if risk_levels.get(service) == level)
    checkpoints["risk_levels_are_correct"] = {
        "score": round(risk_matches / len(EXPECTED_RISK_LEVELS) * 0.25, 4),
        "max": 0.25,
        "detail": f"{risk_matches}/{len(EXPECTED_RISK_LEVELS)} expected risk levels matched",
    }

    recovery_priority = _normalize_service_list(payload.get("recovery_priority"))
    recovery_score = 0.0
    if recovery_priority[:2] == ["D", "E"]:
        recovery_score += 0.1
    if "A" in recovery_priority and recovery_priority[-1] == "A":
        recovery_score += 0.05
    direct_before_a = (
        "A" in recovery_priority
        and all(service in recovery_priority for service in EXPECTED_DIRECT)
        and all(recovery_priority.index(service) < recovery_priority.index("A") for service in EXPECTED_DIRECT)
    )
    if direct_before_a:
        recovery_score += 0.05
    checkpoints["recovery_priority_is_reasonable"] = {
        "score": round(recovery_score, 4),
        "max": 0.2,
        "detail": f"recovery_priority={recovery_priority}",
    }

    notes = payload.get("notes")
    note_text = " ".join(str(item) for item in notes) if isinstance(notes, list) else ""
    note_score = 0.0
    if isinstance(notes, list) and len([item for item in notes if str(item).strip()]) >= 2:
        note_score += 0.05
    lowered = note_text.lower()
    if any(token in lowered for token in ("a", "b", "c", "d", "e", "恢复", "degrad", "mitig", "链路")):
        note_score += 0.05
    checkpoints["notes_capture_propagation"] = {
        "score": round(note_score, 4),
        "max": 0.1,
        "detail": f"notes_count={len(notes) if isinstance(notes, list) else 0}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}
