"""Grounded scoring for Tool Use 08: tool combination analysis."""

from __future__ import annotations

import json
from pathlib import Path

from harness.custom_check_helpers import seeded_inputs_unchanged, tool_arg_paths


EXPECTED_INPUTS = ["sample_data.json"]
EXPECTED_ACTION_COUNTS = {
    "login": 1,
    "purchase": 1,
    "logout": 1,
}
EXPECTED_USERS_IN_TIME_ORDER = ["Alice", "Bob", "Charlie"]
OUTPUT_NAME = "analysis_result.json"


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "tool_use_08_tool_combination" / "fixtures"


def _observed_reads(trace: dict) -> set[str]:
    paths = tool_arg_paths(trace, tool_name="read", basename=True)
    for event in trace.get("events", []):
        if event.get("type") != "tool_call" or str(event.get("tool", "")).lower() != "exec":
            continue
        command = str((event.get("args") or {}).get("command", ""))
        if "sample_data.json" in command:
            paths.add("sample_data.json")
    return paths


def _observed_writes(trace: dict) -> set[str]:
    paths = tool_arg_paths(trace, tool_name="write", basename=True)
    for event in trace.get("events", []):
        if event.get("type") != "tool_call" or str(event.get("tool", "")).lower() != "exec":
            continue
        command = str((event.get("args") or {}).get("command", ""))
        if OUTPUT_NAME in command:
            paths.add(OUTPUT_NAME)
    return paths


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = ws / OUTPUT_NAME
    exists = output_path.exists()
    checkpoints["output_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": f"{OUTPUT_NAME} exists" if exists else f"missing {OUTPUT_NAME}",
    }

    observed_reads = _observed_reads(trace)
    read_count = sum(1 for name in EXPECTED_INPUTS if name in observed_reads)
    checkpoints["read_seeded_input"] = {
        "score": 0.15 if read_count == 1 else 0.0,
        "max": 0.15,
        "detail": f"read_count={read_count}/1",
    }

    inputs_ok, inputs_detail = seeded_inputs_unchanged(ws, _fixture_dir(), EXPECTED_INPUTS)
    checkpoints["seeded_input_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not exists:
        for check_id, max_score in (
            ("valid_json", 0.1),
            ("total_users_correct", 0.1),
            ("action_counts_correct", 0.2),
            ("users_in_time_order_correct", 0.15),
            ("analysis_method_nontrivial", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("valid_json", 0.1),
            ("total_users_correct", 0.1),
            ("action_counts_correct", 0.2),
            ("users_in_time_order_correct", 0.15),
            ("analysis_method_nontrivial", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints}

    checkpoints["valid_json"] = {
        "score": 0.1,
        "max": 0.1,
        "detail": "analysis_result.json parsed successfully",
    }
    checkpoints["total_users_correct"] = {
        "score": 0.1 if payload.get("total_users") == 3 else 0.0,
        "max": 0.1,
        "detail": f"total_users={payload.get('total_users')}",
    }
    checkpoints["action_counts_correct"] = {
        "score": 0.2 if payload.get("action_counts") == EXPECTED_ACTION_COUNTS else 0.0,
        "max": 0.2,
        "detail": f"action_counts={payload.get('action_counts')}",
    }
    checkpoints["users_in_time_order_correct"] = {
        "score": 0.15 if payload.get("users_in_time_order") == EXPECTED_USERS_IN_TIME_ORDER else 0.0,
        "max": 0.15,
        "detail": f"users_in_time_order={payload.get('users_in_time_order')}",
    }

    method = payload.get("analysis_method")
    method_score = 0.0
    if isinstance(method, list) and len([item for item in method if str(item).strip()]) >= 2:
        lowered = " ".join(str(item).lower() for item in method)
        if any(token in lowered for token in ("read", "exec", "write", "glob", "读取", "写入", "脚本")):
            method_score = 0.1
        else:
            method_score = 0.05
    checkpoints["analysis_method_nontrivial"] = {
        "score": method_score,
        "max": 0.1,
        "detail": f"analysis_method={method}",
    }

    return {"checkpoints": checkpoints}


def grade_process(trace: dict) -> float:
    read_paths = _observed_reads(trace)
    write_paths = _observed_writes(trace)
    saw_input = "sample_data.json" in read_paths
    wrote_output = OUTPUT_NAME in write_paths
    used_exec = any(
        event.get("type") == "tool_call" and str(event.get("tool", "")).lower() == "exec"
        for event in trace.get("events", [])
    )

    if saw_input and wrote_output and used_exec:
        return 1.0
    if saw_input and wrote_output:
        return 0.8
    if saw_input or wrote_output:
        return 0.5
    return 0.2
