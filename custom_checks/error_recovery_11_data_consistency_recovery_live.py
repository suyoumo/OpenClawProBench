"""Custom checks for the data consistency recovery scenario."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_CANONICAL = {
    "orders": "A",
    "inventory": ["A", "B"],
}
EXPECTED_ROOT_CAUSES = {
    "B_orders": "replication_lag",
    "C_orders": "missed_rollback",
    "C_inventory": "duplicate_replay",
}
EXPECTED_REPAIR_SEQUENCE = [
    "sync_B_orders_from_A",
    "delete_C_test_order_799",
    "reset_C_inventory_sku_77_to_100",
]


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = ws / "consistency_recovery.json"
    exists = output_path.exists()
    checkpoints["recovery_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "consistency_recovery.json exists" if exists else "missing consistency_recovery.json",
    }
    if not exists:
        for check_id, max_score in (
            ("canonical_sources_are_correct", 0.15),
            ("order_anomalies_are_correct", 0.25),
            ("inventory_fix_is_correct", 0.1),
            ("root_causes_are_correct", 0.2),
            ("repair_sequence_is_correct", 0.1),
            ("verification_is_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("canonical_sources_are_correct", 0.15),
            ("order_anomalies_are_correct", 0.25),
            ("inventory_fix_is_correct", 0.1),
            ("root_causes_are_correct", 0.2),
            ("repair_sequence_is_correct", 0.1),
            ("verification_is_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    canonical = payload.get("canonical_sources")
    canonical_ok = False
    if isinstance(canonical, dict):
        # Accept "A", "Replica A", "Replica A (primary)" etc.
        orders_raw = str(canonical.get("orders", "")).strip().upper()
        orders_ok = orders_raw == "A" or "REPLICA A" in orders_raw
        inv_raw = canonical.get("inventory", [])
        if isinstance(inv_raw, list):
            inv_normalized = [str(item).strip().upper() for item in inv_raw]
            inv_ok = (
                all(any(expected in item for item in inv_normalized) for expected in ["A", "B"])
                and len(inv_raw) == 2
            )
        else:
            inv_ok = False
        canonical_ok = orders_ok and inv_ok
    checkpoints["canonical_sources_are_correct"] = {
        "score": 0.15 if canonical_ok else 0.0,
        "max": 0.15,
        "detail": f"canonical_sources={canonical}",
    }

    missing_in_b = payload.get("orders_missing_in_B")
    extra_in_c = payload.get("orders_extra_in_C")
    anomaly_score = 0.0
    if missing_in_b == [705, 706]:
        anomaly_score += 0.15
    if extra_in_c == [799]:
        anomaly_score += 0.10
    checkpoints["order_anomalies_are_correct"] = {
        "score": round(anomaly_score, 4),
        "max": 0.25,
        "detail": f"missing_in_b={missing_in_b} extra_in_c={extra_in_c}",
    }

    inventory_fix = payload.get("inventory_fix")
    inventory_ok = False
    if isinstance(inventory_fix, dict):
        replica_raw = str(inventory_fix.get("replica", "")).strip().upper()
        replica_ok = replica_raw == "C" or "REPLICA C" in replica_raw or "C" in replica_raw
        inventory_ok = replica_ok and inventory_fix.get("expected_value") == 100
    checkpoints["inventory_fix_is_correct"] = {
        "score": 0.1 if inventory_ok else 0.0,
        "max": 0.1,
        "detail": f"inventory_fix={inventory_fix}",
    }

    root_causes = payload.get("root_causes")
    cause_hits = 0
    if isinstance(root_causes, dict):
        for key, expected in EXPECTED_ROOT_CAUSES.items():
            if str(root_causes.get(key, "")).strip().lower() == expected:
                cause_hits += 1
    checkpoints["root_causes_are_correct"] = {
        "score": round(cause_hits / len(EXPECTED_ROOT_CAUSES) * 0.2, 4),
        "max": 0.2,
        "detail": f"cause_hits={cause_hits}",
    }

    repair_sequence = payload.get("repair_sequence")
    repair_ok = False
    if repair_sequence == EXPECTED_REPAIR_SEQUENCE:
        repair_ok = True
    elif isinstance(repair_sequence, list) and len(repair_sequence) >= 3:
        # Accept natural language if it contains the right semantic steps in order
        combined = " ".join(str(item).lower() for item in repair_sequence)
        has_sync_b = ("705" in combined or "706" in combined) and ("b" in combined)
        has_delete_799 = "799" in combined and ("c" in combined or "delete" in combined or "删除" in combined)
        has_fix_inventory = ("sku_77" in combined or "inventory" in combined or "库存" in combined) and ("100" in combined)
        repair_ok = has_sync_b and has_delete_799 and has_fix_inventory
    checkpoints["repair_sequence_is_correct"] = {
        "score": 0.1 if repair_ok else 0.0,
        "max": 0.1,
        "detail": f"repair_sequence={repair_sequence}",
    }

    verification_steps = payload.get("verification_steps")
    verification_text = " ".join(str(item) for item in verification_steps) if isinstance(verification_steps, list) else ""
    verification_hits = 0
    for keywords in (
        ("row", "count", "行数"),
        ("checksum",),
        ("re-read", "reread", "再次读取", "复核"),
    ):
        if any(keyword in verification_text.lower() or keyword in verification_text for keyword in keywords):
            verification_hits += 1
    verification_score = 0.0
    if isinstance(verification_steps, list) and len([item for item in verification_steps if str(item).strip()]) >= 3:
        verification_score += 0.05
    if verification_hits >= 2:
        verification_score += 0.05
    checkpoints["verification_is_complete"] = {
        "score": round(verification_score, 4),
        "max": 0.1,
        "detail": f"verification_steps={len(verification_steps) if isinstance(verification_steps, list) else 0} hits={verification_hits}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    wrote_json = False
    for e in trace.get("events", []):
        if e.get("type") != "tool_call":
            continue
        if e.get("tool") in ("write", "Write"):
            path = str((e.get("args") or {}).get("path", "") or (e.get("args") or {}).get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    return 1.0 if wrote_json else 0.3
