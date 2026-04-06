"""Grounded scoring for constraints_10_dynamic_adaptation_live."""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

from harness.custom_check_helpers import (
    file_exists_checkpoint,
    load_json_output,
    seeded_inputs_unchanged,
    skip_checkpoints,
    tool_arg_paths,
)


EXPECTED_INPUTS = [
    "slot_constraints.json",
    "workloads.json",
    "output_contract.json",
]
OUTPUT_NAME = "adaptation_plan.json"
SKIPPED_CHECKS = (
    ("top_level_contract_is_exact", 0.05),
    ("slot_decisions_are_optimal", 0.25),
    ("delayed_workloads_are_correct", 0.1),
    ("canceled_workloads_are_correct", 0.1),
    ("total_completed_units_is_correct", 0.1),
    ("notes_capture_adaptation_logic", 0.1),
)


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "constraints_10_dynamic_adaptation" / "fixtures"


def _fixture_json(name: str) -> dict:
    payload, error = load_json_output(_fixture_dir() / name)
    if payload is None:
        raise RuntimeError(f"Invalid fixture JSON for {name}: {error}")
    return payload


def _slot_constraints_payload() -> dict:
    return _fixture_json("slot_constraints.json")


def _workloads_payload() -> dict:
    return _fixture_json("workloads.json")


def _contract_payload() -> dict:
    return _fixture_json("output_contract.json")


def _required_top_level_keys() -> set[str]:
    return set(_contract_payload().get("required_top_level_keys", []))


def _required_slot_fields() -> list[str]:
    return list(_contract_payload().get("slot_decisions_contract", {}).get("required_fields", []))


def _note_requirements() -> dict:
    return dict(_contract_payload().get("notes_requirements", {}))


def _workload_map() -> dict[str, dict]:
    return {
        str(item["workload"]): item
        for item in _workloads_payload().get("workloads", [])
        if isinstance(item, dict) and "workload" in item
    }


def _ordered_slots() -> list[dict]:
    return list(_slot_constraints_payload().get("slots", []))


def _topic_group_hits(text: str, groups: list[list[list[str]]]) -> int:
    lowered = text.lower()
    hits = 0
    for group in groups:
        matched = True
        for token_options in group:
            if not any(str(token).lower() in lowered for token in token_options):
                matched = False
                break
        if matched:
            hits += 1
    return hits


def _feasible_subset(slot: dict, subset: tuple[str, ...]) -> bool:
    workload_map = _workload_map()
    memory_limit = float(slot["memory_gb_max"])
    concurrency_limit = int(slot["concurrency_max"])
    latency_limit = float(slot["latency_s_max"])
    error_limit = float(slot["error_rate_pct_max"])

    memory_total = sum(float(workload_map[name]["memory_gb"]) for name in subset)
    concurrency_total = sum(int(workload_map[name]["concurrency"]) for name in subset)
    if memory_total > memory_limit + 1e-9 or concurrency_total > concurrency_limit:
        return False
    for name in subset:
        item = workload_map[name]
        if float(item["latency_s"]) > latency_limit + 1e-9:
            return False
        if float(item["error_rate_pct"]) > error_limit + 1e-9:
            return False
    return True


