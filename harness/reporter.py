"""Report generation and comparison."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .efficiency import aggregate_metric
from .models import BenchmarkGroup, BenchmarkResult, DIMENSION_WEIGHTS, Dimension


def _stats(values: list[float]) -> dict[str, float]:
    return aggregate_metric(values)


def _print_stat_line(label: str, stats: dict[str, Any], *, prefix: str = "", decimals: int = 4) -> None:
    print(
        f"{label}: "
        f"min={prefix}{stats.get('min', 0):.{decimals}f} "
        f"avg={prefix}{stats.get('avg', 0):.{decimals}f} "
        f"median={prefix}{stats.get('median', 0):.{decimals}f} "
        f"p95={prefix}{stats.get('p95', 0):.{decimals}f} "
        f"max={prefix}{stats.get('max', 0):.{decimals}f}"
    )


def _format_counts(counts: dict[str, Any]) -> str:
    if not counts:
        return "{}"
    return "{" + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)) + "}"


def _report_token_totals(raw: dict[str, Any]) -> dict[str, int]:
    totals = dict(raw.get("total_tokens", {}))
    input_tokens = int(totals.get("input_tokens", 0) or 0)
    output_tokens = int(totals.get("output_tokens", 0) or 0)
    total_tokens = int(totals.get("total_tokens", 0) or 0)
    cache_read_tokens = int(totals.get("cache_read_tokens", 0) or 0)
    cache_write_tokens = int(totals.get("cache_write_tokens", 0) or 0)

    if cache_read_tokens == 0 and cache_write_tokens == 0:
        scenario_cache_read = 0
        scenario_cache_write = 0
        for scenario in raw.get("scenarios", []) or []:
            scenario_totals = dict(scenario.get("total_tokens", {}))
            scenario_cache_read += int(scenario_totals.get("cache_read_tokens", 0) or 0)
            scenario_cache_write += int(scenario_totals.get("cache_write_tokens", 0) or 0)
            if scenario_totals.get("cache_read_tokens") or scenario_totals.get("cache_write_tokens"):
                continue
            for trial in scenario.get("trials", []) or []:
                usage = dict(trial.get("token_usage", {}))
                scenario_cache_read += int(usage.get("cache_read_tokens", 0) or 0)
                scenario_cache_write += int(usage.get("cache_write_tokens", 0) or 0)
        cache_read_tokens = scenario_cache_read
        cache_write_tokens = scenario_cache_write

    accounted_total_tokens = int(
        totals.get("accounted_total_tokens", input_tokens + output_tokens + cache_read_tokens + cache_write_tokens) or 0
    )
    if accounted_total_tokens <= 0:
        accounted_total_tokens = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    effective_total_tokens = max(total_tokens, accounted_total_tokens)
    unclassified_total_tokens = int(
        totals.get("unclassified_total_tokens", max(effective_total_tokens - accounted_total_tokens, 0)) or 0
    )
    if unclassified_total_tokens <= 0:
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


def reserve_report_path(output_dir: Path, model: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    model_slug = model.replace("/", "_").replace(":", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = output_dir / f"result_{model_slug}_{timestamp}.json"
    suffix = 1
    while path.exists():
        path = output_dir / f"result_{model_slug}_{timestamp}_{suffix}.json"
        suffix += 1
    return path


def _compute_ranking_views(result: BenchmarkResult) -> dict[str, Any]:
    """Compute three leaderboard views from the result scenarios (P2-4, 2026-03-25)."""
    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    ranking_core = [
        s for s in result.scenarios
        if s.benchmark_group == BenchmarkGroup.INTELLIGENCE and s.benchmark_core
    ]
    native_core = [
        s for s in ranking_core
        if s.stats.get("signal_source") == "openclaw_native"
    ]
    return {
        "main": {
            "slice": "ranking_core",
            "metric": "capability_score",
            "scenario_count": len(ranking_core),
            "capability_score": _avg([s.capability_score for s in ranking_core]),
            "overall_score": _avg([s.avg_score for s in ranking_core]),
        },
        "efficiency": {
            "slice": "full",
            "metric": "overall_score",
            "scenario_count": len(result.scenarios),
            "capability_score": _avg([s.capability_score for s in result.scenarios]),
            "overall_score": _avg([s.avg_score for s in result.scenarios]),
        },
        "native": {
            "slice": "native_core",
            "metric": "capability_score",
            "label": "informational",
            "scenario_count": len(native_core),
            "capability_score": _avg([s.capability_score for s in native_core]),
            "overall_score": _avg([s.avg_score for s in native_core]),
        },
    }


def write_report(result: BenchmarkResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    result.summary["report_path"] = str(path)
    result.summary["ranking_views"] = _compute_ranking_views(result)  # P2-4, 2026-03-25
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)
    return path


def save_report(result: BenchmarkResult, output_dir: Path) -> Path:
    path = reserve_report_path(output_dir, result.model)
    write_report(result, path)
    return path


def print_summary(result: BenchmarkResult) -> None:
    print(f"model: {result.model}")
    print(f"capability_score: {result.capability_score:.4f}")
    print(f"overall_score: {result.overall_score:.4f}")
    if result.coverage:
        normalized_capability = result.summary.get("normalized_capability_score_on_covered", 0.0) if result.summary else 0.0
        print(
            "coverage: "
            f"dimensions={result.coverage.get('covered_dimension_count', 0)}/"
            f"{result.coverage.get('total_dimension_count', 0)} "
            f"weight={result.coverage.get('covered_weight', 0):.4f} "
            f"normalized_capability={normalized_capability:.4f} "
            f"normalized_score={result.coverage.get('normalized_score_on_covered', 0):.4f}"
        )
        print(
            "execution_modes: "
            f"scenarios={result.coverage.get('scenario_counts_by_execution_mode', {})} "
            f"trials={result.coverage.get('trial_counts_by_execution_mode', {})}"
        )
    print(f"efficiency_score: {result.efficiency_score:.4f}")
    print(f"strict_pass_rate: {result.strict_pass_rate:.4f}")
    print(f"avg_latency_ms: {result.avg_latency_ms:.2f}")
    print(
        "tokens: "
        f"in={int(result.total_tokens.get('input_tokens', 0))} "
        f"out={int(result.total_tokens.get('output_tokens', 0))} "
        f"cache_read={int(result.total_tokens.get('cache_read_tokens', 0))} "
        f"cache_write={int(result.total_tokens.get('cache_write_tokens', 0))} "
        f"accounted={int(result.total_tokens.get('accounted_total_tokens', 0))} "
        f"extra={int(result.total_tokens.get('unclassified_total_tokens', 0))} "
        f"total={int(result.total_tokens.get('total_tokens', 0))}"
    )
    print(f"cost_estimate_usd: ${result.cost_estimate_usd:.8f}")
    if result.aggregate_stats:
        time_stats = result.aggregate_stats.get("time_s", {})
        input_token_stats = result.aggregate_stats.get("input_tokens", {})
        output_token_stats = result.aggregate_stats.get("output_tokens", {})
        cache_read_token_stats = result.aggregate_stats.get("cache_read_tokens", {})
        cache_write_token_stats = result.aggregate_stats.get("cache_write_tokens", {})
        accounted_total_token_stats = result.aggregate_stats.get("accounted_total_tokens", {})
        unclassified_total_token_stats = result.aggregate_stats.get("unclassified_total_tokens", {})
        total_token_stats = result.aggregate_stats.get("total_tokens", {})
        cost_stats = result.aggregate_stats.get("cost_usd", {})
        _print_stat_line("time_stats_s", time_stats, decimals=4)
        _print_stat_line("token_stats_input", input_token_stats, decimals=2)
        _print_stat_line("token_stats_output", output_token_stats, decimals=2)
        _print_stat_line("token_stats_total", total_token_stats, decimals=2)
        _print_stat_line("token_stats_cache_read", cache_read_token_stats, decimals=2)
        _print_stat_line("token_stats_cache_write", cache_write_token_stats, decimals=2)
        _print_stat_line("token_stats_accounted", accounted_total_token_stats, decimals=2)
        _print_stat_line("token_stats_extra", unclassified_total_token_stats, decimals=2)
        _print_stat_line("cost_stats_usd", cost_stats, prefix="$", decimals=8)
    if result.cost_efficiency:
        print(
            "cost_efficiency: "
            f"score_per_dollar={result.cost_efficiency.get('score_per_dollar', 0):.4f} "
            f"score_per_1k_tokens={result.cost_efficiency.get('score_per_1k_tokens', 0):.6f} "
            f"tokens_per_point={result.cost_efficiency.get('tokens_per_point', 0):.2f}"
        )
        duration_top5 = result.cost_efficiency.get("duration_top5", [])
        if duration_top5:
            print("duration_top5:")
            for item in duration_top5:
                print(
                    f"  {item.get('scenario_id', '')}: "
                    f"difficulty={item.get('difficulty', '')} "
                    f"time_s={item.get('wall_time_s', 0):.4f}"
                )
        cost_top5 = result.cost_efficiency.get("cost_top5", [])
        if any(float(item.get("cost_usd", 0.0)) > 0 for item in cost_top5):
            print("cost_top5:")
            for item in cost_top5:
                if float(item.get("cost_usd", 0.0)) <= 0:
                    continue
                print(
                    f"  {item.get('scenario_id', '')}: "
                    f"difficulty={item.get('difficulty', '')} "
                    f"cost=${item.get('cost_usd', 0):.8f} "
                    f"tokens={int(item.get('tokens', 0))}"
                )
    if result.summary:
        benchmark_selection = result.summary.get("benchmark_selection", {})
        progress = result.summary.get("progress", {})
        cost_breakdown = result.summary.get("cost_breakdown", {})
        difficulty_summary = result.summary.get("difficulty_summary", {})
        benchmark_groups = result.summary.get("benchmark_groups", {})
        benchmark_core = result.summary.get("benchmark_core", {})
        outcome_summary = result.summary.get("outcomes", {})
        integrity_summary = result.summary.get("integrity", {})
        execution_summary = result.summary.get("execution", {})
        reliability = result.summary.get("reliability", {})
        runtime = result.summary.get("openclaw_runtime", {})
        isolation = result.summary.get("openclaw_isolation", {})
        score_views = result.summary.get("score_views", {})
        parallel = result.summary.get("parallel", {})
        if benchmark_selection:
            print(
                "benchmark: "
                f"profile={benchmark_selection.get('profile', 'custom')} "
                f"scenarios={benchmark_selection.get('scenario_count', 0)}"
            )
        if runtime:
            version_text = str(runtime.get("version_text", "")).splitlines()[0] if runtime.get("version_text") else ""
            print(
                "openclaw_runtime: "
                f"binary={runtime.get('binary_realpath', runtime.get('resolved_binary', ''))} "
                f"commit={runtime.get('git_commit_short', '')} "
                f"dirty={runtime.get('git_dirty', False)} "
                f"version={version_text}"
            )
        if isolation:
            gateway_port = isolation.get("gateway_port")
            print(
                "openclaw_isolation: "
                f"profile={isolation.get('profile', '') or 'default'} "
                f"state_dir={isolation.get('state_dir', '')} "
                f"config_path={isolation.get('config_path', '')} "
                f"gateway_port={gateway_port if gateway_port is not None else 'auto'}"
            )
        if progress:
            print(
                "progress: "
                f"completed={progress.get('completed_scenarios', 0)}/"
                f"{progress.get('requested_scenarios', 0)} "
                f"remaining={progress.get('remaining_scenarios', 0)} "
                f"checkpoint={progress.get('checkpoint_path', '')}"
            )
        print(
            "benchmark_summary: "
            f"slowest={result.summary.get('slowest_scenario', '')}:{result.summary.get('slowest_time_s', 0):.4f}s "
            f"fastest={result.summary.get('fastest_scenario', '')}:{result.summary.get('fastest_time_s', 0):.4f}s "
            f"avg_cost_per_scenario=${result.summary.get('avg_cost_per_scenario', 0):.8f}"
        )
        if score_views:
            print(
                "score_views: "
                f"capability={score_views.get('capability_score', 0):.4f} "
                f"efficiency_adjusted={score_views.get('efficiency_adjusted_score', 0):.4f} "
                f"drag={score_views.get('efficiency_drag', 0):.4f}"
            )
        if reliability:
            print(
                "reliability: "
                f"trials={reliability.get('trial_count', 0)} "
                f"pass@1={reliability.get('unweighted_pass_at_1', 0):.4f} "
                f"weighted_pass@1={reliability.get('weighted_pass_at_1', 0):.4f} "
                f"pass@k_any={reliability.get('unweighted_pass_at_k_any', 0):.4f} "
                f"weighted_pass@k_any={reliability.get('weighted_pass_at_k_any', 0):.4f} "
                f"pass@k_all={reliability.get('unweighted_pass_at_k_all', 0):.4f} "
                f"weighted_pass@k_all={reliability.get('weighted_pass_at_k_all', 0):.4f} "
                f"avg_stddev={reliability.get('avg_score_stddev', 0):.6f} "
                f"p95_stddev={reliability.get('p95_score_stddev', 0):.6f}"
            )
            print(f"pass_histogram: {_format_counts(reliability.get('pass_count_histogram', {}))}")
        if benchmark_groups:
            print("benchmark_groups:")
            for group_name, values in benchmark_groups.items():
                print(
                    f"  {group_name}: "
                    f"count={values.get('scenario_count', 0)} "
                    f"weight_share={values.get('weight_share', 0):.4f} "
                    f"avg_score={values.get('avg_score', 0):.4f} "
                    f"avg_capability={values.get('avg_capability_score', 0):.4f}"
                )
        if benchmark_core:
            print("benchmark_core:")
            for group_name, values in benchmark_core.items():
                print(
                    f"  {group_name}: "
                    f"count={values.get('scenario_count', 0)} "
                    f"weight_share={values.get('weight_share', 0):.4f}"
                )
        print(
            "cost_breakdown: "
            f"input=${cost_breakdown.get('input_cost_usd', 0):.8f} "
            f"output=${cost_breakdown.get('output_cost_usd', 0):.8f} "
            f"cache=${cost_breakdown.get('cache_cost_usd', 0):.8f}"
        )
        if execution_summary:
            live_preflight = execution_summary.get("live_preflight", {})
            print(
                "execution: "
                f"trial_statuses={_format_counts(execution_summary.get('trial_status_counts', {}))} "
                f"scenario_statuses={_format_counts(execution_summary.get('scenario_status_counts', {}))} "
                f"failures={execution_summary.get('failure_count', 0)}"
            )
            if live_preflight:
                print(
                    "live_preflight: "
                    f"ok={live_preflight.get('ok', False)} "
                    f"exit_code={live_preflight.get('exit_code', 0)} "
                    f"duration_s={live_preflight.get('duration_seconds', 0):.4f} "
                    f"detail={live_preflight.get('error_detail', '')}"
                )
            failure_examples = execution_summary.get("failure_examples", [])
            if failure_examples:
                print("execution_failures:")
                for item in failure_examples:
                    print(
                        f"  {item.get('scenario_id', '')}#t{item.get('trial_id', 0)}: "
                        f"mode={item.get('mode', '')} "
                        f"status={item.get('status', '')} "
                        f"exit_code={item.get('exit_code', 0)} "
                        f"detail={item.get('error_detail', '')}"
                    )
            safety_failure_examples = execution_summary.get("safety_failure_examples", [])
            if safety_failure_examples:
                print("safety_failures:")
                for item in safety_failure_examples:
                    print(
                        f"  {item.get('scenario_id', '')}#t{item.get('trial_id', 0)}: "
                        f"mode={item.get('mode', '')} "
                        f"status={item.get('status', '')} "
                        f"checks={item.get('safety_failures', [])}"
                    )
        if outcome_summary:
            print(
                "outcomes: "
                f"scenarios={_format_counts(outcome_summary.get('scenario_outcome_counts', {}))} "
                f"trials={_format_counts(outcome_summary.get('trial_outcome_counts', {}))}"
            )
            threshold_miss_examples = outcome_summary.get("threshold_miss_examples", [])
            if threshold_miss_examples:
                print("threshold_miss_examples:")
                for item in threshold_miss_examples:
                    print(
                        f"  {item.get('scenario_id', '')}#t{item.get('trial_id', 0)}: "
                        f"score={item.get('score', 0):.4f} "
                        f"capability={item.get('capability_score', 0):.4f} "
                        f"status={item.get('status', '')}"
                    )
        if integrity_summary:
            print(
                "integrity: "
                f"zero_score_scenarios={integrity_summary.get('zero_score_scenario_count', 0)} "
                f"zero_score_trials={integrity_summary.get('zero_score_trial_count', 0)}"
            )
            zero_score_examples = integrity_summary.get("zero_score_scenario_examples", [])
            if zero_score_examples:
                print("zero_score_examples:")
                for item in zero_score_examples:
                    print(
                        f"  {item.get('scenario_id', '')}: "
                        f"avg={item.get('avg_score', 0):.4f} "
                        f"capability={item.get('capability_score', 0):.4f} "
                        f"status={_format_counts(item.get('execution_status_counts', {}))} "
                        f"pass={item.get('pass_count', 0)}/{item.get('trial_count', 0)} "
                        f"strict_pass={item.get('strict_pass_k', False)}"
                    )
        if difficulty_summary:
            print("difficulty_summary:")
            for difficulty_name, values in difficulty_summary.items():
                print(
                    f"  {difficulty_name}: "
                    f"count={values.get('scenario_count', 0)} "
                    f"avg_score={values.get('avg_score', 0):.4f} "
                    f"avg_capability={values.get('avg_capability_score', 0):.4f} "
                    f"pass@1={values.get('pass_at_1', 0):.4f} "
                    f"pass@k_any={values.get('pass_at_k_any', 0):.4f} "
                    f"strict_pass={values.get('strict_pass_rate', 0):.4f} "
                    f"avg_time_s={values.get('avg_latency_s', 0):.4f} "
                    f"avg_tokens={values.get('avg_total_tokens', 0):.2f} "
                    f"avg_cost=${values.get('avg_cost_usd', 0):.8f} "
                    f"weight_share={values.get('weight_share', 0):.4f}"
                )
        if parallel:
            print(
                "parallel: "
                f"requested={parallel.get('requested_workers', 1)} "
                f"replay_workers={parallel.get('replay_workers', 0)} "
                f"live_workers={parallel.get('live_workers', 0)} "
                f"live_final_workers={parallel.get('live_final_workers', parallel.get('live_workers', 0))} "
                f"live_enabled={parallel.get('live_parallelism_enabled', False)} "
                f"live_retries={parallel.get('live_retry_attempts', 0)} "
                f"live_pressure_reruns={parallel.get('live_pressure_rerun_count', 0)} "
                f"replay_scenarios={parallel.get('replay_scenarios', 0)} "
                f"live_scenarios={parallel.get('live_scenarios', 0)}"
            )
            if parallel.get("live_probe_results"):
                print(
                    "live_probe: "
                    f"requested={parallel.get('live_probe_requested_workers', 0)} "
                    f"selected={parallel.get('live_probe_selected_workers', parallel.get('live_workers', 0))} "
                    f"steps={len(parallel.get('live_probe_results', []))}"
                )
            if parallel.get("live_backoff_events"):
                print(
                    "live_backoff: "
                    f"count={parallel.get('live_backoff_count', 0)} "
                    f"final_workers={parallel.get('live_final_workers', parallel.get('live_workers', 0))}"
                )
    if result.resume:
        print(
            "resume: "
            f"resumed={result.resume.get('resumed', False)} "
            f"reused={result.resume.get('reused_scenarios', 0)} "
            f"new={result.resume.get('new_scenarios', 0)} "
            f"source={result.resume.get('source_report', '')}"
        )
    print("dimensions:")
    for name, dim in sorted(result.dimensions.items()):
        print(
            f"  {name}: score={dim.score:.4f} "
            f"capability={dim.capability_score:.4f} "
            f"pass@1={dim.pass_at_1:.4f} "
            f"pass@k_any={dim.pass_at_k_any:.4f} "
            f"strict_pass_rate={dim.strict_pass_rate:.4f} "
            f"scenarios={dim.scenario_count}"
        )
    print("scenarios:")
    for scenario in result.scenarios:
        status_counts = scenario.stats.get("execution_status_counts", {}) if scenario.stats else {}
        status_suffix = ""
        if status_counts and set(status_counts) != {"success"}:
            status_suffix = f" status={_format_counts(status_counts)}"
        print(
            f"  {scenario.scenario_id}: avg={scenario.avg_score:.4f} "
            f"best={scenario.max_score:.4f} "
            f"capability={scenario.capability_score:.4f} "
            f"group={scenario.benchmark_group.value} "
            f"core={scenario.benchmark_core} "
            f"pass@1={scenario.pass_rate:.4f} "
            f"pass@k_any={scenario.pass_at_k_any} "
            f"pass@k_all={scenario.strict_pass_k} "
            f"pass_count={scenario.pass_count}/{scenario.trial_count} "
            f"consistency={scenario.consistency:.6f} "
            f"latency_ms={scenario.avg_latency_ms:.2f} "
            f"tokens={int(scenario.total_tokens.get('total_tokens', 0))} "
            f"cost=${scenario.cost_estimate_usd:.8f}"
            f"{status_suffix}"
        )


def compare_reports(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        raw = json.loads(path.read_text())
        coverage = dict(raw.get("coverage", {}))
        token_totals = _report_token_totals(raw)
        covered_dimensions = coverage.get("covered_dimensions") or sorted(raw.get("dimensions", {}).keys())
        covered_weight = float(coverage.get("covered_weight", 0.0))
        if covered_weight <= 0 and covered_dimensions:
            covered_weight = sum(
                DIMENSION_WEIGHTS[Dimension(name)]
                for name in covered_dimensions
                if name in {dimension.value for dimension in DIMENSION_WEIGHTS}
            )
        normalized_score = coverage.get("normalized_score_on_covered")
        if normalized_score is None:
            normalized_score = raw["overall_score"] / covered_weight if covered_weight else raw["overall_score"]
        summary = dict(raw.get("summary", {}))
        reliability = dict(summary.get("reliability", {}))
        capability_score = float(raw.get("capability_score", raw.get("overall_score", 0.0)))
        normalized_capability = summary.get("normalized_capability_score_on_covered")
        if normalized_capability is None:
            normalized_capability = capability_score / covered_weight if covered_weight else capability_score
        aggregate_stats = dict(raw.get("aggregate_stats", {}))
        rows.append(
            {
                "path": str(path),
                "model": raw["model"],
                "overall_score": raw["overall_score"],
                "capability_score": capability_score,
                "normalized_capability_on_covered": normalized_capability,
                "normalized_score_on_covered": normalized_score,
                "covered_weight": covered_weight,
                "is_partial_coverage": covered_weight < 0.9999,
                "strict_pass_rate": raw["strict_pass_rate"],
                "weighted_pass_at_1": reliability.get("weighted_pass_at_1", 0.0),
                "weighted_pass_at_k_any": reliability.get("weighted_pass_at_k_any", 0.0),
                "weighted_pass_at_k_all": reliability.get("weighted_pass_at_k_all", raw["strict_pass_rate"]),
                "avg_latency_ms": raw["avg_latency_ms"],
                "time_min_s": aggregate_stats.get("time_s", {}).get("min", 0),
                "time_max_s": aggregate_stats.get("time_s", {}).get("max", 0),
                **token_totals,
                "cost_estimate_usd": raw["cost_estimate_usd"],
                "execution_modes": coverage.get("scenario_counts_by_execution_mode", {}),
            }
        )
    rows.sort(
        key=lambda row: (
            -row["covered_weight"],
            -row["normalized_capability_on_covered"],
            -row["normalized_score_on_covered"],
            -row["capability_score"],
            -row["overall_score"],
            row["avg_latency_ms"],
        )
    )
    return rows


def print_comparison(rows: list[dict[str, Any]]) -> None:
    print("model comparison:")
    coverage_groups = {round(float(row["covered_weight"]), 4) for row in rows}
    if len(coverage_groups) > 1:
        print("  note: mixed coverage detected; rows are ordered by coverage first, then covered_score.")
    for row in rows:
        scope = "partial" if row.get("is_partial_coverage", False) else "full"
        print(
            f"  {row['model']}: capability={row['capability_score']:.4f} "
            f"score={row['overall_score']:.4f} "
            f"covered_capability={row['normalized_capability_on_covered']:.4f} "
            f"covered_score={row['normalized_score_on_covered']:.4f} "
            f"coverage={row['covered_weight']:.4f} "
            f"scope={scope} "
            f"pass@1={row['weighted_pass_at_1']:.4f} "
            f"pass@k_any={row['weighted_pass_at_k_any']:.4f} "
            f"pass@k_all={row['weighted_pass_at_k_all']:.4f} "
            f"strict_pass={row['strict_pass_rate']:.4f} "
            f"latency_ms={row['avg_latency_ms']:.2f} "
            f"time_range_s={row['time_min_s']:.2f}-{row['time_max_s']:.2f} "
            f"tokens=in:{int(row['input_tokens'])}/out:{int(row['output_tokens'])}/"
            f"cache_r:{int(row['cache_read_tokens'])}/cache_w:{int(row['cache_write_tokens'])}/"
            f"accounted:{int(row['accounted_total_tokens'])}/extra:{int(row['unclassified_total_tokens'])}/"
            f"total:{int(row['total_tokens'])} "
            f"cost=${row['cost_estimate_usd']:.8f}"
        )
