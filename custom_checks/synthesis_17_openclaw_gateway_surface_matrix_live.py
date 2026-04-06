"""Custom checks for the live OpenClaw gateway surface matrix scenario."""

from __future__ import annotations

from harness.openclaw_native import (
    browser_status_output,
    cron_list_output,
    extract_gateway_target,
    infer_surface_status,
    load_json_file,
    message_dry_run_payload,
    trace_used_openclaw_exec,
)


def _expected_gateway_surface_matrix() -> dict[str, object]:
    browser_output = browser_status_output()
    cron_output = cron_list_output()

    browser_status = infer_surface_status(browser_output)
    cron_status = infer_surface_status(cron_output)
    browser_gateway = extract_gateway_target(browser_output)
    cron_gateway = extract_gateway_target(cron_output)

    try:
        message = message_dry_run_payload(channel="telegram", target="@benchmark_target", message="hello from benchmark")
        message_payload = message.get("payload") or {}
        message_status = "ready"
        delivery_route = str(message_payload.get("to", ""))
        dry_run = bool(message.get("dryRun")) and bool(message_payload.get("dryRun"))
    except RuntimeError:
        message_status = "unavailable"
        delivery_route = ""
        dry_run = False

    safe: list[str] = []
    blocked: list[str] = []
    if browser_status == "ready":
        safe.append("browser")
    elif browser_status == "gateway_closed":
        blocked.append("browser")
    if cron_status == "ready":
        safe.append("cron")
    elif cron_status == "gateway_closed":
        blocked.append("cron")
    if message_status == "ready":
        safe.append("message_dry_run")

    safe = sorted(safe)
    blocked = sorted(blocked)
    return {
        "browser": {"status": browser_status, "gateway_target": browser_gateway},
        "cron": {"status": cron_status, "gateway_target": cron_gateway},
        "message_dry_run": {
            "status": message_status,
            "delivery_route": delivery_route,
            "dry_run": dry_run,
        },
        "safe_for_native_benchmarking_now": safe,
        "blocked_by_gateway": blocked,
        "recommended_starting_surface": safe[0] if safe else "none",
    }


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    payload, detail = load_json_file(workspace, "gateway_surface_matrix.json")

    used_browser = trace_used_openclaw_exec(trace, "openclaw", "browser", "status", "--json")
    used_cron = trace_used_openclaw_exec(trace, "openclaw", "cron", "list", "--json")
    used_message = trace_used_openclaw_exec(trace, "openclaw", "message", "send", "--dry-run", "--channel", "telegram")
    checkpoints["used_browser_status_probe"] = {
        "score": 0.1 if used_browser else 0.0,
        "max": 0.1,
        "detail": "used openclaw browser status --json" if used_browser else "missing browser status probe",
    }
    checkpoints["used_cron_list_probe"] = {
        "score": 0.1 if used_cron else 0.0,
        "max": 0.1,
        "detail": "used openclaw cron list --json" if used_cron else "missing cron list probe",
    }
    checkpoints["used_message_dry_run_probe"] = {
        "score": 0.1 if used_message else 0.0,
        "max": 0.1,
        "detail": "used openclaw message dry-run" if used_message else "missing message dry-run probe",
    }
    checkpoints["report_file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }
    if payload is None:
        for check_id, max_score in (
            ("browser_summary_is_correct", 0.15),
            ("cron_summary_is_correct", 0.15),
            ("message_summary_is_correct", 0.15),
            ("surface_partitions_are_correct", 0.1),
            ("recommended_surface_is_correct", 0.05),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    expected = _expected_gateway_surface_matrix()

    checkpoints["browser_summary_is_correct"] = {
        "score": 0.15 if payload.get("browser") == expected["browser"] else 0.0,
        "max": 0.15,
        "detail": f"browser={payload.get('browser')!r} expected={expected['browser']!r}",
    }
    checkpoints["cron_summary_is_correct"] = {
        "score": 0.15 if payload.get("cron") == expected["cron"] else 0.0,
        "max": 0.15,
        "detail": f"cron={payload.get('cron')!r} expected={expected['cron']!r}",
    }
    checkpoints["message_summary_is_correct"] = {
        "score": 0.15 if payload.get("message_dry_run") == expected["message_dry_run"] else 0.0,
        "max": 0.15,
        "detail": (
            f"message_dry_run={payload.get('message_dry_run')!r} "
            f"expected={expected['message_dry_run']!r}"
        ),
    }

    partitions_ok = (
        payload.get("safe_for_native_benchmarking_now") == expected["safe_for_native_benchmarking_now"]
        and payload.get("blocked_by_gateway") == expected["blocked_by_gateway"]
    )
    checkpoints["surface_partitions_are_correct"] = {
        "score": 0.1 if partitions_ok else 0.0,
        "max": 0.1,
        "detail": (
            f"safe_for_native_benchmarking_now={payload.get('safe_for_native_benchmarking_now')!r} "
            f"blocked_by_gateway={payload.get('blocked_by_gateway')!r}"
        ),
    }
    checkpoints["recommended_surface_is_correct"] = {
        "score": 0.05 if payload.get("recommended_starting_surface") == expected["recommended_starting_surface"] else 0.0,
        "max": 0.05,
        "detail": (
            f"recommended_starting_surface={payload.get('recommended_starting_surface')!r} "
            f"expected={expected['recommended_starting_surface']!r}"
        ),
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    events = trace.get("events", [])
    used_browser = trace_used_openclaw_exec(trace, "openclaw", "browser", "status", "--json")
    used_cron = trace_used_openclaw_exec(trace, "openclaw", "cron", "list", "--json")
    used_message = trace_used_openclaw_exec(trace, "openclaw", "message", "send", "--dry-run", "--channel", "telegram")
    wrote_json = False
    for event in events:
        if event.get("type") != "tool_call" or event.get("tool") != "write":
            continue
        args = event.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", ""))
        if path.endswith(".json"):
            wrote_json = True
            break
    used_count = sum(bool(flag) for flag in (used_browser, used_cron, used_message))
    if used_count == 3:
        return 1.0
    if used_count == 2 and wrote_json:
        return 0.85
    if used_count == 2:
        return 0.6
    if used_count == 1:
        return 0.3
    return 0.2
