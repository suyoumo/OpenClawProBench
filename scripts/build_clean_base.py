#!/usr/bin/env python3
"""Build a new clean-base report by overlaying rerun scenario results onto a source report."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import glob
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.models import BenchmarkResult, ScenarioResult
from harness.reporter import write_report
from harness.runner import BenchmarkRunner


def _model_slug(model: str) -> str:
    return model.replace("/", "_").replace(":", "_")


def _parse_timestamp(value: str) -> float:
    text = value.strip()
    if not text:
        return float("-inf")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return float("-inf")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _load_report(path: Path) -> BenchmarkResult:
    raw = json.loads(path.read_text(encoding="utf-8"))
    result = BenchmarkResult.from_dict(raw)
    result.summary["report_path"] = str(path)
    return result


def _expand_paths(raw_paths: list[str]) -> list[Path]:
    expanded: list[Path] = []
    for raw_path in raw_paths:
        matches = sorted(Path(path).resolve() for path in glob.glob(raw_path))
        if matches:
            expanded.extend(matches)
            continue
        path = Path(raw_path).resolve()
        if path.exists():
            expanded.append(path)
            continue
        raise FileNotFoundError(f"Overlay report path not found: {raw_path}")

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in expanded:
        if path in seen:
            continue
        deduped.append(path)
        seen.add(path)
    return deduped


def _overlay_candidates(paths: list[Path], *, model: str) -> tuple[dict[str, ScenarioResult], dict[str, str]]:
    chosen_results: dict[str, ScenarioResult] = {}
    chosen_paths: dict[str, str] = {}
    chosen_timestamps: dict[str, float] = {}

    for path in paths:
        result = _load_report(path)
        if result.model != model:
            raise ValueError(f"Overlay report model mismatch: {path} has {result.model!r}, expected {model!r}")
        timestamp = _parse_timestamp(result.timestamp)
        for scenario in result.scenarios:
            existing_timestamp = chosen_timestamps.get(scenario.scenario_id, float("-inf"))
            if timestamp < existing_timestamp:
                continue
            chosen_results[scenario.scenario_id] = scenario
            chosen_paths[scenario.scenario_id] = str(path)
            chosen_timestamps[scenario.scenario_id] = timestamp

    return chosen_results, chosen_paths


def _default_output_path(result: BenchmarkResult, *, benchmark_profile: str, output_dir: Path) -> Path:
    count = len(result.scenarios)
    return output_dir / f"result_{_model_slug(result.model)}_{benchmark_profile}{count}_clean_base.json"


def build_clean_base(
    source_path: Path,
    overlay_paths: list[Path],
    *,
    output_path: Path,
) -> Path:
    source_result = _load_report(source_path)
    benchmark_profile = str(source_result.summary.get("benchmark_selection", {}).get("profile", "custom") or "custom")
    overlay_results, overlay_report_paths = _overlay_candidates(overlay_paths, model=source_result.model)

    merged_scenarios: list[ScenarioResult] = []
    replaced_scenarios: list[str] = []
    for scenario in source_result.scenarios:
        replacement = overlay_results.get(scenario.scenario_id)
        if replacement is None:
            merged_scenarios.append(scenario)
            continue
        if replacement.trial_count != source_result.trials_per_scenario:
            raise ValueError(
                f"Overlay trial mismatch for {scenario.scenario_id}: "
                f"{replacement.trial_count} != {source_result.trials_per_scenario}"
            )
        merged_scenarios.append(replacement)
        replaced_scenarios.append(scenario.scenario_id)

    runner = BenchmarkRunner(
        results_dir=output_path.parent,
        execution_mode="live",
        openclaw_binary=str(
            source_result.summary.get("openclaw_runtime", {}).get("configured_binary", "openclaw")
            or "openclaw"
        ),
        show_progress=False,
    )
    merged = runner._build_benchmark_result(
        model=source_result.model,
        scenario_results=merged_scenarios,
        trials=source_result.trials_per_scenario,
        reused_count=max(len(source_result.scenarios) - len(replaced_scenarios), 0),
        total_requested=len(source_result.scenarios),
        resume_source=str(source_path),
        benchmark_profile=benchmark_profile,
        checkpoint_path=output_path,
    )
    if source_result.summary.get("openclaw_runtime"):
        merged.summary["openclaw_runtime"] = dict(source_result.summary["openclaw_runtime"])
    merged.summary["clean_base"] = {
        "source_report": str(source_path),
        "overlay_report_count": len(overlay_paths),
        "overlay_scenario_count": len(replaced_scenarios),
        "overlay_scenarios": {
            scenario_id: overlay_report_paths[scenario_id]
            for scenario_id in replaced_scenarios
        },
    }
    merged.resume = {
        "resumed": True,
        "source_report": str(source_path),
        "reused_scenarios": max(len(source_result.scenarios) - len(replaced_scenarios), 0),
        "new_scenarios": len(replaced_scenarios),
        "overlay_scenarios": len(replaced_scenarios),
    }
    write_report(merged, output_path)
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", required=True, type=Path)
    parser.add_argument(
        "--overlay-report",
        dest="overlay_reports",
        action="append",
        required=True,
        help="Overlay report path or glob. Pass multiple times.",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    source_path = args.source_report.resolve()
    overlay_paths = _expand_paths(list(args.overlay_reports))
    source_result = _load_report(source_path)
    benchmark_profile = str(source_result.summary.get("benchmark_selection", {}).get("profile", "custom") or "custom")
    output_path = args.output.resolve() if args.output else _default_output_path(
        source_result,
        benchmark_profile=benchmark_profile,
        output_dir=source_path.parent,
    )
    path = build_clean_base(source_path, overlay_paths, output_path=output_path)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
