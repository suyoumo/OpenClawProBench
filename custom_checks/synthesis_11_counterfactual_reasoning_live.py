"""Custom checks for the counterfactual reasoning scenario."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_TOP_THREE = [
    ("stack", "monolith_first", -35, 30),
    ("testing", "tdd", -42, 23),
    ("delivery", "sequential_integration", -48, 17),
]
EXPECTED_PLAN = ["delivery", "stack", "testing"]
EXPECTED_COMBINED = {
    "performance_multiplier": 2.4,
    "budget_overrun_pct": 50,
    "schedule_delay_months": 1,
    "risk_points": 3,
    "score": 5,
}
EXPECTED_RECOMMENDATIONS = [
    "adopt_tdd_before_sequential_integration_rollout",
    "prioritize_monolith_first_before_parallel_scaling",
]
REQUIRED_INPUTS = {
    "baseline_outcome.json",
    "decision_delta_matrix.json",
    "scoring_policy.yaml",
    "recommendation_catalog.json",
}


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _basename_set(trace: dict, *, tool_name: str) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        if event.get("tool") != tool_name:
            continue
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if isinstance(raw_path, str) and raw_path:
            paths.add(Path(raw_path).name)
    return paths


def _fixture_dir() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "datasets"
        / "frontier"
        / "synthesis_11_counterfactual_reasoning_live"
        / "fixtures"
    )


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for filename in sorted(REQUIRED_INPUTS):
        seeded = fixture_dir / filename
        current = workspace_path / filename
        if not seeded.exists() or not current.exists():
            return False, f"missing required input file {filename}"
        if current.read_text(encoding="utf-8") != seeded.read_text(encoding="utf-8"):
            return False, f"{filename} drifted from the seeded fixture"
    return True, "seeded inputs are present and unchanged"


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = ws / "counterfactual_analysis.json"
    exists = output_path.exists()
    checkpoints["analysis_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "counterfactual_analysis.json exists" if exists else "missing counterfactual_analysis.json",
    }
    inputs_ok, inputs_detail = _seeded_inputs_ok(ws)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }
    if not exists:
        for check_id, max_score in (
            ("individual_rank_is_correct", 0.25),
            ("individual_scores_are_correct", 0.15),
            ("best_plan_is_correct", 0.1),
            ("combined_projection_is_correct", 0.2),
            ("recommendations_are_exact", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("individual_rank_is_correct", 0.25),
            ("individual_scores_are_correct", 0.15),
            ("best_plan_is_correct", 0.1),
            ("combined_projection_is_correct", 0.2),
            ("recommendations_are_exact", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    rank = payload.get("individual_rank")
    rank_score = 0.0
    score_score = 0.0
    if isinstance(rank, list):
        rank_ids = [
            (
                str(item.get("decision_id", "")).strip(),
                str(item.get("alternative", "")).strip(),
            )
            for item in rank
            if isinstance(item, dict)
        ]
        expected_ids = [(decision_id, alternative) for decision_id, alternative, _, _ in EXPECTED_TOP_THREE]
        if rank_ids == expected_ids:
            rank_score = 0.25

        score_hits = 0
        for actual, expected in zip(rank, EXPECTED_TOP_THREE):
            if not isinstance(actual, dict):
                continue
            _, _, projected_score, score_improvement = expected
            if actual.get("projected_score") == projected_score:
                score_hits += 1
            if actual.get("score_improvement") == score_improvement:
                score_hits += 1
        score_score = round(score_hits / 6 * 0.15, 4)
    checkpoints["individual_rank_is_correct"] = {
        "score": rank_score,
        "max": 0.25,
        "detail": f"individual_rank={rank}",
    }
    checkpoints["individual_scores_are_correct"] = {
        "score": score_score,
        "max": 0.15,
        "detail": f"individual_rank_score_hits={score_score}",
    }

    plan = payload.get("best_three_change_plan")
    checkpoints["best_plan_is_correct"] = {
        "score": 0.1 if plan == EXPECTED_PLAN else 0.0,
        "max": 0.1,
        "detail": f"best_three_change_plan={plan}",
    }

    combined = payload.get("combined_projection")
    combined_hits = 0
    if isinstance(combined, dict):
        for key, expected in EXPECTED_COMBINED.items():
            if combined.get(key) == expected:
                combined_hits += 1
    all_combined_correct = combined_hits == len(EXPECTED_COMBINED)
    checkpoints["combined_projection_is_correct"] = {
        "score": 0.2 if all_combined_correct else 0.0,
        "max": 0.2,
        "detail": f"combined_hits={combined_hits}/{len(EXPECTED_COMBINED)}",
    }

    recommendations = payload.get("recommendations")
    checkpoints["recommendations_are_exact"] = {
        "score": 0.1 if recommendations == EXPECTED_RECOMMENDATIONS else 0.0,
        "max": 0.1,
        "detail": f"recommendations={recommendations}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _basename_set(trace, tool_name="read")
    write_paths = _basename_set(trace, tool_name="write")

    read_count = sum(1 for item in REQUIRED_INPUTS if item in read_paths)
    wrote_output = "counterfactual_analysis.json" in write_paths

    if read_count == 4 and wrote_output:
        return 1.0
    if read_count >= 3 and wrote_output:
        return 0.8
    if read_count >= 2 and wrote_output:
        return 0.65
    if read_count >= 1 or wrote_output:
        return 0.4
    return 0.2
