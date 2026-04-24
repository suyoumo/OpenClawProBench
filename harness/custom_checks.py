"""Optional task-level custom scoring hooks."""

from __future__ import annotations

import importlib.util
import inspect
from copy import deepcopy
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


def normalize_trace_file_args(trace: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(trace)
    events = normalized.get("events")
    if not isinstance(events, list):
        return normalized
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "tool_call":
            continue
        args = event.get("args")
        if not isinstance(args, dict):
            continue
        file_value = args.get("file")
        if not isinstance(file_value, str) or not file_value:
            continue
        args.setdefault("path", file_value)
        args.setdefault("file_path", file_value)
    return normalized


def normalize_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_calls = deepcopy(tool_calls)
    for call in normalized_calls:
        if not isinstance(call, dict):
            continue
        args = call.get("args")
        if not isinstance(args, dict):
            continue
        file_value = args.get("file")
        if not isinstance(file_value, str) or not file_value:
            continue
        args.setdefault("path", file_value)
        args.setdefault("file_path", file_value)
    return normalized_calls


def run_custom_checks(
    scenario: Scenario,
    workspace_path: Path,
    trace: dict[str, Any],
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not scenario.custom_check:
        return None
    normalized_trace = normalize_trace_file_args(trace)
    normalized_tool_calls = normalize_tool_calls(tool_calls)
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
    result = _call_with_supported_arity(module.grade, str(workspace_path), normalized_trace, normalized_tool_calls)
    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise TypeError(f"Custom check file {custom_path} grade() must return a dict")
    if hasattr(module, "grade_process") and result.get("process_score") is None:
        process_score = _call_with_supported_arity(module.grade_process, normalized_trace, normalized_tool_calls)
        result["process_score"] = process_score
    return result
