"""Grounded scoring for tool_use_07_tool_chain_inference_live."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_TOP_CATEGORIES = [
    {
        "rank": 1,
        "category": "Electronics",
        "net_sales": 5095.0,
        "valid_order_count": 8,
        "average_order_amount": 636.88,
        "largest_order": {
            "order_id": "ORD001",
            "product": "Laptop Pro",
            "amount": 2400.0,
        },
    },
    {
        "rank": 2,
        "category": "Clothing",
        "net_sales": 975.0,
        "valid_order_count": 5,
        "average_order_amount": 195.0,
        "largest_order": {
            "order_id": "ORD010",
            "product": "Jeans",
            "amount": 225.0,
        },
    },
    {
        "rank": 3,
        "category": "Home",
        "net_sales": 775.0,
        "valid_order_count": 4,
        "average_order_amount": 193.75,
        "largest_order": {
            "order_id": "ORD019",
            "product": "Blender",
            "amount": 300.0,
        },
    },
]

EXPECTED_DROPPED_ORDERS = ["ORD015", "ORD017"]
EXPECTED_ADJUSTMENT_SUMMARY = {
    "refund_order_ids": ["ORD006", "ORD014"],
    "cancelled_order_ids": ["ORD015", "ORD017"],
}
EXPECTED_SUMMARY = {
    "evaluated_categories": 4,
    "top_category": "Electronics",
    "winner_margin_vs_runner_up": 4120.0,
}
EXPECTED_EVIDENCE_REFS = {
    "analysis_brief.md",
    "sales_data.json",
    "adjustments.json",
    "report_contract.json",
}
EXPECTED_INPUTS = sorted(EXPECTED_EVIDENCE_REFS)


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _normalize_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    for expected in EXPECTED_EVIDENCE_REFS:
        if normalized.endswith(expected):
            return expected
    if normalized.endswith("category_chain_report.json"):
        return "category_chain_report.json"
    return normalized


def _observed_reads(trace: dict) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        tool = str(event.get("tool", ""))
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if tool in ("read", "Read") and isinstance(raw_path, str) and raw_path:
            paths.add(_normalize_path(raw_path))
        if tool in ("exec", "Exec"):
            command = str(args.get("command", ""))
            for expected in EXPECTED_EVIDENCE_REFS:
                if expected in command:
                    paths.add(expected)
            if "category_chain_report.json" in command:
                paths.add("category_chain_report.json")
    return paths


def _observed_writes(trace: dict) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        tool = str(event.get("tool", ""))
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if tool in ("write", "Write") and isinstance(raw_path, str) and raw_path:
            paths.add(_normalize_path(raw_path))
        if tool in ("exec", "Exec") and "category_chain_report.json" in str(args.get("command", "")):
            paths.add("category_chain_report.json")
    return paths


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "frontier" / "tool_use_07_tool_chain_inference_live" / "fixtures"


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for relative in EXPECTED_INPUTS:
        seeded = fixture_dir / relative
        current = workspace_path / relative
        if not seeded.exists() or not current.exists():
            return False, f"missing required input file {relative}"
        if current.read_text(encoding="utf-8") != seeded.read_text(encoding="utf-8"):
            return False, f"{relative} drifted from the seeded fixture"
    return True, "seeded inputs are present and unchanged"


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = workspace_path / "category_chain_report.json"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.1 if output_exists else 0.0,
        "max": 0.1,
        "detail": "category_chain_report.json exists" if output_exists else "missing category_chain_report.json",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        for check_id, max_score in (
            ("ranking_basis_is_correct", 0.05),
            ("top_categories_are_exact", 0.35),
            ("dropped_orders_are_exact", 0.1),
            ("adjustment_summary_is_exact", 0.15),
            ("summary_is_exact", 0.1),
            ("evidence_refs_are_complete", 0.05),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("ranking_basis_is_correct", 0.05),
            ("top_categories_are_exact", 0.35),
            ("dropped_orders_are_exact", 0.1),
            ("adjustment_summary_is_exact", 0.15),
            ("summary_is_exact", 0.1),
            ("evidence_refs_are_complete", 0.05),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["ranking_basis_is_correct"] = {
        "score": 0.05 if payload.get("ranking_basis") == "net_sales_after_adjustments" else 0.0,
        "max": 0.05,
        "detail": f"ranking_basis={payload.get('ranking_basis')!r}",
    }
    checkpoints["top_categories_are_exact"] = {
        "score": 0.35 if payload.get("top_categories") == EXPECTED_TOP_CATEGORIES else 0.0,
        "max": 0.35,
        "detail": f"top_categories={payload.get('top_categories')}",
    }
    checkpoints["dropped_orders_are_exact"] = {
        "score": 0.1 if payload.get("dropped_orders") == EXPECTED_DROPPED_ORDERS else 0.0,
        "max": 0.1,
        "detail": f"dropped_orders={payload.get('dropped_orders')}",
    }
    checkpoints["adjustment_summary_is_exact"] = {
        "score": 0.15 if payload.get("adjustment_summary") == EXPECTED_ADJUSTMENT_SUMMARY else 0.0,
        "max": 0.15,
        "detail": f"adjustment_summary={payload.get('adjustment_summary')}",
    }
    checkpoints["summary_is_exact"] = {
        "score": 0.1 if payload.get("summary") == EXPECTED_SUMMARY else 0.0,
        "max": 0.1,
        "detail": f"summary={payload.get('summary')}",
    }

    evidence_refs = payload.get("evidence_refs")
    evidence_hits = 0
    if isinstance(evidence_refs, list):
        evidence_text = " ".join(str(item) for item in evidence_refs)
        for expected in EXPECTED_EVIDENCE_REFS:
            if expected in evidence_text:
                evidence_hits += 1
    checkpoints["evidence_refs_are_complete"] = {
        "score": 0.05 if isinstance(evidence_refs, list) and len(evidence_refs) >= 3 and evidence_hits >= 3 else 0.0,
        "max": 0.05,
        "detail": f"evidence_refs={evidence_refs}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _observed_reads(trace)
    write_paths = _observed_writes(trace)

    read_count = sum(1 for item in EXPECTED_EVIDENCE_REFS if item in read_paths)
    wrote_output = "category_chain_report.json" in write_paths

    if read_count == 4 and wrote_output:
        return 1.0
    if read_count >= 3 and wrote_output:
        return 0.8
    if read_count >= 2 and wrote_output:
        return 0.6
    if read_count >= 1 or wrote_output:
        return 0.35
    return 0.2
