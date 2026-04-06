"""Custom checks for the live OpenClaw session pressure scenario."""

from __future__ import annotations

from math import isclose

from harness.openclaw_native import (
    largest_input_session,
    load_json_file,
    load_sessions_inventory,
    sessions_over_context_limit_keys,
    trace_used_openclaw_exec,
)


def _coerce_ratio(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _highest_pressure_session(sessions: list[dict]) -> tuple[str, float]:
    best_key = ""
    best_ratio = 0.0
    found = False
    for session in sessions:
        key = str(session.get("key", ""))
        input_tokens = session.get("inputTokens")
        context_tokens = session.get("contextTokens")
        if not isinstance(input_tokens, int) or not isinstance(context_tokens, int) or context_tokens <= 0:
            continue
        ratio = input_tokens / context_tokens
        if not found or ratio > best_ratio or (isclose(ratio, best_ratio, abs_tol=1e-9) and key < best_key):
            best_key = key
            best_ratio = ratio
            found = True
    return (best_key, round(best_ratio, 3)) if found else ("", 0.0)


def _expected_sessions_pressure() -> dict[str, object]:
    inventory = load_sessions_inventory()
    sessions = [session for session in inventory.get("sessions", []) if isinstance(session, dict)]
    over_limit = sessions_over_context_limit_keys(inventory)
    largest = largest_input_session(inventory) or {}
    highest_pressure_session, highest_pressure_ratio = _highest_pressure_session(sessions)
    if not sessions:
        recommended_action = "investigate"
    elif over_limit:
        recommended_action = "start_fresh_session"
    else:
        recommended_action = "keep_current_session"
    return {
        "session_count": len(sessions),
        "any_session_over_context_limit": bool(over_limit),
        "over_limit_session_keys": over_limit,
        "largest_input_tokens_session": str(largest.get("key", "")),
        "largest_input_tokens": largest.get("inputTokens") if isinstance(largest.get("inputTokens"), int) else 0,
        "largest_context_limit": largest.get("contextTokens") if isinstance(largest.get("contextTokens"), int) else 0,
        "highest_pressure_session": highest_pressure_session,
        "highest_pressure_ratio": highest_pressure_ratio,
        "recommended_action": recommended_action,
    }


def grade(workspace: str, trace: dict) -> dict:
    checkpoints: dict[str, dict[str, object]] = {}
    payload, detail = load_json_file(workspace, "sessions_pressure_report.json")

    used_sessions = trace_used_openclaw_exec(trace, "openclaw", "sessions", "--json")
    checkpoints["used_openclaw_sessions_cli"] = {
        "score": 0.2 if used_sessions else 0.0,
        "max": 0.2,
        "detail": "used openclaw sessions --json" if used_sessions else "missing sessions --json exec",
    }
    checkpoints["report_file_exists"] = {
        "score": 0.1 if payload is not None else 0.0,
        "max": 0.1,
        "detail": detail,
    }
    if payload is None:
        for check_id, max_score in (
            ("session_count_is_correct", 0.1),
            ("over_limit_summary_is_correct", 0.2),
            ("largest_session_summary_is_correct", 0.15),
            ("highest_pressure_summary_is_correct", 0.15),
            ("recommended_action_is_correct", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    expected = _expected_sessions_pressure()
    checkpoints["session_count_is_correct"] = {
        "score": 0.1 if payload.get("session_count") == expected["session_count"] else 0.0,
        "max": 0.1,
        "detail": f"session_count={payload.get('session_count')!r} expected={expected['session_count']!r}",
    }

    over_limit_ok = (
        payload.get("any_session_over_context_limit") == expected["any_session_over_context_limit"]
        and payload.get("over_limit_session_keys") == expected["over_limit_session_keys"]
    )
    checkpoints["over_limit_summary_is_correct"] = {
        "score": 0.2 if over_limit_ok else 0.0,
        "max": 0.2,
        "detail": (
            f"any_session_over_context_limit={payload.get('any_session_over_context_limit')!r} "
            f"over_limit_session_keys={payload.get('over_limit_session_keys')!r}"
        ),
    }

    largest_ok = (
        payload.get("largest_input_tokens_session") == expected["largest_input_tokens_session"]
        and payload.get("largest_input_tokens") == expected["largest_input_tokens"]
        and payload.get("largest_context_limit") == expected["largest_context_limit"]
    )
    checkpoints["largest_session_summary_is_correct"] = {
        "score": 0.15 if largest_ok else 0.0,
        "max": 0.15,
        "detail": (
            f"largest_input_tokens_session={payload.get('largest_input_tokens_session')!r} "
            f"largest_input_tokens={payload.get('largest_input_tokens')!r} "
            f"largest_context_limit={payload.get('largest_context_limit')!r}"
        ),
    }

    got_highest_ratio = _coerce_ratio(payload.get("highest_pressure_ratio"))
    expected_highest_ratio = expected["highest_pressure_ratio"]
    highest_pressure_ok = (
        payload.get("highest_pressure_session") == expected["highest_pressure_session"]
        and got_highest_ratio is not None
        and isclose(got_highest_ratio, float(expected_highest_ratio), abs_tol=0.001)
    )
    checkpoints["highest_pressure_summary_is_correct"] = {
        "score": 0.15 if highest_pressure_ok else 0.0,
        "max": 0.15,
        "detail": (
            f"highest_pressure_session={payload.get('highest_pressure_session')!r} "
            f"highest_pressure_ratio={payload.get('highest_pressure_ratio')!r} "
            f"expected_session={expected['highest_pressure_session']!r} "
            f"expected_ratio={expected_highest_ratio!r}"
        ),
    }

    checkpoints["recommended_action_is_correct"] = {
        "score": 0.1 if payload.get("recommended_action") == expected["recommended_action"] else 0.0,
        "max": 0.1,
        "detail": (
            f"recommended_action={payload.get('recommended_action')!r} "
            f"expected={expected['recommended_action']!r}"
        ),
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    used_sessions = trace_used_openclaw_exec(trace, "openclaw", "sessions", "--json")
    return 1.0 if used_sessions else 0.2
