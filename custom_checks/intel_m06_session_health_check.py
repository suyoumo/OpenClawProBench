"""M6: 会话健康检查 — 评分脚本"""

from __future__ import annotations

from harness.openclaw_native import (
    default_agent_record,
    largest_input_session,
    load_agents_inventory,
    load_json_file,
    load_sessions_inventory,
    sessions_over_context_limit_keys,
    trace_native_surface_snapshot,
    trace_used_openclaw_surface,
)


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    # --- checkpoint: used_sessions_cli (0.1) ---
    used_sessions = trace_used_openclaw_surface(trace, "sessions")
    checkpoints["used_sessions_cli"] = {
        "score": 0.1 if used_sessions else 0.0,
        "max": 0.1,
        "detail": "used openclaw sessions" if used_sessions else "missing sessions cli call",
    }

    # --- checkpoint: used_agents_cli (0.1) ---
    used_agents = trace_used_openclaw_surface(trace, "agents")
    checkpoints["used_agents_cli"] = {
        "score": 0.1 if used_agents else 0.0,
        "max": 0.1,
        "detail": "used openclaw agents" if used_agents else "missing agents cli call",
    }

    # --- checkpoint: file_exists (0.1) ---
    payload, detail = load_json_file(workspace, "health_report.json")
    checkpoints["file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }

    if payload is None:
        for cid, mx in (
            ("session_fields_correct", 0.25),
            ("agent_fields_correct", 0.2),
            ("health_summary_correct", 0.25),
        ):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # --- ground truth ---
    session_snapshot = trace_native_surface_snapshot(trace, "sessions")
    if session_snapshot and session_snapshot.get("status") == "ready":
        gt_total_sessions = session_snapshot.get("count")
        gt_over_limit = session_snapshot.get("over_context_limit", [])
        gt_largest_key = str(session_snapshot.get("largest_session_key", ""))
        gt_largest_tokens = session_snapshot.get("largest_session_input_tokens")
    else:
        try:
            sessions_inv = load_sessions_inventory()
            gt_total_sessions = len(sessions_inv.get("sessions", []))
            gt_over_limit = sessions_over_context_limit_keys(sessions_inv)
            gt_largest = largest_input_session(sessions_inv)
            gt_largest_key = str(gt_largest.get("key", "")) if gt_largest else ""
            gt_largest_tokens = gt_largest.get("inputTokens", 0) if gt_largest else 0
        except Exception as exc:
            for cid, mx in (("session_fields_correct", 0.25),):
                checkpoints[cid] = {"score": 0.0, "max": mx, "detail": f"openclaw error: {exc}"}
            gt_total_sessions = None
            gt_over_limit = None
            gt_largest_key = None
            gt_largest_tokens = None

    agent_snapshot = trace_native_surface_snapshot(trace, "agents")
    if agent_snapshot and agent_snapshot.get("status") == "ready":
        gt_total_agents = agent_snapshot.get("count")
        gt_default_model = str(agent_snapshot.get("default_model", ""))
    else:
        try:
            agents_inv = load_agents_inventory()
            gt_total_agents = len(agents_inv)
            gt_default = default_agent_record(agents_inv)
            gt_default_model = str(gt_default.get("model", "")) if gt_default else ""
        except Exception as exc:
            for cid, mx in (("agent_fields_correct", 0.2),):
                checkpoints[cid] = {"score": 0.0, "max": mx, "detail": f"openclaw error: {exc}"}
            gt_total_agents = None
            gt_default_model = None

    # --- checkpoint: session_fields_correct (0.25) ---
    if gt_total_sessions is not None:
        score_s = 0.0
        got_total = payload.get("total_sessions")
        got_over = payload.get("over_context_limit", [])
        got_largest_key = str(payload.get("largest_session_key", ""))
        got_largest_tokens = payload.get("largest_session_input_tokens")

        if got_total == gt_total_sessions:
            score_s += 0.08
        if set(got_over) == set(gt_over_limit):
            score_s += 0.07
        if got_largest_key == gt_largest_key:
            score_s += 0.05
        if got_largest_tokens == gt_largest_tokens:
            score_s += 0.05

        checkpoints["session_fields_correct"] = {
            "score": round(score_s, 4),
            "max": 0.25,
            "detail": f"total={got_total}/{gt_total_sessions} over_limit={len(got_over)}/{len(gt_over_limit)}",
        }
    elif "session_fields_correct" not in checkpoints:
        checkpoints["session_fields_correct"] = {"score": 0.0, "max": 0.25, "detail": "skipped"}

    # --- checkpoint: agent_fields_correct (0.2) ---
    if gt_total_agents is not None:
        score_a = 0.0
        got_agents = payload.get("total_agents")
        got_model = str(payload.get("default_agent_model", ""))

        if got_agents == gt_total_agents:
            score_a += 0.1
        if got_model == gt_default_model:
            score_a += 0.1

        checkpoints["agent_fields_correct"] = {
            "score": round(score_a, 4),
            "max": 0.2,
            "detail": f"agents={got_agents}/{gt_total_agents} model={got_model}/{gt_default_model}",
        }
    elif "agent_fields_correct" not in checkpoints:
        checkpoints["agent_fields_correct"] = {"score": 0.0, "max": 0.2, "detail": "skipped"}

    # --- checkpoint: health_summary_correct (0.25) ---
    # Compute expected summary
    if gt_over_limit is not None and gt_total_agents is not None:
        if len(gt_over_limit) == 0 and gt_total_agents > 0:
            expected_summary = "healthy"
        elif 0 < len(gt_over_limit) <= 2:
            expected_summary = "warning"
        else:
            expected_summary = "critical"
        got_summary = str(payload.get("health_summary", ""))
        summary_ok = got_summary == expected_summary
        checkpoints["health_summary_correct"] = {
            "score": 0.25 if summary_ok else 0.0,
            "max": 0.25,
            "detail": f"got={got_summary} expected={expected_summary}",
        }
    else:
        checkpoints["health_summary_correct"] = {"score": 0.0, "max": 0.25, "detail": "skipped"}

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    used_sessions = trace_used_openclaw_surface(trace, "sessions")
    used_agents = trace_used_openclaw_surface(trace, "agents")
    wrote_json = False
    for e in trace.get("events", []):
        if e.get("type") != "tool_call":
            continue
        if e.get("tool") == "write":
            args = e.get("args") or {}
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if used_sessions and used_agents and wrote_json:
        return 1.0
    if (used_sessions or used_agents) and wrote_json:
        return 0.7
    return 0.3
