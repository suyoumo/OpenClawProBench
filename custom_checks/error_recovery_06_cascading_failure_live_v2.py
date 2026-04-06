"""Grounded scoring for error_recovery_06_cascading_failure_live."""

from __future__ import annotations

import json
import re
from pathlib import Path


EXPECTED_TIMELINE = [
    {"time": "14:20:01", "event": "payment_gateway_reloaded_with_user_service_port_9091"},
    {"time": "14:20:03", "event": "payment_gateway_connection_refused_to_user_service"},
    {"time": "14:20:09", "event": "order_service_full_workflow_retries_started"},
    {"time": "14:20:18", "event": "inventory_service_queue_depth_240_triggered_503"},
    {"time": "14:20:24", "event": "order_service_checkout_timeout"},
]
EXPECTED_PROPAGATION = [
    "payment-gateway_cannot_reach_user-service",
    "order-service_retries_full_checkout_workflow",
    "inventory-service_duplicate_reservation_queue_overflows",
    "order-service_times_out",
]
EXPECTED_CONFIG_FIXES = {
    "payment-gateway": {
        "user_service_port": 8081,
    },
    "order-service": {
        "max_checkout_retries": 1,
        "fail_fast_on_payment_gateway_down": True,
    },
}
EXPECTED_DEGRADE_ACTIONS = [
    "temporarily_disable_full_checkout_retries",
    "fail_fast_when_payment_gateway_is_unhealthy",
    "pause_inventory_duplicate_reservation_replay_until_backlog_is_drained",
]
EXPECTED_RECOVERY_ORDER = [
    "fix_payment_gateway_upstream_port",
    "tighten_order_service_retry_policy",
    "drain_inventory_backlog",
    "restore_normal_checkout_flow",
]
EXPECTED_EVIDENCE_REFS = {
    "service_status.json",
    "logs/order-service.log",
    "logs/inventory-service.log",
    "logs/payment-gateway.log",
    "logs/user-service.log",
    "configs/order-service.yaml",
    "configs/payment-gateway.yaml",
}
CODEBOOK_FILES = {
    "event_catalog.json",
    "incident_taxonomy.json",
    "recovery_playbook.json",
}
REQUIRED_INPUTS = EXPECTED_EVIDENCE_REFS | CODEBOOK_FILES


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _normalize_time_value(value: object) -> str:
    text = str(value).strip()
    match = re.search(r"(\d{2}:\d{2}:\d{2})", text)
    return match.group(1) if match else text


def _timeline_matches(value: object) -> bool:
    if not isinstance(value, list) or len(value) != len(EXPECTED_TIMELINE):
        return False
    normalized_rows: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict):
            return False
        normalized_rows.append(
            {
                "time": _normalize_time_value(row.get("time")),
                "event": str(row.get("event", "")),
            }
        )
    return normalized_rows == EXPECTED_TIMELINE


