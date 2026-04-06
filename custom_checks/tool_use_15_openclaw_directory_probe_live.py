"""Custom checks for the live OpenClaw directory probe scenario."""

from __future__ import annotations

from harness.openclaw_native import (
    directory_peers,
    directory_required_channels,
    load_json_file,
    trace_used_openclaw_exec,
)


def _expected_directory_probe() -> dict[str, object]:
    channels = directory_required_channels()
    peer_counts: dict[str, int] = {}
    for channel in channels:
        peer_counts[channel] = len(directory_peers(channel, limit=3))
    non_empty = sorted(channel for channel, count in peer_counts.items() if count > 0)
    return {
        "ambiguous_self_lookup": bool(channels),
        "channels_requiring_explicit_selection": channels,
        "peer_counts": peer_counts,
        "non_empty_channels": non_empty,
        "first_non_empty_channel": non_empty[0] if non_empty else "",
    }


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    payload, detail = load_json_file(workspace, "directory_probe.json")

    used_self = trace_used_openclaw_exec(trace, "openclaw", "directory", "self", "--json")
    used_peers = trace_used_openclaw_exec(trace, "openclaw", "directory", "peers", "list")
    checkpoints["used_directory_self_probe"] = {
        "score": 0.15 if used_self else 0.0,
        "max": 0.15,
        "detail": "used openclaw directory self --json" if used_self else "missing directory self probe",
    }
    checkpoints["used_directory_peers_probe"] = {
        "score": 0.15 if used_peers else 0.0,
        "max": 0.15,
        "detail": "used openclaw directory peers list" if used_peers else "missing directory peers probe",
    }
    checkpoints["report_file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }
    if payload is None:
        for check_id, max_score in (
            ("ambiguity_summary_is_correct", 0.15),
            ("channels_are_correct", 0.15),
            ("peer_counts_are_correct", 0.2),
            ("non_empty_summary_is_correct", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    expected = _expected_directory_probe()
    checkpoints["ambiguity_summary_is_correct"] = {
        "score": 0.15 if payload.get("ambiguous_self_lookup") == expected["ambiguous_self_lookup"] else 0.0,
        "max": 0.15,
        "detail": f"ambiguous_self_lookup={payload.get('ambiguous_self_lookup')!r}",
    }
    checkpoints["channels_are_correct"] = {
        "score": 0.15 if payload.get("channels_requiring_explicit_selection") == expected["channels_requiring_explicit_selection"] else 0.0,
        "max": 0.15,
        "detail": (
            f"channels={payload.get('channels_requiring_explicit_selection')!r} "
            f"expected={expected['channels_requiring_explicit_selection']!r}"
        ),
    }
    checkpoints["peer_counts_are_correct"] = {
        "score": 0.2 if payload.get("peer_counts") == expected["peer_counts"] else 0.0,
        "max": 0.2,
        "detail": f"peer_counts={payload.get('peer_counts')!r} expected={expected['peer_counts']!r}",
    }
    non_empty_ok = (
        payload.get("non_empty_channels") == expected["non_empty_channels"]
        and payload.get("first_non_empty_channel") == expected["first_non_empty_channel"]
    )
    checkpoints["non_empty_summary_is_correct"] = {
        "score": 0.1 if non_empty_ok else 0.0,
        "max": 0.1,
        "detail": (
            f"non_empty_channels={payload.get('non_empty_channels')!r} "
            f"first_non_empty_channel={payload.get('first_non_empty_channel')!r}"
        ),
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    used_self = trace_used_openclaw_exec(trace, "openclaw", "directory", "self", "--json")
    used_peers = trace_used_openclaw_exec(trace, "openclaw", "directory", "peers", "list")
    if used_self and used_peers:
        return 1.0
    if used_self or used_peers:
        return 0.6
    return 0.2
