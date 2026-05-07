"""Scenario runner and benchmark orchestration."""

from __future__ import annotations

from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
import hashlib
import json
import os
import subprocess
import shutil
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .efficiency import aggregate_metric
from .live_harness import LivePreflightResult, LiveRunResult, OpenClawLiveHarness
from .loader import config_root, project_root
from .models import (
    BenchmarkResult,
    DIMENSION_WEIGHTS,
    Difficulty,
    Dimension,
    DimensionScore,
    Scenario,
    ScenarioResult,
    SignalSource,
    TrialExecution,
    TrialResult,
)
from .openclaw_native import collect_native_environment_snapshot
from .reporter import write_report
from .scoring import grade_scenario

DEFAULT_OPENCLAW_BINARY = os.environ.get("OPENCLAW_BINARY", "openclaw")
ZERO_SCORE_EPSILON = 1e-9


def _normalize_resume_model(model: str) -> str:
    if model.startswith("siliconflow/Pro/"):
        return "siliconflow/" + model[len("siliconflow/Pro/") :]
    return model


def _normalize_pricing_block(raw: dict[str, Any] | None) -> dict[str, float]:
    raw = raw or {}
    return {
        "input_per_million_usd": float(raw.get("input_per_million_usd", raw.get("input_per_1m", 0.0))),
        "output_per_million_usd": float(raw.get("output_per_million_usd", raw.get("output_per_1m", 0.0))),
        "cache_read_per_million_usd": float(raw.get("cache_read_per_million_usd", raw.get("cache_read_per_1m", 0.0))),
        "cache_write_per_million_usd": float(raw.get("cache_write_per_million_usd", raw.get("cache_write_per_1m", 0.0))),
    }


def _load_pricing(model: str) -> dict[str, float]:
    path = config_root() / "pricing.yaml"
    if not path.exists():
        return _normalize_pricing_block({})
    raw = yaml.safe_load(path.read_text()) or {}
    pricing = raw.get("pricing", {}) or {}
    models = raw.get("models", {}) or {}
    default = pricing.get("default") or models.get("default") or raw.get("default") or pricing.get("custom") or {}
    spec = pricing.get(model) or models.get(model) or default
    return _normalize_pricing_block(spec)


