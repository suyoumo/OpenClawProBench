"""Custom checks for the live OpenClaw message dry-run scenario."""

from __future__ import annotations

from harness.openclaw_native import load_json_file, message_dry_run_payload, trace_used_openclaw_exec


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    payload, detail = load_json_file(workspace, "message_dry_run_report.json")

    used_message = trace_used_openclaw_exec(
        trace,
        "openclaw",
        "message",
        "send",
        "--dry-run",
        "--channel",
        "telegram",
    )
    checkpoints["used_openclaw_message_cli"] = {
        "score": 0.2 if used_message else 0.0,
        "max": 0.2,
        "detail": "used openclaw message send --dry-run" if used_message else "missing telegram message dry-run exec",
    }
    checkpoints["report_file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }
    if payload is None:
        for check_id, max_score in (
            ("core_fields_are_correct", 0.25),
            ("delivery_route_is_correct", 0.2),
            ("dry_run_flag_is_correct", 0.15),
            ("transport_fields_are_correct", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    expected = message_dry_run_payload(channel="telegram", target="@benchmark_target", message="hello from benchmark")
    expected_payload = expected.get("payload") or {}

    core_ok = (
        payload.get("channel") == expected.get("channel")
        and payload.get("handled_by") == expected.get("handledBy")
    )
    checkpoints["core_fields_are_correct"] = {
        "score": 0.25 if core_ok else 0.0,
        "max": 0.25,
        "detail": f"channel={payload.get('channel')!r} handled_by={payload.get('handled_by')!r}",
    }
    checkpoints["delivery_route_is_correct"] = {
        "score": 0.2 if payload.get("delivery_route") == expected_payload.get("to") else 0.0,
        "max": 0.2,
        "detail": (
            f"delivery_route={payload.get('delivery_route')!r} "
            f"expected={expected_payload.get('to')!r}"
        ),
    }

    dry_run_expected = bool(expected.get("dryRun")) and bool(expected_payload.get("dryRun"))
    checkpoints["dry_run_flag_is_correct"] = {
        "score": 0.15 if payload.get("dry_run") == dry_run_expected else 0.0,
        "max": 0.15,
        "detail": f"dry_run={payload.get('dry_run')!r} expected={dry_run_expected!r}",
    }

    transport_ok = (
        payload.get("via") == expected_payload.get("via")
        and payload.get("has_media") == bool(expected_payload.get("mediaUrl"))
    )
    checkpoints["transport_fields_are_correct"] = {
        "score": 0.1 if transport_ok else 0.0,
        "max": 0.1,
        "detail": f"via={payload.get('via')!r} has_media={payload.get('has_media')!r}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    used_message = trace_used_openclaw_exec(
        trace,
        "openclaw",
        "message",
        "send",
        "--dry-run",
        "--channel",
        "telegram",
    )
    return 1.0 if used_message else 0.2
