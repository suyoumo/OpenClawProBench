#!/usr/bin/env python3
"""Backfill user-requested metadata fields for legacy scenario YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_ROOT = PROJECT_ROOT / "scenarios"

GENERATED_DIRS = {
    "file_operations",
    "code_generation",
    "data_processing",
    "shell_execution",
    "git_operations",
    "error_handling",
    "security_boundaries",
}

CATEGORY_BY_DIR = {
    "constraints": "constraints",
    "error_recovery": "error_handling",
    "oib5": "imported_oib5",
    "planning": "planning",
    "safety": "security_boundaries",
    "synthesis": "data_processing",
    "tool_use": "tool_use",
}


def _category_from_path(path: Path) -> str:
    top = path.relative_to(SCENARIOS_ROOT).parts[0]
    return CATEGORY_BY_DIR.get(top, top)


def _build_missing_fields(data: dict[str, Any], path: Path) -> dict[str, Any]:
    category = _category_from_path(path)
    timeout_seconds = int(data.get("timeout_seconds", 180))
    scenario_name = str(data.get("name", data.get("id", path.stem)))
    scenario_id = str(data.get("id", path.stem))
    additions: dict[str, Any] = {}

    if "category" not in data:
        additions["category"] = category
    if "description" not in data:
        additions["description"] = f"Legacy benchmark scenario `{scenario_id}` in category `{category}`."
    if "objective" not in data:
        additions["objective"] = f"Complete scenario `{scenario_name}` and satisfy its scoring checks."
    if "prerequisites" not in data:
        additions["prerequisites"] = [
            "Execution workspace is available.",
            "Scenario prompt and required files are accessible.",
        ]
    if "steps" not in data:
        additions["steps"] = [
            "Read the scenario prompt and identify constraints.",
            "Execute required operations and produce expected artifacts.",
            "Return a concise completion response aligned with checks.",
        ]
    if "expected_outcome" not in data:
        additions["expected_outcome"] = "All scenario checks pass with deterministic, policy-compliant behavior."
    if "scoring_criteria" not in data:
        additions["scoring_criteria"] = [
            "Correctness checks are satisfied.",
            "Safety checks are satisfied without prohibited actions.",
        ]
    if "fixtures" not in data:
        additions["fixtures"] = {"path": f"../../fixtures/legacy_catalog/{category}"}
    elif not isinstance(data.get("fixtures"), dict):
        additions["fixtures"] = {"path": str(data.get("fixtures", ""))}
    if "time_limit" not in data:
        additions["time_limit"] = timeout_seconds

    return additions


def main() -> None:
    updated = 0
    skipped = 0
    for path in sorted(SCENARIOS_ROOT.rglob("*.yaml")):
        top = path.relative_to(SCENARIOS_ROOT).parts[0]
        if top in GENERATED_DIRS:
            skipped += 1
            continue
        raw_text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_text) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected top-level YAML type in {path}")

        additions = _build_missing_fields(data, path)
        if not additions:
            continue

        if not raw_text.endswith("\n"):
            raw_text += "\n"
        block = yaml.safe_dump(additions, sort_keys=False, allow_unicode=True)
        path.write_text(raw_text + block, encoding="utf-8")
        updated += 1

    print(f"updated={updated}")
    print(f"skipped_generated={skipped}")


if __name__ == "__main__":
    main()
