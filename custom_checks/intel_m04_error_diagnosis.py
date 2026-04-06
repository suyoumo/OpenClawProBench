"""M4: 错误日志诊断 — 评分脚本"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from harness.openclaw_native import load_json_file


# Ground truth from fixture error_log.json:
# Errors:
#   10:05:12 auth-service    E5001
#   10:05:30 payment-service E5001
#   10:05:45 user-service    E4003
#   10:05:55 auth-service    E5001
#   10:12:00 auth-service    E4003
#
# most_failing_service: auth-service (3 errors)
# most_common_error: E5001 (3 occurrences)
# cascade: 10:05 minute has auth-service, payment-service, user-service = 3 different services -> true
# cascade_window: "2026-03-23T10:05" or similar
# total_errors: 5

EXPECTED_MOST_FAILING = "auth-service"
EXPECTED_MOST_COMMON = "E5001"
EXPECTED_CASCADE = True
EXPECTED_TOTAL = 5


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    # Check if agent read error_log.json
    read_log = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        tool = event.get("tool", "")
        args = event.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", "") or args.get("command", ""))
        if "error_log" in path:
            read_log = True
    checkpoints["read_log"] = {
        "score": 0.1 if read_log else 0.0,
        "max": 0.1,
        "detail": "read error_log.json" if read_log else "did not read error_log.json",
    }

    payload, detail = load_json_file(workspace, "diagnosis.json")
    checkpoints["file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }

    if payload is None:
        for cid, mx in (("most_failing_correct", 0.25), ("most_common_correct", 0.25), ("cascade_correct", 0.3)):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # most_failing_service
    got_failing = payload.get("most_failing_service")
    failing_ok = got_failing == EXPECTED_MOST_FAILING
    checkpoints["most_failing_correct"] = {
        "score": 0.25 if failing_ok else 0.0,
        "max": 0.25,
        "detail": f"got={got_failing!r} expected={EXPECTED_MOST_FAILING!r}",
    }

    # most_common_error
    got_common = payload.get("most_common_error")
    common_ok = got_common == EXPECTED_MOST_COMMON
    checkpoints["most_common_correct"] = {
        "score": 0.25 if common_ok else 0.0,
        "max": 0.25,
        "detail": f"got={got_common!r} expected={EXPECTED_MOST_COMMON!r}",
    }

    # cascade detection
    got_cascade = payload.get("cascade_detected")
    cascade_ok = got_cascade is True
    total_errors = payload.get("total_errors")
    total_ok = total_errors == EXPECTED_TOTAL
    # Give partial credit: cascade detection is worth 0.2, total_errors is worth 0.1
    cascade_score = 0.0
    if cascade_ok:
        cascade_score += 0.2
    if total_ok:
        cascade_score += 0.1
    checkpoints["cascade_correct"] = {
        "score": cascade_score,
        "max": 0.3,
        "detail": f"cascade_detected={got_cascade!r} total_errors={total_errors!r}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    events = trace.get("events", [])
    read_file = False
    wrote_json = False
    for e in events:
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        if tool in ("read", "Read"):
            read_file = True
        if tool == "exec":
            cmd = str(args.get("command", ""))
            if "error_log" in cmd and ("cat" in cmd or "jq" in cmd):
                read_file = True
        if tool == "write":
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if read_file and wrote_json:
        return 1.0
    if wrote_json:
        return 0.6
    return 0.2