def _normalize_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    for expected in REQUIRED_INPUTS:
        if normalized.endswith(expected):
            return expected
    if normalized.endswith("failure_recovery.json"):
        return "failure_recovery.json"
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
            for expected in REQUIRED_INPUTS:
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
        if tool in ("exec", "Exec") and "failure_recovery.json" in str(args.get("command", "")):
            paths.add("failure_recovery.json")
    return paths


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "error_recovery_06_cascading_failure" / "fixtures"


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for relative in sorted(REQUIRED_INPUTS):
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

    output_path = workspace_path / "failure_recovery.json"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.05 if output_exists else 0.0,
        "max": 0.05,
        "detail": "failure_recovery.json exists" if output_exists else "missing failure_recovery.json",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.05 if inputs_ok else 0.0,
        "max": 0.05,
        "detail": inputs_detail,
    }

    if not output_exists:
        for check_id, max_score in (
            ("timeline_is_correct", 0.2),
            ("root_cause_is_correct", 0.15),
            ("propagation_chain_is_correct", 0.15),
            ("config_fixes_are_correct", 0.1),
            ("degrade_actions_are_correct", 0.1),
            ("recovery_order_is_correct", 0.1),
            ("services_to_keep_running_is_correct", 0.05),
            ("evidence_refs_are_complete", 0.05),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("timeline_is_correct", 0.2),
            ("root_cause_is_correct", 0.15),
            ("propagation_chain_is_correct", 0.15),
            ("config_fixes_are_correct", 0.1),
            ("degrade_actions_are_correct", 0.1),
            ("recovery_order_is_correct", 0.1),
            ("services_to_keep_running_is_correct", 0.05),
            ("evidence_refs_are_complete", 0.05),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    timeline = payload.get("timeline")
    checkpoints["timeline_is_correct"] = {
        "score": 0.2 if _timeline_matches(timeline) else 0.0,
        "max": 0.2,
        "detail": f"timeline={timeline}",
    }
    root_cause_ok = (
        payload.get("root_cause_service") == "payment-gateway"
        and payload.get("root_cause") == "user_service_port_misconfigured_to_9091_after_reload"
    )
    checkpoints["root_cause_is_correct"] = {
        "score": 0.15 if root_cause_ok else 0.0,
        "max": 0.15,
        "detail": (
            f"root_cause_service={payload.get('root_cause_service')!r} "
            f"root_cause={payload.get('root_cause')!r}"
        ),
    }
    checkpoints["propagation_chain_is_correct"] = {
        "score": 0.15 if payload.get("propagation_chain") == EXPECTED_PROPAGATION else 0.0,
        "max": 0.15,
        "detail": f"propagation_chain={payload.get('propagation_chain')}",
    }
    config_fixes = payload.get("config_fixes") if isinstance(payload.get("config_fixes"), dict) else {}
    config_score = 0.0
    config_details: list[str] = []

    # payment-gateway port fix (0.04)
    pg_fixes = config_fixes.get("payment-gateway") if isinstance(config_fixes.get("payment-gateway"), dict) else {}
    if pg_fixes.get("user_service_port") == 8081:
        config_score += 0.04
        config_details.append("port=ok")
    else:
        config_details.append(f"port={pg_fixes.get('user_service_port')!r}")

    # order-service fixes (0.06)
    os_fixes = config_fixes.get("order-service") if isinstance(config_fixes.get("order-service"), dict) else {}
    retries = os_fixes.get("max_checkout_retries")
    if isinstance(retries, int) and 1 <= retries <= 2:
        config_score += 0.03
        config_details.append(f"retries={retries}(ok)")
    else:
        config_details.append(f"retries={retries!r}")
    if os_fixes.get("fail_fast_on_payment_gateway_down") is True:
        config_score += 0.03
        config_details.append("fail_fast=ok")
    else:
        config_details.append(f"fail_fast={os_fixes.get('fail_fast_on_payment_gateway_down')!r}")

    checkpoints["config_fixes_are_correct"] = {
        "score": round(config_score, 4),
        "max": 0.1,
        "detail": " ".join(config_details),
    }
    checkpoints["degrade_actions_are_correct"] = {
        "score": 0.1 if payload.get("degrade_actions") == EXPECTED_DEGRADE_ACTIONS else 0.0,
        "max": 0.1,
        "detail": f"degrade_actions={payload.get('degrade_actions')}",
    }
    checkpoints["recovery_order_is_correct"] = {
        "score": 0.1 if payload.get("recovery_order") == EXPECTED_RECOVERY_ORDER else 0.0,
        "max": 0.1,
        "detail": f"recovery_order={payload.get('recovery_order')}",
    }
    checkpoints["services_to_keep_running_is_correct"] = {
        "score": 0.05 if payload.get("services_to_keep_running") == ["user-service"] else 0.0,
        "max": 0.05,
        "detail": f"services_to_keep_running={payload.get('services_to_keep_running')}",
    }

    evidence_refs = payload.get("evidence_refs")
    evidence_set = set(evidence_refs) if isinstance(evidence_refs, list) else set()
    checkpoints["evidence_refs_are_complete"] = {
        "score": 0.05 if evidence_set == EXPECTED_EVIDENCE_REFS and len(evidence_refs) == 7 else 0.0,
        "max": 0.05,
        "detail": f"evidence_refs={evidence_refs}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _observed_reads(trace)
    write_paths = _observed_writes(trace)

    read_count = sum(1 for item in REQUIRED_INPUTS if item in read_paths)
    wrote_output = "failure_recovery.json" in write_paths

    if read_count == 10 and wrote_output:
        return 1.0
    if read_count >= 9 and wrote_output:
        return 0.85
    if read_count >= 8 and wrote_output:
        return 0.7
    if read_count >= 5 and wrote_output:
        return 0.55
    if read_count >= 2 or wrote_output:
        return 0.35
    return 0.2
