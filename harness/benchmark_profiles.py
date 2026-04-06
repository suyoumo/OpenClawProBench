"""Named benchmark profiles for OpenClawProBench."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkProfileSpec:
    profile_id: str
    description: str
    benchmark_group: str | None
    benchmark_core: bool | None
    benchmark_status: str | None
    signal_source: str | None


PROFILE_SPECS: dict[str, BenchmarkProfileSpec] = {
    "core": BenchmarkProfileSpec(
        profile_id="core",
        description="Default ranking suite: high-signal intelligence core only.",
        benchmark_group="intelligence",
        benchmark_core=True,
        benchmark_status="active",
        signal_source=None,
    ),
    "intelligence": BenchmarkProfileSpec(
        profile_id="intelligence",
        description="Full intelligence suite: core plus extended intelligence tasks.",
        benchmark_group="intelligence",
        benchmark_core=None,
        benchmark_status="active",
        signal_source=None,
    ),
    "coverage": BenchmarkProfileSpec(
        profile_id="coverage",
        description="Broad regression coverage: templated and basic-skill scenarios.",
        benchmark_group="coverage",
        benchmark_core=None,
        benchmark_status="active",
        signal_source=None,
    ),
    "full": BenchmarkProfileSpec(
        profile_id="full",
        description="All benchmark scenarios across intelligence and coverage.",
        benchmark_group=None,
        benchmark_core=None,
        benchmark_status="active",
        signal_source=None,
    ),
    "native": BenchmarkProfileSpec(
        profile_id="native",
        description="Active OpenClaw-native live slice only. Informational until native coverage is large enough for ranking.",
        benchmark_group=None,
        benchmark_core=None,
        benchmark_status="active",
        signal_source="openclaw_native",
    ),
}


def benchmark_profile_choices() -> list[str]:
    return list(PROFILE_SPECS)


def get_benchmark_profile(profile_id: str | None) -> BenchmarkProfileSpec:
    normalized = profile_id or "full"
    try:
        return PROFILE_SPECS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unknown benchmark profile: {normalized}") from exc


def infer_benchmark_profile(
    benchmark_group: str | None,
    benchmark_core: bool | None,
    benchmark_status: str | None,
    signal_source: str | None,
) -> str:
    for profile_id, spec in PROFILE_SPECS.items():
        if (
            spec.benchmark_group == benchmark_group
            and spec.benchmark_core == benchmark_core
            and spec.benchmark_status == benchmark_status
            and spec.signal_source == signal_source
        ):
            return profile_id
    return "custom"


def resolve_benchmark_selection(
    benchmark_profile: str | None,
    benchmark_group: str | None = None,
    benchmark_core: bool | None = None,
    benchmark_status: str | None = None,
    signal_source: str | None = None,
) -> dict[str, str | bool | None]:
    requested = get_benchmark_profile(benchmark_profile)
    resolved_group = requested.benchmark_group if benchmark_group is None else benchmark_group
    resolved_core = requested.benchmark_core if benchmark_core is None else benchmark_core
    resolved_status = requested.benchmark_status if benchmark_status is None else benchmark_status
    resolved_signal = requested.signal_source if signal_source is None else signal_source
    if resolved_group == "all":
        resolved_group = None
    if resolved_status == "all":
        resolved_status = None
    if resolved_signal == "all":
        resolved_signal = None
    resolved_profile = infer_benchmark_profile(
        resolved_group,
        resolved_core,
        resolved_status,
        resolved_signal,
    )
    return {
        "requested_benchmark_profile": requested.profile_id,
        "benchmark_profile": resolved_profile,
        "benchmark_group": resolved_group,
        "benchmark_core": resolved_core,
        "benchmark_status": resolved_status,
        "signal_source": resolved_signal,
    }


def benchmark_core_label(benchmark_core: bool | None) -> str:
    if benchmark_core is None:
        return "all"
    return "core" if benchmark_core else "extended"
