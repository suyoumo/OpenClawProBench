"""H4: 矛盾报告解析 — 评分脚本"""

from __future__ import annotations

import json
from pathlib import Path

from harness.openclaw_native import (
    load_json_file,
    trace_used_openclaw_exec,
)

# Ground truth from fixtures:
# Service statuses across reports:
#   auth-service:      ops=healthy,  dev=degraded, pm=healthy     -> CONTRADICTION
#   payment-gateway:   ops=degraded, dev=healthy,  pm=down        -> CONTRADICTION
#   user-db:           ops=healthy,  dev=healthy,  pm=degraded    -> CONTRADICTION
#   cache-layer:       ops=down,     dev=degraded, pm=down        -> CONTRADICTION
#   notification-svc:  ops=healthy,  dev=down,     pm=degraded    -> CONTRADICTION
#
# All 5 services have contradictions (no two reports agree on all).
# Consistent services: none (all have at least one disagreement).

SERVICES = ["auth-service", "payment-gateway", "user-db", "cache-layer", "notification-svc"]

EXPECTED_STATUSES = {
    "auth-service":     {"ops": "healthy",  "dev": "degraded", "pm": "healthy"},
    "payment-gateway":  {"ops": "degraded", "dev": "healthy",  "pm": "down"},
    "user-db":          {"ops": "healthy",  "dev": "healthy",  "pm": "degraded"},
    "cache-layer":      {"ops": "down",     "dev": "degraded", "pm": "down"},
    "notification-svc": {"ops": "healthy",  "dev": "down",     "pm": "degraded"},
}

# Services where all 3 reports agree
CONSISTENT = [s for s in SERVICES if len(set(EXPECTED_STATUSES[s].values())) == 1]
# Services with contradictions
CONTRADICTED = [s for s in SERVICES if len(set(EXPECTED_STATUSES[s].values())) > 1]


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    # --- checkpoint: read_all_3 (0.1) ---
    read_ops = read_dev = read_pm = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        args = event.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", "") or args.get("command", ""))
        if "report_ops" in path:
            read_ops = True
        if "report_dev" in path:
            read_dev = True
        if "report_pm" in path:
            read_pm = True
    all_read = read_ops and read_dev and read_pm
    checkpoints["read_all_3"] = {
        "score": 0.1 if all_read else round(0.1 * sum([read_ops, read_dev, read_pm]) / 3, 4),
        "max": 0.1,
        "detail": f"ops={read_ops} dev={read_dev} pm={read_pm}",
    }

    # --- checkpoint: used_skills_cli (0.1) ---
    used_cli = trace_used_openclaw_exec(trace, "openclaw", "skills")
    checkpoints["used_skills_cli"] = {
        "score": 0.1 if used_cli else 0.0,
        "max": 0.1,
        "detail": "used skills cli" if used_cli else "missing",
    }

    # --- checkpoint: file_exists (0.1) ---
    payload, detail = load_json_file(workspace, "resolution.json")
    checkpoints["file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }

    if payload is None:
        for cid, mx in (
            ("contradictions_found", 0.25),
            ("resolved_correctly", 0.25),
            ("confidence_reasonable", 0.2),
        ):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # --- checkpoint: contradictions_found (0.25) ---
    got_contradictions = payload.get("contradictions", [])
    if not isinstance(got_contradictions, list):
        got_contradictions = []
    got_services = {c.get("service") for c in got_contradictions if isinstance(c, dict)}
    expected_set = set(CONTRADICTED)
    found_correct = got_services & expected_set
    # Partial credit
    ratio = len(found_correct) / max(len(expected_set), 1)
    contra_score = round(0.25 * ratio, 4)
    got_total = payload.get("total_contradictions")
    checkpoints["contradictions_found"] = {
        "score": contra_score,
        "max": 0.25,
        "detail": f"found={sorted(found_correct)} expected={sorted(expected_set)} total={got_total}",
    }

    # --- checkpoint: resolved_correctly (0.25) ---
    resolved_count = 0
    for c in got_contradictions:
        if not isinstance(c, dict):
            continue
        svc = c.get("service", "")
        if svc not in EXPECTED_STATUSES:
            continue
        # Check that ops_says, dev_says, pm_says match ground truth
        expected = EXPECTED_STATUSES[svc]
        ops_ok = str(c.get("ops_says", "")).lower() == expected["ops"]
        dev_ok = str(c.get("dev_says", "")).lower() == expected["dev"]
        pm_ok = str(c.get("pm_says", "")).lower() == expected["pm"]
        has_resolved = isinstance(c.get("resolved_status"), str) and len(c["resolved_status"]) > 0
        if ops_ok and dev_ok and pm_ok and has_resolved:
            resolved_count += 1
    resolved_ratio = resolved_count / max(len(CONTRADICTED), 1)
    checkpoints["resolved_correctly"] = {
        "score": round(0.25 * resolved_ratio, 4),
        "max": 0.25,
        "detail": f"resolved={resolved_count}/{len(CONTRADICTED)}",
    }

    # --- checkpoint: confidence_reasonable (0.2) ---
    valid_confidence = {"high", "medium", "low"}
    confidence_ok = all(
        str(c.get("confidence", "")).lower() in valid_confidence
        for c in got_contradictions
        if isinstance(c, dict)
    )
    has_evidence = all(
        isinstance(c.get("evidence"), str) and len(c["evidence"]) > 5
        for c in got_contradictions
        if isinstance(c, dict)
    )
    conf_score = 0.0
    if confidence_ok:
        conf_score += 0.1
    if has_evidence:
        conf_score += 0.1
    checkpoints["confidence_reasonable"] = {
        "score": conf_score,
        "max": 0.2,
        "detail": f"valid_confidence={confidence_ok} has_evidence={has_evidence}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_count = 0
    used_cli = False
    wrote_json = False
    for e in trace.get("events", []):
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        if tool in ("read", "Read"):
            read_count += 1
        if tool == "exec":
            cmd = str(args.get("command", ""))
            if "openclaw" in cmd:
                used_cli = True
            if "report_" in cmd:
                read_count += 1
        if tool == "write":
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if read_count >= 3 and used_cli and wrote_json:
        return 1.0
    if read_count >= 2 and wrote_json:
        return 0.7
    return 0.3