def _best_plan() -> tuple[list[dict], list[str], list[str], int]:
    workload_map = _workload_map()
    workload_names = sorted(workload_map)
    all_subsets: list[tuple[str, ...]] = []
    for size in range(len(workload_names) + 1):
        for combo in combinations(workload_names, size):
            all_subsets.append(combo)

    slot_decisions: list[dict] = []
    active_any: set[str] = set()
    total_units = 0

    for slot in _ordered_slots():
        best_subset: tuple[str, ...] | None = None
        best_throughput: int | None = None
        for subset in all_subsets:
            if not _feasible_subset(slot, subset):
                continue
            throughput = sum(int(workload_map[name]["throughput_units"]) for name in subset)
            normalized_subset = tuple(sorted(subset))
            if best_subset is None or throughput > best_throughput:
                best_subset = normalized_subset
                best_throughput = throughput
            elif throughput == best_throughput and normalized_subset < best_subset:
                best_subset = normalized_subset
        if best_subset is None or best_throughput is None:
            raise RuntimeError(f"No feasible subset found for slot {slot['slot_start']}")
        slot_decisions.append(
            {
                "slot_start": int(slot["slot_start"]),
                "active_workloads": list(best_subset),
                "throughput_units": int(best_throughput),
            }
        )
        active_any.update(best_subset)
        total_units += int(best_throughput)

    delayed = sorted(
        name
        for name, item in workload_map.items()
        if bool(item.get("delayable")) and not bool(item.get("cancelable")) and name not in slot_decisions[-1]["active_workloads"]
    )
    canceled = sorted(
        name
        for name, item in workload_map.items()
        if bool(item.get("cancelable")) and name not in active_any
    )
    return slot_decisions, delayed, canceled, total_units


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
        if OUTPUT_NAME in command:
            paths.add(OUTPUT_NAME)
    return paths


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = workspace_path / OUTPUT_NAME
    output_exists = file_exists_checkpoint(checkpoints, "plan_file_exists", output_path, max_score=0.1)

    observed_reads = _observed_reads(trace)
    read_count = sum(1 for name in EXPECTED_INPUTS if name in observed_reads)
    checkpoints["read_required_inputs"] = {
        "score": round((read_count / len(EXPECTED_INPUTS)) * 0.1, 4),
        "max": 0.1,
        "detail": f"read_count={read_count}/{len(EXPECTED_INPUTS)}",
    }

    inputs_ok, inputs_detail = seeded_inputs_unchanged(workspace_path, _fixture_dir(), EXPECTED_INPUTS)
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

    actual_keys = set(payload.keys()) if isinstance(payload, dict) else set()
    required_keys = _required_top_level_keys()
    top_level_score = 1.0 if actual_keys == required_keys else 0.5 if actual_keys.issuperset(required_keys) else 0.0
    checkpoints["top_level_contract_is_exact"] = {
        "score": round(0.05 * top_level_score, 4),
        "max": 0.05,
        "detail": f"keys={sorted(actual_keys)}",
    }

    expected_decisions, expected_delayed, expected_canceled, expected_total = _best_plan()
    slot_decisions = payload.get("slot_decisions")
    slot_exact = slot_decisions == expected_decisions
    slot_shape_ok = False
    if isinstance(slot_decisions, list) and len(slot_decisions) == len(expected_decisions):
        slot_shape_ok = True
        prior_slot = None
        for row in slot_decisions:
            if not isinstance(row, dict):
                slot_shape_ok = False
                break
            if not set(_required_slot_fields()).issubset(row.keys()):
                slot_shape_ok = False
                break
            slot_start = int(row.get("slot_start", -999))
            if prior_slot is not None and slot_start < prior_slot:
                slot_shape_ok = False
                break
            workloads = row.get("active_workloads")
            if not isinstance(workloads, list) or workloads != sorted(str(item) for item in workloads):
                slot_shape_ok = False
                break
            prior_slot = slot_start
    checkpoints["slot_decisions_are_optimal"] = {
        "score": 0.25 if slot_exact else 0.12 if slot_shape_ok else 0.0,
        "max": 0.25,
        "detail": f"slot_decisions={slot_decisions}",
    }

    delayed = payload.get("final_delayed_workloads")
    checkpoints["delayed_workloads_are_correct"] = {
        "score": 0.1 if delayed == expected_delayed else 0.0,
        "max": 0.1,
        "detail": f"final_delayed_workloads={delayed}",
    }

    canceled = payload.get("final_canceled_workloads")
    checkpoints["canceled_workloads_are_correct"] = {
        "score": 0.1 if canceled == expected_canceled else 0.0,
        "max": 0.1,
        "detail": f"final_canceled_workloads={canceled}",
    }

    total_completed = payload.get("total_completed_units")
    checkpoints["total_completed_units_is_correct"] = {
        "score": 0.1 if total_completed == expected_total else 0.0,
        "max": 0.1,
        "detail": f"total_completed_units={total_completed}",
    }

    note_requirements = _note_requirements()
    notes = payload.get("notes")
    notes_text = " ".join(str(item) for item in notes) if isinstance(notes, list) else ""
    note_hits = _topic_group_hits(notes_text, note_requirements.get("required_topic_groups", []))
    notes_count = len(notes) if isinstance(notes, list) else 0
    note_target = max(int(note_requirements.get("min_topic_hits", 2)), 1)
    note_score = 0.0
    if notes_count >= int(note_requirements.get("min_items", 2)):
        note_score = min(note_hits / note_target, 1.0)
    checkpoints["notes_capture_adaptation_logic"] = {
        "score": round(0.1 * note_score, 4),
        "max": 0.1,
        "detail": f"notes_count={notes_count} hits={note_hits}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _observed_reads(trace)
    write_paths = _observed_writes(trace)

    read_count = sum(1 for name in EXPECTED_INPUTS if name in read_paths)
    wrote_output = OUTPUT_NAME in write_paths
    rewrote_inputs = any(name in write_paths for name in EXPECTED_INPUTS)

    if read_count == len(EXPECTED_INPUTS) and wrote_output and not rewrote_inputs:
        return 1.0
    if read_count >= 2 and wrote_output and not rewrote_inputs:
        return 0.8
    if read_count >= 1 and wrote_output:
        return 0.6
    if read_count >= 1 or wrote_output:
        return 0.35
    return 0.2
