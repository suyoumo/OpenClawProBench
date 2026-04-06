#!/usr/bin/env python3
"""Lint scenario-definition quality for prompt/input/output/custom-check drift."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.benchmark_profiles import benchmark_profile_choices, resolve_benchmark_selection
from harness.loader import load_scenarios


FILE_REF_RE = re.compile(
    r"(?<![\w./-])([A-Za-z0-9_./-]+\.(?:json|jsonl|md|txt|csv|log|py|bin|yaml|yml|sh|sql|html|xml))(?![\w./-])"
)
FREEFORM_OUTPUT_SUFFIXES = {".md", ".txt"}
INPUT_CONTEXT_KEYWORDS = (
    "只读输入",
    "输入文件",
    "当前工作区",
    "工作区里",
    "工作区中",
    "工作区根目录",
    "已经放好",
    "已经放好了",
    "证据",
    "附件",
    "邮件内容",
    "seeded",
    "read-only",
    "workspace contains",
    "there are",
    "already placed",
    "already contains",
)
OUTPUT_CONTEXT_KEYWORDS = (
    "输出要求",
    "输出 1",
    "输出 2",
    "创建",
    "只创建",
    "create",
    "write",
    "must create",
    "must write",
    "生成",
)
RESET_CONTEXT_KEYWORDS = (
    "任务",
    "挑战",
    "策略",
    "要求",
    "额外要求",
    "constraints",
    "rules",
)
SOFT_CHECK_PATTERNS = {
    "keyword_list": re.compile(r"keywords\s*=\s*\[", re.IGNORECASE),
    "keyword_counter": re.compile(r"found_keywords\s*=", re.IGNORECASE),
    "content_length": re.compile(r"len\s*\(\s*content\s*\)", re.IGNORECASE),
    "content_length_label": re.compile(r"content_length", re.IGNORECASE),
    "reasoning_keywords": re.compile(r"reasoning_keywords\s*=", re.IGNORECASE),
    "has_reasoning": re.compile(r"has_reasoning\s*=", re.IGNORECASE),
}
CUSTOM_OUTPUT_LINE_HINTS = (
    "output_path",
    "output_file",
    "report_path",
    "summary_path",
    "manifest_path",
    "analysis_path",
    "export_path",
    "strategy_path",
    "plan_path",
    "result_path",
)


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    for keyword in keywords:
        if keyword.lower() in lowered or keyword in text:
            return True
    return False


def _normalize_ref(value: str) -> str:
    text = value.strip().strip("`'\"")
    return text.replace("\\", "/")


def _extract_refs(text: str, *, default_context: str = "unknown") -> dict[str, set[str]]:
    refs = {"input": set(), "output": set(), "unknown": set()}
    current_context = default_context

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _has_keyword(line, RESET_CONTEXT_KEYWORDS):
            current_context = default_context
        if _has_keyword(line, OUTPUT_CONTEXT_KEYWORDS):
            current_context = "output"
        elif _has_keyword(line, INPUT_CONTEXT_KEYWORDS):
            current_context = "input"

        matches = {_normalize_ref(match) for match in FILE_REF_RE.findall(line)}
        if not matches:
            continue

        context = current_context
        if _has_keyword(line, OUTPUT_CONTEXT_KEYWORDS):
            context = "output"
        elif _has_keyword(line, INPUT_CONTEXT_KEYWORDS):
            context = "input"

        refs[context].update(matches)
    return refs


def _resolve_seed_dir(scenario) -> Path | None:
    if not scenario.workspace_seed_dir:
        return None
    return (scenario.source_path.parent / scenario.workspace_seed_dir).resolve()


def _declared_inputs(scenario) -> set[str]:
    declared: set[str] = set()

    seed_dir = _resolve_seed_dir(scenario)
    if seed_dir and seed_dir.exists():
        for path in sorted(seed_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(seed_dir).as_posix()
            declared.add(relative)
            declared.add(path.name)

    for entry in scenario.workspace_files:
        if isinstance(entry, str):
            path = _normalize_ref(entry)
            declared.add(path)
            declared.add(Path(path).name)
            continue
        if not isinstance(entry, dict):
            continue
        for key in ("path", "file_path", "name", "filename"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                path = _normalize_ref(value)
                declared.add(path)
                declared.add(Path(path).name)

    for key, value in scenario.fixtures.items():
        declared.add(_normalize_ref(key))
        if isinstance(value, str):
            normalized = _normalize_ref(value)
            declared.add(Path(normalized).name)
            fixture_path = (scenario.source_path.parent / normalized).resolve()
            if fixture_path.is_dir():
                for path in sorted(fixture_path.rglob("*")):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(fixture_path).as_posix()
                    declared.add(relative)
                    declared.add(path.name)
    return declared


def _resolve_custom_check_path(scenario) -> Path | None:
    if not scenario.custom_check:
        return None
    candidates = [
        (scenario.source_path.parents[2] / "custom_checks" / scenario.custom_check).resolve(),
        (scenario.source_path.parents[1] / "custom_checks" / scenario.custom_check).resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _custom_check_output_refs(source: str) -> set[str]:
    refs: set[str] = set()
    for line in source.splitlines():
        if not _has_keyword(line, CUSTOM_OUTPUT_LINE_HINTS):
            continue
        refs.update(_normalize_ref(match) for match in FILE_REF_RE.findall(line))
    return refs


def _soft_check_markers(source: str) -> list[str]:
    markers: list[str] = []
    for marker, pattern in SOFT_CHECK_PATTERNS.items():
        if pattern.search(source):
            markers.append(marker)
    return markers


def _refs_overlap(left: set[str], right: set[str]) -> bool:
    if left & right:
        return True
    left_names = {Path(item).name for item in left}
    right_names = {Path(item).name for item in right}
    return bool(left_names & right_names)


def _raw_scenario_mapping(scenario_path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(scenario_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _raw_expected_outcome(scenario_path: Path) -> str:
    raw = _raw_scenario_mapping(scenario_path)
    if not raw:
        return ""
    return str(raw.get("expected_outcome", "") or "")


def _row_for_scenario(scenario) -> dict[str, Any]:
    raw = _raw_scenario_mapping(scenario.source_path)
    expected_outcome = _raw_expected_outcome(scenario.source_path)
    prompt_refs = _extract_refs(scenario.prompt)
    expected_refs = _extract_refs(expected_outcome, default_context="output")

    input_refs = set(prompt_refs["input"])
    output_refs = set(prompt_refs["output"]) | set(expected_refs["output"])
    unknown_refs = set(prompt_refs["unknown"]) | set(expected_refs["unknown"])
    declared_inputs = _declared_inputs(scenario)

    custom_check_path = _resolve_custom_check_path(scenario)
    custom_source = custom_check_path.read_text(encoding="utf-8") if custom_check_path and custom_check_path.exists() else ""
    custom_output_refs = _custom_check_output_refs(custom_source)
    soft_markers = _soft_check_markers(custom_source)

    missing_inputs: list[str] = []
    for ref in sorted(input_refs):
        normalized = _normalize_ref(ref)
        basename = Path(normalized).name
        if normalized in declared_inputs or basename in declared_inputs:
            continue
        missing_inputs.append(normalized)

    output_suffixes = {Path(ref).suffix.lower() for ref in output_refs if Path(ref).suffix}
    has_zero_seed_inputs = (
        scenario.execution_mode == "live"
        and scenario.signal_source.value == "workspace_live"
        and not scenario.workspace_seed_dir
        and not scenario.workspace_files
        and not scenario.fixtures
    )

    flags: list[str] = []
    if "benchmark_status" not in raw:
        flags.append("missing_explicit_benchmark_status")
    if "signal_source" not in raw:
        flags.append("missing_explicit_signal_source")
    if missing_inputs:
        flags.append("prompt_input_not_declared")
    if has_zero_seed_inputs and output_refs and output_suffixes and output_suffixes.issubset(FREEFORM_OUTPUT_SUFFIXES):
        flags.append("zero_seed_freeform_live")
    if len(soft_markers) >= 3:
        flags.append("keyword_length_heuristic_check")
    if output_refs and custom_output_refs and not _refs_overlap(output_refs, custom_output_refs):
        flags.append("custom_check_output_mismatch")

    return {
        "scenario_id": scenario.scenario_id,
        "dimension": scenario.dimension.value,
        "difficulty": scenario.difficulty.value,
        "benchmark_group": scenario.benchmark_group.value,
        "benchmark_core": scenario.benchmark_core,
        "has_explicit_benchmark_status": "benchmark_status" in raw,
        "has_explicit_signal_source": "signal_source" in raw,
        "signal_source": scenario.signal_source.value,
        "scenario_category": raw.get("category"),
        "execution_mode": scenario.execution_mode,
        "workspace_seed_dir": scenario.workspace_seed_dir,
        "seed_file_count": sum(1 for _ in _resolve_seed_dir(scenario).rglob("*") if _.is_file()) if _resolve_seed_dir(scenario) and _resolve_seed_dir(scenario).exists() else 0,
        "input_refs": sorted(input_refs),
        "output_refs": sorted(output_refs),
        "unknown_refs": sorted(unknown_refs),
        "declared_inputs": sorted(declared_inputs),
        "missing_input_refs": missing_inputs,
        "custom_check": scenario.custom_check,
        "custom_check_output_refs": sorted(custom_output_refs),
        "soft_check_markers": soft_markers,
        "flags": flags,
    }


def lint_scenario_definitions(
    *,
    benchmark_profile: str | None = None,
    benchmark_status: str = "active",
) -> dict[str, Any]:
    selection: dict[str, Any] = {}
    if benchmark_profile:
        selection = resolve_benchmark_selection(benchmark_profile)
        scenarios = load_scenarios(
            benchmark_group=selection["benchmark_group"],
            benchmark_core=selection["benchmark_core"],
            benchmark_status=selection["benchmark_status"],
            signal_source=selection["signal_source"],
        )
    else:
        scenarios = load_scenarios(benchmark_status=benchmark_status)

    rows = [_row_for_scenario(scenario) for scenario in scenarios]
    flag_counts = Counter(flag for row in rows for flag in row["flags"])
    flagged_rows = [row for row in rows if row["flags"]]
    flagged_rows.sort(key=lambda row: (-len(row["flags"]), row["scenario_id"]))

    candidate_views = {
        "explicit_metadata_missing": [
            row
            for row in flagged_rows
            if "missing_explicit_benchmark_status" in row["flags"]
            or "missing_explicit_signal_source" in row["flags"]
        ],
        "prompt_input_mismatch": [row for row in flagged_rows if "prompt_input_not_declared" in row["flags"]],
        "zero_seed_freeform_live": [row for row in flagged_rows if "zero_seed_freeform_live" in row["flags"]],
        "soft_custom_checks": [row for row in flagged_rows if "keyword_length_heuristic_check" in row["flags"]],
        "output_contract_mismatch": [row for row in flagged_rows if "custom_check_output_mismatch" in row["flags"]],
    }

    return {
        "benchmark_profile": benchmark_profile or "custom",
        "benchmark_selection": selection,
        "scenario_count": len(rows),
        "flagged_scenarios": len(flagged_rows),
        "flag_counts": dict(flag_counts),
        "candidate_views": candidate_views,
        "scenarios": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-profile", choices=benchmark_profile_choices(), default="full")
    parser.add_argument("--benchmark-status", choices=("active", "incubating", "deprecated", "all"), default="active")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--fail-on-flags", action="store_true")
    args = parser.parse_args()

    benchmark_profile = args.benchmark_profile if args.benchmark_profile else None
    summary = lint_scenario_definitions(
        benchmark_profile=benchmark_profile,
        benchmark_status=args.benchmark_status,
    )

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"benchmark_profile: {summary['benchmark_profile']}")
        print(f"scenario_count: {summary['scenario_count']}")
        print(f"flagged_scenarios: {summary['flagged_scenarios']}")
        print(f"flag_counts: {summary['flag_counts']}")
        for name, rows in summary["candidate_views"].items():
            print(f"{name}:")
            if not rows:
                print("  none")
                continue
            for row in rows[: args.top]:
                print(
                    "  "
                    f"{row['scenario_id']}: dim={row['dimension']} diff={row['difficulty']} "
                    f"group={row['benchmark_group']} flags={','.join(row['flags'])} "
                    f"missing_inputs={row['missing_input_refs']} soft_markers={row['soft_check_markers']} "
                    f"outputs={row['output_refs']} custom_outputs={row['custom_check_output_refs']}"
                )
    return 1 if args.fail_on_flags and summary["flagged_scenarios"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
