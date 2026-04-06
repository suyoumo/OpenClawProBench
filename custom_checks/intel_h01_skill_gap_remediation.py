"""H1: 技能缺口修复分析 — 评分脚本"""

from __future__ import annotations

from harness.openclaw_native import (
    MISSING_FAMILIES,
    count_missing_family,
    load_json_file,
    load_skills_inventory,
    missing_skill_names,
    skill_has_missing_family,
    skills_by_name,
    trace_used_openclaw_skills_inventory,
)


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    # --- checkpoint: used_cli (0.1) ---
    used_cli = trace_used_openclaw_skills_inventory(trace)
    checkpoints["used_cli"] = {
        "score": 0.1 if used_cli else 0.0,
        "max": 0.1,
        "detail": "used openclaw skills inventory command" if used_cli else "missing skills inventory cli call",
    }

    # --- checkpoint: file_exists (0.1) ---
    payload, detail = load_json_file(workspace, "gap_analysis.json")
    checkpoints["file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }

    if payload is None:
        for cid, mx in (
            ("total_missing_correct", 0.15),
            ("by_family_correct", 0.2),
            ("most_common_correct", 0.15),
            ("skill_lists_correct", 0.15),
            ("priority_order_correct", 0.15),
        ):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # --- ground truth ---
    try:
        inventory = load_skills_inventory()
    except Exception as exc:
        for cid, mx in (
            ("total_missing_correct", 0.15),
            ("by_family_correct", 0.2),
            ("most_common_correct", 0.15),
            ("skill_lists_correct", 0.15),
            ("priority_order_correct", 0.15),
        ):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": f"openclaw error: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    gt_missing = missing_skill_names(inventory)
    gt_total_missing = len(gt_missing)

    # Build by_family ground truth
    gt_by_family: dict[str, int] = {}
    for family in MISSING_FAMILIES:
        cnt = count_missing_family(inventory, family)
        if cnt > 0:
            gt_by_family[family] = cnt

    # Most common family
    gt_most_common = max(gt_by_family, key=gt_by_family.get) if gt_by_family else ""

    # Skills per family
    by_name = skills_by_name(inventory)

    # --- checkpoint: total_missing_correct (0.15) ---
    got_total = payload.get("total_missing")
    total_ok = got_total == gt_total_missing
    checkpoints["total_missing_correct"] = {
        "score": 0.15 if total_ok else 0.0,
        "max": 0.15,
        "detail": f"got={got_total} expected={gt_total_missing}",
    }

    # --- checkpoint: by_family_correct (0.2) ---
    got_family = payload.get("by_family", {})
    if not isinstance(got_family, dict):
        got_family = {}
    # Compare only non-zero families
    family_ok = True
    for fam, cnt in gt_by_family.items():
        if got_family.get(fam) != cnt:
            family_ok = False
            break
    checkpoints["by_family_correct"] = {
        "score": 0.2 if family_ok else 0.0,
        "max": 0.2,
        "detail": f"got={got_family} expected={gt_by_family}",
    }

    # --- checkpoint: most_common_correct (0.15) ---
    got_most = str(payload.get("most_common_family", ""))
    most_ok = got_most == gt_most_common
    checkpoints["most_common_correct"] = {
        "score": 0.15 if most_ok else 0.0,
        "max": 0.15,
        "detail": f"got={got_most} expected={gt_most_common}",
    }

    # --- checkpoint: skill_lists_correct (0.15) ---
    score_lists = 0.0
    checked = 0
    for family in ("bins", "env"):
        key = f"skills_missing_{family}"
        got_list = payload.get(key, [])
        if not isinstance(got_list, list):
            got_list = []
        expected = sorted(
            name
            for name in gt_missing
            if skill_has_missing_family(by_name.get(name), family)
        )
        if sorted(got_list) == expected:
            score_lists += 0.075
        checked += 1
    checkpoints["skill_lists_correct"] = {
        "score": round(score_lists, 4),
        "max": 0.15,
        "detail": f"checked {checked} family lists",
    }

    # --- checkpoint: priority_order_correct (0.15) ---
    got_priority = payload.get("remediation_priority", [])
    if not isinstance(got_priority, list):
        got_priority = []
    # Check descending order by count
    counts = [item.get("count", 0) for item in got_priority if isinstance(item, dict)]
    order_ok = counts == sorted(counts, reverse=True) and len(counts) > 0
    # Check that each entry has fix_suggestion
    has_suggestions = all(
        isinstance(item.get("fix_suggestion"), str) and len(item["fix_suggestion"]) > 5
        for item in got_priority
        if isinstance(item, dict)
    )
    priority_score = 0.0
    if order_ok:
        priority_score += 0.1
    if has_suggestions:
        priority_score += 0.05
    checkpoints["priority_order_correct"] = {
        "score": round(priority_score, 4),
        "max": 0.15,
        "detail": f"order_desc={order_ok} has_suggestions={has_suggestions}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    from harness.openclaw_native import grade_skills_process
    return grade_skills_process(trace)
