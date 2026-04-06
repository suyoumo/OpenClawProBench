#!/usr/bin/env python3
"""Audit custom check modules for referenced, helper, and orphan status."""

from __future__ import annotations

import argparse
import ast
import difflib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.loader import custom_checks_root as repo_custom_checks_root, load_scenarios


def _inspect_python_module(path: Path) -> dict[str, Any]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return {
            "defines_grade": False,
            "defines_grade_process": False,
            "syntax_error": f"{exc.msg} (line {exc.lineno})",
        }

    defines_grade = False
    defines_grade_process = False
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == "grade":
            defines_grade = True
        if node.name == "grade_process":
            defines_grade_process = True

    return {
        "defines_grade": defines_grade,
        "defines_grade_process": defines_grade_process,
        "syntax_error": "",
    }


def _default_references() -> dict[str, list[str]]:
    references: dict[str, list[str]] = {}
    for scenario in load_scenarios(benchmark_status="all"):
        if not scenario.custom_check:
            continue
        references.setdefault(str(scenario.custom_check), []).append(scenario.scenario_id)
    return {
        path: sorted(scenario_ids)
        for path, scenario_ids in sorted(references.items())
    }


def _variant_candidates(relative_path: str) -> list[str]:
    stem = relative_path[:-3] if relative_path.endswith(".py") else relative_path
    candidates = [
        stem.replace("_live_v2", "_live"),
        stem.replace("_live_v2", ""),
        stem.replace("_v2", ""),
        f"{stem}_live",
        f"{stem}_live_v2",
        stem.replace("_live", "_live_v2"),
        stem.replace("_live", ""),
        f"{stem}_v2",
    ]

    deduped: list[str] = []
    for candidate in candidates:
        if not candidate or candidate == stem:
            continue
        value = f"{candidate}.py"
        if value not in deduped:
            deduped.append(value)
    return deduped


def _related_referenced_paths(relative_path: str, referenced_paths: set[str]) -> list[str]:
    return [
        candidate
        for candidate in _variant_candidates(relative_path)
        if candidate in referenced_paths
    ]


def _tracked_paths(custom_checks_root: Path) -> set[str] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", str(custom_checks_root)],
            capture_output=True,
            text=True,
            check=False,
            cwd=PROJECT_ROOT,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    tracked: set[str] = set()
    for line in result.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        path = (PROJECT_ROOT / text).resolve()
        try:
            tracked.add(path.relative_to(custom_checks_root).as_posix())
        except ValueError:
            continue
    return tracked


def _text_similarity(left: Path, right: Path) -> float:
    return round(
        difflib.SequenceMatcher(
            None,
            left.read_text(encoding="utf-8"),
            right.read_text(encoding="utf-8"),
        ).ratio(),
        4,
    )


_REVIEW_ACTION_PRIORITY = {
    "delete_candidate_identical_shadow": 0,
    "confirm_before_delete_divergent_shadow": 1,
    "review_untracked_orphan": 2,
    "review_tracked_orphan": 3,
    "": 4,
}


def _orphan_review_sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
    return (
        _REVIEW_ACTION_PRIORITY.get(str(row.get("recommended_action", "")), 9),
        -float(row.get("shadow_similarity", 0.0) or 0.0),
        str(row.get("path", "")),
    )


