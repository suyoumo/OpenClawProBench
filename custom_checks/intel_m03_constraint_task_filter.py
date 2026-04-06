"""M3: 约束任务过滤 — 评分脚本"""

from __future__ import annotations

import json
from pathlib import Path

from harness.openclaw_native import load_json_file


# Ground truth: apply rules to fixture tasks
# rules: max_priority=3, allowed_categories=["ops","dev"], blocked_owners=["alice"]
# Tasks that pass:
#   t01: priority=1, category=dev, owner=bob       -> PASS
#   t02: priority=2, category=ops, owner=alice      -> BLOCKED (alice)
#   t03: priority=3, category=dev, owner=carol      -> PASS
#   t04: priority=2, category=marketing, owner=dave -> BLOCKED (marketing)
#   t05: priority=1, category=ops, owner=eve        -> PASS
#   t06: priority=4, category=ops, owner=bob        -> BLOCKED (priority 4)
#   t07: priority=2, category=dev, owner=alice      -> BLOCKED (alice)
#   t08: priority=3, category=dev, owner=frank      -> PASS
#   t09: priority=1, category=marketing, owner=carol-> BLOCKED (marketing)
#   t10: priority=2, category=ops, owner=eve        -> PASS
# Expected filtered (sorted by priority asc): t01, t05, t10, t03, t08
EXPECTED_IDS_ORDERED = ["t01", "t05", "t10", "t03", "t08"]
# Expected rejected tasks with reasons
EXPECTED_REJECTED = {
    "t02": "blocked_owners",
    "t04": "allowed_categories",
    "t06": "max_priority",
    "t07": "blocked_owners",
    "t09": "allowed_categories",
}
REASON_ALIASES = {
    "blocked_owners": {"blocked", "alice", "owner", "blocked_owners"},
    "allowed_categories": {"category", "marketing", "allowed_categories", "not in allowed"},
    "max_priority": {"priority", "too high", "exceeds", "max_priority", "> 3", ">=4"},
}
EXPECTED_IDS_SET = set(EXPECTED_IDS_ORDERED)
EXPECTED_COUNT = 5


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    # Check if agent read both files
    read_tasks = False
    read_rules = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        tool = event.get("tool", "")
        args = event.get("args") or {}
        path = str(args.get("path", "") or args.get("file_path", "") or args.get("command", ""))
        if "tasks.json" in path:
            read_tasks = True
        if "rules.json" in path:
            read_rules = True
    checkpoints["read_both"] = {
        "score": 0.15 if (read_tasks and read_rules) else (0.075 if (read_tasks or read_rules) else 0.0),
        "max": 0.15,
        "detail": f"read_tasks={read_tasks} read_rules={read_rules}",
    }

    # load_json_file only accepts dicts; agent may write a raw list
    fpath = Path(workspace) / "filtered_tasks.json"
    payload = None
    raw_data = None
    detail = "missing filtered_tasks.json"
    if fpath.exists():
        try:
            raw_data = json.loads(fpath.read_text(encoding="utf-8"))
            detail = "loaded filtered_tasks.json"
            if isinstance(raw_data, dict):
                payload = raw_data
            elif isinstance(raw_data, list):
                payload = {"_list": raw_data}
            else:
                detail = "filtered_tasks.json is not a JSON object or array"
        except json.JSONDecodeError as exc:
            detail = f"invalid JSON: {exc}"

    file_ok = raw_data is not None
    checkpoints["file_exists"] = {
        "score": 0.1 if file_ok else 0.0,
        "max": 0.1,
        "detail": detail,
    }

    if not file_ok:
        for cid, mx in (("correct_count", 0.15), ("correct_items", 0.2), ("correct_order", 0.15), ("rejected_reasons_correct", 0.15), ("summary_correct", 0.1)):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # The payload could be a dict with a list, or a list directly
    tasks_list = raw_data if isinstance(raw_data, list) else payload.get(
        "tasks",
        payload.get("filtered", payload.get("filtered_tasks", [])),
    )
    if not isinstance(tasks_list, list):
        # Try to find any list value in the dict
        for v in payload.values():
            if isinstance(v, list):
                tasks_list = v
                break
        else:
            tasks_list = []

    got_ids = [t.get("id") for t in tasks_list if isinstance(t, dict) and t.get("id")]

    # Correct count
    count_ok = len(got_ids) == EXPECTED_COUNT
    checkpoints["correct_count"] = {
        "score": 0.15 if count_ok else 0.0,
        "max": 0.15,
        "detail": f"got {len(got_ids)} tasks, expected {EXPECTED_COUNT}",
    }

    # Correct items
    got_set = set(got_ids)
    items_ok = got_set == EXPECTED_IDS_SET
    checkpoints["correct_items"] = {
        "score": 0.2 if items_ok else 0.0,
        "max": 0.2,
        "detail": f"got={sorted(got_set)} expected={sorted(EXPECTED_IDS_SET)}",
    }

    # Correct order (by priority ascending)
    order_ok = got_ids == EXPECTED_IDS_ORDERED
    checkpoints["correct_order"] = {
        "score": 0.15 if order_ok else 0.0,
        "max": 0.15,
        "detail": f"order={'correct' if order_ok else 'wrong'}: {got_ids}",
    }

    # Rejected reasons correct
    rejected_list = payload.get("rejected", [])
    if not isinstance(rejected_list, list):
        rejected_list = []
    rejected_hits = 0
    for item in rejected_list:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("id", ""))
        reason = str(item.get("reason", "")).lower()
        expected_reason = EXPECTED_REJECTED.get(tid)
        if not expected_reason:
            continue
        aliases = REASON_ALIASES.get(expected_reason, set())
        if expected_reason in reason or any(alias in reason for alias in aliases):
            rejected_hits += 1
    checkpoints["rejected_reasons_correct"] = {
        "score": round(0.15 * rejected_hits / max(len(EXPECTED_REJECTED), 1), 4),
        "max": 0.15,
        "detail": f"rejected_hits={rejected_hits}/{len(EXPECTED_REJECTED)}",
    }

    # Summary correct
    summary = payload.get("summary", {})
    summary_ok = (
        isinstance(summary, dict)
        and summary.get("total") == 10
        and summary.get("passed") == 5
        and summary.get("rejected") == 5
    )
    checkpoints["summary_correct"] = {
        "score": 0.1 if summary_ok else 0.0,
        "max": 0.1,
        "detail": f"summary={summary}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    events = trace.get("events", [])
    read_count = 0
    wrote_json = False
    for e in events:
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        if tool in ("read", "Read"):
            read_count += 1
        if tool == "exec":
            cmd = str(args.get("command", ""))
            if ("tasks.json" in cmd or "rules.json" in cmd) and ("cat" in cmd or "jq" in cmd):
                read_count += 1
        if tool == "write":
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if read_count >= 2 and wrote_json:
        return 1.0
    if read_count >= 1 and wrote_json:
        return 0.7
    return 0.3
