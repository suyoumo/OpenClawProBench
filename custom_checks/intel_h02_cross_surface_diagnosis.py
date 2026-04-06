"""H2: 跨 Surface 诊断 — 评分脚本"""

from __future__ import annotations

from harness.openclaw_native import (
    browser_status_output,
    combined_output,
    cron_list_output,
    extract_gateway_target,
    infer_memory_failure_mode,
    infer_surface_status,
    load_json_file,
    load_skills_inventory,
    memory_search_output,
    run_openclaw_command,
    trace_used_openclaw_exec,
)

SURFACE_NAMES = ("skills", "memory", "browser", "cron", "directory")


def _probe_ground_truth() -> dict:
    """Probe all 5 surfaces and return ground truth statuses."""
    gt: dict[str, dict] = {}

    # skills
    try:
        load_skills_inventory()
        gt["skills"] = {"status": "ready"}
    except Exception:
        gt["skills"] = {"status": "error"}

    # memory
    mem_out = memory_search_output("test")
    mem_status = infer_surface_status(mem_out)
    gt["memory"] = {"status": "ready" if mem_status == "ready" else "error"}

    # browser
    br_out = browser_status_output()
    br_status = infer_surface_status(br_out)
    gt["browser"] = {"status": "ready" if br_status == "ready" else "error"}

    # cron
    cr_out = cron_list_output()
    cr_status = infer_surface_status(cr_out)
    gt["cron"] = {"status": "ready" if cr_status == "ready" else "error"}

    # directory
    dir_result = run_openclaw_command("directory", "self", "--json")
    dir_out = combined_output(dir_result)
    dir_status = infer_surface_status(dir_out)
    gt["directory"] = {"status": "ready" if dir_status == "ready" else "error"}

    return gt


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    # --- checkpoint: probed_all_5 (0.15) ---
    probed = 0
    for surface in SURFACE_NAMES:
        if trace_used_openclaw_exec(trace, "openclaw", surface):
            probed += 1
        elif surface == "skills" and trace_used_openclaw_exec(trace, "openclaw", "skills", "list"):
            probed += 1
    checkpoints["probed_all_5"] = {
        "score": 0.15 if probed >= 5 else round(0.15 * probed / 5, 4),
        "max": 0.15,
        "detail": f"probed {probed}/5 surfaces",
    }

    # --- checkpoint: file_exists (0.1) ---
    payload, detail = load_json_file(workspace, "diagnosis.json")
    checkpoints["file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }

    if payload is None:
        for cid, mx in (
            ("statuses_correct", 0.25),
            ("counts_correct", 0.1),
            ("gateway_detection_correct", 0.2),
            ("root_cause_reasonable", 0.2),
        ):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # --- ground truth ---
    try:
        gt = _probe_ground_truth()
    except Exception as exc:
        for cid, mx in (
            ("statuses_correct", 0.25),
            ("counts_correct", 0.1),
            ("gateway_detection_correct", 0.2),
            ("root_cause_reasonable", 0.2),
        ):
            checkpoints[cid] = {"score": 0.0, "max": mx, "detail": f"probe error: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # --- checkpoint: statuses_correct (0.25) ---
    surfaces_data = payload.get("surfaces", {})
    correct_statuses = 0
    for sname in SURFACE_NAMES:
        got_entry = surfaces_data.get(sname, {})
        if not isinstance(got_entry, dict):
            continue
        got_status = str(got_entry.get("status", "")).lower()
        expected_status = gt[sname]["status"]
        # Accept "ready"/"ok"/"healthy" as equivalent to "ready"
        # Accept "error"/"down"/"unavailable"/"gateway_closed" as equivalent to "error"
        ready_aliases = {"ready", "ok", "healthy", "available"}
        error_aliases = {"error", "down", "unavailable", "gateway_closed", "failed"}
        if expected_status == "ready" and got_status in ready_aliases:
            correct_statuses += 1
        elif expected_status == "error" and got_status in error_aliases:
            correct_statuses += 1
    status_score = round(0.25 * correct_statuses / 5, 4)
    checkpoints["statuses_correct"] = {
        "score": status_score,
        "max": 0.25,
        "detail": f"{correct_statuses}/5 statuses correct",
    }

    # --- checkpoint: counts_correct (0.1) ---
    gt_available = sum(1 for s in gt.values() if s["status"] == "ready")
    got_available = payload.get("available_count")
    got_total = payload.get("total_count")
    counts_ok = got_available == gt_available and got_total == 5
    checkpoints["counts_correct"] = {
        "score": 0.1 if counts_ok else 0.0,
        "max": 0.1,
        "detail": f"available={got_available}/{gt_available} total={got_total}/5",
    }

    # --- checkpoint: gateway_detection_correct (0.2) ---
    gt_error_count = sum(1 for s in gt.values() if s["status"] == "error")
    gt_gateway_suspected = gt_error_count >= 3
    got_gateway = payload.get("gateway_issue_suspected")
    gateway_ok = bool(got_gateway) == gt_gateway_suspected
    checkpoints["gateway_detection_correct"] = {
        "score": 0.2 if gateway_ok else 0.0,
        "max": 0.2,
        "detail": f"got={got_gateway} expected={gt_gateway_suspected} (errors={gt_error_count})",
    }

    # --- checkpoint: root_cause_reasonable (0.2) ---
    root_cause = str(payload.get("root_cause_hypothesis", ""))
    root_cause_lower = root_cause.lower()
    # Must be non-trivial AND reference at least one error surface by name
    error_surfaces = [s for s in SURFACE_NAMES if gt[s]["status"] == "error"]
    mentions_error_surface = any(s in root_cause_lower for s in error_surfaces)
    # Also accept "gateway" as a valid root-cause reference when gateway is suspected
    if gt_gateway_suspected and ("gateway" in root_cause_lower or "网关" in root_cause):
        mentions_error_surface = True
    has_root_cause = len(root_cause) > 10 and mentions_error_surface
    checkpoints["root_cause_reasonable"] = {
        "score": 0.2 if has_root_cause else 0.0,
        "max": 0.2,
        "detail": f"root_cause_len={len(root_cause)} mentions_error_surface={mentions_error_surface}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    exec_count = 0
    wrote_json = False
    for e in trace.get("events", []):
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        if tool == "exec" and "openclaw" in str(args.get("command", "")):
            exec_count += 1
        if tool == "write":
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if exec_count >= 5 and wrote_json:
        return 1.0
    if exec_count >= 3 and wrote_json:
        return 0.7
    if exec_count >= 1:
        return 0.4
    return 0.2
