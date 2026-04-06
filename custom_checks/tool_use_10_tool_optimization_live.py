"""Grounded scoring for tool_use_10_tool_optimization_live."""

from __future__ import annotations

import re
from pathlib import Path

from harness.custom_check_helpers import (
    file_exists_checkpoint,
    load_json_output,
    seeded_inputs_unchanged,
    skip_checkpoints,
    tool_arg_paths,
)


CORE_INPUTS = [
    "scan_scope.json",
    "tool_steps.json",
    "validation_policy.md",
    "hit_manifest.json",
]
EXPECTED_PIPELINE = [
    "glob_py_js",
    "exec_union_candidates",
    "read_validate_hits",
    "write_report",
]
ALTERNATIVE_KEYS = [
    "exec_serial_all_files",
    "exec_union_all_files",
    "exec_batched_candidates",
]
OUTPUT_NAME = "tool_strategy.json"
SKIPPED_CHECKS = (
    ("pipeline_is_correct", 0.15),
    ("time_and_memory_are_correct", 0.1),
    ("true_positive_split_is_correct", 0.15),
    ("false_positive_split_is_correct", 0.15),
    ("alternative_rationale_is_complete", 0.075),
    ("validation_rule_is_correct", 0.075),
)


def _fixture_dir() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "datasets"
        / "frontier"
        / "tool_use_10_tool_optimization_live"
        / "fixtures"
    )


def _load_fixture_text(name: str) -> str:
    return (_fixture_dir() / name).read_text(encoding="utf-8")


def _load_fixture_json(name: str) -> dict:
    payload, error = load_json_output(_fixture_dir() / name)
    if payload is None:
        raise RuntimeError(f"Invalid fixture JSON for {name}: {error}")
    return payload


def _hit_summaries() -> list[str]:
    manifest = _load_fixture_json("hit_manifest.json")
    return [str(item) for item in manifest.get("hit_summaries", [])]


def _expected_inputs() -> list[str]:
    return CORE_INPUTS + _hit_summaries()


