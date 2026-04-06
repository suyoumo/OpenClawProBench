#!/usr/bin/env python3
"""Backfill benchmark group metadata onto all scenario YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_ROOT = PROJECT_ROOT / "scenarios"

COVERAGE_DIRS = {
    "file_operations",
    "code_generation",
    "data_processing",
    "shell_execution",
    "git_operations",
    "error_handling",
    "security_boundaries",
}


def _benchmark_group_for_path(path: Path) -> str:
    top_level = path.relative_to(SCENARIOS_ROOT).parts[0]
    return "coverage" if top_level in COVERAGE_DIRS else "intelligence"


def _merge_tags(existing: Any, benchmark_group: str) -> list[str]:
    tags = [str(tag) for tag in (existing or [])]
    tag_name = f"benchmark-{benchmark_group}"
    if tag_name not in tags:
        tags.append(tag_name)
    return tags


def main() -> None:
    updated = 0
    for path in sorted(SCENARIOS_ROOT.rglob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Unexpected top-level YAML type in {path}")

        benchmark_group = _benchmark_group_for_path(path)
        changed = False
        if raw.get("benchmark_group") != benchmark_group:
            raw["benchmark_group"] = benchmark_group
            changed = True

        merged_tags = _merge_tags(raw.get("tags"), benchmark_group)
        if merged_tags != list(raw.get("tags", [])):
            raw["tags"] = merged_tags
            changed = True

        if not changed:
            continue

        path.write_text(
            yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        updated += 1

    print(f"updated={updated}")


if __name__ == "__main__":
    main()