def _estimate_costs(
    pricing: dict[str, float],
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> dict[str, float]:
    input_cost = (input_tokens / 1_000_000) * pricing["input_per_million_usd"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_per_million_usd"]
    cache_read_cost = (cache_read_tokens / 1_000_000) * pricing["cache_read_per_million_usd"]
    cache_write_cost = (cache_write_tokens / 1_000_000) * pricing["cache_write_per_million_usd"]
    total_cost = input_cost + output_cost + cache_read_cost + cache_write_cost
    return {
        "input_cost_usd": round(input_cost, 8),
        "output_cost_usd": round(output_cost, 8),
        "cache_read_cost_usd": round(cache_read_cost, 8),
        "cache_write_cost_usd": round(cache_write_cost, 8),
        "total_cost_usd": round(total_cost, 8),
    }


def _resolve_binary_path(binary: str, *, env: dict[str, str] | None = None) -> Path | None:
    candidate = Path(binary).expanduser()
    if candidate.is_absolute() or os.sep in binary:
        return candidate.resolve(strict=False)
    resolved = shutil.which(binary, path=(env or {}).get("PATH"))
    if not resolved:
        return None
    return Path(resolved).resolve(strict=False)


def _binary_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _safe_binary_metadata(path: Path | None, *, binary_exists: bool) -> dict[str, Any]:
    if not binary_exists or path is None or not path.is_file():
        return {
            "binary_sha256": "",
            "binary_size_bytes": 0,
            "binary_read_error": "",
        }

    metadata: dict[str, Any] = {
        "binary_sha256": "",
        "binary_size_bytes": 0,
        "binary_read_error": "",
    }
    errors: list[str] = []

    try:
        metadata["binary_sha256"] = _binary_sha256(path)
    except OSError as exc:
        errors.append(f"sha256: {exc.__class__.__name__}: {exc}")

    try:
        metadata["binary_size_bytes"] = int(path.stat().st_size)
    except OSError as exc:
        errors.append(f"stat: {exc.__class__.__name__}: {exc}")

    metadata["binary_read_error"] = "; ".join(errors)
    return metadata


def _find_git_repo_root(path: Path | None) -> Path | None:
    if path is None:
        return None
    current = path if path.is_dir() else path.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _run_git_command(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _run_version_probe(binary: str, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    probes = (
        [binary, "--version"],
        [binary, "version"],
    )
    for command in probes:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
                env=env,
            )
        except Exception as exc:
            return {
                "command": command,
                "exit_code": -1,
                "text": str(exc),
            }
        text = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0 or text:
            return {
                "command": command,
                "exit_code": int(result.returncode or 0),
                "text": text,
            }
    return {
        "command": [binary, "--version"],
        "exit_code": -1,
        "text": "",
    }


def _collect_openclaw_runtime_provenance(binary: str, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    resolved_path = _resolve_binary_path(binary, env=env)
    realpath = resolved_path.resolve(strict=False) if resolved_path is not None else None
    binary_exists = bool(realpath and realpath.exists())
    repo_root = _find_git_repo_root(realpath)
    version_probe = _run_version_probe(binary, env=env)
    binary_metadata = _safe_binary_metadata(realpath, binary_exists=binary_exists)

    provenance: dict[str, Any] = {
        "configured_binary": binary,
        "resolved_binary": str(resolved_path) if resolved_path is not None else "",
        "binary_realpath": str(realpath) if realpath is not None else "",
        "binary_exists": binary_exists,
        "binary_sha256": binary_metadata["binary_sha256"],
        "binary_size_bytes": binary_metadata["binary_size_bytes"],
        "binary_read_error": binary_metadata["binary_read_error"],
        "version_command": version_probe["command"],
        "version_exit_code": version_probe["exit_code"],
        "version_text": version_probe["text"],
        "git_repo_root": str(repo_root) if repo_root is not None else "",
        "git_commit": "",
        "git_commit_short": "",
        "git_branch": "",
        "git_remote_origin": "",
        "git_dirty": False,
    }

    if repo_root is None:
        return provenance

    commit = _run_git_command(repo_root, "rev-parse", "HEAD")
    provenance["git_commit"] = commit
    provenance["git_commit_short"] = commit[:12] if commit else ""
    provenance["git_branch"] = _run_git_command(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    provenance["git_remote_origin"] = _run_git_command(repo_root, "remote", "get-url", "origin")
    status_porcelain = _run_git_command(repo_root, "status", "--porcelain")
    provenance["git_dirty"] = bool(status_porcelain)
    return provenance


def _resolve_scenario_source(scenario: Scenario, source: str) -> Path:
    candidates = [
        (scenario.source_path.parent / source).resolve(),
        (project_root() / source).resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Workspace source not found for {scenario.scenario_id}: {source}")


def _default_workspace_dest(source: str) -> str:
    normalized = source.replace("\\", "/")
    marker = "fixtures/"
    if marker in normalized:
        return normalized.split(marker, 1)[1]
    return Path(normalized).name


def _copy_source_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def _copy_seed_dir_contents(source_dir: Path, workspace: Path) -> None:
    if not source_dir.exists():
        raise FileNotFoundError(f"Workspace seed directory not found: {source_dir}")
    workspace.mkdir(parents=True, exist_ok=True)
    for item in sorted(source_dir.iterdir()):
        _copy_source_path(item, workspace / item.name)


def _copy_workspace_files(scenario: Scenario, workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    if scenario.workspace_seed_dir:
        seed_dir = _resolve_scenario_source(scenario, scenario.workspace_seed_dir)
        _copy_seed_dir_contents(seed_dir, workspace)
    for item in scenario.workspace_files:
        if isinstance(item, str):
            source = _resolve_scenario_source(scenario, item)
            target = workspace / _default_workspace_dest(item)
            _copy_source_path(source, target)
            continue
        if "path" in item and "content" in item:
            target = workspace / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(item["content"]), encoding="utf-8")
            continue
        if "source" in item:
            source = _resolve_scenario_source(scenario, str(item["source"]))
            dest = str(item.get("dest") or item.get("path") or _default_workspace_dest(str(item["source"])))
            target = workspace / dest
            _copy_source_path(source, target)


def _workspace_file_manifest(workspace: Path) -> list[str]:
    if not workspace.exists():
        return []
    return sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*") if path.is_file())


def _restore_workspace_from_snapshot(snapshot: Path, workspace: Path) -> None:
    if not snapshot.exists():
        raise FileNotFoundError(f"Workspace snapshot not found: {snapshot}")
    shutil.copytree(snapshot, workspace, dirs_exist_ok=True)


def _run_workspace_script(scenario: Scenario, script_path: str | None, workspace: Path) -> None:
    if not script_path:
        return
    resolved = _resolve_scenario_source(scenario, script_path)
    subprocess.run(
        ["bash", str(resolved)],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
    )


def _scenario_stats(trials: list[TrialResult]) -> dict[str, Any]:
    latency_s = [trial.latency_ms / 1000.0 for trial in trials]
    input_tokens = [float(trial.token_usage.get("input_tokens", 0)) for trial in trials]
    output_tokens = [float(trial.token_usage.get("output_tokens", 0)) for trial in trials]
    cache_read_tokens = [float(trial.token_usage.get("cache_read_tokens", 0)) for trial in trials]
    cache_write_tokens = [float(trial.token_usage.get("cache_write_tokens", 0)) for trial in trials]
    accounted_total_tokens = [float(trial.token_usage.get("accounted_total_tokens", 0)) for trial in trials]
    unclassified_total_tokens = [float(trial.token_usage.get("unclassified_total_tokens", 0)) for trial in trials]
    total_tokens = [float(trial.token_usage.get("total_tokens", 0)) for trial in trials]
    costs = [
        float(trial.token_usage.get("total_cost_usd", trial.token_usage.get("cost_estimate_usd", 0.0)))
        for trial in trials
    ]
    tool_calls = [float(trial.token_usage.get("tool_calls", len(trial.tool_calls))) for trial in trials]
    execution_status_counts = dict(Counter(trial.execution.status for trial in trials))
    return {
        "time_s": aggregate_metric(latency_s),
        "input_tokens": aggregate_metric(input_tokens),
        "output_tokens": aggregate_metric(output_tokens),
        "cache_read_tokens": aggregate_metric(cache_read_tokens),
        "cache_write_tokens": aggregate_metric(cache_write_tokens),
        "accounted_total_tokens": aggregate_metric(accounted_total_tokens),
        "unclassified_total_tokens": aggregate_metric(unclassified_total_tokens),
        "total_tokens": aggregate_metric(total_tokens),
        "cost_usd": aggregate_metric(costs),
        "tool_calls": aggregate_metric(tool_calls),
        "execution_status_counts": execution_status_counts,
    }


def _scenario_live_retry_summary(result: ScenarioResult) -> dict[str, Any]:
    retries_used = 0
    retrying_trials = 0
    exhausted = False
    execution_failure = False

    for trial in result.trials:
        if trial.execution.status != "success":
            execution_failure = True
        retry_state = dict(trial.audit_state.get("live_retry", {})) if isinstance(trial.audit_state, dict) else {}
        used = int(retry_state.get("retries_used", 0) or 0)
        if used > 0:
            retrying_trials += 1
            retries_used += used
        if bool(retry_state.get("exhausted", False)):
            exhausted = True

    return {
        "retries_used": retries_used,
        "retrying_trials": retrying_trials,
        "exhausted": exhausted,
        "execution_failure": execution_failure,
    }


def _token_totals(
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> dict[str, int]:
    accounted_total_tokens = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    effective_total_tokens = max(int(total_tokens), accounted_total_tokens)
    unclassified_total_tokens = max(effective_total_tokens - accounted_total_tokens, 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "accounted_total_tokens": accounted_total_tokens,
        "unclassified_total_tokens": unclassified_total_tokens,
        "total_tokens": effective_total_tokens,
    }


def _load_replay_trace(scenario: Scenario, model: str) -> dict[str, Any]:
    path = scenario.replay_traces.get(model) or scenario.replay_traces.get("default")
    if path is None:
        raise ValueError(f"No replay trace configured for model {model!r} in scenario {scenario.scenario_id!r}")
    return json.loads(path.read_text())


def _scenario_execution_mode(result: ScenarioResult) -> str:
    if result.execution_mode:
        return result.execution_mode
    if result.trials:
        return result.trials[0].execution.mode
    return "replay"


def _scenario_has_execution_failure(result: ScenarioResult) -> bool:
    if any(trial.execution.status != "success" for trial in result.trials):
        return True
    status_counts = dict((result.stats or {}).get("execution_status_counts", {}))
    return any(status != "success" and count for status, count in status_counts.items())


def _build_execution_summary(
    scenario_results: list[ScenarioResult],
    live_preflight: LivePreflightResult | None = None,
) -> dict[str, Any]:
    trial_status_counts: Counter[str] = Counter()
    scenario_status_counts: Counter[str] = Counter()
    failures: list[dict[str, Any]] = []
    safety_failures: list[dict[str, Any]] = []

    for scenario in scenario_results:
        scenario_has_execution_failure = False
        scenario_has_safety_failure = False
        for trial in scenario.trials:
            trial_status_counts[trial.execution.status] += 1
            if trial.execution.status != "success":
                scenario_has_execution_failure = True
                failures.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "trial_id": trial.trial_id,
                        "mode": trial.execution.mode,
                        "status": trial.execution.status,
                        "exit_code": trial.execution.exit_code,
                        "error_detail": trial.execution.error_detail,
                        "agent_id": trial.execution.agent_id,
                        "session_id": trial.execution.session_id,
                    }
                )
            if not trial.safety_passed:
                scenario_has_safety_failure = True
                safety_failures.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "trial_id": trial.trial_id,
                        "mode": trial.execution.mode,
                        "status": trial.execution.status,
                        "safety_failures": list(trial.safety_failures),
                    }
                )
        if scenario_has_execution_failure and scenario_has_safety_failure:
            scenario_status_counts["execution_and_safety_failure"] += 1
        elif scenario_has_execution_failure:
            scenario_status_counts["execution_failure"] += 1
        elif scenario_has_safety_failure:
            scenario_status_counts["safety_failure"] += 1
        else:
            scenario_status_counts["success"] += 1

    summary = {
        "trial_status_counts": dict(trial_status_counts),
        "scenario_status_counts": dict(scenario_status_counts),
        "failure_count": len(failures),
        "failure_examples": failures[:10],
        "safety_failure_count": len(safety_failures),
        "safety_failure_examples": safety_failures[:10],
    }
    if live_preflight is not None:
        summary["live_preflight"] = live_preflight.to_dict()
    return summary


def _trial_outcome_label(trial: TrialResult) -> str:
    if trial.execution.status != "success":
        return "execution_failure"
    if not trial.safety_passed:
        return "safety_failure"
    if not trial.passed:
        return "threshold_miss"
    return "pass"


def _build_integrity_summary(scenario_results: list[ScenarioResult]) -> dict[str, Any]:
    zero_score_trials: list[dict[str, Any]] = []
    zero_score_scenarios: list[dict[str, Any]] = []

    for scenario in scenario_results:
        if scenario.avg_score <= ZERO_SCORE_EPSILON:
            zero_score_scenarios.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "avg_score": round(scenario.avg_score, 4),
                    "capability_score": round(scenario.capability_score, 4),
                    "execution_status_counts": dict((scenario.stats or {}).get("execution_status_counts", {})),
                    "pass_count": scenario.pass_count,
                    "trial_count": scenario.trial_count,
                    "strict_pass_k": scenario.strict_pass_k,
                }
            )
        for trial in scenario.trials:
            if trial.score > ZERO_SCORE_EPSILON:
                continue
            zero_score_trials.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "trial_id": trial.trial_id,
                    "score": round(trial.score, 4),
                    "capability_score": round(trial.capability_score, 4),
                    "status": trial.execution.status,
                    "safety_passed": trial.safety_passed,
                    "error_detail": trial.execution.error_detail,
                }
            )

    return {
        "zero_score_scenario_count": len(zero_score_scenarios),
        "zero_score_trial_count": len(zero_score_trials),
        "zero_score_scenario_examples": zero_score_scenarios[:10],
        "zero_score_trial_examples": zero_score_trials[:10],
    }


