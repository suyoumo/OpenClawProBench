"""Process-quality scoring."""

from __future__ import annotations

from .models import Scenario


def _tool_sequence(trace: dict) -> list[str]:
    return [
        event.get("tool", "")
        for event in trace.get("events", [])
        if event.get("type") == "tool_call"
    ]


def _ordered_match_ratio(actual: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    position = 0
    matched = 0
    for tool_name in expected:
        while position < len(actual) and actual[position] != tool_name:
            position += 1
        if position == len(actual):
            break
        matched += 1
        position += 1
    return matched / len(expected)


def compute_process_score(trace: dict, scenario: Scenario) -> float:
    actual = _tool_sequence(trace)
    expected = scenario.expected_tools or scenario.tools
    ideal_sequence = scenario.ideal_tool_sequence or expected

    if not actual and not expected:
        return 1.0

    actual_set = {tool for tool in actual if tool}
    expected_set = {tool for tool in expected if tool}
    if not actual_set and expected_set:
        tool_appropriateness = 0.0
    elif not expected_set:
        tool_appropriateness = 1.0
    else:
        precision = len(actual_set & expected_set) / len(actual_set) if actual_set else 0.0
        recall = len(actual_set & expected_set) / len(expected_set) if expected_set else 1.0
        tool_appropriateness = 0.0 if precision + recall == 0 else (2 * precision * recall) / (precision + recall)

    sequence_quality = _ordered_match_ratio(actual, ideal_sequence)

    optimal_steps = max(1, scenario.optimal_steps)
    redundant_steps = max(0, len(actual) - optimal_steps)
    redundancy_ratio = min(1.0, redundant_steps / max(1, len(actual))) if actual else 0.0

    score = (
        tool_appropriateness * 0.4
        + sequence_quality * 0.3
        + (1.0 - redundancy_ratio) * 0.3
    )
    return round(max(0.0, min(1.0, score)), 4)

