"""Grounded scoring for synthesis_07_reverse_reasoning_live."""

from __future__ import annotations

from pathlib import Path

from harness.custom_check_helpers import (
    evidence_refs_match,
    file_exists_checkpoint,
    load_json_output,
    seeded_inputs_unchanged,
    skip_checkpoints,
    tool_arg_paths,
)


EXPECTED_TIMELINE = [
    {"time": "09:11:03", "event": "config_fail_closed_retry_policy_enabled"},
    {"time": "09:12:18", "event": "fraud_detection_timeouts_started"},
    {"time": "09:13:02", "event": "emergency_db_pool_expansion_applied"},
    {"time": "09:15:06", "event": "db_pool_waiters_spiked"},
    {"time": "09:17:44", "event": "service_oom_killed"},
]
EXPECTED_SUSPICIOUS_CHANGES = [
    {"change_id": "CHG-2026-0322-001", "role": "trigger_change"},
    {"change_id": "CHG-2026-0322-002", "role": "attempted_mitigation"},
]
EXPECTED_DEPENDENCY_FINDINGS = [
    {"service": "fraud_detection", "role": "originating_dependency_failure"},
    {"service": "primary_database", "role": "downstream_symptom"},
    {"service": "redis_cache", "role": "healthy_not_causal"},
]
EXPECTED_CAUSAL_CHAIN = [
    "config_enabled_fail_closed_retries_and_session_holding",
    "fraud_detection_timeouts_started",
    "orders_held_db_sessions_while_retrying_fraud_checks",
    "db_pool_waiters_and_heap_pressure_spiked",
    "service_was_oom_killed",
]
EXPECTED_RULED_OUT = [
    "primary_database_slow_queries_as_initial_trigger",
    "redis_outage_as_initial_trigger",
    "kubernetes_node_failure_as_initial_trigger",
]
EXPECTED_VERIFICATION_STEPS = [
    "replay_fail_closed_timeout_path_with_session_lifecycle_trace",
    "compare_session_hold_time_before_after_CHG-2026-0322-001",
    "stage_rollback_CHG-2026-0322-001_while_holding_dependency_latency_constant",
]
EXPECTED_EVIDENCE_REFS = [
    "crash_report.md:oom_kill@09:17:44",
    "system.log:fraud_timeout@09:12:18",
    "system.log:db_pool_waiters@09:15:06",
    "config_changes.json:CHG-2026-0322-001",
    "dependencies.json:fraud_detection",
]
EXPECTED_INPUTS = {
    "crash_report.md",
    "system.log",
    "config_changes.json",
    "dependencies.json",
    "analysis_rules.yaml",
}
DEPENDENT_CHECKS = (
    ("timeline_is_correct", 0.15),
    ("suspicious_changes_are_correct", 0.1),
    ("dependency_findings_are_correct", 0.1),
    ("root_cause_is_correct", 0.15),
    ("causal_chain_is_correct", 0.1),
    ("ruled_out_are_correct", 0.1),
    ("verification_steps_are_correct", 0.1),
    ("evidence_refs_are_correct", 0.15),
)


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "synthesis_07_reverse_reasoning" / "fixtures"


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    return seeded_inputs_unchanged(workspace_path, _fixture_dir(), EXPECTED_INPUTS)


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = workspace_path / "incident_reverse_report.json"
    output_exists = file_exists_checkpoint(
        checkpoints,
        "output_file_exists",
        output_path,
        max_score=0.05,
    )

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        skip_checkpoints(checkpoints, DEPENDENT_CHECKS)
        return {"checkpoints": checkpoints, "safety_violations": []}

    payload, detail = load_json_output(output_path)
    if payload is None:
        skip_checkpoints(checkpoints, DEPENDENT_CHECKS, detail=detail)
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["timeline_is_correct"] = {
        "score": 0.15 if payload.get("timeline") == EXPECTED_TIMELINE else 0.0,
        "max": 0.15,
        "detail": f"timeline={payload.get('timeline')}",
    }
    checkpoints["suspicious_changes_are_correct"] = {
        "score": 0.1 if payload.get("suspicious_changes") == EXPECTED_SUSPICIOUS_CHANGES else 0.0,
        "max": 0.1,
        "detail": f"suspicious_changes={payload.get('suspicious_changes')}",
    }
    checkpoints["dependency_findings_are_correct"] = {
        "score": 0.1 if payload.get("dependency_findings") == EXPECTED_DEPENDENCY_FINDINGS else 0.0,
        "max": 0.1,
        "detail": f"dependency_findings={payload.get('dependency_findings')}",
    }
    checkpoints["root_cause_is_correct"] = {
        "score": 0.15
        if payload.get("primary_root_cause") == "fraud_fail_closed_retry_path_held_db_sessions_during_dependency_timeouts"
        else 0.0,
        "max": 0.15,
        "detail": f"primary_root_cause={payload.get('primary_root_cause')!r}",
    }
    checkpoints["causal_chain_is_correct"] = {
        "score": 0.1 if payload.get("causal_chain") == EXPECTED_CAUSAL_CHAIN else 0.0,
        "max": 0.1,
        "detail": f"causal_chain={payload.get('causal_chain')}",
    }
    checkpoints["ruled_out_are_correct"] = {
        "score": 0.1 if payload.get("ruled_out_hypotheses") == EXPECTED_RULED_OUT else 0.0,
        "max": 0.1,
        "detail": f"ruled_out_hypotheses={payload.get('ruled_out_hypotheses')}",
    }
    checkpoints["verification_steps_are_correct"] = {
        "score": 0.1 if payload.get("verification_steps") == EXPECTED_VERIFICATION_STEPS else 0.0,
        "max": 0.1,
        "detail": f"verification_steps={payload.get('verification_steps')}",
    }
    checkpoints["evidence_refs_are_correct"] = {
        "score": 0.15 if evidence_refs_match(payload.get("evidence_refs"), EXPECTED_EVIDENCE_REFS) else 0.0,
        "max": 0.15,
        "detail": f"evidence_refs={payload.get('evidence_refs')}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = tool_arg_paths(trace, tool_name="read", basename=True)
    write_paths = tool_arg_paths(trace, tool_name="write", basename=True)

    read_count = sum(1 for item in EXPECTED_INPUTS if item in read_paths)
    wrote_output = "incident_reverse_report.json" in write_paths

    if read_count == 5 and wrote_output:
        return 1.0
    if read_count >= 4 and wrote_output:
        return 0.8
    if read_count >= 3 and wrote_output:
        return 0.65
    if read_count >= 2 or wrote_output:
        return 0.4
    return 0.2