def _build_outcome_summary(scenario_results: list[ScenarioResult]) -> dict[str, Any]:
    trial_outcome_counts: Counter[str] = Counter()
    scenario_outcome_counts: Counter[str] = Counter()
    threshold_miss_examples: list[dict[str, Any]] = []

    for scenario in scenario_results:
        scenario_outcome = "pass"
        for trial in scenario.trials:
            label = _trial_outcome_label(trial)
            trial_outcome_counts[label] += 1
            if label == "execution_failure":
                scenario_outcome = "execution_failure"
            elif label == "safety_failure" and scenario_outcome == "pass":
                scenario_outcome = "safety_failure"
            elif label == "threshold_miss" and scenario_outcome == "pass":
                scenario_outcome = "threshold_miss"
            if label == "threshold_miss":
                threshold_miss_examples.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "trial_id": trial.trial_id,
                        "score": round(trial.score, 4),
                        "capability_score": round(trial.capability_score, 4),
                        "status": trial.execution.status,
                    }
                )
        scenario_outcome_counts[scenario_outcome] += 1

    return {
        "trial_outcome_counts": dict(trial_outcome_counts),
        "scenario_outcome_counts": dict(scenario_outcome_counts),
        "threshold_miss_count": trial_outcome_counts.get("threshold_miss", 0),
        "threshold_miss_examples": threshold_miss_examples[:10],
    }


def _build_coverage(scenario_results: list[ScenarioResult], overall_score: float) -> dict[str, Any]:
    covered_dimensions = sorted({item.dimension.value for item in scenario_results})
    all_dimensions = sorted(dimension.value for dimension in DIMENSION_WEIGHTS)
    missing_dimensions = [item for item in all_dimensions if item not in covered_dimensions]
    covered_weight = sum(
        DIMENSION_WEIGHTS[Dimension(name)]
        for name in covered_dimensions
    )
    normalized_score = overall_score / covered_weight if covered_weight > 0 else 0.0

    scenario_counts_by_mode: dict[str, int] = {}
    trial_counts_by_mode: dict[str, int] = {}
    for item in scenario_results:
        mode = _scenario_execution_mode(item)
        scenario_counts_by_mode[mode] = scenario_counts_by_mode.get(mode, 0) + 1
        trial_counts_by_mode[mode] = trial_counts_by_mode.get(mode, 0) + len(item.trials)

    return {
        "covered_dimensions": covered_dimensions,
        "missing_dimensions": missing_dimensions,
        "covered_dimension_count": len(covered_dimensions),
        "total_dimension_count": len(all_dimensions),
        "covered_weight": round(covered_weight, 4),
        "normalized_score_on_covered": round(normalized_score, 4),
        "scenario_counts_by_execution_mode": scenario_counts_by_mode,
        "trial_counts_by_execution_mode": trial_counts_by_mode,
    }


def _scenario_aggregate_weights(scenario_results: list[ScenarioResult]) -> tuple[dict[str, float], dict[str, float]]:
    by_dimension_weight_sum: dict[Dimension, float] = {}
    for item in scenario_results:
        by_dimension_weight_sum[item.dimension] = by_dimension_weight_sum.get(item.dimension, 0.0) + item.difficulty_weight

    raw_weights: dict[str, float] = {}
    for item in scenario_results:
        dimension_weight = DIMENSION_WEIGHTS[item.dimension]
        difficulty_share = item.difficulty_weight / by_dimension_weight_sum[item.dimension] if by_dimension_weight_sum[item.dimension] > 0 else 0.0
        raw_weights[item.scenario_id] = dimension_weight * difficulty_share

    total_weight = sum(raw_weights.values())
    normalized_weights = {
        scenario_id: (weight / total_weight if total_weight > 0 else 0.0)
        for scenario_id, weight in raw_weights.items()
    }
    return raw_weights, normalized_weights


def _build_reliability_summary(scenario_results: list[ScenarioResult]) -> dict[str, Any]:
    if not scenario_results:
        return {
            "trial_count": 0,
            "unweighted_pass_at_1": 0.0,
            "weighted_pass_at_1": 0.0,
            "unweighted_pass_at_k_any": 0.0,
            "weighted_pass_at_k_any": 0.0,
            "unweighted_pass_at_k_all": 0.0,
            "weighted_pass_at_k_all": 0.0,
            "avg_score_stddev": 0.0,
            "p95_score_stddev": 0.0,
            "avg_efficiency_drag": 0.0,
            "weighted_efficiency_drag": 0.0,
            "pass_count_histogram": {},
        }

    _, normalized_weights = _scenario_aggregate_weights(scenario_results)
    consistency_stats = aggregate_metric([item.consistency for item in scenario_results])
    efficiency_drags = {
        item.scenario_id: max(item.capability_score - item.avg_score, 0.0)
        for item in scenario_results
    }
    histogram = Counter(
        f"{item.pass_count}/{max(item.trial_count, 1)}"
        for item in scenario_results
    )

    def _weighted(getter) -> float:
        return round(sum(getter(item) * normalized_weights.get(item.scenario_id, 0.0) for item in scenario_results), 4)

    def _unweighted(getter) -> float:
        return round(sum(getter(item) for item in scenario_results) / len(scenario_results), 4)

    return {
        "trial_count": max(item.trial_count for item in scenario_results),
        "unweighted_completion_at_1": _unweighted(lambda item: item.pass_rate),
        "weighted_completion_at_1": _weighted(lambda item: item.pass_rate),
        "unweighted_completion_at_k_any": _unweighted(lambda item: 1.0 if item.pass_at_k_any else 0.0),
        "weighted_completion_at_k_any": _weighted(lambda item: 1.0 if item.pass_at_k_any else 0.0),
        "unweighted_completion_at_k_all": _unweighted(lambda item: 1.0 if item.strict_pass_k else 0.0),
        "weighted_completion_at_k_all": _weighted(lambda item: 1.0 if item.strict_pass_k else 0.0),
        "unweighted_pass_at_1": _unweighted(lambda item: item.pass_rate),
        "weighted_pass_at_1": _weighted(lambda item: item.pass_rate),
        "unweighted_pass_at_k_any": _unweighted(lambda item: 1.0 if item.pass_at_k_any else 0.0),
        "weighted_pass_at_k_any": _weighted(lambda item: 1.0 if item.pass_at_k_any else 0.0),
        "unweighted_pass_at_k_all": _unweighted(lambda item: 1.0 if item.strict_pass_k else 0.0),
        "weighted_pass_at_k_all": _weighted(lambda item: 1.0 if item.strict_pass_k else 0.0),
        "avg_score_stddev": round(consistency_stats.get("avg", 0.0), 6),
        "p95_score_stddev": round(consistency_stats.get("p95", 0.0), 6),
        "avg_efficiency_drag": _unweighted(lambda item: efficiency_drags[item.scenario_id]),
        "weighted_efficiency_drag": _weighted(lambda item: efficiency_drags[item.scenario_id]),
        "completion_count_histogram": {
            key: histogram[key]
            for key in sorted(histogram, key=lambda value: (int(value.split("/", 1)[0]), value))
        },
        "pass_count_histogram": {
            key: histogram[key]
            for key in sorted(histogram, key=lambda value: (int(value.split("/", 1)[0]), value))
        },
    }


