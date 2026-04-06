"""Efficiency penalty and aggregation helpers."""

from __future__ import annotations

import math
from statistics import mean, median


def compute_efficiency_penalty(actual_steps: int, optimal_steps: int, *, cap: float = 0.30, rate: float = 0.15) -> float:
    if optimal_steps <= 0 or actual_steps <= optimal_steps:
        return 0.0
    penalty = ((actual_steps - optimal_steps) / optimal_steps) * rate
    return round(min(cap, max(0.0, penalty)), 4)


def efficiency_score_from_penalty(penalty: float, *, cap: float = 0.30) -> float:
    if penalty <= 0.0:
        return 1.0
    return round(max(0.0, 1.0 - (penalty / cap)), 4)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * p / 100
    floor_index = int(math.floor(index))
    ceil_index = int(math.ceil(index))
    if floor_index == ceil_index:
        return ordered[floor_index]
    lower = ordered[floor_index]
    upper = ordered[ceil_index]
    return lower + (upper - lower) * (index - floor_index)


def aggregate_metric(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0, "p95": 0.0}
    return {
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "avg": round(mean(values), 4),
        "median": round(median(values), 4),
        "p95": round(_percentile(values, 95), 4),
    }

