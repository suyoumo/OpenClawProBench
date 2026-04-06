"""Grounded scoring for synthesis_10_cross_modal_reasoning_live."""

from __future__ import annotations

import json
import re
from pathlib import Path


EXPECTED_TIMELINE = [
    {"time": "09:13:58", "event": "u431_opened_profile_preferences"},
    {"time": "09:14:07", "event": "u431_submitted_locale_zh-Hans-CN"},
    {"time": "09:14:08", "event": "profile_api_failed_in_normalize_locale"},
    {"time": "09:14:09", "event": "ui_banner_profile_save_failed_rendered"},
    {"time": "09:15:00", "event": "profile_save_error_rate_spike_confirmed"},
]
EXPECTED_CAUSAL_CHAIN = [
    "user_selected_three_part_locale",
    "backend_replaced_hyphen_with_underscore",
    "normalize_locale_raised_value_error",
    "profile_save_returned_500",
    "client_rendered_PROFILE_SAVE_FAILED_banner",
]
EXPECTED_FIXES = [
    "support_three_part_locales_in_normalize_locale",
    "add_regression_test_for_zh_Hans_CN",
    "return_validation_error_instead_of_500_for_bad_locale_shapes",
]
EXPECTED_EVIDENCE_MARKERS = {
    "application.log",
    "metrics.json",
    "users.csv",
    "screenshot.txt",
    "buggy_code.py",
}


def _normalize_time_value(value: object) -> str:
    text = str(value).strip()
    match = re.search(r"(\d{2}:\d{2}:\d{2})", text)
    return match.group(1) if match else text


def _timeline_matches(value: object) -> bool:
    if not isinstance(value, list) or len(value) != len(EXPECTED_TIMELINE):
        return False
    normalized_rows: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict):
            return False
        normalized_rows.append(
            {
                "time": _normalize_time_value(row.get("time")),
                "event": str(row.get("event", "")),
            }
        )
    return normalized_rows == EXPECTED_TIMELINE


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
        / "synthesis_10_cross_modal_reasoning_live"
        / "fixtures"
    )


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for filename in (
        "application.log",
        "metrics.json",
        "users.csv",
        "screenshot.txt",
        "buggy_code.py",
        "event_catalog.json",
        "incident_taxonomy.json",
        "fix_catalog.json",
    ):
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

    output_path = workspace_path / "incident_story.json"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.05 if output_exists else 0.0,
        "max": 0.05,
        "detail": "incident_story.json exists" if output_exists else "missing incident_story.json",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.05 if inputs_ok else 0.0,
        "max": 0.05,
        "detail": inputs_detail,
    }

    if not output_exists:
        for check_id, max_score in (
            ("timeline_is_correct", 0.2),
            ("user_and_trigger_are_correct", 0.15),
            ("symptom_and_root_cause_are_correct", 0.15),
            ("causal_chain_is_correct", 0.1),
            ("fix_recommendations_are_correct", 0.1),
            ("confidence_is_correct", 0.1),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("timeline_is_correct", 0.2),
            ("user_and_trigger_are_correct", 0.15),
            ("symptom_and_root_cause_are_correct", 0.15),
            ("causal_chain_is_correct", 0.1),
            ("fix_recommendations_are_correct", 0.1),
            ("confidence_is_correct", 0.1),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    timeline = payload.get("timeline")
    checkpoints["timeline_is_correct"] = {
        "score": 0.2 if _timeline_matches(timeline) else 0.0,
        "max": 0.2,
        "detail": f"timeline={timeline}",
    }

    user_and_trigger_ok = (
        payload.get("affected_user") == "u-431"
        and payload.get("trigger_action") == "save_profile_with_locale_zh-Hans-CN"
    )
    checkpoints["user_and_trigger_are_correct"] = {
        "score": 0.15 if user_and_trigger_ok else 0.0,
        "max": 0.15,
        "detail": (
            f"affected_user={payload.get('affected_user')!r} "
            f"trigger_action={payload.get('trigger_action')!r}"
        ),
    }

    symptom_and_root_ok = (
        payload.get("ui_symptom") == "PROFILE_SAVE_FAILED"
        and payload.get("root_cause") == "normalize_locale_unpacked_three_part_locale_into_two_variables"
    )
    checkpoints["symptom_and_root_cause_are_correct"] = {
        "score": 0.15 if symptom_and_root_ok else 0.0,
        "max": 0.15,
        "detail": (
            f"ui_symptom={payload.get('ui_symptom')!r} "
            f"root_cause={payload.get('root_cause')!r}"
        ),
    }
    checkpoints["causal_chain_is_correct"] = {
        "score": 0.1 if payload.get("causal_chain") == EXPECTED_CAUSAL_CHAIN else 0.0,
        "max": 0.1,
        "detail": f"causal_chain={payload.get('causal_chain')}",
    }
    checkpoints["fix_recommendations_are_correct"] = {
        "score": 0.1 if payload.get("fix_recommendations") == EXPECTED_FIXES else 0.0,
        "max": 0.1,
        "detail": f"fix_recommendations={payload.get('fix_recommendations')}",
    }
    checkpoints["confidence_is_correct"] = {
        "score": 0.1 if payload.get("confidence") == "high" else 0.0,
        "max": 0.1,
        "detail": f"confidence={payload.get('confidence')!r}",
    }

    evidence_refs = payload.get("evidence_refs")
    evidence_text = " ".join(str(item) for item in evidence_refs) if isinstance(evidence_refs, list) else ""
    evidence_hits = {marker for marker in EXPECTED_EVIDENCE_MARKERS if marker in evidence_text}
    checkpoints["evidence_refs_are_complete"] = {
        "score": 0.1
        if isinstance(evidence_refs, list)
        and len(evidence_refs) >= 5
        and evidence_hits == EXPECTED_EVIDENCE_MARKERS
        else 0.0,
        "max": 0.1,
        "detail": f"evidence_refs={evidence_refs}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _basename_set(trace, tool_name="read")
    write_paths = _basename_set(trace, tool_name="write")

    required_reads = {
        "application.log",
        "metrics.json",
        "users.csv",
        "screenshot.txt",
        "buggy_code.py",
        "event_catalog.json",
        "incident_taxonomy.json",
        "fix_catalog.json",
    }
    read_count = sum(1 for item in required_reads if item in read_paths)
    wrote_output = "incident_story.json" in write_paths

    if read_count == 8 and wrote_output:
        return 1.0
    if read_count >= 7 and wrote_output:
        return 0.8
    if read_count >= 6 and wrote_output:
        return 0.65
    if read_count >= 4 or wrote_output:
        return 0.4
    return 0.2
