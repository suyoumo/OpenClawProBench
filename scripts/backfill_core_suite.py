#!/usr/bin/env python3
"""Mark the curated high-signal intelligence core suite."""

from __future__ import annotations

from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_ROOT = PROJECT_ROOT / "scenarios"

CORE_SCENARIO_IDS = {
    "tool_use_01_single_search",
    "tool_use_02_workspace_extract_live",
    "tool_use_05_adversarial_tools",
    "constraints_02_ambiguous_recipient",
    "constraints_03_exact_format_live",
    "error_recovery_01_clear_error_retry",
    "error_recovery_05_partial_data_recovery",
    "planning_02_release_handoff_live",
    "planning_04_dynamic_replan",
    "safety_02_secret_refusal_live",
    "safety_04_embedded_trap",
    "synthesis_06_multi_hop_reasoning",
    "oib5_t01_file_extraction",
    "oib5_t09_debug_iteration",
    "oib5_t15_multi_source",
    "oib5_t17_fault_recovery",
    "oib5_t19_safety_boundary",
    "oib5_t20_prompt_injection",
    "oib5_t21_contradiction",
    "oib5_t23_fullstack_project",
}


def main() -> None:
    updated = 0
    intelligence_count = 0
    core_count = 0

    for path in sorted(SCENARIOS_ROOT.rglob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Unexpected top-level YAML type in {path}")

        benchmark_group = str(raw.get("benchmark_group", "intelligence"))
        scenario_id = str(raw.get("id", path.stem))
        is_core = scenario_id in CORE_SCENARIO_IDS
        changed = False

        if benchmark_group == "intelligence":
            intelligence_count += 1
            if is_core:
                core_count += 1

        if raw.get("benchmark_core") != is_core:
            raw["benchmark_core"] = is_core
            changed = True

        tags = [str(tag) for tag in raw.get("tags", [])]
        if is_core and "benchmark-core" not in tags:
            tags.append("benchmark-core")
            changed = True
        if not is_core and "benchmark-core" in tags:
            tags = [tag for tag in tags if tag != "benchmark-core"]
            changed = True
        if changed:
            raw["tags"] = tags
            path.write_text(
                yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            updated += 1

    print(f"updated={updated}")
    print(f"intelligence_total={intelligence_count}")
    print(f"core_total={core_count}")


if __name__ == "__main__":
    main()
