"""Custom checks for the live OpenClaw skill source audit scenario."""

from __future__ import annotations

from harness.openclaw_native import (
    count_missing_family,
    example_skill_names,
    grade_skills_process,
    load_json_file,
    load_skills_inventory,
    trace_used_openclaw_skills_inventory,
)


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    payload, detail = load_json_file(workspace, "skill_source_audit.json")

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
            ("count_summary_is_correct", 0.35),
            ("example_buckets_are_correct", 0.35),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    inventory = load_skills_inventory()
    expected_counts = {
        "ready_bundled_count": sum(
            1
            for skill in inventory.get("skills", [])
            if isinstance(skill, dict) and skill.get("eligible") and skill.get("bundled")
        ),
        "ready_external_count": sum(
            1
            for skill in inventory.get("skills", [])
            if isinstance(skill, dict) and skill.get("eligible") and not skill.get("bundled")
        ),
        "missing_due_to_bins_count": count_missing_family(inventory, "bins"),
    }
    actual_counts = {key: payload.get(key) for key in expected_counts}
    count_hits = sum(payload.get(key) == value for key, value in expected_counts.items())
    checkpoints["count_summary_is_correct"] = {
        "score": round(count_hits / len(expected_counts) * 0.35, 4),
        "max": 0.35,
        "detail": f"{count_hits}/{len(expected_counts)} counts correct; reported_counts={actual_counts!r} expected_counts={expected_counts!r}",
    }

    expected_examples = {
        "ready_bundled_examples": example_skill_names(
            inventory,
            eligible=True,
            bundled=True,
            limit=2,
        ),
        "ready_external_examples": example_skill_names(
            inventory,
            eligible=True,
            bundled=False,
            limit=2,
        ),
        "missing_due_to_bins_examples": example_skill_names(
            inventory,
            eligible=False,
            missing_family="bins",
            limit=3,
        ),
    }
    actual_examples = {key: payload.get(key) for key in expected_examples}
    example_hits = sum(payload.get(key) == value for key, value in expected_examples.items())
    checkpoints["example_buckets_are_correct"] = {
        "score": round(example_hits / len(expected_examples) * 0.35, 4),
        "max": 0.35,
        "detail": f"expected_examples={expected_examples!r} actual_examples={actual_examples!r}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    return grade_skills_process(trace)
