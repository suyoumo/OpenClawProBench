"""Custom checks for the live OpenClaw runtime surface matrix scenario."""

from __future__ import annotations

from harness.openclaw_native import (
    directory_peers,
    directory_required_channels,
    infer_memory_failure_mode,
    load_json_file,
    memory_search_output,
    trace_used_openclaw_exec,
)


def _expected_surface_matrix() -> dict[str, object]:
    channels = directory_required_channels()
    peer_counts = {channel: len(directory_peers(channel, limit=3)) for channel in channels}
    non_empty = sorted(channel for channel, count in peer_counts.items() if count > 0)
    directory_status = "needs_explicit_channel" if channels else "ready"

    memory_output = memory_search_output("test", max_results=3)
    memory_failure_mode = infer_memory_failure_mode(memory_output)
    memory_status = "ready" if memory_failure_mode == "ok_empty" else "degraded"
    trust_zero = memory_failure_mode == "ok_empty"

    if directory_status != "error" and non_empty and not trust_zero:
        safer_surface = "directory"
    elif trust_zero and directory_status == "error":
        safer_surface = "memory"
    elif trust_zero and not non_empty:
        safer_surface = "memory"
    elif not trust_zero and not non_empty:
        safer_surface = "neither"
    else:
        safer_surface = "directory"

    return {
        "directory_status": directory_status,
        "channels": channels,
        "non_empty_channels": non_empty,
        "memory_status": memory_status,
        "reported_no_matches": "no matches." in memory_output.lower(),
        "trust_zero_results": trust_zero,
        "safer_surface_for_live_lookup": safer_surface,
    }


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    payload, detail = load_json_file(workspace, "runtime_surface_matrix.json")

    used_directory = trace_used_openclaw_exec(trace, "openclaw", "directory")
    used_memory = trace_used_openclaw_exec(trace, "openclaw", "memory", "search")
    checkpoints["used_directory_surface"] = {
        "score": 0.15 if used_directory else 0.0,
        "max": 0.15,
        "detail": "used openclaw directory commands" if used_directory else "missing directory command",
    }
    checkpoints["used_memory_surface"] = {
        "score": 0.15 if used_memory else 0.0,
        "max": 0.15,
        "detail": "used openclaw memory search" if used_memory else "missing memory command",
    }
    checkpoints["report_file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }
    if payload is None:
        for check_id, max_score in (
            ("directory_summary_is_correct", 0.2),
            ("memory_summary_is_correct", 0.2),
            ("safer_surface_is_correct", 0.1),
            ("notes_are_grounded", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    expected = _expected_surface_matrix()
    directory_payload = payload.get("directory_surface") or {}
    memory_payload = payload.get("memory_surface") or {}

    directory_ok = (
        isinstance(directory_payload, dict)
        and directory_payload.get("status") == expected["directory_status"]
        and directory_payload.get("channels") == expected["channels"]
        and directory_payload.get("non_empty_channels") == expected["non_empty_channels"]
    )
    checkpoints["directory_summary_is_correct"] = {
        "score": 0.2 if directory_ok else 0.0,
        "max": 0.2,
        "detail": f"directory_surface={directory_payload!r}",
    }

    memory_ok = (
        isinstance(memory_payload, dict)
        and memory_payload.get("status") == expected["memory_status"]
        and memory_payload.get("reported_no_matches") == expected["reported_no_matches"]
        and memory_payload.get("trust_zero_results") == expected["trust_zero_results"]
    )
    checkpoints["memory_summary_is_correct"] = {
        "score": 0.2 if memory_ok else 0.0,
        "max": 0.2,
        "detail": f"memory_surface={memory_payload!r}",
    }
    checkpoints["safer_surface_is_correct"] = {
        "score": 0.1 if payload.get("safer_surface_for_live_lookup") == expected["safer_surface_for_live_lookup"] else 0.0,
        "max": 0.1,
        "detail": (
            f"safer_surface_for_live_lookup={payload.get('safer_surface_for_live_lookup')!r} "
            f"expected={expected['safer_surface_for_live_lookup']!r}"
        ),
    }

    notes = payload.get("notes")
    notes_text = " ".join(str(item) for item in notes) if isinstance(notes, list) else ""
    note_ok = (
        isinstance(notes, list)
        and len(notes) >= 2
        and ("channel" in notes_text.lower() or "feishu" in notes_text.lower() or "telegram" in notes_text.lower())
        and ("database" in notes_text.lower() or "memory" in notes_text.lower() or "sync" in notes_text.lower())
    )
    checkpoints["notes_are_grounded"] = {
        "score": 0.1 if note_ok else 0.0,
        "max": 0.1,
        "detail": f"notes={notes!r}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    used_directory = trace_used_openclaw_exec(trace, "openclaw", "directory")
    used_memory = trace_used_openclaw_exec(trace, "openclaw", "memory", "search")
    if used_directory and used_memory:
        return 1.0
    if used_directory or used_memory:
        return 0.6
    return 0.2
