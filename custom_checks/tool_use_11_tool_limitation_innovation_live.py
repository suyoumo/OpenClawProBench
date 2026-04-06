"""Custom checks for the limited-tool innovation scenario."""

from __future__ import annotations

import json
from pathlib import Path

from harness.custom_check_helpers import seeded_inputs_unchanged, tool_arg_paths


EXPECTED_WORKFLOW = ["glob_chunks", "read_each_summary", "write_running_totals", "final_rank"]
EXPECTED_INPUTS = [
    "chunk_001.summary",
    "chunk_002.summary",
    "chunk_003.summary",
    "chunk_004.summary",
]


def _fixture_dir() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "datasets"
        / "frontier"
        / "tool_use_11_tool_limitation_innovation_live"
        / "fixtures"
    )


def _parse_summary(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pair in path.read_text(encoding="utf-8").strip().split(","):
        key, value = pair.split("=", 1)
        counts[key.strip()] = int(value.strip())
    return counts


def _expected_counts() -> dict[str, int]:
    totals: dict[str, int] = {}
    for name in EXPECTED_INPUTS:
        for key, value in _parse_summary(_fixture_dir() / name).items():
            totals[key] = totals.get(key, 0) + value
    return totals


def _expected_top3() -> list[str]:
    counts = _expected_counts()
    ranking = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ranking[:3]]


def _observed_reads(trace: dict) -> set[str]:
    paths = tool_arg_paths(trace, tool_name="read", basename=True)
    for event in trace.get("events", []):
        if event.get("type") != "tool_call" or str(event.get("tool", "")).lower() != "exec":
            continue
        command = str((event.get("args") or {}).get("command", ""))
        for name in EXPECTED_INPUTS:
            if name in command:
                paths.add(name)
    return paths


def _observed_writes(trace: dict) -> set[str]:
    paths = tool_arg_paths(trace, tool_name="write", basename=True)
    for event in trace.get("events", []):
        if event.get("type") != "tool_call" or str(event.get("tool", "")).lower() != "exec":
            continue
        command = str((event.get("args") or {}).get("command", ""))
        if "tool_innovation.json" in command:
            paths.add("tool_innovation.json")
        for name in EXPECTED_INPUTS:
            if name in command:
                paths.add(name)
    return paths


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}
    expected_counts = _expected_counts()
    expected_top3 = _expected_top3()
    observed_reads = _observed_reads(trace)

    output_path = ws / "tool_innovation.json"
    exists = output_path.exists()
    checkpoints["innovation_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "tool_innovation.json exists" if exists else "missing tool_innovation.json",
    }
    read_count = sum(1 for name in EXPECTED_INPUTS if name in observed_reads)
    checkpoints["read_seeded_shards"] = {
        "score": round((read_count / len(EXPECTED_INPUTS)) * 0.1, 4),
        "max": 0.1,
        "detail": f"read_count={read_count}/{len(EXPECTED_INPUTS)}",
    }
    inputs_ok, inputs_detail = seeded_inputs_unchanged(ws, _fixture_dir(), EXPECTED_INPUTS)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }
    if not exists:
        for check_id, max_score in (
            ("workflow_is_correct", 0.15),
            ("chunk_order_is_correct", 0.1),
            ("aggregated_counts_are_correct", 0.25),
            ("top_words_are_correct", 0.15),
            ("why_it_works_is_nontrivial", 0.05),
            ("invalid_shortcuts_are_rejected", 0.05),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("workflow_is_correct", 0.2),
            ("chunk_order_is_correct", 0.1),
            ("aggregated_counts_are_correct", 0.25),
            ("top_words_are_correct", 0.15),
            ("why_it_works_is_nontrivial", 0.1),
            ("invalid_shortcuts_are_rejected", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["workflow_is_correct"] = {
        "score": 0.15 if payload.get("workflow") == EXPECTED_WORKFLOW else 0.075 if isinstance(payload.get("workflow"), list) and set(payload.get("workflow")) == set(EXPECTED_WORKFLOW) else 0.0,
        "max": 0.15,
        "detail": f"workflow={payload.get('workflow')}",
    }
    checkpoints["chunk_order_is_correct"] = {
        "score": 0.1 if payload.get("chunk_read_order") == EXPECTED_INPUTS else 0.05 if isinstance(payload.get("chunk_read_order"), list) and set(payload.get("chunk_read_order")) == set(EXPECTED_INPUTS) else 0.0,
        "max": 0.1,
        "detail": f"chunk_read_order={payload.get('chunk_read_order')}",
    }

    counts = payload.get("aggregated_counts")
    count_hits = 0
    if isinstance(counts, dict):
        for key, expected in expected_counts.items():
            if counts.get(key) == expected:
                count_hits += 1
    checkpoints["aggregated_counts_are_correct"] = {
        "score": round(count_hits / len(expected_counts) * 0.25, 4),
        "max": 0.25,
        "detail": f"count_hits={count_hits}",
    }

    checkpoints["top_words_are_correct"] = {
        "score": 0.15 if payload.get("top_3_words") == expected_top3 else 0.0,
        "max": 0.15,
        "detail": f"top_3_words={payload.get('top_3_words')}",
    }

    why_it_works = payload.get("why_simple_tools_still_work")
    why_text = " ".join(str(item) for item in why_it_works) if isinstance(why_it_works, list) else ""
    why_hits = 0
    for keywords in (
        ("shard", "summary", "摘要"),
        ("incremental", "累积"),
        ("read", "write"),
    ):
        if any(keyword in why_text.lower() or keyword in why_text for keyword in keywords):
            why_hits += 1
    why_score = 0.0
    if isinstance(why_it_works, list) and len([item for item in why_it_works if str(item).strip()]) >= 2:
        why_score += 0.025
    if why_hits >= 2:
        why_score += 0.025
    checkpoints["why_it_works_is_nontrivial"] = {
        "score": round(why_score, 4),
        "max": 0.05,
        "detail": f"why_count={len(why_it_works) if isinstance(why_it_works, list) else 0} hits={why_hits}",
    }

    invalid = payload.get("invalid_shortcuts_rejected")
    invalid_text = " ".join(str(item) for item in invalid) if isinstance(invalid, list) else ""
    invalid_hits = 0
    for keywords in (
        ("pipe", "管道"),
        ("read all", "一次性", "10gb"),
        ("complex script", "复杂脚本"),
    ):
        if any(keyword in invalid_text.lower() or keyword in invalid_text for keyword in keywords):
            invalid_hits += 1
    invalid_score = 0.0
    if isinstance(invalid, list) and len([item for item in invalid if str(item).strip()]) >= 2:
        invalid_score += 0.025
    if invalid_hits >= 2:
        invalid_score += 0.025
    checkpoints["invalid_shortcuts_are_rejected"] = {
        "score": round(invalid_score, 4),
        "max": 0.05,
        "detail": f"invalid_count={len(invalid) if isinstance(invalid, list) else 0} hits={invalid_hits}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _observed_reads(trace)
    write_paths = _observed_writes(trace)

    read_count = sum(1 for name in EXPECTED_INPUTS if name in read_paths)
    wrote_output = "tool_innovation.json" in write_paths
    rewrote_inputs = any(name in write_paths for name in EXPECTED_INPUTS)

    if read_count == len(EXPECTED_INPUTS) and wrote_output and not rewrote_inputs:
        return 1.0
    if read_count >= 3 and wrote_output and not rewrote_inputs:
        return 0.8
    if read_count >= 2 and wrote_output:
        return 0.6
    if read_count >= 1 or wrote_output:
        return 0.35
    return 0.2
