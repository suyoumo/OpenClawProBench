"""Grounded scoring for planning_08_uncertainty_reasoning_live."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


EXPECTED_BLOCKED_OPTIONS = [
    {
        "option": "full_launch_q4",
        "reason_codes": [
            "full_scale_not_ready",
            "market_confidence_below_threshold",
            "finance_confidence_below_threshold",
            "parallel_high_risk_limit_reached",
        ],
    },
    {
        "option": "defer_to_q1",
        "reason_codes": [
            "violates_q4_release_requirement",
        ],
    },
]

EXPECTED_UNCERTAINTY_REGISTER = [
    {"factor": "market_demand_confidence", "value": 0.78, "level": "medium"},
    {"factor": "engineering_on_time_probability", "value": 0.72, "level": "high"},
    {"factor": "finance_forecast_confidence", "value": 0.74, "level": "high"},
    {"factor": "support_readiness_score", "value": 0.62, "level": "high"},
]

EXPECTED_SCENARIO_ESTIMATES = {
    "full_launch_q4": {
        "best_case_net_usd": 980000,
        "base_case_net_usd": 130000,
        "worst_case_net_usd": -1170000,
    },
    "pilot_launch_q4": {
        "best_case_net_usd": 420000,
        "base_case_net_usd": 40000,
        "worst_case_net_usd": -370000,
    },
    "defer_to_q1": {
        "best_case_net_usd": 0,
        "base_case_net_usd": 0,
        "worst_case_net_usd": 0,
    },
}

EXPECTED_NEXT_ACTIONS = [
    "run_q4_pilot_with_14_beta_customers",
    "finish_support_playbook_before_pilot_enablement",
    "reassess_full_launch_after_payments_migration_and_confidence_refresh",
]

EXPECTED_EVIDENCE_REFS = {
    "market_research.json",
    "engineering_readiness.json",
    "finance_bounds.json",
    "decision_rules.yaml",
    "support_readiness.json",
}

BLOCK_REASON_ALIAS_MAP = {
    "full_launch_q4": {
        "full_scale_not_ready": "full_scale_not_ready",
        "market_confidence_below_threshold": "market_confidence_below_threshold",
        "finance_confidence_below_threshold": "finance_confidence_below_threshold",
        "parallel_high_risk_limit_reached": "parallel_high_risk_limit_reached",
        "high_risk_capacity_reached": "parallel_high_risk_limit_reached",
    },
    "defer_to_q1": {
        "violates_q4_release_requirement": "violates_q4_release_requirement",
    },
}


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _normalize_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    for expected in EXPECTED_EVIDENCE_REFS:
        if normalized.endswith(expected):
            return expected
    if normalized.endswith("launch_decision.json"):
        return "launch_decision.json"
    return normalized


def _observed_reads(trace: dict) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        tool = event.get("tool")
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if tool in ("read", "Read") and isinstance(raw_path, str) and raw_path:
            paths.add(_normalize_path(raw_path))
        if tool in ("exec", "Exec"):
            command = str(args.get("command", ""))
            for expected in EXPECTED_EVIDENCE_REFS:
                if expected in command:
                    paths.add(expected)
    return paths


def _observed_writes(trace: dict) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        tool = event.get("tool")
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if tool in ("write", "Write") and isinstance(raw_path, str) and raw_path:
            paths.add(_normalize_path(raw_path))
        if tool in ("exec", "Exec") and "launch_decision.json" in str(args.get("command", "")):
            paths.add("launch_decision.json")
    return paths


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "planning_08_uncertainty_reasoning" / "fixtures"


def _decision_rules() -> dict:
    return yaml.safe_load((_fixture_dir() / "decision_rules.yaml").read_text(encoding="utf-8"))


def _normalize_blocked_options(blocked_options: object) -> object:
    if not isinstance(blocked_options, list):
        return blocked_options

    normalized: list[dict[str, object]] = []
    for item in blocked_options:
        if not isinstance(item, dict):
            return blocked_options
        option = item.get("option")
        reason_codes = item.get("reason_codes")
        if not isinstance(option, str) or not isinstance(reason_codes, list):
            return blocked_options
        alias_map = BLOCK_REASON_ALIAS_MAP.get(option, {})
        normalized_reason_codes: list[str] = []
        for reason in reason_codes:
            if not isinstance(reason, str):
                return blocked_options
            normalized_reason_codes.append(alias_map.get(reason, reason))
        normalized.append({"option": option, "reason_codes": normalized_reason_codes})
    return normalized


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for relative in sorted(EXPECTED_EVIDENCE_REFS):
        seeded = fixture_dir / relative
        current = workspace_path / relative
        if not seeded.exists() or not current.exists():
            return False, f"missing required input file {relative}"
        if current.read_text(encoding="utf-8") != seeded.read_text(encoding="utf-8"):
            return False, f"{relative} drifted from the seeded fixture"
    return True, "seeded inputs are present and unchanged"


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}
    decision_rules = _decision_rules()
    expected_next_actions = decision_rules.get("next_action_codes", EXPECTED_NEXT_ACTIONS)

    output_path = workspace_path / "launch_decision.json"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.1 if output_exists else 0.0,
        "max": 0.1,
        "detail": "launch_decision.json exists" if output_exists else "missing launch_decision.json",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        for check_id, max_score in (
            ("recommendation_is_correct", 0.1),
            ("blocked_options_are_exact", 0.15),
            ("uncertainty_register_is_exact", 0.15),
            ("scenario_estimates_are_exact", 0.15),
            ("next_actions_are_exact", 0.15),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("recommendation_is_correct", 0.1),
            ("blocked_options_are_exact", 0.15),
            ("uncertainty_register_is_exact", 0.15),
            ("scenario_estimates_are_exact", 0.15),
            ("next_actions_are_exact", 0.15),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["recommendation_is_correct"] = {
        "score": 0.1 if payload.get("recommendation") == "pilot_launch_q4" else 0.0,
        "max": 0.1,
        "detail": f"recommendation={payload.get('recommendation')!r}",
    }
    normalized_blocked_options = _normalize_blocked_options(payload.get("blocked_options"))
    checkpoints["blocked_options_are_exact"] = {
        "score": 0.15 if normalized_blocked_options == EXPECTED_BLOCKED_OPTIONS else 0.0,
        "max": 0.15,
        "detail": f"blocked_options={payload.get('blocked_options')}",
    }
    checkpoints["uncertainty_register_is_exact"] = {
        "score": 0.15 if payload.get("uncertainty_register") == EXPECTED_UNCERTAINTY_REGISTER else 0.0,
        "max": 0.15,
        "detail": f"uncertainty_register={payload.get('uncertainty_register')}",
    }
    checkpoints["scenario_estimates_are_exact"] = {
        "score": 0.15 if payload.get("scenario_estimates") == EXPECTED_SCENARIO_ESTIMATES else 0.0,
        "max": 0.15,
        "detail": f"scenario_estimates={payload.get('scenario_estimates')}",
    }
    checkpoints["next_actions_are_exact"] = {
        "score": 0.15 if payload.get("next_actions") == expected_next_actions else 0.0,
        "max": 0.15,
        "detail": f"next_actions={payload.get('next_actions')}",
    }

    evidence_refs = payload.get("evidence_refs")
    evidence_set = set(evidence_refs) if isinstance(evidence_refs, list) else set()
    checkpoints["evidence_refs_are_complete"] = {
        "score": 0.1 if evidence_set == EXPECTED_EVIDENCE_REFS and len(evidence_refs) == 5 else 0.0,
        "max": 0.1,
        "detail": f"evidence_refs={evidence_refs}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _observed_reads(trace)
    write_paths = _observed_writes(trace)

    read_count = sum(1 for item in EXPECTED_EVIDENCE_REFS if item in read_paths)
    wrote_output = "launch_decision.json" in write_paths

    if read_count == 5 and wrote_output:
        return 1.0
    if read_count >= 4 and wrote_output:
        return 0.85
    if read_count >= 3 and wrote_output:
        return 0.7
    if read_count >= 2 and wrote_output:
        return 0.55
    if read_count >= 2 or wrote_output:
        return 0.35
    return 0.2
