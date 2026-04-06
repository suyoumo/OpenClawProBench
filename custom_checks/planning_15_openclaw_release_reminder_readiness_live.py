"""Custom checks for the live OpenClaw release reminder readiness scenario."""

from __future__ import annotations

from harness.openclaw_native import (
    default_agent_record,
    first_missing_family,
    load_agents_inventory,
    load_json_file,
    load_skills_inventory,
    message_dry_run_payload,
    skills_by_name,
    trace_used_openclaw_exec,
)


def _calendar_skill_status() -> str:
    inventory = load_skills_inventory()
    row = skills_by_name(inventory).get("feishu-calendar")
    if row is None:
        return "not_found"
    if row.get("eligible"):
        return "ready_bundled" if row.get("bundled") else "ready_external"
    family = first_missing_family(row)
    return f"blocked_{family}" if family else "blocked_unknown"


def _expected_readiness() -> dict[str, object]:
    agents = load_agents_inventory()
    default_agent = default_agent_record(agents) or {}
    default_agent_id = str(default_agent.get("id", "")) if default_agent else ""
    default_agent_model = str(default_agent.get("model", "")) if default_agent else ""
    default_agent_workspace = str(default_agent.get("workspace", "")) if default_agent else ""

    calendar_skill_status = _calendar_skill_status()
    message = message_dry_run_payload(channel="telegram", target="@benchmark_target", message="hello from benchmark")
    message_payload = message.get("payload") or {}

    message_ready = (
        bool(message_payload.get("to"))
        and bool(message.get("handledBy"))
        and bool(message_payload.get("via"))
        and bool(message.get("dryRun"))
        and bool(message_payload.get("dryRun"))
    )

    blocking_reasons: list[str] = []
    if not default_agent_id:
        blocking_reasons.append("missing_default_agent")
    if not calendar_skill_status.startswith("ready_"):
        blocking_reasons.append("calendar_skill_not_ready")
    if not message_ready:
        blocking_reasons.append("telegram_dry_run_unavailable")

    return {
        "default_agent_id": default_agent_id,
        "default_agent_model": default_agent_model,
        "default_agent_workspace": default_agent_workspace,
        "calendar_skill_status": calendar_skill_status,
        "telegram_delivery_route": str(message_payload.get("to", "")),
        "telegram_handled_by": str(message.get("handledBy", "")),
        "telegram_via": str(message_payload.get("via", "")),
        "safe_to_stage_release_reminder": not blocking_reasons,
        "blocking_reasons": sorted(blocking_reasons),
    }


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    payload, detail = load_json_file(workspace, "release_reminder_readiness.json")

    used_agents = trace_used_openclaw_exec(trace, "openclaw", "agents", "list", "--json")
    used_skills = trace_used_openclaw_exec(trace, "openclaw", "skills", "list", "--json")
    used_message = trace_used_openclaw_exec(
        trace,
        "openclaw",
        "message",
        "send",
        "--dry-run",
        "--channel",
        "telegram",
    )
    checkpoints["used_openclaw_agents_cli"] = {
        "score": 0.1 if used_agents else 0.0,
        "max": 0.1,
        "detail": "used openclaw agents list --json" if used_agents else "missing agents list --json exec",
    }
    checkpoints["used_openclaw_skills_cli"] = {
        "score": 0.1 if used_skills else 0.0,
        "max": 0.1,
        "detail": "used openclaw skills list --json" if used_skills else "missing skills list --json exec",
    }
    checkpoints["used_openclaw_message_cli"] = {
        "score": 0.1 if used_message else 0.0,
        "max": 0.1,
        "detail": "used openclaw message send --dry-run" if used_message else "missing telegram message dry-run exec",
    }
    checkpoints["report_file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }
    if payload is None:
        for check_id, max_score in (
            ("agent_summary_is_correct", 0.2),
            ("calendar_skill_status_is_correct", 0.15),
            ("telegram_delivery_summary_is_correct", 0.15),
            ("readiness_decision_is_correct", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    expected = _expected_readiness()

    agent_summary_ok = (
        payload.get("default_agent_id") == expected["default_agent_id"]
        and payload.get("default_agent_model") == expected["default_agent_model"]
        and payload.get("default_agent_workspace") == expected["default_agent_workspace"]
    )
    checkpoints["agent_summary_is_correct"] = {
        "score": 0.2 if agent_summary_ok else 0.0,
        "max": 0.2,
        "detail": (
            f"default_agent_id={payload.get('default_agent_id')!r} "
            f"default_agent_model={payload.get('default_agent_model')!r} "
            f"default_agent_workspace={payload.get('default_agent_workspace')!r}"
        ),
    }

    checkpoints["calendar_skill_status_is_correct"] = {
        "score": 0.15 if payload.get("calendar_skill_status") == expected["calendar_skill_status"] else 0.0,
        "max": 0.15,
        "detail": (
            f"calendar_skill_status={payload.get('calendar_skill_status')!r} "
            f"expected={expected['calendar_skill_status']!r}"
        ),
    }

    telegram_ok = (
        payload.get("telegram_delivery_route") == expected["telegram_delivery_route"]
        and payload.get("telegram_handled_by") == expected["telegram_handled_by"]
        and payload.get("telegram_via") == expected["telegram_via"]
    )
    checkpoints["telegram_delivery_summary_is_correct"] = {
        "score": 0.15 if telegram_ok else 0.0,
        "max": 0.15,
        "detail": (
            f"telegram_delivery_route={payload.get('telegram_delivery_route')!r} "
            f"telegram_handled_by={payload.get('telegram_handled_by')!r} "
            f"telegram_via={payload.get('telegram_via')!r}"
        ),
    }

    readiness_ok = (
        payload.get("safe_to_stage_release_reminder") == expected["safe_to_stage_release_reminder"]
        and payload.get("blocking_reasons") == expected["blocking_reasons"]
    )
    checkpoints["readiness_decision_is_correct"] = {
        "score": 0.1 if readiness_ok else 0.0,
        "max": 0.1,
        "detail": (
            f"safe_to_stage_release_reminder={payload.get('safe_to_stage_release_reminder')!r} "
            f"blocking_reasons={payload.get('blocking_reasons')!r}"
        ),
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    used_agents = trace_used_openclaw_exec(trace, "openclaw", "agents", "list", "--json")
    used_skills = trace_used_openclaw_exec(trace, "openclaw", "skills", "list", "--json")
    used_message = trace_used_openclaw_exec(
        trace,
        "openclaw",
        "message",
        "send",
        "--dry-run",
        "--channel",
        "telegram",
    )

    exec_count = sum(
        1
        for event in trace.get("events", [])
        if event.get("type") == "tool_call" and event.get("tool") == "exec"
    )
    wrote_json = any(
        event.get("type") == "tool_call"
        and event.get("tool") == "write"
        and str((event.get("args") or {}).get("path", "") or (event.get("args") or {}).get("file_path", "")).endswith(".json")
        for event in trace.get("events", [])
    )

    used_count = sum([used_agents, used_skills, used_message])
    if used_count == 3 and wrote_json and exec_count <= 4:
        return 1.0
    if used_count == 3 and wrote_json:
        return 0.8
    if used_count >= 2:
        return 0.6
    if used_count == 1:
        return 0.4
    return 0.2
