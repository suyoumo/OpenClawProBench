"""CLI entrypoint for OpenClawProBench."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import shlex

from harness.benchmark_profiles import (
    benchmark_core_label,
    benchmark_profile_choices,
    resolve_benchmark_selection,
)
from harness.loader import load_scenarios, results_root, summarize_scenarios
from harness.models import BenchmarkResult
from harness.reporter import compare_reports, print_comparison, print_summary, reserve_report_path, write_report
from harness.runner import BenchmarkRunner
from harness.scoring import SUPPORTED_CHECK_TYPES

DEFAULT_OPENCLAW_BINARY = os.environ.get("OPENCLAW_BINARY", "openclaw")


def _benchmark_selection(args: argparse.Namespace) -> dict[str, str | bool | None]:
    return resolve_benchmark_selection(
        benchmark_profile=getattr(args, "benchmark_profile", None),
        benchmark_group=getattr(args, "benchmark_group", None),
        benchmark_core=getattr(args, "core_only", None),
        benchmark_status=getattr(args, "benchmark_status", None),
        signal_source=getattr(args, "signal_source", None),
    )


def _scenario_filters(args: argparse.Namespace) -> dict[str, str | bool | None]:
    execution_mode = None if getattr(args, "execution_mode", "auto") == "auto" else args.execution_mode
    selection = _benchmark_selection(args)
    if getattr(args, "scenario", None):
        selection = {
            **selection,
            "benchmark_group": None,
            "benchmark_core": None,
            "benchmark_status": None,
            "signal_source": None,
        }
    return {
        "dimension": args.dimension,
        "scenario_id": args.scenario,
        "difficulty": getattr(args, "difficulty", None),
        "tag": getattr(args, "tag", None),
        "execution_mode": execution_mode,
        "benchmark_group": selection["benchmark_group"],
        "benchmark_core": selection["benchmark_core"],
        "benchmark_status": selection["benchmark_status"],
        "signal_source": selection["signal_source"],
    }


def _exclude_scenarios(scenarios, exclude_ids: list[str] | None):
    excluded = {str(item).strip() for item in (exclude_ids or []) if str(item).strip()}
    if not excluded:
        return scenarios
    return [scenario for scenario in scenarios if scenario.scenario_id not in excluded]


def _model_slug(model: str) -> str:
    return model.replace("/", "_").replace(":", "_")


def _apply_timeout_multiplier(scenarios, multiplier: float):
    if multiplier == 1.0:
        return scenarios
    adjusted = []
    for scenario in scenarios:
        adjusted_timeout = max(1, math.ceil(scenario.timeout_seconds * multiplier))
        adjusted.append(replace(scenario, timeout_seconds=adjusted_timeout))
    return adjusted


def _load_existing_result(path: Path) -> BenchmarkResult:
    raw = json.loads(path.read_text(encoding="utf-8"))
    result = BenchmarkResult.from_dict(raw)
    result.summary["report_path"] = str(path)
    return result


def _find_latest_report(results_dir: Path, model: str) -> Path | None:
    prefix = f"result_{_model_slug(model)}_"
    matches = sorted(results_dir.glob(f"{prefix}*.json"))
    return matches[-1] if matches else None


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _report_is_complete(result: BenchmarkResult) -> bool:
    progress = result.summary.get("progress", {}) if result.summary else {}
    completed = _coerce_int(progress.get("completed_scenarios"), len(result.scenarios))
    requested_default = int(result.total_scenarios or len(result.scenarios))
    requested = _coerce_int(progress.get("requested_scenarios"), requested_default)
    return requested > 0 and completed >= requested


def _inventory_payload(args: argparse.Namespace) -> dict[str, object]:
    selection = _benchmark_selection(args)
    scenarios = load_scenarios(**_scenario_filters(args))
    scenarios = _exclude_scenarios(scenarios, getattr(args, "exclude_scenario", None))
    summary = summarize_scenarios(scenarios)
    tag_counts = Counter(tag for scenario in scenarios for tag in scenario.tags)
    difficulty_weight_mass = Counter()
    directory_weight_mass = Counter()
    for scenario in scenarios:
        effective_weight = scenario.effective_weight
        difficulty_weight_mass[scenario.difficulty.value] += effective_weight
        directory_weight_mass[scenario.source_path.parent.name] += effective_weight
    payload: dict[str, object] = {
        "benchmark_profile": selection["benchmark_profile"],
        "benchmark_selection": {
            "requested_profile": selection["requested_benchmark_profile"],
            "resolved_profile": selection["benchmark_profile"],
            "benchmark_group": selection["benchmark_group"] or "all",
            "benchmark_core": benchmark_core_label(selection["benchmark_core"]),
            "benchmark_status": selection["benchmark_status"] or "all",
            "signal_source": selection["signal_source"] or "all",
        },
        "count": summary["count"],
        "dimensions": summary["dimensions"],
        "difficulties": summary["difficulties"],
        "execution_modes": summary["execution_modes"],
        "benchmark_groups": summary["benchmark_groups"],
        "benchmark_core": summary["benchmark_core"],
        "benchmark_statuses": summary["benchmark_statuses"],
        "signal_sources": summary["signal_sources"],
        "openclaw_surfaces": summary["openclaw_surfaces"],
        "difficulty_weight_mass": dict(sorted(difficulty_weight_mass.items())),
        "directory_weight_mass": dict(sorted(directory_weight_mass.items())),
        "tags": dict(sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))),
    }
    if getattr(args, "list", False):
        payload["scenarios"] = [
            {
                "id": scenario.scenario_id,
                "dimension": scenario.dimension.value,
                "difficulty": scenario.difficulty.value,
                "benchmark_group": scenario.benchmark_group.value,
                "benchmark_core": scenario.benchmark_core,
                "benchmark_status": scenario.benchmark_status.value,
                "execution_mode": scenario.execution_mode,
                "signal_source": scenario.signal_source.value,
            }
            for scenario in scenarios
        ]
    return payload


def cmd_inventory(args: argparse.Namespace) -> int:
    payload = _inventory_payload(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"benchmark_profile: {payload['benchmark_profile']}")
    print(f"benchmark_selection: {payload['benchmark_selection']}")
    print(f"scenarios: {payload['count']}")
    print(f"dimensions: {payload['dimensions']}")
    print(f"difficulties: {payload['difficulties']}")
    print(f"execution_modes: {payload['execution_modes']}")
    print(f"benchmark_groups: {payload['benchmark_groups']}")
    print(f"benchmark_core: {payload['benchmark_core']}")
    print(f"benchmark_statuses: {payload['benchmark_statuses']}")
    print(f"signal_sources: {payload['signal_sources']}")
    print(f"openclaw_surfaces: {payload['openclaw_surfaces']}")
    print(f"difficulty_weight_mass: {payload['difficulty_weight_mass']}")
    print(f"directory_weight_mass: {payload['directory_weight_mass']}")
    print(f"tags: {payload['tags']}")
    if args.list:
        for scenario in payload.get("scenarios", []):
            print(
                f"  {scenario['id']} "
                f"[{scenario['dimension']}/{scenario['difficulty']}/{scenario['benchmark_group']}/core={scenario['benchmark_core']}/status={scenario['benchmark_status']}/{scenario['execution_mode']}/{scenario['signal_source']}]"
            )
    return 0


def cmd_dry(args: argparse.Namespace) -> int:
    selection = _benchmark_selection(args)
    scenarios = load_scenarios(**_scenario_filters(args))
    scenarios = _exclude_scenarios(scenarios, getattr(args, "exclude_scenario", None))
    summary = summarize_scenarios(scenarios)
    print(f"benchmark_profile: {selection['benchmark_profile']}")
    print(
        "benchmark_selection: "
        f"requested={selection['requested_benchmark_profile']} "
        f"group={selection['benchmark_group'] or 'all'} "
        f"core={benchmark_core_label(selection['benchmark_core'])} "
        f"status={selection['benchmark_status'] or 'all'} "
        f"signal={selection['signal_source'] or 'all'}"
    )
    print(f"scenarios: {summary['count']}")
    print(f"dimensions: {summary['dimensions']}")
    print(f"difficulties: {summary['difficulties']}")
    print(f"execution_modes: {summary['execution_modes']}")
    print(f"benchmark_groups: {summary['benchmark_groups']}")
    print(f"benchmark_core: {summary['benchmark_core']}")
    print(f"benchmark_statuses: {summary['benchmark_statuses']}")
    print(f"signal_sources: {summary['signal_sources']}")
    print(f"openclaw_surfaces: {summary['openclaw_surfaces']}")
    for scenario in scenarios:
        missing = [
            check.check_type for check in scenario.checks if check.check_type not in SUPPORTED_CHECK_TYPES
        ]
        if missing and not scenario.custom_check:
            raise ValueError(f"{scenario.scenario_id} has unsupported checks: {missing}")
        if scenario.execution_mode == "replay" and not scenario.replay_traces:
            raise ValueError(f"{scenario.scenario_id} is replay mode but has no replay traces configured")
        print(
            f"  ok {scenario.scenario_id} "
            f"[{scenario.dimension.value}/{scenario.difficulty.value}/{scenario.execution_mode}]"
        )
    return 0


def _run_common(args: argparse.Namespace) -> int:
    if getattr(args, "continue_run", False) and getattr(args, "resume_from", None):
        raise ValueError("Use only one of --continue or --resume-from.")
    scenarios = load_scenarios(**_scenario_filters(args))
    scenarios = _exclude_scenarios(scenarios, getattr(args, "exclude_scenario", None))
    if not scenarios:
        raise ValueError("No scenarios matched the current filters.")
    timeout_multiplier = float(getattr(args, "timeout_multiplier", 1.0) or 1.0)
    if timeout_multiplier <= 0:
        raise ValueError("--timeout-multiplier must be > 0.")
    if timeout_multiplier != 1.0:
        scenarios = _apply_timeout_multiplier(scenarios, timeout_multiplier)
        print(f"timeout_multiplier: {timeout_multiplier}x")
    workspace_root = Path(args.workspace_root) if getattr(args, "workspace_root", None) else None
    results_dir = Path(args.results_dir)
    existing_result = None
    if getattr(args, "resume_from", None):
        existing_result = _load_existing_result(Path(args.resume_from))
    elif getattr(args, "continue_run", False):
        latest = _find_latest_report(results_dir, args.model)
        if latest is not None:
            existing_result = _load_existing_result(latest)
    existing_report_path = Path(existing_result.summary["report_path"]) if existing_result and existing_result.summary.get("report_path") else None
    preserve_completed_source = bool(existing_result and existing_report_path and _report_is_complete(existing_result))
    if preserve_completed_source:
        report_path = reserve_report_path(results_dir, args.model)
    else:
        report_path = existing_report_path if existing_report_path else reserve_report_path(results_dir, args.model)
    if existing_result:
        print(
            "resume_source: "
            f"reused={len(existing_result.scenarios)} "
            f"path={existing_result.summary.get('report_path', '')}"
        )
    if preserve_completed_source:
        print(
            "resume_checkpoint: "
            f"source_complete=True preserved={existing_report_path} "
            f"target={report_path}"
        )
    if getattr(args, "rerun_execution_failures", False):
        print("resume_policy: prior execution failures stay pending and will be rerun on resume")
    print(f"progress_report: {report_path}")
    resume_hint_parts = [
        "python3",
        "run.py",
        args.command,
        "--model",
        args.model,
    ]
    if getattr(args, "openclaw_binary", None):
        resume_hint_parts.extend(["--openclaw-binary", args.openclaw_binary])
    for flag, value in (
        ("--openclaw-profile", getattr(args, "openclaw_profile", None)),
        ("--openclaw-state-dir", getattr(args, "openclaw_state_dir", None)),
        ("--openclaw-config-path", getattr(args, "openclaw_config_path", None)),
    ):
        if value:
            resume_hint_parts.extend([flag, str(value)])
    if getattr(args, "openclaw_gateway_port", None):
        resume_hint_parts.extend(["--openclaw-gateway-port", str(args.openclaw_gateway_port)])
    if getattr(args, "rerun_execution_failures", False):
        resume_hint_parts.append("--rerun-execution-failures")
    resume_hint_parts.append("--continue")
    print(
        "resume_hint: "
        f"{shlex.join(resume_hint_parts)}"
    )
    runner = BenchmarkRunner(
        results_dir=results_dir,
        execution_mode=args.execution_mode,
        workspace_root=workspace_root,
        openclaw_binary=args.openclaw_binary,
        openclaw_profile=getattr(args, "openclaw_profile", None),
        openclaw_state_dir=getattr(args, "openclaw_state_dir", None),
        openclaw_config_path=getattr(args, "openclaw_config_path", None),
        openclaw_gateway_port=getattr(args, "openclaw_gateway_port", None),
        use_local_agent=args.local_agent,
        cleanup_agents=args.cleanup_agents,
        parallelism=args.parallel,
        allow_live_parallelism=getattr(args, "allow_live_parallelism", False),
        live_retry_attempts=getattr(args, "live_retries", 0),
        show_progress=not getattr(args, "quiet_progress", False),
        progress_interval_seconds=args.progress_interval_seconds,
    )
    try:
        result = runner.run_with_resume(
            model=args.model,
            scenarios=scenarios,
            trials=args.trials,
            existing_result=existing_result,
            rerun_execution_failures=getattr(args, "rerun_execution_failures", False),
            benchmark_profile=str(_benchmark_selection(args)["benchmark_profile"]),
            checkpoint_path=report_path,
        )
        path = write_report(result, report_path)
        print_summary(result)
        print(f"report: {path}")
        return 0
    finally:
        runner.close()


def cmd_run(args: argparse.Namespace) -> int:
    if not args.model:
        raise ValueError("--model is required for run")
    return _run_common(args)


def cmd_compare(args: argparse.Namespace) -> int:
    if args.paths:
        paths = [Path(path) for path in args.paths]
    else:
        paths = sorted(Path(args.results_dir).glob("result_*.json"))
    if not paths:
        raise ValueError("No report files found to compare.")
    rows = compare_reports(paths)
    print_comparison(rows)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openclawprobench")
    parser.set_defaults(func=None)
    subparsers = parser.add_subparsers(dest="command")

    profile_choices = benchmark_profile_choices()
    benchmark_status_choices = ["active", "incubating", "all"]
    signal_source_choices = ["workspace_live", "openclaw_native", "all"]

    inventory = subparsers.add_parser("inventory", help="Show scenario inventory and distribution summary.")
    inventory.add_argument("--dimension", default=None)
    inventory.add_argument("--scenario", default=None)
    inventory.add_argument("--difficulty", choices=["easy", "medium", "hard", "expert"], default=None)
    inventory.add_argument(
        "--benchmark-profile",
        choices=profile_choices,
        default="full",
        help="Named benchmark slice: core, intelligence, coverage, native, or full.",
    )
    inventory.add_argument("--benchmark-group", choices=["intelligence", "coverage", "all"], default=None, help=argparse.SUPPRESS)
    inventory.add_argument("--core-only", action=argparse.BooleanOptionalAction, default=None, help=argparse.SUPPRESS)
    inventory.add_argument("--benchmark-status", choices=benchmark_status_choices, default=None, help=argparse.SUPPRESS)
    inventory.add_argument("--signal-source", choices=signal_source_choices, default=None, help=argparse.SUPPRESS)
    inventory.add_argument("--tag", default=None)
    inventory.add_argument("--exclude-scenario", action="append", default=[])
    inventory.add_argument("--execution-mode", choices=["auto", "live"], default="auto")
    inventory.add_argument("--list", action="store_true")
    inventory.add_argument("--json", action="store_true")
    inventory.set_defaults(func=cmd_inventory)

    dry = subparsers.add_parser("dry", help="Validate scenario loading and schema.")
    dry.add_argument("--dimension", default=None)
    dry.add_argument("--scenario", default=None)
    dry.add_argument("--difficulty", choices=["easy", "medium", "hard", "expert"], default=None)
    dry.add_argument(
        "--benchmark-profile",
        choices=profile_choices,
        default="full",
        help="Named benchmark slice: core, intelligence, coverage, native, or full.",
    )
    dry.add_argument("--benchmark-group", choices=["intelligence", "coverage", "all"], default=None, help=argparse.SUPPRESS)
    dry.add_argument("--core-only", action=argparse.BooleanOptionalAction, default=None, help=argparse.SUPPRESS)
    dry.add_argument("--benchmark-status", choices=benchmark_status_choices, default=None, help=argparse.SUPPRESS)
    dry.add_argument("--signal-source", choices=signal_source_choices, default=None, help=argparse.SUPPRESS)
    dry.add_argument("--tag", default=None)
    dry.add_argument("--exclude-scenario", action="append", default=[])
    dry.add_argument("--execution-mode", choices=["auto", "live"], default="auto")
    dry.set_defaults(func=cmd_dry)

    run = subparsers.add_parser("run", help="Run benchmark with active live scenarios.")
    run.add_argument("--model", required=True)
    run.add_argument("--dimension", default=None)
    run.add_argument("--scenario", default=None)
    run.add_argument("--difficulty", choices=["easy", "medium", "hard", "expert"], default=None)
    run.add_argument(
        "--benchmark-profile",
        choices=profile_choices,
        default="core",
        help="Named benchmark slice. Default is the intelligence core ranking suite.",
    )
    run.add_argument("--benchmark-group", choices=["intelligence", "coverage", "all"], default=None, help=argparse.SUPPRESS)
    run.add_argument("--core-only", action=argparse.BooleanOptionalAction, default=None, help=argparse.SUPPRESS)
    run.add_argument("--benchmark-status", choices=benchmark_status_choices, default=None, help=argparse.SUPPRESS)
    run.add_argument("--signal-source", choices=signal_source_choices, default=None, help=argparse.SUPPRESS)
    run.add_argument("--tag", default=None)
    run.add_argument("--exclude-scenario", action="append", default=[])
    run.add_argument("--trials", type=int, default=3)
    run.add_argument("--execution-mode", choices=["auto", "live"], default="live")
    run.add_argument("--results-dir", default=str(results_root()))
    run.add_argument("--workspace-root", default=None)
    run.add_argument("--openclaw-binary", default=DEFAULT_OPENCLAW_BINARY)
    run.add_argument("--openclaw-profile", default=None, help="Use an isolated named OpenClaw profile for live runs.")
    run.add_argument("--openclaw-state-dir", default=None, help="Override the OpenClaw state dir for live runs.")
    run.add_argument("--openclaw-config-path", default=None, help="Override the OpenClaw config path for live runs.")
    run.add_argument("--openclaw-gateway-port", type=int, default=None, help="Override the OpenClaw gateway port for live runs.")
    run.add_argument("--local-agent", action="store_true")
    run.add_argument("--cleanup-agents", action="store_true")
    run.add_argument("--parallel", type=int, default=1)
    run.add_argument("--allow-live-parallelism", action="store_true")
    run.add_argument("--live-retries", type=int, default=0)
    run.add_argument("--timeout-multiplier", type=float, default=1.0)
    run.add_argument("--progress-interval-seconds", type=int, default=60)
    run.add_argument("--quiet-progress", action="store_true")
    run.add_argument("--continue", dest="continue_run", action="store_true")
    run.add_argument("--resume-from", default=None)
    run.add_argument(
        "--rerun-execution-failures",
        action="store_true",
        help="When resuming, treat prior execution/runtime failures as pending work instead of completed progress.",
    )
    run.set_defaults(func=cmd_run)

    compare = subparsers.add_parser("compare", help="Compare benchmark reports.")
    compare.add_argument("paths", nargs="*")
    compare.add_argument("--results-dir", default=str(results_root()))
    compare.set_defaults(func=cmd_compare)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.func is None:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
