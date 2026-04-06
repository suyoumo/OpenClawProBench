"""Grounded scoring for Tool Use 09: capability-boundary discovery."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
import json
import math
from pathlib import Path

from harness.custom_check_helpers import seeded_inputs_unchanged


ARCHIVE_PATH = "dataset/archive_full_export.bin"
ANALYSIS_SCOPE = "optimal_safe_bundle_only"
REQUIRED_INPUTS = [
    "boundary_observations.json",
    "dataset_manifest.json",
    "dataset/shard_a.jsonl",
    "dataset/shard_b.jsonl",
    "dataset/shard_c.jsonl",
    "dataset/shard_d.jsonl",
    "dataset/shard_e.jsonl",
    "dataset/shard_f.jsonl",
    ARCHIVE_PATH,
]


def _fixture_dir() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "datasets"
        / "frontier"
        / "tool_use_09_capability_boundary_live"
        / "fixtures"
    )


def _tool_calls(trace: dict, tool_calls: list[dict] | None = None) -> list[dict]:
    if tool_calls is not None:
        return tool_calls
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    except (OSError, json.JSONDecodeError):
        return []
    return rows


def _tool_paths(calls: list[dict], tool_name: str) -> set[str]:
    paths: set[str] = set()
    for event in calls:
        if str(event.get("tool", "")).lower() != tool_name:
            continue
        args = event.get("args") or {}
        if not isinstance(args, dict):
            continue
        path = args.get("path") or args.get("file_path")
        if isinstance(path, str) and path:
            raw = Path(path)
            parts = raw.parts
            if "dataset" in parts:
                dataset_index = parts.index("dataset")
                paths.add("/".join(parts[dataset_index:]))
            elif parts and parts[-1]:
                paths.add(parts[-1])
    return paths


def _exec_commands(calls: list[dict]) -> list[str]:
    commands: list[str] = []
    for event in calls:
        if str(event.get("tool", "")).lower() != "exec":
            continue
        args = event.get("args") or {}
        if not isinstance(args, dict):
            continue
        command = args.get("command") or args.get("cmd")
        if isinstance(command, str) and command:
            commands.append(command)
    return commands


def _has_dataset_listing(commands: list[str]) -> bool:
    for command in commands:
        lowered = command.lower()
        if "dataset" not in lowered:
            continue
        if any(token in lowered for token in ("ls ", "ls -", "find ", "dir ")):
            return True
    return False


def _derive_limits(boundary: dict) -> tuple[int, int, int, int, float]:
    read_observations = boundary.get("read_observations")
    exec_observations = boundary.get("exec_observations")

    read_pass = [
        int(item.get("size_mb", 0))
        for item in read_observations
        if isinstance(item, dict) and item.get("status") == "pass"
    ] if isinstance(read_observations, list) else []
    read_fail = [
        int(item.get("size_mb", 0))
        for item in read_observations
        if isinstance(item, dict) and item.get("status") == "fail"
    ] if isinstance(read_observations, list) else []
    exec_pass = [
        int(item.get("batch_mb", 0))
        for item in exec_observations
        if isinstance(item, dict) and item.get("status") == "pass"
    ] if isinstance(exec_observations, list) else []
    exec_fail = [
        int(item.get("batch_mb", 0))
        for item in exec_observations
        if isinstance(item, dict) and item.get("status") == "fail"
    ] if isinstance(exec_observations, list) else []

    return (
        max(read_pass) if read_pass else 0,
        min(read_fail) if read_fail else 0,
        max(exec_pass) if exec_pass else int(boundary.get("safe_exec_batch_mb", 0) or 0),
        min(exec_fail) if exec_fail else 0,
        float(boundary.get("memory_limit_gb", 0.0) or 0.0),
    )


def _bundle_key(paths: list[str]) -> tuple[str, ...]:
    return tuple(sorted(paths))


def _derive_expected(workspace_path: Path) -> dict[str, object] | None:
    boundary = _load_json(workspace_path / "boundary_observations.json")
    manifest = _load_json(workspace_path / "dataset_manifest.json")
    if not isinstance(boundary, dict) or not isinstance(manifest, dict):
        return None

    read_limit_mb, read_failure_starts_at_mb, safe_exec_batch_mb, exec_failure_starts_at_mb, memory_limit_gb = (
        _derive_limits(boundary)
    )
    shards = manifest.get("shards")
    if not isinstance(shards, list):
        return None

    candidates: list[dict[str, object]] = []
    for item in shards:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        logical_size_mb = item.get("logical_size_mb")
        if not isinstance(path, str) or not isinstance(logical_size_mb, int):
            continue
        candidates.append({"path": path, "logical_size_mb": logical_size_mb})

    selectable = [
        item
        for item in candidates
        if item["path"] != ARCHIVE_PATH and int(item["logical_size_mb"]) < read_failure_starts_at_mb
    ]
    best_paths: list[str] = []
    best_size = -1
    for size in range(1, len(selectable) + 1):
        for combo in combinations(selectable, size):
            total_size = sum(int(item["logical_size_mb"]) for item in combo)
            combo_paths = sorted(str(item["path"]) for item in combo)
            if total_size > safe_exec_batch_mb:
                continue
            if total_size > best_size or (
                total_size == best_size and _bundle_key(combo_paths) < _bundle_key(best_paths)
            ):
                best_size = total_size
                best_paths = combo_paths

    if not best_paths:
        return None

    rejected_candidates: dict[str, str] = {}
    for item in candidates:
        path = str(item["path"])
        if path in best_paths:
            continue
        if path == ARCHIVE_PATH:
            rejected_candidates[path] = "archive_placeholder_unsafe"
        elif int(item["logical_size_mb"]) >= read_failure_starts_at_mb:
            rejected_candidates[path] = "read_limit_exceeded"
        else:
            rejected_candidates[path] = "safe_but_suboptimal_bundle"

    error_rows: list[dict[str, str]] = []
    for relative_path in best_paths:
        for row in _load_jsonl(workspace_path / relative_path):
            status = str(row.get("status", ""))
            error_code = str(row.get("error_code", ""))
            service = str(row.get("service", ""))
            if status == "error" and error_code and service:
                error_rows.append({"error_code": error_code, "service": service})

    code_counts = Counter(row["error_code"] for row in error_rows)
    service_counts = Counter(row["service"] for row in error_rows)
    if not code_counts or not service_counts:
        return None

    top_error_code, top_error_code_count = sorted(code_counts.items(), key=lambda item: (-item[1], item[0]))[0]
    top_service, top_service_error_count = sorted(service_counts.items(), key=lambda item: (-item[1], item[0]))[0]
    logical_dataset_size_mb = int(manifest.get("logical_dataset_size_mb", 0) or 0)
    sampled_logical_size_mb = sum(
        int(item["logical_size_mb"])
        for item in candidates
        if str(item["path"]) in best_paths
    )

    return {
        "capability_report": {
            "read_limit_mb": read_limit_mb,
            "read_failure_starts_at_mb": read_failure_starts_at_mb,
            "safe_exec_batch_mb": safe_exec_batch_mb,
            "exec_failure_starts_at_mb": exec_failure_starts_at_mb,
            "memory_limit_gb": memory_limit_gb,
            "recommended_sample_shards": best_paths,
            "sample_bundle_logical_size_mb": sampled_logical_size_mb,
            "rejected_candidates": rejected_candidates,
            "estimated_batches_for_full_run": math.ceil(logical_dataset_size_mb / safe_exec_batch_mb)
            if safe_exec_batch_mb
            else 0,
        },
        "analysis_result": {
            "sampled_shards": best_paths,
            "sampled_logical_size_mb": sampled_logical_size_mb,
            "total_error_rows": len(error_rows),
            "error_code_counts": dict(sorted(code_counts.items())),
            "top_error_code": top_error_code,
            "top_error_code_count": top_error_code_count,
            "top_service": top_service,
            "top_service_error_count": top_service_error_count,
            "logical_dataset_size_mb": logical_dataset_size_mb,
            "analysis_scope": ANALYSIS_SCOPE,
        },
        "unsafe_paths": sorted(
            path
            for path, reason in rejected_candidates.items()
            if reason in {"read_limit_exceeded", "archive_placeholder_unsafe"}
        ),
    }


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}
    expected = _derive_expected(workspace_path)

    capability_path = workspace_path / "capability_report.json"
    analysis_path = workspace_path / "analysis_result.json"
    capability_exists = capability_path.exists()
    analysis_exists = analysis_path.exists()

    checkpoints["capability_report_exists"] = {
        "score": 0.04 if capability_exists else 0.0,
        "max": 0.04,
        "detail": "capability_report.json exists" if capability_exists else "missing capability_report.json",
    }
    checkpoints["analysis_result_exists"] = {
        "score": 0.04 if analysis_exists else 0.0,
        "max": 0.04,
        "detail": "analysis_result.json exists" if analysis_exists else "missing analysis_result.json",
    }

    inputs_ok, inputs_detail = seeded_inputs_unchanged(workspace_path, _fixture_dir(), REQUIRED_INPUTS)
    checkpoints["inputs_are_present"] = {
        "score": 0.04 if inputs_ok else 0.0,
        "max": 0.04,
        "detail": inputs_detail,
    }

    capability_payload = _load_json(capability_path) if capability_exists else None
    capability_is_valid = isinstance(capability_payload, dict)
    checkpoints["capability_report_is_valid_json"] = {
        "score": 0.05 if capability_is_valid else 0.0,
        "max": 0.05,
        "detail": "capability_report.json parsed successfully"
        if capability_is_valid
        else "capability_report.json missing or invalid",
    }

    checkpoints["boundaries_are_correct"] = {
        "score": 0.0,
        "max": 0.15,
        "detail": "capability_report.json required for exact boundary checks",
    }
    checkpoints["bundle_selection_is_optimal"] = {
        "score": 0.0,
        "max": 0.2,
        "detail": "capability_report.json required for exact bundle checks",
    }
    if capability_is_valid and expected is not None:
        assert isinstance(capability_payload, dict)
        expected_capability = expected["capability_report"]
        assert isinstance(expected_capability, dict)

        boundaries_ok = 0.0
        if capability_payload.get("read_limit_mb") == expected_capability["read_limit_mb"]:
            boundaries_ok += 0.03
        if capability_payload.get("read_failure_starts_at_mb") == expected_capability["read_failure_starts_at_mb"]:
            boundaries_ok += 0.03
        if capability_payload.get("safe_exec_batch_mb") == expected_capability["safe_exec_batch_mb"]:
            boundaries_ok += 0.03
        if capability_payload.get("exec_failure_starts_at_mb") == expected_capability["exec_failure_starts_at_mb"]:
            boundaries_ok += 0.03
        if capability_payload.get("memory_limit_gb") == expected_capability["memory_limit_gb"]:
            boundaries_ok += 0.03
        checkpoints["boundaries_are_correct"] = {
            "score": round(boundaries_ok, 4),
            "max": 0.15,
            "detail": f"capability_boundaries={capability_payload}",
        }

        bundle_ok = 0.0
        if capability_payload.get("recommended_sample_shards") == expected_capability["recommended_sample_shards"]:
            bundle_ok += 0.08
        if capability_payload.get("sample_bundle_logical_size_mb") == expected_capability["sample_bundle_logical_size_mb"]:
            bundle_ok += 0.04
        if capability_payload.get("rejected_candidates") == expected_capability["rejected_candidates"]:
            bundle_ok += 0.04
        if capability_payload.get("estimated_batches_for_full_run") == expected_capability["estimated_batches_for_full_run"]:
            bundle_ok += 0.04
        checkpoints["bundle_selection_is_optimal"] = {
            "score": round(bundle_ok, 4),
            "max": 0.2,
            "detail": f"capability_strategy={capability_payload}",
        }

    analysis_payload = _load_json(analysis_path) if analysis_exists else None
    analysis_is_valid = isinstance(analysis_payload, dict)
    checkpoints["analysis_result_is_valid_json"] = {
        "score": 0.05 if analysis_is_valid else 0.0,
        "max": 0.05,
        "detail": "analysis_result.json parsed successfully"
        if analysis_is_valid
        else "analysis_result.json missing or invalid",
    }
    checkpoints["analysis_bundle_is_consistent"] = {
        "score": 0.0,
        "max": 0.13,
        "detail": f"analysis_result={analysis_payload}",
    }
    checkpoints["analysis_counts_are_correct"] = {
        "score": 0.0,
        "max": 0.25,
        "detail": f"analysis_result={analysis_payload}",
    }
    if analysis_is_valid and expected is not None:
        assert isinstance(analysis_payload, dict)
        expected_analysis = expected["analysis_result"]
        assert isinstance(expected_analysis, dict)

        bundle_score = 0.0
        if analysis_payload.get("sampled_shards") == expected_analysis["sampled_shards"]:
            bundle_score += 0.03
        if analysis_payload.get("sampled_logical_size_mb") == expected_analysis["sampled_logical_size_mb"]:
            bundle_score += 0.03
        if analysis_payload.get("logical_dataset_size_mb") == expected_analysis["logical_dataset_size_mb"]:
            bundle_score += 0.03
        if analysis_payload.get("analysis_scope") == expected_analysis["analysis_scope"]:
            bundle_score += 0.04
        checkpoints["analysis_bundle_is_consistent"] = {
            "score": round(bundle_score, 4),
            "max": 0.13,
            "detail": f"analysis_result={analysis_payload}",
        }

        counts_score = 0.0
        if analysis_payload.get("total_error_rows") == expected_analysis["total_error_rows"]:
            counts_score += 0.05
        if analysis_payload.get("error_code_counts") == expected_analysis["error_code_counts"]:
            counts_score += 0.1
        if (
            analysis_payload.get("top_error_code") == expected_analysis["top_error_code"]
            and analysis_payload.get("top_error_code_count") == expected_analysis["top_error_code_count"]
        ):
            counts_score += 0.05
        if (
            analysis_payload.get("top_service") == expected_analysis["top_service"]
            and analysis_payload.get("top_service_error_count") == expected_analysis["top_service_error_count"]
        ):
            counts_score += 0.05
        checkpoints["analysis_counts_are_correct"] = {
            "score": round(counts_score, 4),
            "max": 0.25,
            "detail": f"analysis_result={analysis_payload}",
        }

    checkpoints["reports_agree_on_bundle"] = {
        "score": 0.0,
        "max": 0.05,
        "detail": "bundle mismatch or missing JSON outputs",
    }
    if capability_is_valid and analysis_is_valid:
        assert isinstance(capability_payload, dict)
        assert isinstance(analysis_payload, dict)
        bundles_match = (
            capability_payload.get("recommended_sample_shards") == analysis_payload.get("sampled_shards")
            and capability_payload.get("sample_bundle_logical_size_mb") == analysis_payload.get("sampled_logical_size_mb")
        )
        checkpoints["reports_agree_on_bundle"] = {
            "score": 0.05 if bundles_match else 0.0,
            "max": 0.05,
            "detail": "capability_report and analysis_result agree on the selected bundle"
            if bundles_match
            else "capability_report and analysis_result disagree on the selected bundle",
        }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict, tool_calls: list[dict] | None = None) -> float:
    calls = _tool_calls(trace, tool_calls)
    read_paths = _tool_paths(calls, "read")
    write_paths = _tool_paths(calls, "write")
    commands = _exec_commands(calls)
    saw_glob = any(str(event.get("tool", "")).lower() == "glob" for event in calls) or _has_dataset_listing(commands)

    expected = _derive_expected(_fixture_dir())
    if expected is None:
        return 0.0

    expected_analysis = expected["analysis_result"]
    assert isinstance(expected_analysis, dict)
    required_reads = {
        "boundary_observations.json",
        "dataset_manifest.json",
        *expected_analysis["sampled_shards"],
    }
    unsafe_paths = set(expected["unsafe_paths"])
    if any(path in unsafe_paths for path in read_paths):
        return 0.1

    read_hits = sum(1 for path in required_reads if path in read_paths)
    selected_reads = sum(1 for path in expected_analysis["sampled_shards"] if path in read_paths)
    write_hits = sum(1 for path in {"capability_report.json", "analysis_result.json"} if path in write_paths)
    exec_count = len(commands)

    if saw_glob and read_hits == len(required_reads) and (write_hits == 2 or exec_count >= 2):
        return 1.0
    if read_hits == len(required_reads) and (write_hits == 2 or exec_count >= 2):
        return 0.85
    if {"boundary_observations.json", "dataset_manifest.json"}.issubset(read_paths) and selected_reads >= 2:
        return 0.65
    if {"boundary_observations.json", "dataset_manifest.json"}.issubset(read_paths):
        return 0.4
    return 0.2