def audit_custom_checks(
    *,
    custom_checks_root: Path | None = None,
    references_by_path: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    custom_checks_root = (custom_checks_root or repo_custom_checks_root()).resolve()
    references_by_path = references_by_path or _default_references()
    referenced_paths = set(references_by_path)
    tracked_paths = _tracked_paths(custom_checks_root)

    rows: list[dict[str, Any]] = []
    orphan_custom_checks: list[str] = []
    helper_modules: list[str] = []
    syntax_errors: list[dict[str, str]] = []
    orphan_reasons: dict[str, int] = {}
    recommendation_counts: dict[str, int] = {}

    for path in sorted(custom_checks_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative_path = path.relative_to(custom_checks_root).as_posix()
        module_info = _inspect_python_module(path)
        status = "helper"
        git_tracking_status = "unknown"
        if tracked_paths is not None:
            git_tracking_status = "tracked" if relative_path in tracked_paths else "untracked"
        related_paths = _related_referenced_paths(relative_path, referenced_paths)
        orphan_reason = ""
        shadow_similarity = 0.0
        recommended_action = ""
        if module_info["syntax_error"]:
            status = "syntax_error"
            syntax_errors.append(
                {"path": relative_path, "detail": str(module_info["syntax_error"])}
            )
        elif module_info["defines_grade"]:
            if relative_path in referenced_paths:
                status = "referenced"
            else:
                status = "orphan"
                orphan_custom_checks.append(relative_path)
                if related_paths:
                    orphan_reason = "shadowed_by_referenced_variant"
                    related_path = custom_checks_root / related_paths[0]
                    shadow_similarity = _text_similarity(path, related_path)
                    if shadow_similarity >= 1.0:
                        recommended_action = "delete_candidate_identical_shadow"
                    else:
                        recommended_action = "confirm_before_delete_divergent_shadow"
                elif git_tracking_status == "untracked":
                    orphan_reason = "untracked_orphan"
                    recommended_action = "review_untracked_orphan"
                else:
                    orphan_reason = "unreferenced_standalone"
                    recommended_action = "review_tracked_orphan"
                orphan_reasons[orphan_reason] = orphan_reasons.get(orphan_reason, 0) + 1
                recommendation_counts[recommended_action] = recommendation_counts.get(recommended_action, 0) + 1
        else:
            helper_modules.append(relative_path)

        rows.append(
            {
                "path": relative_path,
                "status": status,
                "defines_grade": bool(module_info["defines_grade"]),
                "defines_grade_process": bool(module_info["defines_grade_process"]),
                "referenced_by": references_by_path.get(relative_path, []),
                "related_referenced_paths": related_paths,
                "shadow_similarity": shadow_similarity,
                "git_tracking_status": git_tracking_status,
                "orphan_reason": orphan_reason,
                "recommended_action": recommended_action,
                "syntax_error": str(module_info["syntax_error"]),
            }
        )

    missing_references = sorted(referenced_paths - {row["path"] for row in rows})
    orphan_review_queue = sorted(
        (
            {
                "path": row["path"],
                "git_tracking_status": row["git_tracking_status"],
                "orphan_reason": row["orphan_reason"],
                "recommended_action": row["recommended_action"],
                "shadow_similarity": row["shadow_similarity"],
                "related_referenced_paths": list(row["related_referenced_paths"]),
            }
            for row in rows
            if row["status"] == "orphan"
        ),
        key=_orphan_review_sort_key,
    )
    summary = {
        "python_file_count": len(rows),
        "referenced_count": sum(1 for row in rows if row["status"] == "referenced"),
        "helper_count": sum(1 for row in rows if row["status"] == "helper"),
        "orphan_count": len(orphan_custom_checks),
        "orphan_reasons": dict(sorted(orphan_reasons.items())),
        "recommendation_counts": dict(sorted(recommendation_counts.items())),
        "syntax_error_count": len(syntax_errors),
        "missing_reference_count": len(missing_references),
    }

    return {
        "summary": summary,
        "referenced_custom_checks": sorted(referenced_paths),
        "orphan_custom_checks": sorted(orphan_custom_checks),
        "orphan_review_queue": orphan_review_queue,
        "helper_modules": sorted(helper_modules),
        "missing_references": missing_references,
        "syntax_errors": syntax_errors,
        "modules": rows,
    }


def _print_text(summary: dict[str, Any]) -> None:
    print(
        "custom_checks: "
        f"python_files={summary['python_file_count']} "
        f"referenced={summary['referenced_count']} "
        f"helpers={summary['helper_count']} "
        f"orphans={summary['orphan_count']} "
        f"syntax_errors={summary['syntax_error_count']} "
        f"missing_refs={summary['missing_reference_count']}"
    )
    orphan_reasons = dict(summary.get("orphan_reasons", {}))
    if orphan_reasons:
        print(f"orphan_reasons={orphan_reasons}")
    recommendation_counts = dict(summary.get("recommendation_counts", {}))
    if recommendation_counts:
        print(f"recommendations={recommendation_counts}")


def _format_related_paths(value: list[str]) -> str:
    return ",".join(value) if value else "-"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument(
        "--fail-on-orphans",
        action="store_true",
        help="Exit non-zero when orphan custom checks, syntax errors, or missing references are present.",
    )
    args = parser.parse_args(argv)

    result = audit_custom_checks()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_text(result["summary"])
        if result["orphan_review_queue"]:
            print("orphan_review_queue:")
            for item in result["orphan_review_queue"]:
                print(
                    "  "
                    f"{item['recommended_action']} "
                    f"shadow_similarity={item['shadow_similarity']:.4f} "
                    f"git={item['git_tracking_status']} "
                    f"related={_format_related_paths(item['related_referenced_paths'])} "
                    f"path={item['path']}"
                )
        if result["missing_references"]:
            print("missing_references:")
            for path in result["missing_references"]:
                print(f"  {path}")
        if result["syntax_errors"]:
            print("syntax_errors:")
            for item in result["syntax_errors"]:
                print(f"  {item['path']}: {item['detail']}")

    should_fail = bool(
        args.fail_on_orphans
        and (
            result["orphan_custom_checks"]
            or result["missing_references"]
            or result["syntax_errors"]
        )
    )
    return 1 if should_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
