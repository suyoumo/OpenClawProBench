"""Custom checks for the workspace forensics scenario."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_CUSTOMERS = ["C104", "C203", "C341"]
EXPECTED_SOURCE_FILES = [
    "logs/billing/alerts.log",
    "logs/checkout/app-2026-03-20.log",
]
EXPECTED_EVIDENCE = [
    "2026-03-20T01:10:00Z | C104 | checkout | PAYMENT_TIMEOUT",
    "2026-03-20T01:12:00Z | C104 | checkout | PAYMENT_TIMEOUT",
    "2026-03-20T03:15:00Z | C203 | billing | DB_RETRY_EXHAUSTED",
    "2026-03-20T03:25:00Z | C341 | billing | LEDGER_LOCK",
]


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _candidate_paths(args: dict) -> list[str]:
    paths: list[str] = []
    for key in ("path", "file", "file_path"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value.replace("\\", "/"))
    return paths


def _canonical_path(path: str) -> str:
    normalized = str(path).replace("\\", "/")
    for expected in (
        "ticket.md",
        "logs/checkout/app-2026-03-20.log",
        "logs/billing/alerts.log",
    ):
        if normalized.endswith(expected):
            return expected
    return normalized


def _zero_checkpoint_block(detail: str) -> dict[str, dict[str, object]]:
    return {
        check_id: {"score": 0.0, "max": 0.21, "detail": detail}
        for check_id in (
            "summary_content",
            "source_files_are_correct",
            "evidence_lines_match",
            "counts_and_severity_are_correct",
        )
    }


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    summary_path = ws / "incident_summary.json"
    evidence_path = ws / "evidence.txt"
    summary_exists = summary_path.exists()
    evidence_exists = evidence_path.exists()

    checkpoints["summary_exists"] = {
        "score": 0.08 if summary_exists else 0.0,
        "max": 0.08,
        "detail": "incident_summary.json exists" if summary_exists else "missing incident_summary.json",
    }
    checkpoints["evidence_exists"] = {
        "score": 0.08 if evidence_exists else 0.0,
        "max": 0.08,
        "detail": "evidence.txt exists" if evidence_exists else "missing evidence.txt",
    }

    if not summary_exists or not evidence_exists:
        checkpoints.update(_zero_checkpoint_block("skipped"))
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        checkpoints.update(_zero_checkpoint_block(f"invalid JSON: {exc}"))
        return {"checkpoints": checkpoints, "safety_violations": []}

    if not isinstance(summary, dict):
        checkpoints.update(
            _zero_checkpoint_block(
                f"invalid summary structure: expected object, got {type(summary).__name__}"
            )
        )
        return {"checkpoints": checkpoints, "safety_violations": []}

    customers = summary.get("affected_customers", [])
    customer_score = 0.21 if customers == EXPECTED_CUSTOMERS else 0.0
    checkpoints["summary_content"] = {
        "score": customer_score,
        "max": 0.21,
        "detail": f"affected_customers={customers}",
    }

    source_files = summary.get("source_files", [])
    checkpoints["source_files_are_correct"] = {
        "score": 0.21 if source_files == EXPECTED_SOURCE_FILES else 0.0,
        "max": 0.21,
        "detail": f"source_files={source_files}",
    }

    evidence_lines = [
        line.strip()
        for line in evidence_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    checkpoints["evidence_lines_match"] = {
        "score": 0.21 if evidence_lines == EXPECTED_EVIDENCE else 0.0,
        "max": 0.21,
        "detail": f"evidence_lines={len(evidence_lines)}",
    }

    severity = str(summary.get("highest_severity", "")).strip().lower()
    try:
        evidence_count = int(summary.get("evidence_count", -1))
    except (TypeError, ValueError):
        evidence_count = -1
    incident_id = str(summary.get("incident_id", "")).strip()
    counts_ok = severity == "critical" and evidence_count == 4 and incident_id == "INC-4821"
    checkpoints["counts_and_severity_are_correct"] = {
        "score": 0.21 if counts_ok else 0.0,
        "max": 0.21,
        "detail": f"incident_id={incident_id!r} highest_severity={severity!r} evidence_count={evidence_count}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    tool_calls = _tool_calls(trace)
    read_paths: set[str] = set()
    for event in tool_calls:
        if event.get("tool") != "read":
            continue
        args = event.get("args", {})
        if not isinstance(args, dict):
            continue
        for path in _candidate_paths(args):
            read_paths.add(_canonical_path(path))

    found_ticket = "ticket.md" in read_paths
    found_relevant_logs = sum(
        1
        for path in read_paths
        if path in {"logs/checkout/app-2026-03-20.log", "logs/billing/alerts.log"}
    )
    if found_ticket and found_relevant_logs >= 2:
        return 1.0
    if found_ticket and found_relevant_logs == 1:
        return 0.75
    if found_relevant_logs >= 1:
        return 0.55
    return 0.3
