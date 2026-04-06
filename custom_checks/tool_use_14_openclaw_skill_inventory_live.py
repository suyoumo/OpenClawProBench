"""Custom checks for the live OpenClaw skill inventory scenario."""

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
    payload, detail = load_json_file(workspace, "skills_inventory_report.json")

    used_cli = trace_used_openclaw_skills_inventory(trace)
    checkpoints["used_openclaw_skills_cli"] = {
        "score": 0.2 if used_cli else 0.0,
        "max": 0.2,
        "detail": "used openclaw skills list --json" if used_cli else "missing openclaw skills list --json exec",
    }
    checkpoints["report_file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }
    if payload is None:
        for check_id, max_score in (
            ("counts_are_correct", 0.25),
            ("paths_are_correct", 0.2),
            ("example_lists_are_correct", 0.25),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    skill_snapshot = trace_native_surface_snapshot(trace, "skills")
    if skill_snapshot and skill_snapshot.get("status") == "ready":
        ready = list(skill_snapshot.get("ready_list", []))
        missing = list(skill_snapshot.get("missing_list", []))
        workspace_dir_expected = skill_snapshot.get("workspace_dir")
        managed_skills_dir_expected = skill_snapshot.get("managed_skills_dir")
        expected_ready_examples = list(skill_snapshot.get("ready_examples", []))
        expected_missing_examples = list(skill_snapshot.get("missing_examples", []))
    else:
        inventory = load_skills_inventory()
        ready = eligible_skill_names(inventory)
        missing = missing_skill_names(inventory)
        workspace_dir_expected = inventory.get("workspaceDir")
        managed_skills_dir_expected = inventory.get("managedSkillsDir")
        expected_ready_examples = ready[:3]
        expected_missing_examples = missing[:3]

    ready_count = payload.get("ready_count")
    missing_count = payload.get("missing_count")
    counts_ok = ready_count == len(ready) and missing_count == len(missing)
    checkpoints["counts_are_correct"] = {
        "score": 0.25 if counts_ok else 0.0,
        "max": 0.25,
        "detail": f"ready_count={ready_count!r} missing_count={missing_count!r}",
    }

    workspace_dir = payload.get("workspace_dir")
    managed_skills_dir = payload.get("managed_skills_dir")
    paths_ok = (
        workspace_dir == workspace_dir_expected
        and managed_skills_dir == managed_skills_dir_expected
    )
    checkpoints["paths_are_correct"] = {
        "score": 0.2 if paths_ok else 0.0,
        "max": 0.2,
        "detail": f"workspace_dir={workspace_dir!r} managed_skills_dir={managed_skills_dir!r}",
    }

    ready_examples = payload.get("ready_examples")
    missing_examples = payload.get("missing_examples")
    examples_ok = ready_examples == expected_ready_examples and missing_examples == expected_missing_examples
    checkpoints["example_lists_are_correct"] = {
        "score": 0.25 if examples_ok else 0.0,
        "max": 0.25,
        "detail": (
            f"ready_examples={ready_examples!r} expected_ready_examples={expected_ready_examples!r} "
            f"missing_examples={missing_examples!r} expected_missing_examples={expected_missing_examples!r}"
        ),
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    return grade_skills_process(trace)
