"""Optional task-level custom scoring hooks."""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

from .models import Scenario

_LOAD_ATTEMPTS = int(os.environ.get("OPENCLAW_CUSTOM_CHECK_LOAD_ATTEMPTS", "10"))
_LOAD_BASE_DELAY_SECONDS = float(os.environ.get("OPENCLAW_CUSTOM_CHECK_LOAD_BASE_DELAY_SECONDS", "0.2"))
_MODULE_CACHE: dict[str, tuple[tuple[int, int] | None, ModuleType]] = {}
_MODULE_CACHE_LOCK = threading.Lock()


def _module_cache_key(path: Path) -> str:
    return str(path.resolve(strict=False))


def _module_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _load_module_from_source(path: Path, module_name: str, spec) -> ModuleType:
    source = path.read_text(encoding="utf-8")
    module = ModuleType(module_name)
    module.__file__ = str(path)
    module.__loader__ = spec.loader if spec is not None else None
    module.__package__ = ""
    module.__spec__ = spec
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def _load_module(path: Path):
    cache_key = _module_cache_key(path)
    fingerprint = _module_fingerprint(path)
    with _MODULE_CACHE_LOCK:
        cached = _MODULE_CACHE.get(cache_key)
        if cached and cached[0] == fingerprint:
            return cached[1]

        last_error: Exception | None = None
        for attempt in range(max(_LOAD_ATTEMPTS, 1)):
            importlib.invalidate_caches()
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Could not load custom check module from {path}")
            module = importlib.util.module_from_spec(spec)
            previous_module = sys.modules.get(spec.name)
            try:
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                _MODULE_CACHE[cache_key] = (fingerprint, module)
                return module
            except PermissionError as exc:
                last_error = exc
                try:
                    module = _load_module_from_source(path, spec.name, spec)
                    _MODULE_CACHE[cache_key] = (fingerprint, module)
                    return module
                except PermissionError as fallback_exc:
                    last_error = fallback_exc
                finally:
                    if previous_module is None:
                        sys.modules.pop(spec.name, None)
                    else:
                        sys.modules[spec.name] = previous_module
                if attempt == _LOAD_ATTEMPTS - 1:
                    break
                time.sleep(_LOAD_BASE_DELAY_SECONDS * (attempt + 1))
            except Exception:
                if previous_module is None:
                    sys.modules.pop(spec.name, None)
                else:
                    sys.modules[spec.name] = previous_module
                raise
        assert last_error is not None
        raise PermissionError(f"Could not load custom check module from {path}: {last_error}") from last_error


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


def _normalize_tool_args(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        normalized = deepcopy(args)
    else:
        normalized = {}
        if args not in (None, ""):
            normalized["raw"] = args
            normalized["command"] = str(args)
    file_value = normalized.get("file")
    if isinstance(file_value, str) and file_value:
        normalized.setdefault("path", file_value)
        normalized.setdefault("file_path", file_value)
    return normalized


def normalize_trace_file_args(trace: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(trace)
    events = normalized.get("events")
    if not isinstance(events, list):
        return normalized
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "tool_call":
            continue
        event["args"] = _normalize_tool_args(event.get("args"))
    return normalized


def normalize_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_calls = deepcopy(tool_calls)
    for call in normalized_calls:
        if not isinstance(call, dict):
            continue
        call["args"] = _normalize_tool_args(call.get("args"))
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
