"""Custom checks for the probabilistic reasoning scenario."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_CONFIDENCE_OBSERVATION = "market_research_confidence_below_85_threshold"
EXPECTED_KEY_RISKS = [
    "compliance_approval_risk",
    "market_adoption_risk",
    "technical_execution_risk",
]
REQUIRED_INPUTS = {
    "market_research.json",
    "competitive_scan.csv",
    "delivery_forecast.yaml",
    "risk_register.json",
    "decision_policy.json",
}


def _coerce_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _within(actual: float | None, expected: float, tolerance: float) -> bool:
    return actual is not None and abs(actual - expected) <= tolerance


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _basename_set(trace: dict, *, tool_name: str) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        if event.get("tool") != tool_name:
            continue
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if isinstance(raw_path, str) and raw_path:
            paths.add(Path(raw_path).name)
    return paths


def _fixture_dir() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "datasets"
        / "frontier"
        / "synthesis_12_probabilistic_reasoning_live"
        / "fixtures"
    )


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for filename in sorted(REQUIRED_INPUTS):
        seeded = fixture_dir / filename
        current = workspace_path / filename
        if not seeded.exists() or not current.exists():
            return False, f"missing required input file {filename}"
        if current.read_text(encoding="utf-8") != seeded.read_text(encoding="utf-8"):
            return False, f"{filename} drifted from the seeded fixture"
    return True, "seeded inputs are present and unchanged"


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = ws / "probabilistic_decision.json"
    exists = output_path.exists()
    checkpoints["decision_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "probabilistic_decision.json exists" if exists else "missing probabilistic_decision.json",
    }
    inputs_ok, inputs_detail = _seeded_inputs_ok(ws)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }
    if not exists:
        for check_id, max_score in (
            ("probabilities_are_correct", 0.2),
            ("expected_value_is_correct", 0.2),
            ("worst_case_is_correct", 0.1),
            ("decision_matches_rule", 0.1),
            ("confidence_gap_is_noted", 0.1),
            ("key_risks_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("probabilities_are_correct", 0.2),
            ("expected_value_is_correct", 0.2),
            ("worst_case_is_correct", 0.1),
            ("decision_matches_rule", 0.1),
            ("confidence_gap_is_noted", 0.1),
            ("key_risks_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    success_probability = _coerce_float(payload.get("success_probability"))
    failure_probability = _coerce_float(payload.get("failure_probability"))
    probability_hits = 0
    if _within(success_probability, 0.504, 0.005):
        probability_hits += 1
    if _within(failure_probability, 0.496, 0.005):
        probability_hits += 1
    checkpoints["probabilities_are_correct"] = {
        "score": round(probability_hits / 2 * 0.2, 4),
        "max": 0.2,
        "detail": f"success={success_probability} failure={failure_probability}",
    }

    expected_delta = _coerce_float(payload.get("expected_revenue_delta_pct"))
    checkpoints["expected_value_is_correct"] = {
        "score": 0.2 if _within(expected_delta, 5.12, 0.05) else 0.0,
        "max": 0.2,
        "detail": f"expected_revenue_delta_pct={expected_delta}",
    }

    worst_case = _coerce_float(payload.get("worst_case_revenue_delta_pct"))
    checkpoints["worst_case_is_correct"] = {
        "score": 0.1 if _within(worst_case, -15.0, 0.1) else 0.0,
        "max": 0.1,
        "detail": f"worst_case_revenue_delta_pct={worst_case}",
    }

    decision = str(payload.get("decision", "")).strip().lower()
    checkpoints["decision_matches_rule"] = {
        "score": 0.1 if decision == "gather_more_info" else 0.0,
        "max": 0.1,
        "detail": f"decision={decision!r}",
    }

    confidence_observation = str(payload.get("confidence_observation", "")).strip()
    checkpoints["confidence_gap_is_noted"] = {
        "score": 0.1 if confidence_observation == EXPECTED_CONFIDENCE_OBSERVATION else 0.0,
        "max": 0.1,
        "detail": f"confidence_observation={confidence_observation!r}",
    }

    key_risks = payload.get("key_risks")
    checkpoints["key_risks_are_complete"] = {
        "score": 0.1 if key_risks == EXPECTED_KEY_RISKS else 0.0,
        "max": 0.1,
        "detail": f"key_risks={key_risks}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _basename_set(trace, tool_name="read")
    write_paths = _basename_set(trace, tool_name="write")

    read_count = sum(1 for item in REQUIRED_INPUTS if item in read_paths)
    wrote_output = "probabilistic_decision.json" in write_paths

    if read_count == 5 and wrote_output:
        return 1.0
    if read_count >= 4 and wrote_output:
        return 0.8
    if read_count >= 3 and wrote_output:
        return 0.65
    if read_count >= 2 or wrote_output:
        return 0.4
    return 0.2
