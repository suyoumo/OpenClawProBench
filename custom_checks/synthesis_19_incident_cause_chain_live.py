"""Custom checks for synthesis_19_incident_cause_chain_live."""

from __future__ import annotations

import json
from pathlib import Path

EXPECTED_TIMELINE = [
    {"time": "09:14", "event": "checkout_config_v42_deployed"},
    {"time": "09:16", "event": "tax_service_region_mismatch_errors_started"},
    {"time": "09:19", "event": "eu_checkout_failures_crossed_alert_threshold"},
    {"time": "09:23", "event": "rollback_started"},
    {"time": "09:27", "event": "checkout_errors_returned_to_baseline"},
]
EXPECTED_RULED_OUT = ["payment_gateway_outage", "database_pool_exhaustion"]
EXPECTED_REFS = [
    "incident_ticket.md",
    "service_logs.json",
    "deploy_history.json",
    "runbook_excerpt.txt",
]


def _text(raw: object) -> str:
    return str(raw or "").strip().lower().replace("-", "_")


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}
    output_path = ws / "incident_cause_chain.json"
    exists = output_path.exists()
    checkpoints["cause_chain_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "incident_cause_chain.json exists" if exists else "missing incident_cause_chain.json",
    }
    if not exists:
        for check_id, max_score in (
            ("timeline_is_exact", 0.2),
            ("root_cause_is_grounded", 0.2),
            ("causal_chain_is_grounded", 0.15),
            ("ruled_out_is_grounded", 0.1),
            ("mitigation_is_grounded", 0.1),
            ("confidence_and_refs_are_correct", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("timeline_is_exact", 0.2),
            ("root_cause_is_grounded", 0.2),
            ("causal_chain_is_grounded", 0.15),
            ("ruled_out_is_grounded", 0.1),
            ("mitigation_is_grounded", 0.1),
            ("confidence_and_refs_are_correct", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["timeline_is_exact"] = {
        "score": 0.2 if payload.get("timeline") == EXPECTED_TIMELINE else 0.0,
        "max": 0.2,
        "detail": f"timeline={payload.get('timeline')}",
    }

    root = _text(payload.get("root_cause"))
    root_ok = all(k in root for k in ("config", "v42", "tax", "region")) and any(k in root for k in ("misrouting", "mismatch", "misroute"))
    checkpoints["root_cause_is_grounded"] = {
        "score": 0.2 if root_ok else 0.0,
        "max": 0.2,
        "detail": f"root_cause={payload.get('root_cause')!r}",
    }

    chain = payload.get("why_it_happened")
    chain_text = " ".join(str(x).lower() for x in chain) if isinstance(chain, list) else ""
    chain_ok = isinstance(chain, list) and len(chain) == 3 and all(term in chain_text for term in ("deploy", "config", "tax", "region"))
    checkpoints["causal_chain_is_grounded"] = {
        "score": 0.15 if chain_ok else 0.0,
        "max": 0.15,
        "detail": f"why_it_happened={payload.get('why_it_happened')}",
    }

    ruled = payload.get("ruled_out_hypotheses")
    ruled_text = " ".join(str(x).lower() for x in ruled) if isinstance(ruled, list) else ""
    ruled_ok = isinstance(ruled, list) and len(ruled) == 2 and "payment" in ruled_text and ("database" in ruled_text or "pool" in ruled_text)
    checkpoints["ruled_out_is_grounded"] = {
        "score": 0.1 if ruled_ok else 0.0,
        "max": 0.1,
        "detail": f"ruled_out_hypotheses={payload.get('ruled_out_hypotheses')}",
    }

    mitigation = _text(payload.get("immediate_mitigation"))
    mitigation_ok = "rollback" in mitigation and ("v41" in mitigation or "last_known_good" in mitigation)
    checkpoints["mitigation_is_grounded"] = {
        "score": 0.1 if mitigation_ok else 0.0,
        "max": 0.1,
        "detail": f"immediate_mitigation={payload.get('immediate_mitigation')!r}",
    }

    refs_ok = payload.get("confidence") == "high" and payload.get("evidence_refs") == EXPECTED_REFS
    checkpoints["confidence_and_refs_are_correct"] = {
        "score": 0.1 if refs_ok else 0.0,
        "max": 0.1,
        "detail": f"confidence={payload.get('confidence')!r} evidence_refs={payload.get('evidence_refs')}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_hits = 0
    wrote = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        tool = str(event.get("tool", "")).lower()
        args = event.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", ""))
        if tool == "read" and any(name in path for name in EXPECTED_REFS):
            read_hits += 1
        if tool == "write" and path.endswith("incident_cause_chain.json"):
            wrote = True
    if read_hits >= 4 and wrote:
        return 1.0
    if read_hits >= 2 and wrote:
        return 0.7
    if wrote:
        return 0.45
    return 0.2
