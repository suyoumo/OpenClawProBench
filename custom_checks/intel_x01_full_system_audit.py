"""X1: 全系统审计 — 评分脚本"""

from __future__ import annotations

from harness.openclaw_native import (
    default_agent_record,
    eligible_skill_names,
    infer_surface_status,
    load_agents_inventory,
    load_json_file,
    load_sessions_inventory,
    load_skills_inventory,
    memory_search_output,
    missing_skill_names,
    sessions_over_context_limit_keys,
    trace_native_surface_snapshot,
    trace_openclaw_surfaces_used,
    trace_used_openclaw_exec_count,
)

ALL_SURFACES = ("skills", "memory", "browser", "cron", "directory", "agents", "sessions")


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    # --- checkpoint: probed_7_surfaces (0.15) ---
    surfaces_hit = trace_openclaw_surfaces_used(trace)
    probed = sum(1 for surface in ALL_SURFACES if surface in surfaces_hit)
    checkpoints["probed_7_surfaces"] = {
        "score": round(0.15 * min(probed, 7) / 7, 4),
        "max": 0.15,
        "detail": f"probed {probed}/7 surfaces",
    }

    # --- checkpoint: file_exists (0.05) ---
    payload, detail = load_json_file(workspace, "audit_report.json")
    checkpoints["file_exists"] = {
        "score": 0.05 if payload is not None else 0.0,
        "max": 0.05,
        "detail": detail,
    }

    if payload is None:
        for cid, mx in (
            ("skills_status_correct", 0.1),
            ("memory_status_correct", 0.1),
            ("agents_correct", 0.1),
            ("sessions_correct", 0.1),
            ("risks_identified", 0.15),
            ("overall_health_correct", 0.15),
            ("health_score_reasonable", 0.1),
        ):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    surface_status = payload.get("surface_status", {})
    if not isinstance(surface_status, dict):
        surface_status = {}

    # --- ground truth: skills ---
    skills_snapshot = trace_native_surface_snapshot(trace, "skills")
    if skills_snapshot and skills_snapshot.get("status") == "ready":
        gt_ready = skills_snapshot.get("ready_count")
        gt_missing = skills_snapshot.get("missing_count")
    else:
        try:
            inventory = load_skills_inventory()
            gt_ready = len(eligible_skill_names(inventory))
            gt_missing = len(missing_skill_names(inventory))
        except Exception:
            gt_ready = None
            gt_missing = None

    # --- checkpoint: skills_status_correct (0.1) ---
    skills_data = surface_status.get("skills", {})
    if gt_ready is not None:
        got_ready = skills_data.get("ready_count")
        got_missing = skills_data.get("missing_count")
        skills_ok = got_ready == gt_ready and got_missing == gt_missing
        checkpoints["skills_status_correct"] = {
            "score": 0.1 if skills_ok else 0.05 if (got_ready == gt_ready or got_missing == gt_missing) else 0.0,
            "max": 0.1,
            "detail": f"ready={got_ready}/{gt_ready} missing={got_missing}/{gt_missing}",
        }
    else:
        checkpoints["skills_status_correct"] = {"score": 0.0, "max": 0.1, "detail": "openclaw error"}

    # --- ground truth: memory ---
    memory_snapshot = trace_native_surface_snapshot(trace, "memory")
    if memory_snapshot and memory_snapshot.get("status"):
        gt_mem_status = str(memory_snapshot.get("status", "")).lower()
    else:
        mem_out = memory_search_output("test")
        gt_mem_status = infer_surface_status(mem_out)

    # --- checkpoint: memory_status_correct (0.1) ---
    mem_data = surface_status.get("memory", {})
    got_mem_status = str(mem_data.get("status", "")).lower()
    ready_aliases = {"ready", "ok", "healthy", "available"}
    error_aliases = {"error", "down", "unavailable", "gateway_closed", "failed"}
    if gt_mem_status == "ready":
        mem_ok = got_mem_status in ready_aliases
    else:
        mem_ok = got_mem_status in error_aliases
    checkpoints["memory_status_correct"] = {
        "score": 0.1 if mem_ok else 0.0,
        "max": 0.1,
        "detail": f"got={got_mem_status} expected_category={'ready' if gt_mem_status == 'ready' else 'error'}",
    }

    # --- ground truth: agents ---
    agents_snapshot = trace_native_surface_snapshot(trace, "agents")
    if agents_snapshot and agents_snapshot.get("status") == "ready":
        gt_agent_count = agents_snapshot.get("count")
        gt_default_model = str(agents_snapshot.get("default_model", ""))
    else:
        try:
            agents = load_agents_inventory()
            gt_agent_count = len(agents)
            gt_default = default_agent_record(agents)
            gt_default_model = str(gt_default.get("model", "")) if gt_default else ""
        except Exception:
            gt_agent_count = None
            gt_default_model = None

    # --- checkpoint: agents_correct (0.1) ---
    agents_data = surface_status.get("agents", {})
    if gt_agent_count is not None:
        got_count = agents_data.get("count")
        got_model = str(agents_data.get("default_model", ""))
        agents_ok = got_count == gt_agent_count and got_model == gt_default_model
        checkpoints["agents_correct"] = {
            "score": 0.1 if agents_ok else 0.05 if got_count == gt_agent_count else 0.0,
            "max": 0.1,
            "detail": f"count={got_count}/{gt_agent_count} model={got_model}/{gt_default_model}",
        }
    else:
        checkpoints["agents_correct"] = {"score": 0.0, "max": 0.1, "detail": "openclaw error"}

    # --- ground truth: sessions ---
    sessions_snapshot = trace_native_surface_snapshot(trace, "sessions")
    if sessions_snapshot and sessions_snapshot.get("status") == "ready":
        gt_session_count = sessions_snapshot.get("count")
        gt_over_limit = sessions_snapshot.get("over_context_limit", [])
    else:
        try:
            sessions = load_sessions_inventory()
            gt_session_count = len(sessions.get("sessions", []))
            gt_over_limit = sessions_over_context_limit_keys(sessions)
        except Exception:
            gt_session_count = None
            gt_over_limit = None

    # --- checkpoint: sessions_correct (0.1) ---
    sessions_data = surface_status.get("sessions", {})
    if gt_session_count is not None:
        got_s_count = sessions_data.get("count")
        got_over = sessions_data.get("over_limit", [])
        if not isinstance(got_over, list):
            got_over = []
        sessions_ok = got_s_count == gt_session_count and set(got_over) == set(gt_over_limit)
        checkpoints["sessions_correct"] = {
            "score": 0.1 if sessions_ok else 0.05 if got_s_count == gt_session_count else 0.0,
            "max": 0.1,
            "detail": f"count={got_s_count}/{gt_session_count} over_limit={len(got_over)}/{len(gt_over_limit)}",
        }
    else:
        checkpoints["sessions_correct"] = {"score": 0.0, "max": 0.1, "detail": "openclaw error"}

    # --- checkpoint: risks_identified (0.15) ---
    risks = payload.get("risks", [])
    if not isinstance(risks, list):
        risks = []
    valid_severities = {"high", "medium", "low"}
    valid_risks = [
        r for r in risks
        if isinstance(r, dict)
        and str(r.get("severity", "")).lower() in valid_severities
        and isinstance(r.get("description"), str)
        and len(r["description"]) > 10
        and isinstance(r.get("remediation"), str)
        and len(r["remediation"]) > 5
    ]
    risk_score = min(0.15, round(0.15 * len(valid_risks) / 3, 4))
    checkpoints["risks_identified"] = {
        "score": risk_score,
        "max": 0.15,
        "detail": f"valid_risks={len(valid_risks)} total_risks={len(risks)}",
    }

    # --- checkpoint: overall_health_correct (0.15) ---
    got_health = str(payload.get("overall_health", "")).lower()
    valid_health = {"healthy", "degraded", "critical"}
    health_present = got_health in valid_health
    checkpoints["overall_health_correct"] = {
        "score": 0.15 if health_present else 0.0,
        "max": 0.15,
        "detail": f"overall_health={got_health}",
    }

    # --- checkpoint: health_score_reasonable (0.1) ---
    got_score = payload.get("health_score")
    score_ok = isinstance(got_score, (int, float)) and 0.0 <= got_score <= 1.0
    checkpoints["health_score_reasonable"] = {
        "score": 0.1 if score_ok else 0.0,
        "max": 0.1,
        "detail": f"health_score={got_score}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    exec_count = trace_used_openclaw_exec_count(trace, "openclaw")
    wrote_json = False
    surfaces_hit = trace_openclaw_surfaces_used(trace)
    for e in trace.get("events", []):
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        if tool == "write":
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if len(surfaces_hit) >= 7 and wrote_json:
        return 1.0
    if len(surfaces_hit) >= 5 and wrote_json:
        return 0.8
    if len(surfaces_hit) >= 3 and wrote_json:
        return 0.6
    if exec_count >= 1:
        return 0.3
    return 0.1
