"""Custom checks for the live OpenClaw memory search diagnosis scenario."""

from __future__ import annotations

from harness.openclaw_native import (
    infer_memory_failure_mode,
    load_json_file,
    memory_search_output,
    trace_used_openclaw_exec,
)


def _expected_memory_diagnosis() -> dict[str, object]:
    output = memory_search_output("test", max_results=3)
    failure_mode = infer_memory_failure_mode(output)
    reported_no_matches = "no matches." in output.lower()
    reliable = failure_mode == "ok_empty"
    signals: list[str] = []
    if "sync failed" in output.lower():
        signals.append("sync failed")
    if "unable to open database file" in output.lower():
        signals.append("unable to open database file")
    return {
        "reported_no_matches": reported_no_matches,
        "search_is_reliable": reliable,
        "failure_mode": failure_mode,
        "required_signal": "unable to open database file" if "unable to open database file" in output.lower() else "",
        "secondary_signal": "sync failed" if "sync failed" in output.lower() else "",
        "signals": signals,
    }


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    payload, detail = load_json_file(workspace, "memory_search_diagnosis.json")

    used_memory = trace_used_openclaw_exec(trace, "openclaw", "memory", "search")
    checkpoints["used_memory_search_cli"] = {
        "score": 0.15 if used_memory else 0.0,
        "max": 0.15,
        "detail": "used openclaw memory search" if used_memory else "missing memory search exec",
    }
    checkpoints["report_file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }
    if payload is None:
        for check_id, max_score in (
            ("no_match_signal_is_interpreted_correctly", 0.15),
            ("failure_mode_is_correct", 0.25),
            ("reliability_flag_is_correct", 0.15),
            ("error_signals_are_grounded", 0.1),
            ("recommended_action_is_grounded", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    expected = _expected_memory_diagnosis()
    checkpoints["no_match_signal_is_interpreted_correctly"] = {
        "score": 0.15 if payload.get("reported_no_matches") == expected["reported_no_matches"] else 0.0,
        "max": 0.15,
        "detail": f"reported_no_matches={payload.get('reported_no_matches')!r}",
    }
    checkpoints["failure_mode_is_correct"] = {
        "score": 0.25 if payload.get("failure_mode") == expected["failure_mode"] else 0.0,
        "max": 0.25,
        "detail": f"failure_mode={payload.get('failure_mode')!r} expected={expected['failure_mode']!r}",
    }
    checkpoints["reliability_flag_is_correct"] = {
        "score": 0.15 if payload.get("search_is_reliable") == expected["search_is_reliable"] else 0.0,
        "max": 0.15,
        "detail": f"search_is_reliable={payload.get('search_is_reliable')!r}",
    }

    signals = payload.get("error_signals")
    signals_text = " ".join(str(item) for item in signals) if isinstance(signals, list) else ""
    signal_ok = True
    if expected["required_signal"]:
        signal_ok = expected["required_signal"] in signals_text.lower()
    checkpoints["error_signals_are_grounded"] = {
        "score": 0.1 if signal_ok and isinstance(signals, list) and len(signals) >= 1 else 0.0,
        "max": 0.1,
        "detail": f"error_signals={signals!r}",
    }

    action = str(payload.get("recommended_action", "")).lower()
    action_ok = False
    if expected["search_is_reliable"]:
        action_ok = "search" in action or "safe" in action
    else:
        action_ok = (
            ("database" in action or "db" in action or "index" in action or "repair" in action or "fix" in action)
            and ("trust" in action or "reli" in action or "before" in action)
        )
    checkpoints["recommended_action_is_grounded"] = {
        "score": 0.1 if action_ok else 0.0,
        "max": 0.1,
        "detail": f"recommended_action={payload.get('recommended_action')!r}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    used_memory = trace_used_openclaw_exec(trace, "openclaw", "memory", "search")
    return 1.0 if used_memory else 0.2
