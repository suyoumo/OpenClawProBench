"""Optional task-level custom scoring hooks."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from typing import Any

from .models import Scenario


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load custom check module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call_with_supported_arity(func, *args):
    parameters = list(inspect.signature(func).parameters.values())
    positional = [
        parameter
        for parameter in parameters
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
        return func(*args)
    return func(*args[: len(positional)])


def run_custom_checks(
    scenario: Scenario,
    workspace_path: Path,
    trace: dict[str, Any],
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not scenario.custom_check:
        return None
    candidates = [
        (scenario.source_path.parents[2] / "custom_checks" / scenario.custom_check).resolve(),
        (scenario.source_path.parents[1] / "custom_checks" / scenario.custom_check).resolve(),
    ]
    custom_path = next((path for path in candidates if path.exists()), candidates[0])
    if not custom_path.exists():
        raise FileNotFoundError(f"Custom check file not found: {custom_path}")
    module = _load_module(custom_path)
    if not hasattr(module, "grade"):
        raise AttributeError(f"Custom check file {custom_path} must define grade()")
    result = _call_with_supported_arity(module.grade, str(workspace_path), trace, tool_calls)
    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise TypeError(f"Custom check file {custom_path} grade() must return a dict")
    if hasattr(module, "grade_process") and result.get("process_score") is None:
        process_score = _call_with_supported_arity(module.grade_process, trace, tool_calls)
        result["process_score"] = process_score
    return result