def _build_benchmark_group_summary(scenario_results: list[ScenarioResult]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    total_weight = sum(item.difficulty_weight for item in scenario_results)
    for group_name in sorted({item.benchmark_group.value for item in scenario_results}):
        matching = [item for item in scenario_results if item.benchmark_group.value == group_name]
        weight_sum = sum(item.difficulty_weight for item in matching)
        summary[group_name] = {
            "scenario_count": len(matching),
            "weight_share": round(weight_sum / total_weight, 4) if total_weight > 0 else 0.0,
            "avg_score": round(sum(item.avg_score for item in matching) / len(matching), 4),
            "avg_capability_score": round(sum(item.capability_score for item in matching) / len(matching), 4),
        }
    return summary


def _build_benchmark_core_summary(scenario_results: list[ScenarioResult]) -> dict[str, Any]:
    if not scenario_results:
        return {}
    total_weight = sum(item.difficulty_weight for item in scenario_results)
    core_matching = [item for item in scenario_results if item.benchmark_core]
    extended_matching = [item for item in scenario_results if not item.benchmark_core]
    summary: dict[str, Any] = {}
    if core_matching:
        core_weight = sum(item.difficulty_weight for item in core_matching)
        summary["core"] = {
            "scenario_count": len(core_matching),
            "weight_share": round(core_weight / total_weight, 4) if total_weight > 0 else 0.0,
        }
    if extended_matching:
        extended_weight = sum(item.difficulty_weight for item in extended_matching)
        summary["extended"] = {
            "scenario_count": len(extended_matching),
            "weight_share": round(extended_weight / total_weight, 4) if total_weight > 0 else 0.0,
        }
    return summary


def _build_difficulty_summary(scenario_results: list[ScenarioResult]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    total_weight = sum(item.difficulty_weight for item in scenario_results)
    for difficulty in Difficulty:
        matching = [item for item in scenario_results if item.difficulty == difficulty]
        if not matching:
            continue
        weight_sum = sum(item.difficulty_weight for item in matching)
        summary[difficulty.value] = {
            "scenario_count": len(matching),
            "avg_score": round(sum(item.avg_score for item in matching) / len(matching), 4),
            "avg_capability_score": round(sum(item.capability_score for item in matching) / len(matching), 4),
            "completion_at_1": round(sum(item.pass_rate for item in matching) / len(matching), 4),
            "completion_at_k_any": round(sum(1.0 if item.pass_at_k_any else 0.0 for item in matching) / len(matching), 4),
            "completion_at_k_all": round(
                sum(1.0 if item.strict_pass_k else 0.0 for item in matching) / len(matching),
                4,
            ),
            "pass_at_1": round(sum(item.pass_rate for item in matching) / len(matching), 4),
            "pass_at_k_any": round(sum(1.0 if item.pass_at_k_any else 0.0 for item in matching) / len(matching), 4),
            "strict_pass_rate": round(
                sum(1.0 if item.strict_pass_k else 0.0 for item in matching) / len(matching),
                4,
            ),
            "avg_latency_s": round(sum(item.avg_latency_ms for item in matching) / (len(matching) * 1000.0), 4),
            "avg_total_tokens": round(
                sum(int(item.total_tokens.get("total_tokens", 0)) for item in matching) / len(matching),
                2,
            ),
            "avg_cost_usd": round(sum(item.cost_estimate_usd for item in matching) / len(matching), 8),
            "weight_share": round(weight_sum / total_weight, 4) if total_weight > 0 else 0.0,
        }
    return summary


class BenchmarkRunner:
    def __init__(
        self,
        results_dir: Path,
        execution_mode: str = "auto",
        workspace_root: Path | None = None,
        openclaw_binary: str = DEFAULT_OPENCLAW_BINARY,
        openclaw_profile: str | None = None,
        openclaw_state_dir: str | None = None,
        openclaw_config_path: str | None = None,
        openclaw_gateway_port: int | None = None,
        use_local_agent: bool = False,
        cleanup_agents: bool = False,
        parallelism: int = 1,
        allow_live_parallelism: bool = False,
        live_retry_attempts: int = 0,
        show_progress: bool = True,
        progress_interval_seconds: int = 60,
    ):
        if parallelism < 1:
            raise ValueError("parallelism must be >= 1")
        if live_retry_attempts < 0:
            raise ValueError("live_retry_attempts must be >= 0")
        if openclaw_gateway_port is not None and int(openclaw_gateway_port) <= 0:
            raise ValueError("openclaw_gateway_port must be > 0")
        self.results_dir = results_dir
        self.execution_mode = execution_mode
        self.workspace_root = workspace_root
        self.openclaw_binary = openclaw_binary
        os.environ["OPENCLAW_BINARY"] = openclaw_binary
        self.openclaw_profile = str(openclaw_profile or "").strip() or None
        self.openclaw_state_dir = str(openclaw_state_dir or "").strip() or None
        self.openclaw_config_path = str(openclaw_config_path or "").strip() or None
        self.openclaw_gateway_port = int(openclaw_gateway_port) if openclaw_gateway_port else None
        self.use_local_agent = use_local_agent
        self.parallelism = parallelism
        self.allow_live_parallelism = allow_live_parallelism
        self.live_retry_attempts = live_retry_attempts
        self.show_progress = show_progress
        self.progress_interval_seconds = max(progress_interval_seconds, 1)
        self.live_harness = OpenClawLiveHarness(
            openclaw_bin=openclaw_binary,
            cleanup_agents=cleanup_agents,
            use_local_agent=use_local_agent,
            openclaw_profile=self.openclaw_profile,
            openclaw_state_dir=self.openclaw_state_dir,
            openclaw_config_path=self.openclaw_config_path,
            openclaw_gateway_port=self.openclaw_gateway_port,
            progress_callback=self._progress,
            progress_interval_seconds=self.progress_interval_seconds,
            agent_pool_size=parallelism if allow_live_parallelism and parallelism > 1 else 0,
        )
        self._active_live_preflight: LivePreflightResult | None = None

    def close(self) -> None:
        self.live_harness.close()

    def run(
        self,
        model: str,
        scenarios: list[Scenario],
        trials: int = 3,
        benchmark_profile: str = "custom",
    ) -> BenchmarkResult:
        return self.run_with_resume(
            model=model,
            scenarios=scenarios,
            trials=trials,
            existing_result=None,
            benchmark_profile=benchmark_profile,
        )

    def run_with_resume(
        self,
        model: str,
        scenarios: list[Scenario],
        trials: int = 3,
        existing_result: BenchmarkResult | None = None,
        rerun_execution_failures: bool = False,
        benchmark_profile: str = "custom",
        checkpoint_path: Path | None = None,
    ) -> BenchmarkResult:
        pricing = _load_pricing(model)
        requested_ids = {scenario.scenario_id for scenario in scenarios}
        existing_by_id: dict[str, ScenarioResult] = {}
        rerun_pending_count = 0
        if existing_result and _normalize_resume_model(existing_result.model) == _normalize_resume_model(model):
            for item in existing_result.scenarios:
                if item.scenario_id not in requested_ids or len(item.trials) < trials:
                    continue
                if rerun_execution_failures and _scenario_has_execution_failure(item):
                    rerun_pending_count += 1
                    continue
                existing_by_id[item.scenario_id] = item

        pending_scenarios = [scenario for scenario in scenarios if scenario.scenario_id not in existing_by_id]
        self._progress(
            "run-start "
            f"profile={benchmark_profile} "
            f"requested={len(scenarios)} "
            f"reused={len(existing_by_id)} "
            f"pending={len(pending_scenarios)} "
            f"rerun_execution_failures={rerun_pending_count} "
            f"mode={self.execution_mode}"
        )

        scenario_results_by_id: dict[str, ScenarioResult] = dict(existing_by_id)

        def _checkpoint(result: ScenarioResult) -> None:
            scenario_results_by_id[result.scenario_id] = result
            if checkpoint_path is None:
                return
            ordered = [
                scenario_results_by_id[scenario.scenario_id]
                for scenario in scenarios
                if scenario.scenario_id in scenario_results_by_id
            ]
            partial = self._build_benchmark_result(
                model=model,
                scenario_results=ordered,
                trials=trials,
                reused_count=len(existing_by_id),
                total_requested=len(scenarios),
                resume_source=existing_result.summary.get("report_path", "") if existing_result else "",
                rerun_execution_failures=rerun_execution_failures,
                rerun_execution_failure_count=rerun_pending_count,
                benchmark_profile=benchmark_profile,
                checkpoint_path=checkpoint_path,
            )
            write_report(partial, checkpoint_path)
            self._progress(
                "checkpoint "
                f"completed={len(ordered)}/{len(scenarios)} "
                f"remaining={max(len(scenarios) - len(ordered), 0)} "
                f"path={checkpoint_path.name}"
            )

        pending_results, parallel_summary, live_preflight = self._run_pending_scenarios(
            model=model,
            scenarios=pending_scenarios,
            trials=trials,
            pricing=pricing,
            total_requested=len(scenarios),
            completed_offset=len(existing_by_id),
            on_scenario_complete=_checkpoint,
        )

        scenario_results: list[ScenarioResult] = []
        for scenario in scenarios:
            cached = existing_by_id.get(scenario.scenario_id)
            if cached is not None:
                scenario_results.append(cached)
                continue
            scenario_results.append(pending_results[scenario.scenario_id])

        return self._build_benchmark_result(
            model=model,
            scenario_results=scenario_results,
            trials=trials,
            reused_count=len(existing_by_id),
            total_requested=len(scenarios),
            resume_source=existing_result.summary.get("report_path", "") if existing_result else "",
            rerun_execution_failures=rerun_execution_failures,
            rerun_execution_failure_count=rerun_pending_count,
            parallel_summary=parallel_summary,
            live_preflight=live_preflight,
            benchmark_profile=benchmark_profile,
            checkpoint_path=checkpoint_path,
        )

    def _build_benchmark_result(
        self,
        model: str,
        scenario_results: list[ScenarioResult],
        trials: int,
        reused_count: int = 0,
        total_requested: int | None = None,
        resume_source: str = "",
        rerun_execution_failures: bool = False,
        rerun_execution_failure_count: int = 0,
        parallel_summary: dict[str, Any] | None = None,
        live_preflight: LivePreflightResult | None = None,
        benchmark_profile: str = "custom",
        checkpoint_path: Path | None = None,
    ) -> BenchmarkResult:
        total_requested = total_requested if total_requested is not None else len(scenario_results)

        dimension_scores: dict[str, DimensionScore] = {}
        for dimension_name in sorted({item.dimension for item in scenario_results}, key=lambda value: value.value):
            matching = [item for item in scenario_results if item.dimension == dimension_name]
            weighted = sum(item.avg_score * item.difficulty_weight for item in matching)
            capability_weighted = sum(item.capability_score * item.difficulty_weight for item in matching)
            weights = sum(item.difficulty_weight for item in matching)
            score = weighted / weights if weights else 0.0
            strict_pass_rate = sum(1.0 if item.strict_pass_k else 0.0 for item in matching) / len(matching)
            dimension_scores[dimension_name.value] = DimensionScore(
                dimension=dimension_name,
                score=round(score, 4),
                capability_score=round(capability_weighted / weights, 4) if weights else 0.0,
                scenario_count=len(matching),
                pass_at_1=round(sum(item.pass_rate for item in matching) / len(matching), 4),
                pass_at_k_any=round(sum(1.0 if item.pass_at_k_any else 0.0 for item in matching) / len(matching), 4),
                strict_pass_rate=round(strict_pass_rate, 4),
            )

        overall_score = 0.0
        capability_score = 0.0
        for dimension_score in dimension_scores.values():
            overall_score += dimension_score.score * DIMENSION_WEIGHTS[dimension_score.dimension]
            capability_score += dimension_score.capability_score * DIMENSION_WEIGHTS[dimension_score.dimension]

        all_trials = [trial for scenario in scenario_results for trial in scenario.trials]
        efficiency_scores = [trial.efficiency_score for trial in all_trials]
        all_latencies = [trial.latency_ms for trial in all_trials]
        total_input = sum(item.total_tokens["input_tokens"] for item in scenario_results)
        total_output = sum(item.total_tokens["output_tokens"] for item in scenario_results)
        total_cache_read = sum(int(item.total_tokens.get("cache_read_tokens", 0)) for item in scenario_results)
        total_cache_write = sum(int(item.total_tokens.get("cache_write_tokens", 0)) for item in scenario_results)
        total_accounted = sum(int(item.total_tokens.get("accounted_total_tokens", 0)) for item in scenario_results)
        total_unclassified = sum(int(item.total_tokens.get("unclassified_total_tokens", 0)) for item in scenario_results)
        total_tokens = sum(item.total_tokens["total_tokens"] for item in scenario_results)
        total_cost = sum(item.cost_estimate_usd for item in scenario_results)

        time_values = [trial.latency_ms / 1000.0 for trial in all_trials]
        input_values = [float(trial.token_usage.get("input_tokens", 0)) for trial in all_trials]
        output_values = [float(trial.token_usage.get("output_tokens", 0)) for trial in all_trials]
        cache_read_values = [float(trial.token_usage.get("cache_read_tokens", 0)) for trial in all_trials]
        cache_write_values = [float(trial.token_usage.get("cache_write_tokens", 0)) for trial in all_trials]
        accounted_total_values = [float(trial.token_usage.get("accounted_total_tokens", 0)) for trial in all_trials]
        unclassified_total_values = [float(trial.token_usage.get("unclassified_total_tokens", 0)) for trial in all_trials]
        total_token_values = [float(trial.token_usage.get("total_tokens", 0)) for trial in all_trials]
        cost_values = [
            float(trial.token_usage.get("total_cost_usd", trial.token_usage.get("cost_estimate_usd", 0.0)))
            for trial in all_trials
        ]
        tool_call_values = [float(trial.token_usage.get("tool_calls", len(trial.tool_calls))) for trial in all_trials]
        input_cost_total = sum(float(trial.token_usage.get("input_cost_usd", 0.0)) for trial in all_trials)
        output_cost_total = sum(float(trial.token_usage.get("output_cost_usd", 0.0)) for trial in all_trials)
        cache_cost_total = sum(
            float(trial.token_usage.get("cache_read_cost_usd", 0.0))
            + float(trial.token_usage.get("cache_write_cost_usd", 0.0))
            for trial in all_trials
        )
        slowest = max(scenario_results, key=lambda item: item.avg_latency_ms, default=None)
        fastest = min(scenario_results, key=lambda item: item.avg_latency_ms, default=None)
        priciest = max(scenario_results, key=lambda item: item.cost_estimate_usd, default=None)
        reliability_summary = _build_reliability_summary(scenario_results)
        aggregate_stats = {
            "time_s": aggregate_metric(time_values),
            "input_tokens": aggregate_metric(input_values),
            "output_tokens": aggregate_metric(output_values),
            "cache_read_tokens": aggregate_metric(cache_read_values),
            "cache_write_tokens": aggregate_metric(cache_write_values),
            "accounted_total_tokens": aggregate_metric(accounted_total_values),
            "unclassified_total_tokens": aggregate_metric(unclassified_total_values),
            "total_tokens": aggregate_metric(total_token_values),
            "cost_usd": aggregate_metric(cost_values),
            "tool_calls": aggregate_metric(tool_call_values),
        }
        cost_efficiency = {
            "score_per_dollar": round(overall_score / total_cost, 4) if total_cost > 0 else 0.0,
            "score_per_1k_tokens": round(overall_score / (total_tokens / 1000.0), 6) if total_tokens > 0 else 0.0,
            "tokens_per_point": round(total_tokens / overall_score, 2) if overall_score > 0 else 0.0,
            "duration_top5": [
                {
                    "scenario_id": item.scenario_id,
                    "difficulty": item.difficulty.value,
                    "wall_time_s": round(item.avg_latency_ms / 1000.0, 4),
                }
                for item in sorted(scenario_results, key=lambda value: value.avg_latency_ms, reverse=True)[:5]
            ],
            "cost_top5": [
                {
                    "scenario_id": item.scenario_id,
                    "difficulty": item.difficulty.value,
                    "cost_usd": round(item.cost_estimate_usd, 8),
                    "tokens": int(item.total_tokens.get("total_tokens", 0)),
                }
                for item in sorted(scenario_results, key=lambda value: value.cost_estimate_usd, reverse=True)[:5]
            ],
        }
        summary = {
            "benchmark_selection": {
                "profile": benchmark_profile,
                "scenario_count": len(scenario_results),
            },
            "progress": {
                "completed_scenarios": len(scenario_results),
                "requested_scenarios": total_requested,
                "remaining_scenarios": max(total_requested - len(scenario_results), 0),
                "checkpoint_path": str(checkpoint_path) if checkpoint_path else "",
            },
            "total_scenarios": len(scenario_results),
            "total_trials": len(all_trials),
            "transcript_coverage": {
                "trials_with_transcript": sum(1 for t in all_trials if t.transcript),
                "trials_missing_transcript": sum(1 for t in all_trials if not t.transcript),
                "coverage_ratio": round(
                    sum(1 for t in all_trials if t.transcript) / len(all_trials), 4
                ) if all_trials else 0.0,
            },
            "total_wall_time_s": round(sum(time_values), 4),
            "total_tokens": int(total_tokens),
            "total_cost_usd": round(total_cost, 8),
            "avg_time_per_scenario_s": round(sum(time_values) / len(scenario_results), 4) if scenario_results else 0.0,
            "slowest_scenario": slowest.scenario_id if slowest else "",
            "slowest_time_s": round((slowest.avg_latency_ms / 1000.0), 4) if slowest else 0.0,
            "fastest_scenario": fastest.scenario_id if fastest else "",
            "fastest_time_s": round((fastest.avg_latency_ms / 1000.0), 4) if fastest else 0.0,
            "avg_tokens_per_scenario": round(total_tokens / len(scenario_results), 2) if scenario_results else 0.0,
            "most_expensive_scenario": priciest.scenario_id if priciest else "",
            "most_expensive_tokens": int(priciest.total_tokens.get("total_tokens", 0)) if priciest else 0,
            "avg_cost_per_scenario": round(total_cost / len(scenario_results), 8) if scenario_results else 0.0,
            "score_views": {
                "capability_score": round(capability_score, 4),
                "efficiency_adjusted_score": round(overall_score, 4),
                "efficiency_drag": round(max(capability_score - overall_score, 0.0), 4),
            },
            "reliability": reliability_summary,
            "cost_breakdown": {
                "input_cost_usd": round(input_cost_total, 8),
                "output_cost_usd": round(output_cost_total, 8),
                "cache_cost_usd": round(cache_cost_total, 8),
            },
            "difficulty_summary": _build_difficulty_summary(scenario_results),
            "benchmark_groups": _build_benchmark_group_summary(scenario_results),
            "benchmark_core": _build_benchmark_core_summary(scenario_results),
        }
        coverage = _build_coverage(scenario_results, overall_score)
        execution_summary = _build_execution_summary(scenario_results, live_preflight=live_preflight)
        integrity_summary = _build_integrity_summary(scenario_results)
        outcome_summary = _build_outcome_summary(scenario_results)
        if any(_scenario_execution_mode(item) == "live" for item in scenario_results):
            summary["openclaw_runtime"] = _collect_openclaw_runtime_provenance(
                self.openclaw_binary,
                env=self.live_harness.command_env,
            )
            summary["openclaw_isolation"] = self.live_harness.isolation_metadata()
        if coverage:
            summary["covered_weight"] = coverage["covered_weight"]
            summary["normalized_score_on_covered"] = coverage["normalized_score_on_covered"]
            summary["normalized_capability_score_on_covered"] = round(
                capability_score / coverage["covered_weight"],
                4,
            ) if coverage["covered_weight"] > 0 else 0.0
        summary["execution"] = execution_summary
        summary["outcomes"] = outcome_summary
        summary["integrity"] = integrity_summary
        if parallel_summary:
            summary["parallel"] = dict(parallel_summary)
        summary["report_path"] = ""
        resume = {
            "resumed": reused_count > 0,
            "source_report": resume_source,
            "reused_scenarios": reused_count,
            "new_scenarios": max(total_requested - reused_count, 0),
        }
        if rerun_execution_failures or rerun_execution_failure_count:
            resume["rerun_execution_failures"] = rerun_execution_failures
            resume["rerun_execution_failure_scenarios"] = rerun_execution_failure_count

        return BenchmarkResult(
            model=model,
            dimensions=dimension_scores,
            overall_score=round(overall_score, 4),
            capability_score=round(capability_score, 4),
            efficiency_score=round(sum(efficiency_scores) / len(efficiency_scores), 4) if efficiency_scores else 0.0,
            total_scenarios=len(scenario_results),
            passed_scenarios=sum(1 for item in scenario_results if item.avg_score >= 0.6),
            strict_pass_rate=round(sum(1.0 if item.strict_pass_k else 0.0 for item in scenario_results) / len(scenario_results), 4) if scenario_results else 0.0,
            avg_latency_ms=round(sum(all_latencies) / len(all_latencies), 2) if all_latencies else 0.0,
            total_tokens={
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cache_read_tokens": total_cache_read,
                "cache_write_tokens": total_cache_write,
                "accounted_total_tokens": total_accounted,
                "unclassified_total_tokens": total_unclassified,
                "total_tokens": total_tokens,
            },
            cost_estimate_usd=round(total_cost, 8),
            timestamp=datetime.now(timezone.utc).isoformat(),
            scenarios=scenario_results,
            trials_per_scenario=trials,
            aggregate_stats=aggregate_stats,
            cost_efficiency=cost_efficiency,
            coverage=coverage,
            resume=resume,
            summary=summary,
        )

    def _run_pending_scenarios(
        self,
        model: str,
        scenarios: list[Scenario],
        trials: int,
        pricing: dict[str, float],
        total_requested: int,
        completed_offset: int = 0,
        on_scenario_complete=None,
    ) -> tuple[dict[str, ScenarioResult], dict[str, Any], LivePreflightResult | None]:
        results_by_id: dict[str, ScenarioResult] = {}
        replay_scenarios: list[Scenario] = []
        live_scenarios: list[Scenario] = []
        for scenario in scenarios:
            if self._resolve_execution_mode(scenario) == "live":
                live_scenarios.append(scenario)
            else:
                replay_scenarios.append(scenario)

        replay_workers = min(self.parallelism, len(replay_scenarios)) if replay_scenarios else 0
        requested_live_workers = min(self.parallelism, len(live_scenarios)) if live_scenarios else 0
        started_count = completed_offset
        if replay_workers > 1:
            with ThreadPoolExecutor(max_workers=replay_workers) as executor:
                future_to_id = {
                    executor.submit(self._run_scenario, model, scenario, trials, pricing): scenario.scenario_id
                    for scenario in replay_scenarios
                }
                for scenario in replay_scenarios:
                    started_count += 1
                    self._progress(
                        f"[{started_count}/{total_requested}] start scenario={scenario.scenario_id} "
                        f"mode={self._resolve_execution_mode(scenario)} difficulty={scenario.difficulty.value}"
                    )
                for future in as_completed(future_to_id):
                    result = future.result()
                    results_by_id[future_to_id[future]] = result
                    self._progress_scenario_complete(
                        result,
                        completed=completed_offset + len(results_by_id),
                        total=total_requested,
                    )
                    if on_scenario_complete is not None:
                        on_scenario_complete(result)
        else:
            for scenario in replay_scenarios:
                started_count += 1
                self._progress(
                    f"[{started_count}/{total_requested}] start scenario={scenario.scenario_id} "
                    f"mode={self._resolve_execution_mode(scenario)} difficulty={scenario.difficulty.value}"
                )
                result = self._run_scenario(model, scenario, trials, pricing)
                results_by_id[scenario.scenario_id] = result
                self._progress_scenario_complete(
                    result,
                    completed=completed_offset + len(results_by_id),
                    total=total_requested,
                )
                if on_scenario_complete is not None:
                        on_scenario_complete(result)

        live_preflight = self.live_harness.preflight() if live_scenarios else None
        live_workers = min(requested_live_workers, len(live_scenarios)) if live_scenarios else 0
        live_initial_workers = live_workers
        live_final_workers = live_workers
        live_backoff_events: list[dict[str, Any]] = []
        pressure_rerun_count = 0
        if live_preflight is not None:
            self._progress(
                "live-preflight "
                f"ok={live_preflight.ok} "
                f"exit_code={live_preflight.exit_code} "
                f"duration_s={live_preflight.duration_seconds:.2f}"
            )
        live_initial_workers = live_workers
        previous_live_preflight = self._active_live_preflight
        self._active_live_preflight = live_preflight
        try:
            if live_workers > 1:
                active_live_workers = live_workers
                retry_pressure_budget = 0
                pending_live = deque(live_scenarios)
                pressure_rerun_counts: dict[str, int] = {}
                pressure_rerun_history: dict[str, list[dict[str, Any]]] = {}
                pressure_rerun_count = 0
                with ThreadPoolExecutor(max_workers=live_workers) as executor:
                    future_to_state: dict[Any, tuple[Scenario, int]] = {}

                    def _submit_live_until_capacity() -> None:
                        nonlocal started_count
                        while pending_live and len(future_to_state) < active_live_workers:
                            scenario = pending_live.popleft()
                            rerun_count = pressure_rerun_counts.get(scenario.scenario_id, 0)
                            future = executor.submit(self._run_scenario, model, scenario, trials, pricing)
                            future_to_state[future] = (scenario, rerun_count)
                            if rerun_count > 0:
                                self._progress(
                                    "live-rerun-start "
                                    f"scenario={scenario.scenario_id} "
                                    f"rerun={rerun_count} "
                                    f"mode={self._resolve_execution_mode(scenario)} "
                                    f"difficulty={scenario.difficulty.value}"
                                )
                            else:
                                started_count += 1
                                self._progress(
                                    f"[{started_count}/{total_requested}] start scenario={scenario.scenario_id} "
                                    f"mode={self._resolve_execution_mode(scenario)} difficulty={scenario.difficulty.value}"
                                )

                    _submit_live_until_capacity()
                    while future_to_state:
                        done, _ = wait(set(future_to_state), return_when=FIRST_COMPLETED)
                        for future in done:
                            scenario, pressure_reruns_used = future_to_state.pop(future)
                            result = future.result()
                            retry_summary = _scenario_live_retry_summary(result)
                            if retry_summary["execution_failure"] or retry_summary["exhausted"]:
                                retry_pressure_budget = max(retry_pressure_budget, 2)
                            elif retry_summary["retrying_trials"] > 0:
                                retry_pressure_budget += retry_summary["retrying_trials"]

                            if active_live_workers > 1 and retry_pressure_budget >= 2:
                                previous_workers = active_live_workers
                                active_live_workers -= 1
                                retry_pressure_budget = 0
                                reason = "execution_failure" if retry_summary["execution_failure"] else (
                                    "retry_exhausted" if retry_summary["exhausted"] else "retry_pressure"
                                )
                                backoff_event = {
                                    "scenario_id": result.scenario_id,
                                    "from_workers": previous_workers,
                                    "to_workers": active_live_workers,
                                    "reason": reason,
                                    "retries_used": retry_summary["retries_used"],
                                }
                                live_backoff_events.append(backoff_event)
                                self._progress(
                                    "live-backoff "
                                    f"scenario={result.scenario_id} "
                                    f"from={previous_workers} "
                                    f"to={active_live_workers} "
                                    f"reason={reason}"
                                )

                            should_pressure_rerun = (
                                retry_summary["execution_failure"]
                                and active_live_workers < live_initial_workers
                                and pressure_reruns_used < 1
                            )
                            if should_pressure_rerun:
                                pressure_rerun_counts[scenario.scenario_id] = pressure_reruns_used + 1
                                pressure_rerun_count += 1
                                pressure_rerun_history.setdefault(scenario.scenario_id, []).append(
                                    {
                                        "attempt": pressure_reruns_used + 1,
                                        "workers_after_backoff": active_live_workers,
                                        "status_counts": dict(result.stats.get("execution_status_counts", {})),
                                        "avg_score": result.avg_score,
                                        "capability_score": result.capability_score,
                                    }
                                )
                                pending_live.appendleft(scenario)
                                self._progress(
                                    "live-rerun "
                                    f"scenario={scenario.scenario_id} "
                                    f"rerun={pressure_rerun_counts[scenario.scenario_id]} "
                                    f"workers={active_live_workers}"
                                )
                                continue

                            if scenario.scenario_id in pressure_rerun_history:
                                for trial in result.trials:
                                    trial.audit_state = dict(trial.audit_state)
                                    trial.audit_state["live_parallel_rerun"] = {
                                        "count": pressure_rerun_counts.get(scenario.scenario_id, 0),
                                        "history": list(pressure_rerun_history.get(scenario.scenario_id, [])),
                                    }

                            results_by_id[scenario.scenario_id] = result
                            self._progress_scenario_complete(
                                result,
                                completed=completed_offset + len(results_by_id),
                                total=total_requested,
                            )
                            if on_scenario_complete is not None:
                                on_scenario_complete(result)

                        _submit_live_until_capacity()
                live_final_workers = active_live_workers
            else:
                for scenario in live_scenarios:
                    started_count += 1
                    self._progress(
                        f"[{started_count}/{total_requested}] start scenario={scenario.scenario_id} "
                        f"mode={self._resolve_execution_mode(scenario)} difficulty={scenario.difficulty.value}"
                    )
                    result = self._run_scenario(model, scenario, trials, pricing)
                    results_by_id[scenario.scenario_id] = result
                    self._progress_scenario_complete(
                        result,
                        completed=completed_offset + len(results_by_id),
                        total=total_requested,
                    )
                    if on_scenario_complete is not None:
                        on_scenario_complete(result)
                live_final_workers = live_workers
        finally:
            self._active_live_preflight = previous_live_preflight

        parallel_summary = {
            "requested_workers": self.parallelism,
            "replay_workers": replay_workers or (1 if replay_scenarios else 0),
            "live_workers": live_initial_workers,
            "live_initial_workers": live_initial_workers,
            "live_final_workers": live_final_workers,
            "replay_scenarios": len(replay_scenarios),
            "live_scenarios": len(live_scenarios),
            "live_execution_serialized": bool(live_scenarios and live_initial_workers <= 1),
            "live_parallelism_enabled": bool(live_scenarios and self.allow_live_parallelism),
            "live_retry_attempts": self.live_retry_attempts,
            "live_backoff_count": len(live_backoff_events),
            "live_pressure_rerun_count": pressure_rerun_count if live_scenarios else 0,
        }
        if live_backoff_events:
            parallel_summary["live_backoff_events"] = live_backoff_events
        return results_by_id, parallel_summary, live_preflight

    def _progress(self, message: str) -> None:
        if not self.show_progress:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}", flush=True)

    def _progress_scenario_complete(self, result: ScenarioResult, *, completed: int, total: int) -> None:
        status_counts = result.stats.get("execution_status_counts", {}) if result.stats else {}
        status_label = ",".join(f"{key}={value}" for key, value in sorted(status_counts.items())) or "unknown"
        self._progress(
            f"[{completed}/{total}] done scenario={result.scenario_id} "
            f"avg={result.avg_score:.4f} best={result.max_score:.4f} capability={result.capability_score:.4f} "
            f"pass={result.pass_count}/{result.trial_count} "
            f"time_s={result.avg_latency_ms / 1000.0:.2f} "
            f"status={status_label}"
        )

    def _run_scenario(
        self,
        model: str,
        scenario: Scenario,
        trials: int,
        pricing: dict[str, float],
    ) -> ScenarioResult:
        trial_results: list[TrialResult] = []
        for trial_id in range(1, trials + 1):
            trial_results.append(self._run_trial(model, scenario, trial_id, pricing))
        return self._build_scenario_result(scenario, trial_results)

    def _build_scenario_result(self, scenario: Scenario, trial_results: list[TrialResult]) -> ScenarioResult:
        scores = [trial.score for trial in trial_results]
        capability_scores = [trial.capability_score for trial in trial_results]
        passes = [1.0 if trial.passed else 0.0 for trial in trial_results]
        latencies = [trial.latency_ms for trial in trial_results]
        total_input = sum(int(trial.token_usage.get("input_tokens", 0)) for trial in trial_results)
        total_output = sum(int(trial.token_usage.get("output_tokens", 0)) for trial in trial_results)
        total_cache_read = sum(int(trial.token_usage.get("cache_read_tokens", 0)) for trial in trial_results)
        total_cache_write = sum(int(trial.token_usage.get("cache_write_tokens", 0)) for trial in trial_results)
        total_accounted = sum(int(trial.token_usage.get("accounted_total_tokens", 0)) for trial in trial_results)
        total_unclassified = sum(int(trial.token_usage.get("unclassified_total_tokens", 0)) for trial in trial_results)
        total_tokens = sum(int(trial.token_usage.get("total_tokens", 0)) for trial in trial_results)
        total_cost = sum(
            float(trial.token_usage.get("total_cost_usd", trial.token_usage.get("cost_estimate_usd", 0.0)))
            for trial in trial_results
        )
        pass_count = sum(1 for trial in trial_results if trial.passed)
        trial_count = len(trial_results)
        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            name=scenario.name,
            dimension=scenario.dimension,
            difficulty=scenario.difficulty,
            benchmark_group=scenario.benchmark_group,
            benchmark_core=scenario.benchmark_core,
            trials=trial_results,
            avg_score=round(sum(scores) / len(scores), 4),
            max_score=round(max(scores), 4),
            capability_score=round(sum(capability_scores) / len(capability_scores), 4),
            pass_rate=round(sum(passes) / len(passes), 4),
            pass_at_k_any=pass_count > 0,
            pass_count=pass_count,
            trial_count=trial_count,
            strict_pass_k=pass_count == trial_count,
            consistency=round(statistics.pstdev(scores), 6) if len(scores) > 1 else 0.0,
            avg_latency_ms=round(sum(latencies) / len(latencies), 2),
            total_tokens={
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cache_read_tokens": total_cache_read,
                "cache_write_tokens": total_cache_write,
                "accounted_total_tokens": total_accounted,
                "unclassified_total_tokens": total_unclassified,
                "total_tokens": total_tokens,
            },
            cost_estimate_usd=round(total_cost, 8),
            difficulty_weight=scenario.effective_weight,
            execution_mode=self._resolve_execution_mode(scenario),
            stats=_scenario_stats(trial_results),
        )

    def _resolve_execution_mode(self, scenario: Scenario) -> str:
        if self.execution_mode in {"replay", "live"}:
            return self.execution_mode
        if scenario.execution_mode == "live" or not scenario.replay_traces:
            return "live"
        return "replay"

    def _run_trial(
        self,
        model: str,
        scenario: Scenario,
        trial_id: int,
        pricing: dict[str, float],
    ) -> TrialResult:
        execution_mode = self._resolve_execution_mode(scenario)
        if execution_mode != "live":
            return self._run_trial_once(model, scenario, trial_id, pricing, execution_mode=execution_mode)

        max_attempts = self.live_retry_attempts + 1
        attempts: list[dict[str, Any]] = []
        final_trial: TrialResult | None = None
        for attempt_index in range(1, max_attempts + 1):
            trial = self._run_trial_once(model, scenario, trial_id, pricing, execution_mode=execution_mode)
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": trial.execution.status,
                    "exit_code": trial.execution.exit_code,
                    "error_detail": trial.execution.error_detail,
                    "latency_ms": round(trial.latency_ms, 2),
                    "workspace_path": trial.workspace_path,
                }
            )
            final_trial = trial
            should_retry = attempt_index < max_attempts and self._should_retry_live_trial(trial)
            if not should_retry:
                break
            self._progress(
                "live-retry "
                f"scenario={scenario.scenario_id} "
                f"trial={trial_id} "
                f"next_attempt={attempt_index + 1}/{max_attempts} "
                f"status={trial.execution.status} "
                f"detail={trial.execution.error_detail[:120]}"
            )

        if final_trial is None:  # pragma: no cover - defensive
            raise RuntimeError(f"Live trial did not produce a result for {scenario.scenario_id}")

        final_trial.audit_state = dict(final_trial.audit_state)
        final_trial.audit_state["live_retry"] = {
            "enabled": self.live_retry_attempts > 0,
            "max_attempts": max_attempts,
            "attempt_count": len(attempts),
            "retries_used": max(len(attempts) - 1, 0),
            "exhausted": bool(
                attempts
                and len(attempts) == max_attempts
                and self._should_retry_live_trial(final_trial)
            ),
            "attempts": attempts,
        }
        return final_trial

    def _should_retry_live_trial(self, trial: TrialResult) -> bool:
        if trial.execution.mode != "live":
            return False
        if self._active_live_preflight is not None and not self._active_live_preflight.ok:
            return False
        return trial.execution.status in {"error", "timeout"}

    def _should_use_local_agent_for_live_trial(
        self,
        scenario: Scenario,
        *,
        execution_mode: str,
        expected_workspace_files: list[str],
    ) -> bool:
        if execution_mode != "live":
            return False
        if self.use_local_agent:
            return True
        return scenario.signal_source == SignalSource.WORKSPACE_LIVE and bool(expected_workspace_files)

    def _run_trial_once(
        self,
        model: str,
        scenario: Scenario,
        trial_id: int,
        pricing: dict[str, float],
        *,
        execution_mode: str,
    ) -> TrialResult:
        workspace_parent = str(self.workspace_root) if self.workspace_root else None
        with tempfile.TemporaryDirectory(prefix=f"openclawprobench_{scenario.scenario_id}_", dir=workspace_parent) as workspace_dir:
            workspace = Path(workspace_dir)
            _copy_workspace_files(scenario, workspace)
            _run_workspace_script(scenario, scenario.setup_script, workspace)
            live_result = None
            workspace_snapshot_dir: tempfile.TemporaryDirectory[str] | None = None
            try:
                trace: dict[str, Any]
                execution = TrialExecution(mode=execution_mode)
                if execution_mode == "live":
                    if self._active_live_preflight is not None and not self._active_live_preflight.ok:
                        live_result = self._preflight_failure_live_result(self._active_live_preflight)
                    else:
                        expected_workspace_files = _workspace_file_manifest(workspace)
                        use_local_agent = self._should_use_local_agent_for_live_trial(
                            scenario,
                            execution_mode=execution_mode,
                            expected_workspace_files=expected_workspace_files,
                        )
                        restore_workspace = None
                        if expected_workspace_files:
                            workspace_snapshot_dir = tempfile.TemporaryDirectory(
                                prefix=f"openclawprobench_{scenario.scenario_id}_prepared_",
                                dir=workspace_parent,
                            )
                            shutil.copytree(workspace, workspace_snapshot_dir.name, dirs_exist_ok=True)

                            def restore_workspace(target_workspace: Path, *, snapshot_dir: str = workspace_snapshot_dir.name) -> None:
                                _restore_workspace_from_snapshot(Path(snapshot_dir), target_workspace)

                        live_result = self.live_harness.execute_turn(
                            model=model,
                            prompt=scenario.prompt,
                            workspace_path=workspace,
                            timeout=scenario.timeout_seconds,
                            expected_workspace_files=expected_workspace_files,
                            repair_workspace=restore_workspace,
                            use_local_agent=use_local_agent,
                        )
                    trace = live_result.trace
                    execution.status = live_result.status
                    execution.exit_code = live_result.exit_code
                    execution.error_detail = live_result.error_detail
                    execution.agent_id = live_result.agent_id
                    execution.session_id = live_result.session_id
                    metrics = dict(trace.get("metrics", {}))
                    metrics.setdefault("wall_time_s", round(live_result.duration_seconds, 2))
                    metrics.setdefault("duration_seconds", round(live_result.duration_seconds, 2))
                    trace["metrics"] = metrics
                    if scenario.signal_source.value == "openclaw_native" and scenario.openclaw_surfaces:
                        audit_state = dict(trace.get("audit_state", {}))
                        audit_state["native_environment"] = collect_native_environment_snapshot(
                            scenario.openclaw_surfaces,
                            openclaw_bin=self.live_harness.openclaw_bin,
                            env=self.live_harness.command_env,
                        )
                        trace["audit_state"] = audit_state
                else:
                    trace = _load_replay_trace(scenario, model)

                metrics = dict(trace.get("metrics", {}))
                input_tokens = int(metrics.get("input_tokens", 0))
                output_tokens = int(metrics.get("output_tokens", 0))
                cache_read_tokens = int(metrics.get("cache_read_tokens", 0))
                cache_write_tokens = int(metrics.get("cache_write_tokens", 0))
                token_totals = _token_totals(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=int(metrics.get("total_tokens", 0)),
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                )
                costs = _estimate_costs(
                    pricing,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                )
                metrics.update(costs)
                metrics["cost_estimate_usd"] = costs["total_cost_usd"]
                trace["metrics"] = metrics

                breakdown = grade_scenario(scenario, workspace, trace)
                tool_calls = [event for event in trace.get("events", []) if event.get("type") == "tool_call"]
                latency_ms = float(metrics.get("wall_time_s", metrics.get("duration_seconds", 0.0))) * 1000.0
                passed = (
                    execution.status == "success"
                    and breakdown.final_score >= scenario.pass_threshold
                    and breakdown.safety_passed
                )
                return TrialResult(
                    trial_id=trial_id,
                    score=breakdown.final_score,
                    capability_score=breakdown.capability_score,
                    passed=passed,
                    safety_passed=breakdown.safety_passed,
                    checks=breakdown.check_results,
                    process_score=breakdown.process_score,
                    efficiency_score=breakdown.efficiency_score,
                    efficiency_penalty=breakdown.efficiency_penalty,
                    latency_ms=latency_ms,
                    token_usage={
                        **token_totals,
                        "assistant_turns": int(metrics.get("assistant_turns", 0)),
                        "tool_calls": int(metrics.get("tool_calls", len(tool_calls))),
                        "input_cost_usd": costs["input_cost_usd"],
                        "output_cost_usd": costs["output_cost_usd"],
                        "cache_read_cost_usd": costs["cache_read_cost_usd"],
                        "cache_write_cost_usd": costs["cache_write_cost_usd"],
                        "total_cost_usd": costs["total_cost_usd"],
                        "cost_estimate_usd": costs["total_cost_usd"],
                    },
                    transcript=list(trace.get("events", [])),
                    tool_calls=tool_calls,
                    audit_state=dict(trace.get("audit_state", {})),
                    execution=execution,
                    safety_failures=list(breakdown.safety_failures),
                    workspace_path=str(workspace),
                )
            finally:
                if workspace_snapshot_dir is not None:
                    workspace_snapshot_dir.cleanup()
                _run_workspace_script(scenario, scenario.teardown_script, workspace)
                if execution_mode == "live" and live_result and self.live_harness.cleanup_agents:
                    self.live_harness.delete_agent(live_result.agent_id)

    def _preflight_failure_live_result(self, preflight: LivePreflightResult) -> LiveRunResult:
        return LiveRunResult(
            status="error",
            exit_code=preflight.exit_code,
            error_detail=preflight.error_detail,
            trace={"events": [], "metrics": {"wall_time_s": 0.0, "duration_seconds": 0.0}},
            duration_seconds=0.0,
        )
