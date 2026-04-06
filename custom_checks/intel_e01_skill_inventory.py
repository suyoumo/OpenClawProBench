"""E1: 技能清单快照 — 评分脚本"""

from __future__ import annotations

from harness.openclaw_native import (
    eligible_skill_names,
    grade_skills_process,
    load_json_file,
    load_skills_inventory,
    missing_skill_names,
    trace_native_surface_snapshot,
    trace_used_openclaw_skills_inventory,
)


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    payload, detail = load_json_file(workspace, "skill_report.json")

    used_cli = trace_used_openclaw_skills_inventory(trace)
    checkpoints["used_openclaw_skills_cli"] = {
        "score": 0.2 if used_cli else 0.0,
        "max": 0.2,
        "detail": "used openclaw skills list --json" if used_cli else "missing cli call",
    }
    checkpoints["report_file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }
    if payload is None:
        for cid, mx in (("counts_correct", 0.35), ("lists_correct", 0.35)):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    skill_snapshot = trace_native_surface_snapshot(trace, "skills")
    if skill_snapshot and skill_snapshot.get("status") == "ready":
        ready = list(skill_snapshot.get("ready_list", []))
        missing = list(skill_snapshot.get("missing_list", []))
    else:
        try:
            inventory = load_skills_inventory()
        except Exception as exc:
            for cid, mx in (("counts_correct", 0.35), ("lists_correct", 0.35)):
                checkpoints[cid] = {"score": 0.0, "max": mx, "detail": f"openclaw error: {exc}"}
            return {"checkpoints": checkpoints, "safety_violations": []}
        ready = eligible_skill_names(inventory)
        missing = missing_skill_names(inventory)
    total = len(ready) + len(missing)

    got_total = payload.get("total_skills")
    got_ready = payload.get("ready_count")
    got_missing = payload.get("missing_count")
    count_hits = sum(
        (
            got_total == total,
            got_ready == len(ready),
            got_missing == len(missing),
        )
    )
    checkpoints["counts_correct"] = {
        "score": round(count_hits / 3 * 0.35, 4),
        "max": 0.35,
        "detail": f"{count_hits}/3 counts correct; total={got_total!r} ready={got_ready!r} missing={got_missing!r}",
    }

    got_ready_list = payload.get("ready_list")
    got_missing_list = payload.get("missing_list")
    list_hits = sum(
        (
            got_ready_list == ready,
            got_missing_list == missing,
        )
    )
    checkpoints["lists_correct"] = {
        "score": round(list_hits / 2 * 0.35, 4),
        "max": 0.35,
        "detail": f"ready_list match={got_ready_list == ready} missing_list match={got_missing_list == missing}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    return grade_skills_process(trace)
