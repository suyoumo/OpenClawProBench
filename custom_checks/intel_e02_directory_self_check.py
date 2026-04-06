"""E2: 目录自检快照 — 评分脚本"""

from __future__ import annotations

from harness.openclaw_native import (
    extract_json_payload,
    load_json_file,
    run_openclaw_command,
    combined_output,
    trace_used_openclaw_exec,
)


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    used_cli = trace_used_openclaw_exec(trace, "openclaw", "directory", "self")
    checkpoints["used_openclaw_directory_cli"] = {
        "score": 0.2 if used_cli else 0.0,
        "max": 0.2,
        "detail": "used openclaw directory self" if used_cli else "missing cli call",
    }

    payload, detail = load_json_file(workspace, "self_info.json")
    checkpoints["file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }

    if payload is None:
        checkpoints["has_valid_json"] = {"score": 0.0, "max": 0.3, "detail": "skipped"}
        checkpoints["fields_match_cli"] = {"score": 0.0, "max": 0.4, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # Valid JSON with at least some fields
    has_fields = len(payload) >= 1
    checkpoints["has_valid_json"] = {
        "score": 0.3 if has_fields else 0.0,
        "max": 0.3,
        "detail": f"found {len(payload)} fields" if has_fields else "empty object",
    }

    # Compare against real CLI output
    try:
        result = run_openclaw_command("directory", "self", "--json")
        ground_truth = extract_json_payload(combined_output(result))
    except Exception as exc:
        checkpoints["fields_match_cli"] = {"score": 0.0, "max": 0.4, "detail": f"openclaw error: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    if not isinstance(ground_truth, dict) or not ground_truth:
        # Multi-channel ambiguity: CLI returns an error message instead of JSON.
        # The agent still ran the command and saw the same output, so grade based
        # on whether the agent captured the ambiguity signal (e.g. listed channels).
        from harness.openclaw_native import parse_configured_channels
        channels = parse_configured_channels(combined_output(result))
        if channels:
            # Agent should have reported the ambiguity; give partial credit if
            # the output mentions channels or ambiguity.
            got_channels = payload.get("channels") or payload.get("configured_channels") or []
            if isinstance(got_channels, list) and set(got_channels) == set(channels):
                checkpoints["fields_match_cli"] = {
                    "score": 0.4,
                    "max": 0.4,
                    "detail": f"ambiguous directory: channels match {channels}",
                }
            elif isinstance(got_channels, list) and got_channels:
                checkpoints["fields_match_cli"] = {
                    "score": 0.2,
                    "max": 0.4,
                    "detail": f"ambiguous directory: partial channel match got={got_channels} expected={channels}",
                }
            else:
                checkpoints["fields_match_cli"] = {
                    "score": 0.0,
                    "max": 0.4,
                    "detail": f"ambiguous directory: no channels captured, expected={channels}",
                }
        else:
            checkpoints["fields_match_cli"] = {"score": 0.0, "max": 0.4, "detail": "ground truth not a dict and no channel ambiguity detected"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # Count how many ground truth keys are present and match
    matched = 0
    total_keys = len(ground_truth)
    for key, expected_val in ground_truth.items():
        if key in payload and payload[key] == expected_val:
            matched += 1

    ratio = matched / total_keys if total_keys > 0 else 0.0
    score = round(0.4 * ratio, 4)
    checkpoints["fields_match_cli"] = {
        "score": score,
        "max": 0.4,
        "detail": f"matched {matched}/{total_keys} fields",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    events = trace.get("events", [])
    exec_count = 0
    wrote_json = False
    for e in events:
        if e.get("type") != "tool_call":
            continue
        if e.get("tool") == "exec":
            exec_count += 1
        if e.get("tool") == "write":
            path = str((e.get("args") or {}).get("path", "") or (e.get("args") or {}).get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if exec_count <= 2 and wrote_json:
        return 1.0
    if exec_count <= 4 and wrote_json:
        return 0.8
    if wrote_json:
        return 0.6
    return 0.2
