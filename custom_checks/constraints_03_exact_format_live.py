"""Grounded scoring for constraints_03_exact_format_live."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import yaml


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
    return Path(__file__).resolve().parents[1] / "datasets" / "frontier" / "constraints_03_enhanced" / "fixtures"


def _load_request(path: Path) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _load_config(path: Path) -> dict | None:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return raw if isinstance(raw, dict) else None


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for filename in ("request.json", "config.yaml"):
        seeded = fixture_dir / filename
        current = workspace_path / filename
        if not seeded.exists() or not current.exists():
            return False, f"missing required input file {filename}"
        if current.read_text(encoding="utf-8") != seeded.read_text(encoding="utf-8"):
            return False, f"{filename} drifted from the seeded fixture"
    return True, "seeded inputs are present and unchanged"


def _expected_decision(workspace_path: Path) -> tuple[dict | None, str]:
    request = _load_request(workspace_path / "request.json")
    config = _load_config(workspace_path / "config.yaml")
    if not request or not config:
        return None, "missing or invalid request/config inputs"

    release_policy = config.get("release_policy") or {}
    risk_policy = config.get("risk_policy") or {}
    business_hours = release_policy.get("business_hours_utc") or {}
    impact_multipliers = risk_policy.get("impact_multipliers") or {}

    release_time = datetime.fromisoformat(str(request.get("release_time", "")).replace("Z", "+00:00"))
    weekday = release_time.strftime("%a")
    hour = release_time.hour
    allowed_weekdays = set(str(item) for item in release_policy.get("allowed_weekdays", []))
    start_hour = int(business_hours.get("start_hour", 9))
    end_hour = int(business_hours.get("end_hour_exclusive", 18))
    minimum_test_coverage = float(release_policy.get("minimum_test_coverage", 0.90))
    maximum_open_bugs = int(release_policy.get("maximum_open_bugs", 0))
    test_coverage = float(request.get("test_coverage", 0.0))
    bug_count = int(request.get("bug_count", 0))
    impact_scope = str(request.get("impact_scope", "minor"))
    impact_multiplier = int(impact_multipliers.get(impact_scope, 1))
    risk_score = bug_count * impact_multiplier
    medium_max = int(risk_policy.get("medium_max", 4))

    within_window = weekday in allowed_weekdays and start_hour <= hour < end_hour
    status = "GO" if within_window and test_coverage >= minimum_test_coverage and bug_count <= maximum_open_bugs else "HOLD"

    if risk_score == 0:
        risk = "low"
    elif risk_score <= medium_max:
        risk = "medium"
    else:
        risk = "high"

    return {
        "status": status,
        "risk": risk,
        "weekday": weekday,
        "hour": hour,
        "bug_count": bug_count,
        "test_coverage": test_coverage,
        "risk_score": risk_score,
        "maximum_open_bugs": maximum_open_bugs,
    }, "loaded request and config"


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = workspace_path / "release_status.txt"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.1 if output_exists else 0.0,
        "max": 0.1,
        "detail": "release_status.txt exists" if output_exists else "missing release_status.txt",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    expected, expected_detail = _expected_decision(workspace_path)
    if expected is None or not output_exists:
        for check_id, max_score in (
            ("format_is_exact", 0.2),
            ("status_is_correct", 0.2),
            ("risk_is_correct", 0.15),
            ("reason_is_grounded", 0.25),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    lines = [line.rstrip() for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    format_ok = (
        len(lines) == 3
        and lines[0].startswith("STATUS: ")
        and lines[1].startswith("RISK: ")
        and lines[2].startswith("REASON: ")
    )
    checkpoints["format_is_exact"] = {
        "score": 0.2 if format_ok else 0.0,
        "max": 0.2,
        "detail": repr(lines),
    }

    actual_status = lines[0].split(": ", 1)[1].strip() if len(lines) >= 1 and ": " in lines[0] else ""
    actual_risk = lines[1].split(": ", 1)[1].strip() if len(lines) >= 2 and ": " in lines[1] else ""
    reason = lines[2].split(": ", 1)[1].strip() if len(lines) >= 3 and ": " in lines[2] else ""

    checkpoints["status_is_correct"] = {
        "score": 0.2 if actual_status == expected["status"] else 0.0,
        "max": 0.2,
        "detail": f"status={actual_status!r} expected={expected['status']!r}",
    }
    checkpoints["risk_is_correct"] = {
        "score": 0.15 if actual_risk == expected["risk"] else 0.0,
        "max": 0.15,
        "detail": (
            f"risk={actual_risk!r} expected={expected['risk']!r} "
            f"risk_score={expected['risk_score']}"
        ),
    }

    reason_lower = reason.lower()
    reason_len_ok = 0 < len(reason) <= 80

    # Require concrete numeric evidence, not just keyword mentions.
    # Time/weekday evidence: must mention the actual day name or "sat"
    has_time_evidence = bool(re.search(r"\bsat(urday)?\b", reason_lower))
    # Bug evidence: must mention the actual count "2"
    has_bug_evidence = bool(re.search(r"\b2\b", reason_lower) and any(m in reason_lower for m in ("bug", "缺陷")))
    # Coverage evidence: must mention "92" or "0.92"
    has_coverage_evidence = bool(re.search(r"(92%?|0\.92)", reason_lower))
    # Risk score evidence: must mention "4" in risk context
    has_risk_evidence = bool(re.search(r"risk.{0,20}\b4\b|\b4\b.{0,20}risk|score.{0,10}\b4\b", reason_lower))

    concrete_facts = sum([has_time_evidence, has_bug_evidence, has_coverage_evidence, has_risk_evidence])

    if reason_len_ok and concrete_facts >= 2:
        reason_score = 0.25
    elif reason_len_ok and concrete_facts == 1:
        reason_score = 0.12
    else:
        reason_score = 0.0

    checkpoints["reason_is_grounded"] = {
        "score": reason_score,
        "max": 0.25,
        "detail": (
            f"reason={reason!r} len_ok={reason_len_ok} "
            f"time={has_time_evidence} bug={has_bug_evidence} "
            f"coverage={has_coverage_evidence} risk={has_risk_evidence} "
            f"concrete_facts={concrete_facts}"
        ),
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _basename_set(trace, tool_name="read")
    write_paths = _basename_set(trace, tool_name="write")

    found_reads = sum(1 for item in ("request.json", "config.yaml") if item in read_paths)
    wrote_output = "release_status.txt" in write_paths

    if found_reads == 2 and wrote_output:
        return 1.0
    if found_reads == 2:
        return 0.75
    if found_reads == 1 and wrote_output:
        return 0.65
    if found_reads == 1 or wrote_output:
        return 0.4
    return 0.2