def _parse_summary(name: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in _load_fixture_text(name).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def _is_true_positive(summary: dict[str, str]) -> bool:
    snippet = summary.get("snippet", "")
    normalized = snippet.lower()
    if "process.env" in normalized:
        return False
    if snippet.lstrip().startswith("//"):
        return False
    if "${token}" in snippet or "${bearer" in snippet:
        return False
    if "logger." in normalized and "token" in normalized:
        return True
    return bool(
        re.search(
            r"\b(?:[A-Z0-9_]*?(?:PASSWORD|TOKEN|SECRET|API_KEY)[A-Z0-9_]*)\b\s*=\s*[\"'][^\"']+[\"']",
            snippet,
        )
    )


def _expected_splits() -> tuple[list[str], list[str]]:
    true_positives: list[str] = []
    false_positives: list[str] = []
    for name in _hit_summaries():
        summary = _parse_summary(name)
        target = true_positives if _is_true_positive(summary) else false_positives
        target.append(summary.get("path", ""))
    return sorted(true_positives), sorted(false_positives)


def _expected_time_and_memory() -> tuple[int, float]:
    step_specs = _load_fixture_json("tool_steps.json").get("steps", {})
    total_seconds = 0.0
    peak_memory = 0.0
    for step in EXPECTED_PIPELINE:
        spec = step_specs.get(step, {})
        total_seconds += float(spec.get("time_seconds", 0))
        peak_memory = max(peak_memory, float(spec.get("peak_memory_gb", 0.0)))
    return int(total_seconds), round(peak_memory, 4)


def _observed_reads(trace: dict) -> set[str]:
    expected_inputs = set(_expected_inputs())
    paths = tool_arg_paths(trace, tool_name="read", basename=True)
    for event in trace.get("events", []):
        if event.get("type") != "tool_call" or str(event.get("tool", "")).lower() != "exec":
            continue
        command = str((event.get("args") or {}).get("command", ""))
        if "hit_*.summary" in command:
            paths.update(_hit_summaries())
        for name in expected_inputs:
            if name in command:
                paths.add(name)
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
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}
    expected_inputs = _expected_inputs()
    expected_true_positives, expected_false_positives = _expected_splits()
    expected_total_seconds, expected_peak_memory = _expected_time_and_memory()

    output_path = workspace_path / OUTPUT_NAME
    output_exists = file_exists_checkpoint(
        checkpoints,
        "strategy_file_exists",
        output_path,
        max_score=0.1,
    )

    observed_reads = _observed_reads(trace)
    read_count = sum(1 for name in expected_inputs if name in observed_reads)
    checkpoints["read_seeded_inputs"] = {
        "score": round((read_count / len(expected_inputs)) * 0.2, 4),
        "max": 0.2,
        "detail": f"read_count={read_count}/{len(expected_inputs)}",
    }

    inputs_ok, inputs_detail = seeded_inputs_unchanged(workspace_path, _fixture_dir(), expected_inputs)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        skip_checkpoints(checkpoints, SKIPPED_CHECKS)
        return {"checkpoints": checkpoints, "safety_violations": []}

    payload, error = load_json_output(output_path)
    if payload is None:
        skip_checkpoints(checkpoints, SKIPPED_CHECKS, detail=error)
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["pipeline_is_correct"] = {
        "score": 0.15 if payload.get("selected_pipeline") == EXPECTED_PIPELINE else 0.075 if isinstance(payload.get("selected_pipeline"), list) and len(payload.get("selected_pipeline")) == 4 else 0.0,
        "max": 0.15,
        "detail": f"selected_pipeline={payload.get('selected_pipeline')}",
    }

    total_seconds = payload.get("estimated_total_seconds")
    peak_memory = payload.get("estimated_peak_memory_gb")
    time_memory_score = 0.0
    if isinstance(total_seconds, (int, float)) and abs(float(total_seconds) - expected_total_seconds) <= 1:
        time_memory_score += 0.05
    if isinstance(peak_memory, (int, float)) and abs(float(peak_memory) - expected_peak_memory) <= 0.05:
        time_memory_score += 0.05
    checkpoints["time_and_memory_are_correct"] = {
        "score": round(time_memory_score, 4),
        "max": 0.1,
        "detail": f"estimated_total_seconds={total_seconds} estimated_peak_memory_gb={peak_memory}",
    }

    checkpoints["true_positive_split_is_correct"] = {
        "score": 0.15 if payload.get("true_positive_files") == expected_true_positives else 0.075 if isinstance(payload.get("true_positive_files"), list) and set(payload.get("true_positive_files")) == set(expected_true_positives) else 0.0,
        "max": 0.15,
        "detail": f"true_positive_files={payload.get('true_positive_files')}",
    }
    checkpoints["false_positive_split_is_correct"] = {
        "score": 0.15 if payload.get("false_positive_files") == expected_false_positives else 0.075 if isinstance(payload.get("false_positive_files"), list) and set(payload.get("false_positive_files")) == set(expected_false_positives) else 0.0,
        "max": 0.15,
        "detail": f"false_positive_files={payload.get('false_positive_files')}",
    }

    alternatives = payload.get("why_not_alternatives")
    alternative_score = 0.0
    if isinstance(alternatives, dict):
        complete_count = 0
        for key in ALTERNATIVE_KEYS:
            text = str(alternatives.get(key, "")).strip()
            if not text:
                continue
            normalized = text.lower()
            if any(token in normalized for token in ("time", "memory", "scan", "candidate", "过滤", "内存", "耗时")):
                complete_count += 1
        alternative_score = 0.075 if complete_count == len(ALTERNATIVE_KEYS) else round(complete_count / len(ALTERNATIVE_KEYS) * 0.05, 4)
    checkpoints["alternative_rationale_is_complete"] = {
        "score": alternative_score,
        "max": 0.075,
        "detail": f"why_not_alternatives_keys={sorted(alternatives) if isinstance(alternatives, dict) else alternatives}",
    }

    validation_rule = str(payload.get("validation_rule", "")).lower()
    has_hardcoded = "hardcoded" in validation_rule or "硬编码" in validation_rule
    has_log = "log" in validation_rule or "日志" in validation_rule
    has_exclusion = any(token in validation_rule for token in ("process.env", "环境变量", "注释", "comment", "template", "模板"))
    validation_score = 0.0
    if has_hardcoded:
        validation_score += 0.025
    if has_log:
        validation_score += 0.025
    if has_exclusion:
        validation_score += 0.025
    checkpoints["validation_rule_is_correct"] = {
        "score": validation_score,
        "max": 0.075,
        "detail": "validation rule covers hardcoded secrets, token logging, and exclusions"
        if validation_score == 0.075
        else f"validation rule incomplete: hardcoded={has_hardcoded} log={has_log} exclusion={has_exclusion}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    expected_inputs = _expected_inputs()
    read_paths = _observed_reads(trace)
    write_paths = _observed_writes(trace)

    read_count = sum(1 for name in expected_inputs if name in read_paths)
    wrote_output = OUTPUT_NAME in write_paths

    if read_count == len(expected_inputs) and wrote_output:
        return 1.0
    if read_count >= len(expected_inputs) - 2 and wrote_output:
        return 0.8
    if read_count >= len(_hit_summaries()) + 2 and wrote_output:
        return 0.6
    if read_count >= 3 or wrote_output:
        return 0.35
    return 0.2
