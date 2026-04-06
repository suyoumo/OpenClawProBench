"""Scenario loading and validation."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .models import (
    BenchmarkGroup,
    BenchmarkStatus,
    CheckCategory,
    CheckSpec,
    Difficulty,
    Dimension,
    Scenario,
    SignalSource,
)


OPENCLAW_SURFACE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("calendar_", "calendar"),
    ("gmail_", "gmail"),
    ("contacts_", "contacts"),
    ("message_", "message"),
    ("directory_", "directory"),
    ("memory_", "memory"),
    ("browser_", "browser"),
    ("feishu_", "feishu"),
    ("task_", "task"),
    ("bitable_", "bitable"),
    ("wiki_", "wiki"),
    ("sheet_", "sheet"),
    ("im_", "im"),
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def scenarios_root() -> Path:
    return project_root() / "scenarios"


def results_root() -> Path:
    return project_root() / "results"


def config_root() -> Path:
    return project_root() / "config"


def _parse_dimension(value: str) -> Dimension:
    return Dimension(value.strip())


def _parse_difficulty(value: str) -> Difficulty:
    return Difficulty(value.strip())


def _parse_benchmark_group(value: str) -> BenchmarkGroup:
    return BenchmarkGroup(value.strip())


def _parse_benchmark_status(value: str) -> BenchmarkStatus:
    return BenchmarkStatus(value.strip())


def _parse_signal_source(value: str) -> SignalSource:
    return SignalSource(value.strip())


def _parse_category(value: str) -> CheckCategory:
    return CheckCategory(value.strip())


def _normalize_tags(
    raw_tags: list[Any] | None,
    benchmark_group: BenchmarkGroup,
    benchmark_core: bool,
    benchmark_status: BenchmarkStatus,
    signal_source: SignalSource,
) -> list[str]:
    normalized = [
        str(tag)
        for tag in (raw_tags or [])
        if not str(tag).startswith("benchmark-")
        and not str(tag).startswith("signal-")
    ]
    normalized.append(f"benchmark-{benchmark_group.value}")
    normalized.append("benchmark-core" if benchmark_core else "benchmark-extended")
    normalized.append(f"benchmark-{benchmark_status.value}")
    normalized.append(f"signal-{signal_source.value}")
    deduped: list[str] = []
    for tag in normalized:
        if tag not in deduped:
            deduped.append(tag)
    return deduped


def custom_checks_root() -> Path:
    return project_root() / "custom_checks"


def _validate_scenario_metadata(raw: dict[str, Any], scenario_path: Path) -> tuple[BenchmarkGroup, BenchmarkStatus]:
    benchmark_group_raw = raw.get("benchmark_group")
    if not benchmark_group_raw:
        raise ValueError(f"{scenario_path}: missing required benchmark_group")
    benchmark_group = _parse_benchmark_group(str(benchmark_group_raw))
    benchmark_status = _parse_benchmark_status(str(raw.get("benchmark_status", "active")))
    benchmark_core = bool(raw.get("benchmark_core", False))

    if benchmark_group == BenchmarkGroup.COVERAGE and benchmark_core:
        raise ValueError(f"{scenario_path}: coverage scenarios cannot be benchmark_core")

    custom_check = raw.get("custom_check")
    if benchmark_status == BenchmarkStatus.ACTIVE and custom_check:
        custom_check_path = (custom_checks_root() / str(custom_check)).resolve()
        if not custom_check_path.exists():
            raise ValueError(
                f"{scenario_path}: active scenario references missing custom_check {custom_check!r}"
            )

    return benchmark_group, benchmark_status


def _infer_openclaw_surfaces(raw_tools: list[Any] | None, raw_surfaces: list[Any] | None) -> list[str]:
    explicit = [str(surface).strip() for surface in (raw_surfaces or []) if str(surface).strip()]
    if explicit:
        return explicit

    inferred: list[str] = []
    for raw_tool in raw_tools or []:
        tool = str(raw_tool).strip()
        for prefix, surface in OPENCLAW_SURFACE_PREFIXES:
            if tool.startswith(prefix) and surface not in inferred:
                inferred.append(surface)
    return inferred


def _infer_signal_source(
    *,
    execution_mode: str,
    raw_signal_source: Any,
    openclaw_surfaces: list[str],
) -> SignalSource:
    if raw_signal_source:
        return _parse_signal_source(str(raw_signal_source))
    if execution_mode == "replay":
        return SignalSource.REPLAY
    if openclaw_surfaces:
        return SignalSource.OPENCLAW_NATIVE
    return SignalSource.WORKSPACE_LIVE


def load_scenario(path: str | Path) -> Scenario:
    scenario_path = Path(path).resolve()
    raw = yaml.safe_load(scenario_path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{scenario_path}: expected a mapping at top level")
    benchmark_group, benchmark_status = _validate_scenario_metadata(raw, scenario_path)
    replay_traces: dict[str, Path] = {}
    for model_name, relative_path in (raw.get("replay_traces") or {}).items():
        replay_traces[str(model_name)] = (scenario_path.parent / str(relative_path)).resolve()

    checks: list[CheckSpec] = []
    raw_checks = raw.get("checks")
    if raw_checks is None:
        raw_checks = ((raw.get("scoring") or {}).get("checks")) or []
    for raw_check in raw_checks:
        cfg = dict(raw_check)
        cfg.pop("id", None)
        cfg.pop("type", None)
        cfg.pop("points", None)
        cfg.pop("category", None)
        cfg.pop("description", None)
        checks.append(
            CheckSpec(
                check_id=raw_check["id"],
                check_type=raw_check["type"],
                points=float(raw_check.get("points", 1.0)),
                category=_parse_category(raw_check.get("category", "correctness")),
                description=raw_check.get("description", ""),
                config=cfg,
            )
        )

    execution_mode = str(raw.get("execution_mode", "replay")).strip()
    openclaw_surfaces = _infer_openclaw_surfaces(raw.get("tools", []), raw.get("openclaw_surfaces", []))
    signal_source = _infer_signal_source(
        execution_mode=execution_mode,
        raw_signal_source=raw.get("signal_source"),
        openclaw_surfaces=openclaw_surfaces,
    )

    return Scenario(
        scenario_id=raw["id"],
        name=raw.get("name", raw["id"]),
        dimension=_parse_dimension(raw["dimension"]),
        difficulty=_parse_difficulty(raw.get("difficulty", "medium")),
        benchmark_group=benchmark_group,
        benchmark_status=benchmark_status,
        signal_source=signal_source,
        benchmark_core=bool(raw.get("benchmark_core", False)),
        weight=float(raw.get("weight", 1.0)),
        timeout_seconds=int(raw.get("timeout_seconds", 180)),
        optimal_steps=int(raw.get("optimal_steps", 5)),
        prompt=raw.get("prompt", "").strip(),
        tools=list(raw.get("tools", [])),
        checks=checks,
        source_path=scenario_path,
        tags=_normalize_tags(
            raw.get("tags", []),
            benchmark_group=benchmark_group,
            benchmark_core=bool(raw.get("benchmark_core", False)),
            benchmark_status=benchmark_status,
            signal_source=signal_source,
        ),
        openclaw_surfaces=openclaw_surfaces,
        pass_threshold=float(raw.get("pass_threshold", 0.6)),
        expected_tools=list(raw.get("expected_tools", [])),
        ideal_tool_sequence=list(raw.get("ideal_tool_sequence", [])),
        mock_responses=dict(raw.get("mock_responses", {})),
        fault_injection=list(raw.get("fault_injection", [])),
        fixtures=dict(raw.get("fixtures", {})),
        workspace_files=list(raw.get("workspace_files", [])),
        workspace_seed_dir=raw.get("workspace_seed_dir"),
        setup_script=raw.get("setup_script"),
        teardown_script=raw.get("teardown_script"),
        replay_traces=replay_traces,
        custom_check=raw.get("custom_check"),
        execution_mode=execution_mode,
        efficiency_penalty_cap=raw.get("efficiency_penalty_cap"),
        efficiency_penalty_rate=raw.get("efficiency_penalty_rate"),
    )


def load_scenarios(
    root: str | Path | None = None,
    dimension: str | None = None,
    scenario_id: str | None = None,
    difficulty: str | None = None,
    tag: str | None = None,
    execution_mode: str | None = None,
    benchmark_group: str | None = None,
    benchmark_core: bool | None = None,
    benchmark_status: str | None = "active",
    signal_source: str | None = None,
) -> list[Scenario]:
    base = Path(root) if root is not None else scenarios_root()
    scenarios: list[Scenario] = []
    for path in sorted(base.rglob("*.yaml")):
        scenario = load_scenario(path)
        if dimension and scenario.dimension.value != dimension:
            continue
        if scenario_id and scenario.scenario_id != scenario_id:
            continue
        if difficulty and scenario.difficulty.value != difficulty:
            continue
        if benchmark_group and benchmark_group != "all" and scenario.benchmark_group.value != benchmark_group:
            continue
        if benchmark_core is not None and scenario.benchmark_core != benchmark_core:
            continue
        if benchmark_status and benchmark_status != "all" and scenario.benchmark_status.value != benchmark_status:
            continue
        if signal_source and signal_source != "all" and scenario.signal_source.value != signal_source:
            continue
        if tag and tag not in scenario.tags:
            continue
        if execution_mode and execution_mode != "auto" and scenario.execution_mode != execution_mode:
            continue
        scenarios.append(scenario)
    return scenarios


def summarize_scenarios(scenarios: list[Scenario]) -> dict[str, Any]:
    by_dimension = Counter(s.dimension.value for s in scenarios)
    by_difficulty = Counter(s.difficulty.value for s in scenarios)
    by_mode = Counter(s.execution_mode for s in scenarios)
    by_group = Counter(s.benchmark_group.value for s in scenarios)
    by_core = Counter("core" if s.benchmark_core else "extended" for s in scenarios)
    by_status = Counter(s.benchmark_status.value for s in scenarios)
    by_signal = Counter(s.signal_source.value for s in scenarios)
    by_surface = Counter(surface for s in scenarios for surface in s.openclaw_surfaces)
    return {
        "count": len(scenarios),
        "dimensions": dict(by_dimension),
        "difficulties": dict(by_difficulty),
        "execution_modes": dict(by_mode),
        "benchmark_groups": dict(by_group),
        "benchmark_core": dict(by_core),
        "benchmark_statuses": dict(by_status),
        "signal_sources": dict(by_signal),
        "openclaw_surfaces": dict(by_surface),
    }
