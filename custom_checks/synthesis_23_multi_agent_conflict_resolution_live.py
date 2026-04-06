from __future__ import annotations

import json
from pathlib import Path

EXPECTED_INVALIDATED = [
    {
        "proposal_id": "alpha-plan",
        "reason": "claims rollout can continue despite the source-of-truth error budget threshold requiring rollback",
    }
]
EXPECTED_REFS = ["agent_summaries.json", "source_of_truth.md", "output_spec.json"]


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_paths(trace: dict) -> set[str]:
    paths: set[str] = set()
    for event in trace.get("events", []):
        if event.get("type") != "tool_call" or event.get("tool") != "read":
            continue
        args = event.get("args") or {}
        raw = args.get("file_path") or args.get("path")
        if isinstance(raw, str) and raw:
            paths.add(Path(raw).name)
    return paths


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    payload = _load_json(workspace_path / "multi_agent_resolution.json")
    source_text = _read_text(workspace_path / "source_of_truth.md").lower()
    checkpoints: dict[str, dict[str, object]] = {}

    read_paths = _read_paths(trace)
    used_all_inputs = {"agent_summaries.json", "source_of_truth.md", "output_spec.json"}.issubset(read_paths)
    checkpoints["used_all_inputs"] = {
        "score": 0.15 if used_all_inputs else 0.0,
        "max": 0.15,
        "detail": f"read_paths={sorted(read_paths)!r}",
    }
    checkpoints["report_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": "multi_agent_resolution.json exists" if payload is not None else "missing or invalid multi_agent_resolution.json",
    }

    if payload is None:
        for check_id, max_score in (("winner_is_correct", 0.2), ("final_decision_is_grounded", 0.2), ("invalidated_proposals_are_correct", 0.15), ("evidence_refs_are_exact", 0.1), ("reason_mentions_budget_breach", 0.1)):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    winner_ok = payload.get("winning_proposal_id") == "beta-plan" and payload.get("selected_agent") == "agent_beta"
    checkpoints["winner_is_correct"] = {
        "score": 0.2 if winner_ok else 0.0,
        "max": 0.2,
        "detail": f"winning_proposal_id={payload.get('winning_proposal_id')!r} selected_agent={payload.get('selected_agent')!r}",
    }

    final_ok = payload.get("final_owner") == "release-manager" and payload.get("rollback_required") is True
    checkpoints["final_decision_is_grounded"] = {
        "score": 0.2 if final_ok else 0.0,
        "max": 0.2,
        "detail": f"final_owner={payload.get('final_owner')!r} rollback_required={payload.get('rollback_required')!r}",
    }

    checkpoints["invalidated_proposals_are_correct"] = {
        "score": 0.15 if payload.get("invalidated_proposals") == EXPECTED_INVALIDATED else 0.0,
        "max": 0.15,
        "detail": f"invalidated_proposals={payload.get('invalidated_proposals')!r}",
    }
    checkpoints["evidence_refs_are_exact"] = {
        "score": 0.1 if payload.get("evidence_refs") == EXPECTED_REFS else 0.0,
        "max": 0.1,
        "detail": f"evidence_refs={payload.get('evidence_refs')!r}",
    }

    decision_reason = str(payload.get("decision_reason", "")).lower()
    mentions_budget = ("0.8" in decision_reason or "0.8%" in decision_reason) and ("2.0" in decision_reason or "2.0%" in decision_reason) and ("rollback" in decision_reason) and ("error budget" in decision_reason or "budget" in source_text)
    checkpoints["reason_mentions_budget_breach"] = {
        "score": 0.1 if mentions_budget else 0.0,
        "max": 0.1,
        "detail": f"decision_reason={payload.get('decision_reason')!r}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _read_paths(trace)
    wrote_output = any(
        event.get("type") == "tool_call"
        and event.get("tool") == "write"
        and str((event.get("args") or {}).get("file_path", "")).endswith("multi_agent_resolution.json")
        for event in trace.get("events", [])
    )
    read_count = sum(1 for name in ("agent_summaries.json", "source_of_truth.md", "output_spec.json") if name in read_paths)
    if read_count == 3 and wrote_output:
        return 1.0
    if read_count == 3:
        return 0.75
    if read_count >= 2 and wrote_output:
        return 0.65
    if read_count >= 1 or wrote_output:
        return 0.4
    return 0.2
