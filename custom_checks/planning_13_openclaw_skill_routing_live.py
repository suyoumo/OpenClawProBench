"""Custom checks for the live OpenClaw skill routing scenario."""

from __future__ import annotations

from harness.openclaw_native import (
    first_missing_family,
    grade_skills_process,
    load_json_file,
    load_skills_inventory,
    skills_by_name,
    trace_native_surface_snapshot,
    trace_used_openclaw_skills_inventory,
)


REQUEST_TO_SKILL = {
    "feishu_calendar_event": "feishu-calendar",
    "weather_lookup": "weather",
    "slack_messaging": "slack",
}


def _expected_routing(trace: dict | None = None) -> dict[str, object]:
    skill_snapshot = trace_native_surface_snapshot(trace or {}, "skills")
    if skill_snapshot and skill_snapshot.get("status") == "ready":
        ready_names = set(skill_snapshot.get("ready_list", []))
        missing_names = set(skill_snapshot.get("missing_list", []))
        missing_families = skill_snapshot.get("first_missing_family_by_skill", {})
    else:
        inventory = load_skills_inventory()
        by_name = skills_by_name(inventory)
        ready_names = {name for name, row in by_name.items() if row.get("eligible")}
        missing_names = set(by_name) - ready_names
        missing_families = {
            name: first_missing_family(row)
            for name, row in by_name.items()
            if first_missing_family(row) is not None
        }

    supported_now: list[str] = []
    blocked_now: list[str] = []
    blocked_reasons: dict[str, str] = {}
    skill_by_request: dict[str, str] = {}

    for request_id, skill_name in REQUEST_TO_SKILL.items():
        skill_by_request[request_id] = skill_name
        if skill_name in ready_names:
            supported_now.append(request_id)
            continue
        if skill_name not in missing_names:
            blocked_now.append(request_id)
            blocked_reasons[request_id] = "not_found"
            continue
        blocked_now.append(request_id)
        blocked_reasons[request_id] = str(missing_families.get(skill_name) or "unknown")

    return {
        "skill_by_request": skill_by_request,
        "supported_now": sorted(supported_now),
        "blocked_now": sorted(blocked_now),
        "blocked_reasons": blocked_reasons,
    }


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    payload, detail = load_json_file(workspace, "skill_routing_report.json")

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
            ("skill_mapping_is_correct", 0.25),
            ("support_partition_is_correct", 0.25),
            ("blocked_reasons_are_correct", 0.2),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    expected = _expected_routing(trace)

    mapping_ok = payload.get("skill_by_request") == expected["skill_by_request"]
    checkpoints["skill_mapping_is_correct"] = {
        "score": 0.25 if mapping_ok else 0.0,
        "max": 0.25,
        "detail": f"skill_by_request={payload.get('skill_by_request')!r}",
    }

    partition_ok = (
        payload.get("supported_now") == expected["supported_now"]
        and payload.get("blocked_now") == expected["blocked_now"]
    )
    checkpoints["support_partition_is_correct"] = {
        "score": 0.25 if partition_ok else 0.0,
        "max": 0.25,
        "detail": (
            f"supported_now={payload.get('supported_now')!r} expected_supported={expected['supported_now']!r} "
            f"blocked_now={payload.get('blocked_now')!r} expected_blocked={expected['blocked_now']!r}"
        ),
    }

    reasons_ok = payload.get("blocked_reasons") == expected["blocked_reasons"]
    checkpoints["blocked_reasons_are_correct"] = {
        "score": 0.2 if reasons_ok else 0.0,
        "max": 0.2,
        "detail": (
            f"blocked_reasons={payload.get('blocked_reasons')!r} "
            f"expected_blocked_reasons={expected['blocked_reasons']!r}"
        ),
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    return grade_skills_process(trace)
