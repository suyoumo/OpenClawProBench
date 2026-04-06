#!/usr/bin/env python3
"""Audit benchmark profile shape against quality guardrails."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.benchmark_profiles import benchmark_profile_choices, resolve_benchmark_selection
from harness.loader import load_scenarios


CORE_POLICY = {
    "min_scenarios": 12,
    "min_dimensions": 6,
    "min_dimension_case_count": 2,
    "max_easy_weight_share": 0.15,
    "min_hard_expert_weight_share": 0.60,
    "min_live_case_share": 1.00,
}

CORE_LIVE_POLICY = {
    "min_scenarios": 12,
    "max_easy_weight_share": 0.05,
    "max_medium_weight_share": 0.20,
    "min_hard_expert_weight_share": 0.75,
    "min_expert_weight_share": 0.20,
    "min_dimensions": 6,
    "min_dimension_case_count": 2,
}


def _weight_share(scenarios, predicate) -> float:
    total_weight = sum(scenario.difficulty_weight for scenario in scenarios)
    if total_weight <= 0:
        return 0.0
    selected = sum(scenario.difficulty_weight for scenario in scenarios if predicate(scenario))
    return round(selected / total_weight, 4)


def _subset_summary(scenarios) -> dict[str, Any]:
    dimensions = Counter(scenario.dimension.value for scenario in scenarios)
    difficulties = Counter(scenario.difficulty.value for scenario in scenarios)
    return {
        "scenario_count": len(scenarios),
        "dimensions": dict(dimensions),
        "difficulties": dict(difficulties),
        "easy_weight_share": _weight_share(scenarios, lambda scenario: scenario.difficulty.value == "easy"),
        "medium_weight_share": _weight_share(scenarios, lambda scenario: scenario.difficulty.value == "medium"),
        "hard_expert_weight_share": _weight_share(
            scenarios,
            lambda scenario: scenario.difficulty.value in {"hard", "expert"},
        ),
        "expert_weight_share": _weight_share(scenarios, lambda scenario: scenario.difficulty.value == "expert"),
    }


def audit_profile(profile: str) -> dict[str, Any]:
    selection = resolve_benchmark_selection(profile)
    scenarios = load_scenarios(
        benchmark_group=selection["benchmark_group"],
        benchmark_core=selection["benchmark_core"],
        benchmark_status=selection["benchmark_status"],
        signal_source=selection["signal_source"],
    )

    dimensions = Counter(scenario.dimension.value for scenario in scenarios)
    difficulties = Counter(scenario.difficulty.value for scenario in scenarios)
    execution_modes = Counter(scenario.execution_mode for scenario in scenarios)
    violations: list[str] = []

    summary: dict[str, Any] = {
        "profile": selection["benchmark_profile"],
        "scenario_count": len(scenarios),
        "dimensions": dict(dimensions),
        "difficulties": dict(difficulties),
        "execution_modes": dict(execution_modes),
        "signal_sources": dict(Counter(scenario.signal_source.value for scenario in scenarios)),
        "easy_weight_share": _weight_share(scenarios, lambda scenario: scenario.difficulty.value == "easy"),
        "hard_expert_weight_share": _weight_share(
            scenarios,
            lambda scenario: scenario.difficulty.value in {"hard", "expert"},
        ),
        "replay_case_share": round(execution_modes.get("replay", 0) / len(scenarios), 4) if scenarios else 0.0,
        "live_case_share": round(execution_modes.get("live", 0) / len(scenarios), 4) if scenarios else 0.0,
        "live_subset": _subset_summary([scenario for scenario in scenarios if scenario.execution_mode == "live"]),
        "violations": violations,
    }

    if profile != "core":
        return summary

    if len(scenarios) < CORE_POLICY["min_scenarios"]:
        violations.append(
            "core suite dropped below "
            f"{CORE_POLICY['min_scenarios']} scenarios"
        )
    if len(dimensions) < CORE_POLICY["min_dimensions"]:
        violations.append("core suite no longer covers all benchmark dimensions")
    for dimension_name, count in sorted(dimensions.items()):
        if count < CORE_POLICY["min_dimension_case_count"]:
            violations.append(
                f"dimension {dimension_name} dropped below {CORE_POLICY['min_dimension_case_count']} core cases"
            )
    if summary["easy_weight_share"] > CORE_POLICY["max_easy_weight_share"]:
        violations.append(
            f"easy weight share {summary['easy_weight_share']:.4f} exceeds {CORE_POLICY['max_easy_weight_share']:.4f}"
        )
    if summary["hard_expert_weight_share"] < CORE_POLICY["min_hard_expert_weight_share"]:
        violations.append(
            "hard+expert weight share "
            f"{summary['hard_expert_weight_share']:.4f} fell below {CORE_POLICY['min_hard_expert_weight_share']:.4f}"
        )
    if summary["live_case_share"] < CORE_POLICY["min_live_case_share"]:
        violations.append(
            f"live case share {summary['live_case_share']:.4f} fell below {CORE_POLICY['min_live_case_share']:.4f}"
        )

    live_subset = summary["live_subset"]
    if live_subset["scenario_count"] < CORE_LIVE_POLICY["min_scenarios"]:
        violations.append(
            "live leaderboard subset dropped below "
            f"{CORE_LIVE_POLICY['min_scenarios']} scenarios"
        )
    if len(live_subset["dimensions"]) < CORE_LIVE_POLICY["min_dimensions"]:
        violations.append("live leaderboard subset no longer covers all benchmark dimensions")
    for dimension_name, count in sorted(live_subset["dimensions"].items()):
        if count < CORE_LIVE_POLICY["min_dimension_case_count"]:
            violations.append(
                "live leaderboard dimension "
                f"{dimension_name} dropped below {CORE_LIVE_POLICY['min_dimension_case_count']} cases"
            )
    if live_subset["easy_weight_share"] > CORE_LIVE_POLICY["max_easy_weight_share"]:
        violations.append(
            "live easy weight share "
            f"{live_subset['easy_weight_share']:.4f} exceeds {CORE_LIVE_POLICY['max_easy_weight_share']:.4f}"
        )
    if live_subset["medium_weight_share"] > CORE_LIVE_POLICY["max_medium_weight_share"]:
        violations.append(
            "live medium weight share "
            f"{live_subset['medium_weight_share']:.4f} exceeds {CORE_LIVE_POLICY['max_medium_weight_share']:.4f}"
        )
    if live_subset["hard_expert_weight_share"] < CORE_LIVE_POLICY["min_hard_expert_weight_share"]:
        violations.append(
            "live hard+expert weight share "
            f"{live_subset['hard_expert_weight_share']:.4f} fell below {CORE_LIVE_POLICY['min_hard_expert_weight_share']:.4f}"
        )
    if live_subset["expert_weight_share"] < CORE_LIVE_POLICY["min_expert_weight_share"]:
        violations.append(
            "live expert weight share "
            f"{live_subset['expert_weight_share']:.4f} fell below {CORE_LIVE_POLICY['min_expert_weight_share']:.4f}"
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=benchmark_profile_choices(), default="core")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    summary = audit_profile(args.profile)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"profile: {summary['profile']}")
        print(f"scenario_count: {summary['scenario_count']}")
        print(f"dimensions: {summary['dimensions']}")
        print(f"difficulties: {summary['difficulties']}")
        print(f"execution_modes: {summary['execution_modes']}")
        print(f"easy_weight_share: {summary['easy_weight_share']:.4f}")
        print(f"hard_expert_weight_share: {summary['hard_expert_weight_share']:.4f}")
        print(f"replay_case_share: {summary['replay_case_share']:.4f}")
        print(f"live_case_share: {summary['live_case_share']:.4f}")
        print(f"live_subset: {summary['live_subset']}")
        if summary["violations"]:
            print("violations:")
            for violation in summary["violations"]:
                print(f"  - {violation}")
        else:
            print("violations: none")
    return 1 if summary["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
