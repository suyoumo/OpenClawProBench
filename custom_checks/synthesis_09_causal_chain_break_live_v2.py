"""Grounded scoring for synthesis_09_causal_chain_break_live."""

from __future__ import annotations

from pathlib import Path

from harness.custom_check_helpers import (
    evidence_refs_match,
    file_exists_checkpoint,
    load_json_output,
    seeded_inputs_unchanged,
    skip_checkpoints,
    tool_arg_paths,
)


EXPECTED_STEP_VERDICTS = [
    {"step": "data_collection", "status": "raw_schema_published"},
    {"step": "data_cleaning", "status": "canonical_key_shifted_to_id"},
    {"step": "feature_extraction", "status": "downstream_contract_preserved"},
    {"step": "model_prediction", "status": "predictions_nonempty_but_id_only"},
    {"step": "result_output", "status": "silent_zero_row_failure"},
]
EXPECTED_BREAK_SUMMARY = {
    "observed_failure_step": "result_output",
    "contract_drift_source_step": "data_cleaning",
    "failure_mode": "hidden_dependency_join_key_mismatch",
    "hidden_input": "collected_data.json",
}
EXPECTED_CONTRACT_BREAK_CHAIN = [
    "collection_exposed_record_id_only",
    "cleaning_shifted_canonical_key_to_id",
    "prediction_emitted_id_only_records",
    "result_output_joined_against_hidden_raw_collection_input",
    "join_dropped_all_rows_but_step_reported_success",
]
EXPECTED_RULED_OUT_CAUSES = [
    "feature_extraction_empty_batch",
    "model_prediction_zero_rows",
    "scheduler_race_before_prediction_write",
]
EXPECTED_IMPACT_SUMMARY = {
    "prediction_rows": 4,
    "final_output_rows": 0,
    "dropped_rows": 4,
    "severity": "sev_1_complete_data_loss",
}
EXPECTED_REPAIR_PLAN = [
    "declare_collected_data_as_result_output_extra_input",
    "add_explicit_id_record_id_alias_mapping_before_join",
    "raise_error_when_joined_rows_are_zero_with_nonempty_predictions",
]
EXPECTED_EVIDENCE_REFS = [
    "pipeline_run.log:result_output_join_left_predictions.id",
    "pipeline_run.log:result_output_zero_matches",
    "config.yaml:result_output_missing_extra_inputs",
    "collected_data.json:record_id_only_schema",
    "predictions.json:id_only_schema",
    "final_output.json:empty_array",
]
EXPECTED_INPUTS = {
    "pipeline_run.log",
    "config.yaml",
    "dependency_graph.md",
    "collected_data.json",
    "cleaned_data.json",
    "features.json",
    "predictions.json",
    "final_output.json",
    "analysis_rules.yaml",
}
DEPENDENT_CHECKS = (
    ("step_verdicts_are_correct", 0.15),
    ("break_summary_is_correct", 0.15),
    ("contract_break_chain_is_correct", 0.1),
    ("ruled_out_causes_are_correct", 0.1),
    ("impact_summary_is_correct", 0.1),
    ("repair_plan_is_correct", 0.15),
    ("evidence_refs_are_correct", 0.1),
)


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "synthesis_09_causal_chain_break" / "fixtures"


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    return seeded_inputs_unchanged(workspace_path, _fixture_dir(), EXPECTED_INPUTS)


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = workspace_path / "causal_chain_break_report.json"
    output_exists = file_exists_checkpoint(
        checkpoints,
        "output_file_exists",
        output_path,
        max_score=0.05,
    )

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    if not output_exists:
        skip_checkpoints(checkpoints, DEPENDENT_CHECKS)
        return {"checkpoints": checkpoints, "safety_violations": []}

    payload, detail = load_json_output(output_path)
    if payload is None:
        skip_checkpoints(checkpoints, DEPENDENT_CHECKS, detail=detail)
        return {"checkpoints": checkpoints, "safety_violations": []}

    checkpoints["step_verdicts_are_correct"] = {
        "score": 0.15 if payload.get("step_verdicts") == EXPECTED_STEP_VERDICTS else 0.0,
        "max": 0.15,
        "detail": f"step_verdicts={payload.get('step_verdicts')}",
    }
    checkpoints["break_summary_is_correct"] = {
        "score": 0.15 if payload.get("break_summary") == EXPECTED_BREAK_SUMMARY else 0.0,
        "max": 0.15,
        "detail": f"break_summary={payload.get('break_summary')}",
    }
    checkpoints["contract_break_chain_is_correct"] = {
        "score": 0.1 if payload.get("contract_break_chain") == EXPECTED_CONTRACT_BREAK_CHAIN else 0.0,
        "max": 0.1,
        "detail": f"contract_break_chain={payload.get('contract_break_chain')}",
    }
    checkpoints["ruled_out_causes_are_correct"] = {
        "score": 0.1 if payload.get("ruled_out_causes") == EXPECTED_RULED_OUT_CAUSES else 0.0,
        "max": 0.1,
        "detail": f"ruled_out_causes={payload.get('ruled_out_causes')}",
    }
    checkpoints["impact_summary_is_correct"] = {
        "score": 0.1 if payload.get("impact_summary") == EXPECTED_IMPACT_SUMMARY else 0.0,
        "max": 0.1,
        "detail": f"impact_summary={payload.get('impact_summary')}",
    }
    checkpoints["repair_plan_is_correct"] = {
        "score": 0.15 if payload.get("repair_plan") == EXPECTED_REPAIR_PLAN else 0.0,
        "max": 0.15,
        "detail": f"repair_plan={payload.get('repair_plan')}",
    }
    checkpoints["evidence_refs_are_correct"] = {
        "score": 0.1 if evidence_refs_match(payload.get("evidence_refs"), EXPECTED_EVIDENCE_REFS) else 0.0,
        "max": 0.1,
        "detail": f"evidence_refs={payload.get('evidence_refs')}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = tool_arg_paths(trace, tool_name="read", basename=True)
    write_paths = tool_arg_paths(trace, tool_name="write", basename=True)

    read_count = sum(1 for item in EXPECTED_INPUTS if item in read_paths)
    wrote_output = "causal_chain_break_report.json" in write_paths

    if read_count == 9 and wrote_output:
        return 1.0
    if read_count >= 7 and wrote_output:
        return 0.85
    if read_count >= 5 and wrote_output:
        return 0.7
    if read_count >= 3 and wrote_output:
        return 0.5
    if read_count >= 2 or wrote_output:
        return 0.3
    return 0.15
