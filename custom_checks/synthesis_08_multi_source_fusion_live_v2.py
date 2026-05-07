"""Grounded scoring for synthesis_08_multi_source_fusion_live."""

from __future__ import annotations

import json
from pathlib import Path
from harness.custom_check_helpers import evidence_refs_match


EXPECTED_SOURCE_ASSESSMENTS = [
    {"source": "user_feedback.json", "reliability_score": 6, "bias_code": "review_campaign_noise"},
    {"source": "sales_data.csv", "reliability_score": 9, "bias_code": "seasonal_promo_distortion"},
    {"source": "support_tickets.json", "reliability_score": 8, "bias_code": "duplicate_incident_reports"},
    {"source": "competitor_analysis.md", "reliability_score": 4, "bias_code": "marketing_bias_and_outdated_claims"},
]
EXPECTED_ISSUE_CLUSTERS = [
    {"issue_code": "battery_drain_after_firmware_1_4", "ticket_count": 4},
    {"issue_code": "bluetooth_pairing_failure_android_14", "ticket_count": 3},
]
EXPECTED_CONTRADICTIONS = [
    {
        "claim_code": "battery_life_is_consistently_three_days",
        "resolution_code": "reject_using_ticket_cluster_and_return_trend",
    },
    {
        "claim_code": "pairing_issues_are_isolated_setup_errors",
        "resolution_code": "reject_using_duplicate_verified_reports",
    },
]
EXPECTED_PRODUCT_TRUTH = {
    "demand_status": "demand_softened_after_promo_peak",
    "quality_status": "real_quality_regression_present",
    "primary_issue": "battery_drain_after_firmware_1_4",
    "secondary_issue": "bluetooth_pairing_failure_android_14",
}
EXPECTED_UNCERTAINTIES = [
    "review_sentiment_share_is_distorted_by_incentivized_posts",
    "competitor_price_comparisons_may_be_stale",
]
EXPECTED_EVIDENCE_REFS = [
    "user_feedback.json:review_burst@2026-02-10",
    "sales_data.csv:2026-02:return_rate=8.6",
    "support_tickets.json:cluster=battery_drain_after_firmware_1_4",
    "support_tickets.json:cluster=bluetooth_pairing_failure_android_14",
    "competitor_analysis.md:contains_sponsor_disclaimer",
]
EXPECTED_INPUTS = {
    "user_feedback.json",
    "sales_data.csv",
    "support_tickets.json",
    "competitor_analysis.md",
    "fusion_rules.yaml",
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
    return Path(__file__).resolve().parents[1] / "datasets" / "synthesis_08_multi_source_fusion" / "fixtures"


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for filename in sorted(EXPECTED_INPUTS):
        seeded = fixture_dir / filename
        current = workspace_path / filename
        if not seeded.exists() or not current.exists():
            return False, f"missing required input file {filename}"
        if current.read_text(encoding="utf-8") != seeded.read_text(encoding="utf-8"):
            return False, f"{filename} drifted from the seeded fixture"
    return True, "seeded inputs are present and unchanged"


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = workspace_path / "product_truth_fusion.json"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.05 if output_exists else 0.0,
        "max": 0.05,
        "detail": "product_truth_fusion.json exists" if output_exists else "missing product_truth_fusion.json",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        for check_id, max_score in (
            ("source_assessments_are_correct", 0.15),
            ("issue_clusters_are_correct", 0.1),
            ("contradictions_are_correct", 0.1),
            ("product_truth_is_correct", 0.15),
            ("decision_recommendation_is_correct", 0.1),
            ("uncertainties_are_correct", 0.1),
            ("evidence_refs_are_correct", 0.15),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("source_assessments_are_correct", 0.15),
            ("issue_clusters_are_correct", 0.1),
            ("contradictions_are_correct", 0.1),
            ("product_truth_is_correct", 0.15),
            ("decision_recommendation_is_correct", 0.1),
            ("uncertainties_are_correct", 0.1),
            ("evidence_refs_are_correct", 0.15),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["source_assessments_are_correct"] = {
        "score": 0.15 if payload.get("source_assessments") == EXPECTED_SOURCE_ASSESSMENTS else 0.0,
        "max": 0.15,
        "detail": f"source_assessments={payload.get('source_assessments')}",
    }
    checkpoints["issue_clusters_are_correct"] = {
        "score": 0.1 if payload.get("deduplicated_issue_clusters") == EXPECTED_ISSUE_CLUSTERS else 0.0,
        "max": 0.1,
        "detail": f"deduplicated_issue_clusters={payload.get('deduplicated_issue_clusters')}",
    }
    checkpoints["contradictions_are_correct"] = {
        "score": 0.1 if payload.get("contradictions") == EXPECTED_CONTRADICTIONS else 0.0,
        "max": 0.1,
        "detail": f"contradictions={payload.get('contradictions')}",
    }
    checkpoints["product_truth_is_correct"] = {
        "score": 0.15 if payload.get("product_truth") == EXPECTED_PRODUCT_TRUTH else 0.0,
        "max": 0.15,
        "detail": f"product_truth={payload.get('product_truth')}",
    }
    checkpoints["decision_recommendation_is_correct"] = {
        "score": 0.1
        if payload.get("decision_recommendation") == "pause_paid_growth_fix_firmware_and_pairing_before_next_campaign"
        else 0.0,
        "max": 0.1,
        "detail": f"decision_recommendation={payload.get('decision_recommendation')!r}",
    }
    checkpoints["uncertainties_are_correct"] = {
        "score": 0.1 if payload.get("uncertainties") == EXPECTED_UNCERTAINTIES else 0.0,
        "max": 0.1,
        "detail": f"uncertainties={payload.get('uncertainties')}",
    }
    checkpoints["evidence_refs_are_correct"] = {
        "score": 0.15 if evidence_refs_match(payload.get("evidence_refs"), EXPECTED_EVIDENCE_REFS) else 0.0,
        "max": 0.15,
        "detail": f"evidence_refs={payload.get('evidence_refs')}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _basename_set(trace, tool_name="read")
    write_paths = _basename_set(trace, tool_name="write")

    read_count = sum(1 for item in EXPECTED_INPUTS if item in read_paths)
    wrote_output = "product_truth_fusion.json" in write_paths

    if read_count == 5 and wrote_output:
        return 1.0
    if read_count >= 4 and wrote_output:
        return 0.8
    if read_count >= 3 and wrote_output:
        return 0.65
    if read_count >= 2 or wrote_output:
        return 0.4
    return 0.2
