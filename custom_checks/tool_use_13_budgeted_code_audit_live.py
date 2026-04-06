"""Custom checks for the budgeted code audit scenario."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_FINDINGS = [
    {"path": "src/auth/session.py", "issue": "logs_bearer_token"},
    {"path": "src/config/local.py", "issue": "hard_coded_live_api_key"},
    {"path": "src/reports/exporter.py", "issue": "writes_auth_header_to_audit_log"},
]
EXPECTED_REJECTED = [
    "src/payments/stripe.py",
    "src/tests/fixtures.py",
]

ISSUE_ALIASES = {
    "src/auth/session.py": {
        "logs_bearer_token", "bearer_token_logged", "bearer_token_in_log",
        "logs bearer token", "bearer token logged", "bearer token in log",
        "writes bearer token to log", "persisting bearer",
        "bearer token", "bearer", "token 写入日志", "token 写入 log",
    },
    "src/config/local.py": {
        "hard_coded_live_api_key", "hardcoded_live_key", "hardcoded_api_key",
        "hard coded live key", "hardcoded live api key", "live api key hardcoded",
        "live key", "live_key", "sk-live", "硬编码", "hard coded", "hardcoded",
    },
    "src/reports/exporter.py": {
        "writes_auth_header_to_audit_log", "auth_header_in_log",
        "writes auth header to log", "auth header logged", "auth token in audit log",
        "authorization header", "auth header to audit", "auth header",
        "authorization", "auth_header", "认证头", "授权头",
    },
}


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _read_paths(trace: dict) -> list[str]:
    paths: list[str] = []
    for event in _tool_calls(trace):
        args = event.get("args") or {}
        if isinstance(args, dict):
            path = args.get("path") or args.get("file_path")
            if isinstance(path, str):
                paths.append(path)
    return paths


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}
    output_path = ws / "audit_report.json"
    exists = output_path.exists()
    checkpoints["audit_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "audit_report.json exists" if exists else "missing audit_report.json",
    }
    if not exists:
        for check_id, max_score in (
            ("inspection_plan_is_budget_aware", 0.20),
            ("findings_are_correct", 0.35),
            ("rejected_suspects_are_correct", 0.15),
            ("reported_budget_is_correct", 0.1),
            ("notes_are_nontrivial", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("inspection_plan_is_budget_aware", 0.20),
            ("findings_are_correct", 0.35),
            ("rejected_suspects_are_correct", 0.15),
            ("reported_budget_is_correct", 0.1),
            ("notes_are_nontrivial", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    plan = payload.get("inspection_plan")
    plan_text = " ".join(str(item) for item in plan) if isinstance(plan, list) else ""
    plan_hits = 0
    for keyword_group in (
        ("brief",),
        ("suspects",),
        ("inspect", "budget"),
        ("report",),
    ):
        if any(keyword in plan_text.lower() or keyword in plan_text for keyword in keyword_group):
            plan_hits += 1
    checkpoints["inspection_plan_is_budget_aware"] = {
        "score": 0.20 if isinstance(plan, list) and len(plan) >= 4 and plan_hits >= 3 else 0.0,
        "max": 0.20,
        "detail": f"inspection_plan={plan}",
    }
    # --- findings: partial credit per file, with issue alias matching ---
    got_findings = payload.get("confirmed_findings", [])
    if not isinstance(got_findings, list):
        got_findings = []
    got_paths = {}
    for item in got_findings:
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            got_paths[item["path"]] = str(item.get("issue", "")).lower()

    finding_hits = 0
    for expected in EXPECTED_FINDINGS:
        path = expected["path"]
        got_issue = got_paths.get(path, "")
        if not got_issue:
            continue
        canonical = expected["issue"]
        aliases = ISSUE_ALIASES.get(path, set())
        if got_issue == canonical or got_issue in aliases or any(alias in got_issue for alias in aliases):
            finding_hits += 1

    findings_score = round(0.35 * finding_hits / len(EXPECTED_FINDINGS), 4)
    checkpoints["findings_are_correct"] = {
        "score": findings_score,
        "max": 0.35,
        "detail": f"matched {finding_hits}/{len(EXPECTED_FINDINGS)} findings got_paths={list(got_paths.keys())}",
    }

    # --- rejected: normalize paths, partial credit per correct rejection ---
    got_rejected = payload.get("rejected_suspects", [])
    if not isinstance(got_rejected, list):
        got_rejected = []
    normalized_rejected = set()
    for item in got_rejected:
        s = str(item).strip()
        for expected_path in EXPECTED_REJECTED:
            if s.startswith(expected_path):
                normalized_rejected.add(expected_path)
                break
    rejected_hits = sum(1 for p in EXPECTED_REJECTED if p in normalized_rejected)
    # Penalize if a finding file was incorrectly rejected
    false_rejections = 0
    finding_paths = {f["path"] for f in EXPECTED_FINDINGS}
    for item in got_rejected:
        s = str(item).strip()
        for fp in finding_paths:
            if s.startswith(fp):
                false_rejections += 1
                break
    rejected_score = round(0.15 * rejected_hits / len(EXPECTED_REJECTED), 4)
    if false_rejections > 0:
        rejected_score = round(rejected_score * 0.5, 4)  # halve score for false rejections
    checkpoints["rejected_suspects_are_correct"] = {
        "score": rejected_score,
        "max": 0.15,
        "detail": f"rejected_hits={rejected_hits}/{len(EXPECTED_REJECTED)} false_rejections={false_rejections} rejected_suspects={got_rejected}",
    }
    checkpoints["reported_budget_is_correct"] = {
        "score": 0.1 if payload.get("read_budget_used") == 5 else 0.0,
        "max": 0.1,
        "detail": f"read_budget_used={payload.get('read_budget_used')!r}",
    }

    notes = payload.get("notes")
    notes_text = " ".join(str(item) for item in notes) if isinstance(notes, list) else ""
    note_hits = 0
    for keyword_group in (
        ("env", "environment"),
        ("fixture", "test"),
        ("token", "key"),
    ):
        if any(keyword in notes_text.lower() or keyword in notes_text for keyword in keyword_group):
            note_hits += 1
    checkpoints["notes_are_nontrivial"] = {
        "score": 0.1 if isinstance(notes, list) and len(notes) >= 2 and note_hits >= 2 else 0.0,
        "max": 0.1,
        "detail": f"notes_count={len(notes) if isinstance(notes, list) else 0} hits={note_hits}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _read_paths(trace)
    src_reads = [path for path in read_paths if path.startswith("src/")]
    required = {
        "src/auth/session.py",
        "src/config/local.py",
        "src/reports/exporter.py",
        "src/payments/stripe.py",
        "src/tests/fixtures.py",
    }
    hit_count = sum(1 for path in set(src_reads) if path in required)
    if len(src_reads) <= 5 and hit_count >= 4:
        return 1.0
    if len(src_reads) <= 5 and hit_count >= 3:
        return 0.8
    if len(src_reads) <= 6 and hit_count >= 3:
        return 0.55
    return 0.25
