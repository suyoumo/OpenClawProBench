"""Custom checks for the checkpoint selection recovery scenario."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_REJECTIONS = [
    {"id": "C1", "reason": "higher_total_cost"},
    {"id": "C3", "reason": "suspect_duplicate_write_penalty"},
    {"id": "C4", "reason": "invalid_missing_index_on_orders"},
]
REJECTION_REASON_ALIASES = {
    "C1": {
        "higher_total_cost", "cost_too_high", "not_optimal", "higher_cost",
        "总成本", "高于", "not lowest cost",
    },
    "C3": {
        "suspect_duplicate_write_penalty", "risk_penalty", "suspect",
        "duplicate_write", "风险惩罚", "suspect_duplicate",
    },
    "C4": {
        "invalid_missing_index_on_orders", "invalid", "missing_index",
        "不可用", "invalid_status",
    },
}

SEQUENCE_STEP_ALIASES = {
    "restore_C2": {"restore", "恢复", "c2", "检查点"},
    "replay_09_35_to_10_00": {"replay", "重放", "09:35", "09_35", "binlog", "事务日志"},
    "run_orders_integrity_check": {"integrity", "完整性", "验证", "check", "核对"},
    "reopen_write_traffic": {"reopen", "恢复", "write", "写入", "流量", "traffic"},
}


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}
    output_path = ws / "checkpoint_recovery.json"
    exists = output_path.exists()
    checkpoints["recovery_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "checkpoint_recovery.json exists" if exists else "missing checkpoint_recovery.json",
    }
    if not exists:
        for check_id, max_score in (
            ("selected_checkpoint_is_correct", 0.2),
            ("total_cost_is_correct", 0.15),
            ("rejections_are_correct", 0.2),
            ("recovery_sequence_is_correct", 0.15),
            ("verification_focus_is_complete", 0.1),
            ("notes_are_nontrivial", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("selected_checkpoint_is_correct", 0.2),
            ("total_cost_is_correct", 0.15),
            ("rejections_are_correct", 0.2),
            ("recovery_sequence_is_correct", 0.15),
            ("verification_focus_is_complete", 0.1),
            ("notes_are_nontrivial", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["selected_checkpoint_is_correct"] = {
        "score": 0.2 if payload.get("selected_checkpoint") == "C2" else 0.0,
        "max": 0.2,
        "detail": f"selected_checkpoint={payload.get('selected_checkpoint')!r}",
    }
    checkpoints["total_cost_is_correct"] = {
        "score": 0.15 if payload.get("total_recovery_cost") == 51 else 0.0,
        "max": 0.15,
        "detail": f"total_recovery_cost={payload.get('total_recovery_cost')!r}",
    }
    # --- rejections: accept alias reasons ---
    got_rejections = payload.get("rejected_checkpoints", [])
    rejection_hits = 0
    if isinstance(got_rejections, list):
        got_by_id = {}
        for item in got_rejections:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                got_by_id[item["id"]] = str(item.get("reason", "")).lower()
        for expected in EXPECTED_REJECTIONS:
            eid = expected["id"]
            got_reason = got_by_id.get(eid, "")
            if not got_reason:
                continue
            if got_reason == expected["reason"]:
                rejection_hits += 1
            else:
                aliases = REJECTION_REASON_ALIASES.get(eid, set())
                if any(alias in got_reason for alias in aliases):
                    rejection_hits += 1
    checkpoints["rejections_are_correct"] = {
        "score": round(0.2 * rejection_hits / len(EXPECTED_REJECTIONS), 4),
        "max": 0.2,
        "detail": f"rejection_hits={rejection_hits}/{len(EXPECTED_REJECTIONS)} rejected_checkpoints={got_rejections}",
    }

    # --- recovery sequence: accept alias steps ---
    got_sequence = payload.get("recovery_sequence", [])
    sequence_hits = 0
    if isinstance(got_sequence, list) and len(got_sequence) >= 4:
        combined_steps = [str(item).lower() for item in got_sequence]
        for step_key, aliases in SEQUENCE_STEP_ALIASES.items():
            for step_text in combined_steps:
                if any(alias in step_text for alias in aliases):
                    sequence_hits += 1
                    break
    checkpoints["recovery_sequence_is_correct"] = {
        "score": round(0.15 * sequence_hits / len(SEQUENCE_STEP_ALIASES), 4),
        "max": 0.15,
        "detail": f"sequence_hits={sequence_hits}/{len(SEQUENCE_STEP_ALIASES)} recovery_sequence={got_sequence}",
    }

    verification_focus = payload.get("verification_focus")
    focus_text = " ".join(str(item) for item in verification_focus) if isinstance(verification_focus, list) else ""
    focus_hits = 0
    for keyword_group in (
        ("orders",),
        ("payments", "settlement"),
    ):
        if any(keyword in focus_text.lower() or keyword in focus_text for keyword in keyword_group):
            focus_hits += 1
    checkpoints["verification_focus_is_complete"] = {
        "score": 0.1 if isinstance(verification_focus, list) and len(verification_focus) >= 2 and focus_hits >= 2 else 0.0,
        "max": 0.1,
        "detail": f"verification_focus={verification_focus}",
    }

    notes = payload.get("notes")
    notes_text = " ".join(str(item) for item in notes) if isinstance(notes, list) else ""
    note_hits = 0
    for keyword_group in (
        ("invalid", "C4"),
        ("risk_penalty", "C3"),
        ("lowest", "51", "C2"),
    ):
        if any(keyword in notes_text.lower() or keyword in notes_text for keyword in keyword_group):
            note_hits += 1
    checkpoints["notes_are_nontrivial"] = {
        "score": 0.1 if isinstance(notes, list) and len(notes) >= 2 and note_hits >= 2 else 0.0,
        "max": 0.1,
        "detail": f"notes_count={len(notes) if isinstance(notes, list) else 0} hits={note_hits}",
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
