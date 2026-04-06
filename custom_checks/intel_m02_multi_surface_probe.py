"""M2: 多表面探测 — 评分脚本"""

from __future__ import annotations

from harness.openclaw_native import (
    browser_status_output,
    infer_surface_status,
    load_json_file,
    load_skills_inventory,
    memory_search_output,
    trace_used_openclaw_exec,
)


def _ground_truth_surfaces() -> dict[str, str]:
    """Probe each surface and return ground truth status map."""
    statuses: dict[str, str] = {}

    # skills
    try:
        load_skills_inventory()
        statuses["skills"] = "ready"
    except Exception:
        statuses["skills"] = "error"

    # memory
    try:
        mem_out = memory_search_output("test")
        mem_status = infer_surface_status(mem_out)
        statuses["memory"] = "ready" if mem_status == "ready" else "error"
    except Exception:
        statuses["memory"] = "error"

    # browser
    try:
        browser_out = browser_status_output()
        browser_status = infer_surface_status(browser_out)
        statuses["browser"] = "ready" if browser_status == "ready" else "error"
    except Exception:
        statuses["browser"] = "error"

    return statuses


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}

    # Check CLI probes
    probed_skills = trace_used_openclaw_exec(trace, "openclaw", "skills")
    probed_memory = trace_used_openclaw_exec(trace, "openclaw", "memory")
    probed_browser = trace_used_openclaw_exec(trace, "openclaw", "browser")

    checkpoints["probed_skills"] = {
        "score": 0.1 if probed_skills else 0.0,
        "max": 0.1,
        "detail": "probed skills" if probed_skills else "missing skills probe",
    }
    checkpoints["probed_memory"] = {
        "score": 0.1 if probed_memory else 0.0,
        "max": 0.1,
        "detail": "probed memory" if probed_memory else "missing memory probe",
    }
    checkpoints["probed_browser"] = {
        "score": 0.1 if probed_browser else 0.0,
        "max": 0.1,
        "detail": "probed browser" if probed_browser else "missing browser probe",
    }

    payload, detail = load_json_file(workspace, "surface_status.json")
    checkpoints["file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }

    if payload is None:
        checkpoints["statuses_correct"] = {"score": 0.0, "max": 0.35, "detail": "skipped"}
        checkpoints["counts_correct"] = {"score": 0.0, "max": 0.25, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # Get ground truth
    try:
        truth = _ground_truth_surfaces()
    except Exception as exc:
        checkpoints["statuses_correct"] = {"score": 0.0, "max": 0.35, "detail": f"probe error: {exc}"}
        checkpoints["counts_correct"] = {"score": 0.0, "max": 0.25, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    surfaces = payload.get("surfaces")
    if not isinstance(surfaces, dict):
        checkpoints["statuses_correct"] = {"score": 0.0, "max": 0.35, "detail": "surfaces not a dict"}
        checkpoints["counts_correct"] = {"score": 0.0, "max": 0.25, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # Compare statuses
    matched = 0
    for name in ("skills", "memory", "browser"):
        entry = surfaces.get(name)
        if not isinstance(entry, dict):
            continue
        got_status = str(entry.get("status", "")).lower()
        expected = truth.get(name, "error")
        if got_status == expected:
            matched += 1
        elif got_status in ("ready", "error") and expected in ("ready", "error"):
            # Accept reasonable mapping
            pass

    ratio = matched / 3
    score = round(0.35 * ratio, 4)
    checkpoints["statuses_correct"] = {
        "score": score,
        "max": 0.35,
        "detail": f"matched {matched}/3 surface statuses",
    }

    # Check counts
    expected_available = sum(1 for v in truth.values() if v == "ready")
    total_count = payload.get("total_count")
    available_count = payload.get("available_count")
    counts_ok = total_count == 3 and available_count == expected_available
    checkpoints["counts_correct"] = {
        "score": 0.25 if counts_ok else 0.0,
        "max": 0.25,
        "detail": f"available_count={available_count!r} expected={expected_available} total_count={total_count!r}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    events = trace.get("events", [])
    exec_commands: list[str] = []
    wrote_json = False
    for e in events:
        if e.get("type") != "tool_call":
            continue
        if e.get("tool") == "exec":
            exec_commands.append(str((e.get("args") or {}).get("command", "")))
        if e.get("tool") == "write":
            path = str((e.get("args") or {}).get("path", "") or (e.get("args") or {}).get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True

    probed = sum(1 for s in ("skills", "memory", "browser") if any(s in cmd for cmd in exec_commands))
    if probed >= 3 and wrote_json and len(exec_commands) <= 5:
        return 1.0
    if probed >= 2 and wrote_json:
        return 0.7
    if probed >= 1:
        return 0.4
    return 0.2
