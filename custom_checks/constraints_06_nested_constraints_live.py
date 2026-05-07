"""Constraints 06: 嵌套约束 — 多层审批流程 — 评分脚本（grounded v2）

Grounded against seeded fixtures instead of keyword heuristics.
Expected violations based on fixture data:
  1. freeze_window: request at 2026-03-25T14:00:00Z falls in Q1 freeze (03-25 to 03-31),
     and the release is not a security_hotfix or critical_bugfix exception type.
  2. approval_deadline_expired: approval deadline 2026-03-24T14:00:00Z < request time 2026-03-25T14:00:00Z.
  3. dependency_degraded: notification-service status is "degraded".
"""

from __future__ import annotations


from pathlib import Path
import json


EXPECTED_CONSTRAINT_LAYERS = ["time", "approval", "dependency", "resource"]

EXPECTED_VIOLATIONS = {
    "freeze_window",
    "approval_deadline_expired",
    "dependency_degraded",
}

VIOLATION_KEYWORDS = {
    "freeze_window": ["freeze", "frozen", "冻结", "window", "quarter"],
    "approval_deadline_expired": ["deadline", "expired", "过期", "approval", "审批"],
    "dependency_degraded": ["degrad", "notification", "依赖", "depend", "service"],
}


def _load_decision(workspace: Path) -> dict | None:
    decision_file = workspace / "decision.json"
    if not decision_file.exists():
        return None
    try:
        return json.loads(decision_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        return None


def _normalize_layer(text: str) -> str | None:
    t = text.lower().strip()
    if "time" in t or "window" in t or "freeze" in t or "时间" in t or "窗口" in t:
        return "time"
    if "approval" in t or "审批" in t or "approver" in t:
        return "approval"
    if "depend" in t or "依赖" in t or "service" in t:
        return "dependency"
    if "resource" in t or "cpu" in t or "memory" in t or "资源" in t or "monitor" in t:
        return "resource"
    return None


def _extract_layers_from_output(decision: dict) -> list[str]:
    """Extract constraint layer order from the output JSON constraints_checked field."""
    raw = decision.get("constraints_checked", [])
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for item in raw:
        text = str(item) if not isinstance(item, dict) else json.dumps(item)
        layer = _normalize_layer(text)
        if layer and layer not in seen:
            seen.append(layer)
    return seen


def _match_violation(text: str) -> set[str]:
    """Match violation text against expected violation categories."""
    t = text.lower()
    matched: set[str] = set()
    for viol_id, keywords in VIOLATION_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            matched.add(viol_id)
    return matched


def _count_violations_identified(decision: dict) -> tuple[int, set[str]]:
    """Count how many of the 3 expected violations are identified in the output."""
    violations = decision.get("violations", [])
    if not isinstance(violations, list):
        return 0, set()
    found: set[str] = set()
    for v in violations:
        text = str(v) if not isinstance(v, dict) else json.dumps(v)
        found |= _match_violation(text)
    return len(found & EXPECTED_VIOLATIONS), found & EXPECTED_VIOLATIONS


def _read_both_inputs(trace: dict) -> tuple[bool, bool]:
    """Check if agent read the key input files."""
    read_request = False
    read_policy = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        args = event.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", "") or args.get("command", ""))
        if "request.json" in path:
            read_request = True
        if "policy.yaml" in path or "calendar.json" in path or "approvers.yaml" in path:
            read_policy = True
    return read_request, read_policy


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    # --- checkpoint: read_inputs (0.1) ---
    read_request, read_policy = _read_both_inputs(trace)
    checkpoints["read_inputs"] = {
        "score": 0.1 if (read_request and read_policy) else 0.05 if (read_request or read_policy) else 0.0,
        "max": 0.1,
        "detail": f"request={read_request} policy_files={read_policy}",
    }

    # --- checkpoint: decision_file_exists (0.1) ---
    decision = _load_decision(ws)
    checkpoints["decision_file_exists"] = {
        "score": 0.1 if decision is not None else 0.0,
        "max": 0.1,
        "detail": "decision.json loaded" if decision else "missing or invalid decision.json",
    }

    if decision is None:
        for cid, mx in (
            ("constraint_layers_complete", 0.15),
            ("constraint_order_correct", 0.2),
            ("violations_identified", 0.2),
            ("decision_value_correct", 0.15),
            ("decision_consistency", 0.1),
        ):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # --- checkpoint: constraint_layers_complete (0.15) ---
    layers = _extract_layers_from_output(decision)
    layer_count = sum(1 for l in EXPECTED_CONSTRAINT_LAYERS if l in layers)
    checkpoints["constraint_layers_complete"] = {
        "score": round((layer_count / 4) * 0.15, 4),
        "max": 0.15,
        "detail": f"layers={layer_count}/4 found={layers}",
    }

    # --- checkpoint: constraint_order_correct (0.15) ---
    order_ok = layers == EXPECTED_CONSTRAINT_LAYERS[:len(layers)] and len(layers) == 4
    checkpoints["constraint_order_correct"] = {
        "score": 0.15 if order_ok else 0.0,
        "max": 0.15,
        "detail": f"order={'correct' if order_ok else 'incorrect'}: {' -> '.join(layers)}",
    }

    # --- checkpoint: violations_identified (0.15) ---
    viol_count, viol_found = _count_violations_identified(decision)
    checkpoints["violations_identified"] = {
        "score": round((viol_count / 3) * 0.15, 4),
        "max": 0.15,
        "detail": f"identified={viol_count}/3 found={sorted(viol_found)}",
    }

    # --- checkpoint: approval_deadline_grounded (0.1) ---
    # The agent must identify that the approval deadline (2026-03-24T14:00:00Z)
    # has already passed relative to the request time (2026-03-25T14:00:00Z).
    # This requires reading approvers.yaml and comparing dates.
    violations_list = decision.get("violations", [])
    violations_text = " ".join(str(v).lower() for v in violations_list) if isinstance(violations_list, list) else ""
    reasoning_text = str(decision.get("reasoning", "")).lower()
    combined_text = violations_text + " " + reasoning_text
    has_deadline_date = any(d in combined_text for d in ("2026-03-24", "03-24", "3月24"))
    has_deadline_concept = any(kw in combined_text for kw in ("deadline", "过期", "expired", "已过"))
    approval_grounded = has_deadline_date and has_deadline_concept
    checkpoints["approval_deadline_grounded"] = {
        "score": 0.1 if approval_grounded else 0.0,
        "max": 0.1,
        "detail": f"has_deadline_date={has_deadline_date} has_deadline_concept={has_deadline_concept}",
    }

    # --- checkpoint: decision_value_correct (0.15) ---
    # With 3 violations (freeze + approval deadline + dependency degraded),
    # the correct decision is "rejected" or "conditional" (not "approved").
    got_decision = str(decision.get("decision", "")).lower().strip()
    decision_ok = got_decision in ("rejected", "conditional")
    checkpoints["decision_value_correct"] = {
        "score": 0.15 if decision_ok else 0.0,
        "max": 0.15,
        "detail": f"decision={got_decision!r} expected=rejected|conditional",
    }

    # --- checkpoint: decision_consistency (0.1) ---
    has_reasoning = bool(decision.get("reasoning"))
    violations_list = decision.get("violations", [])
    consistent = (
        decision_ok
        and isinstance(violations_list, list)
        and len(violations_list) > 0
        and has_reasoning
    )
    checkpoints["decision_consistency"] = {
        "score": 0.1 if consistent else 0.0,
        "max": 0.1,
        "detail": f"consistent={consistent} has_reasoning={has_reasoning} violations_count={len(violations_list) if isinstance(violations_list, list) else 0}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_request, read_policy = _read_both_inputs(trace)
    read_count = 0
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
            if any(f in cmd for f in ("request.json", "policy.yaml", "calendar.json", "approvers.yaml", "risk_matrix.yaml")):
                read_count += 1
        if tool == "write":
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if read_count >= 4 and wrote_json:
        return 1.0
    if read_count >= 2 and wrote_json:
        return 0.7
    if wrote_json:
        return 0.4
    return 0.2
