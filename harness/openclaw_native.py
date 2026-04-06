"""Helpers for grading live scenarios against the local OpenClaw installation."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


MISSING_FAMILIES: tuple[str, ...] = ("bins", "anyBins", "env", "config", "os")
NATIVE_TOOL_CANONICAL_COMMANDS: dict[str, str] = {
    "skills_list": "openclaw skills list --json",
    "agents_list": "openclaw agents list --json",
    "sessions_list": "openclaw sessions --json",
    "session_status": "openclaw sessions status --json",
    "browser_status": "openclaw browser status --json",
    "directory_self": "openclaw directory self --json",
    "directory_peers": "openclaw directory peers list --json",
    "memory_search": "openclaw memory search",
    "message_send": "openclaw message send",
    "cron": "openclaw cron",
    "gateway": "openclaw gateway",
}
NATIVE_TOOL_SURFACE_MAP: dict[str, str] = {
    "skills_list": "skills",
    "agents_list": "agents",
    "sessions_list": "sessions",
    "session_status": "sessions",
    "browser_status": "browser",
    "directory_self": "directory",
    "directory_peers": "directory",
    "memory_search": "memory",
    "message_send": "message",
    "cron": "cron",
    "gateway": "gateway",
}
OPENCLAW_SURFACES: tuple[str, ...] = ("skills", "memory", "browser", "cron", "directory", "agents", "sessions", "message", "gateway")


def resolve_openclaw_bin(
    openclaw_bin: str = "openclaw",
    *,
    env: dict[str, str] | None = None,
) -> str:
    source_env = env or os.environ
    configured = source_env.get("OPENCLAW_BINARY", "").strip()
    if openclaw_bin and openclaw_bin != "openclaw":
        return openclaw_bin
    if configured:
        return configured
    return openclaw_bin or "openclaw"


def extract_json_payload(text: str) -> Any | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    try:
        payload, _ = decoder.raw_decode(stripped)
        return payload
    except json.JSONDecodeError:
        pass
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return payload
    return None


def run_openclaw_command(
    *args: str,
    timeout: int = 30,
    openclaw_bin: str = "openclaw",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    resolved_bin = resolve_openclaw_bin(openclaw_bin, env=env)
    return subprocess.run(
        [resolved_bin, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=env,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout or stderr


def run_openclaw_json(
    *args: str,
    timeout: int = 30,
    openclaw_bin: str = "openclaw",
    env: dict[str, str] | None = None,
) -> Any:
    result = run_openclaw_command(*args, timeout=timeout, openclaw_bin=openclaw_bin, env=env)
    payload = (
        extract_json_payload(result.stdout)
        or extract_json_payload(result.stderr)
        or extract_json_payload(combined_output(result))
    )
    resolved_bin = resolve_openclaw_bin(openclaw_bin, env=env)
    if result.returncode != 0:
        detail = combined_output(result).strip() or "OpenClaw command failed"
        raise RuntimeError(f"{' '.join([resolved_bin, *args])} exited {result.returncode}: {detail}")
    if payload is None:
        detail = combined_output(result).strip() or "missing JSON payload"
        raise RuntimeError(f"{' '.join([resolved_bin, *args])} did not return JSON: {detail}")
    return payload


def load_skills_inventory(openclaw_bin: str = "openclaw", *, env: dict[str, str] | None = None) -> dict[str, Any]:
    payload = run_openclaw_json("skills", "list", "--json", openclaw_bin=openclaw_bin, env=env)
    if not isinstance(payload, dict) or not isinstance(payload.get("skills"), list):
        raise RuntimeError("OpenClaw skills inventory payload is malformed")
    return payload


def skills_by_name(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload.get("skills") or []
    return {
        str(row.get("name")): row
        for row in rows
        if isinstance(row, dict) and str(row.get("name", "")).strip()
    }


def first_missing_family(skill: dict[str, Any] | None) -> str | None:
    if not isinstance(skill, dict):
        return None
    missing = skill.get("missing") or {}
    for family in MISSING_FAMILIES:
        values = missing.get(family)
        if isinstance(values, list) and values:
            return family
    return None


def eligible_skill_names(payload: dict[str, Any]) -> list[str]:
    return sorted(
        str(skill.get("name"))
        for skill in payload.get("skills", [])
        if isinstance(skill, dict) and skill.get("eligible") and str(skill.get("name", "")).strip()
    )


def missing_skill_names(payload: dict[str, Any]) -> list[str]:
    return sorted(
        str(skill.get("name"))
        for skill in payload.get("skills", [])
        if isinstance(skill, dict) and not skill.get("eligible") and str(skill.get("name", "")).strip()
    )


def count_missing_family(payload: dict[str, Any], family: str) -> int:
    count = 0
    for skill in payload.get("skills", []):
        if not isinstance(skill, dict):
            continue
        missing = skill.get("missing") or {}
        values = missing.get(family)
        if isinstance(values, list) and values:
            count += 1
    return count


def skill_has_missing_family(skill: dict[str, Any] | None, family: str) -> bool:
    if not isinstance(skill, dict):
        return False
    missing = skill.get("missing") or {}
    values = missing.get(family)
    return isinstance(values, list) and bool(values)


def example_skill_names(
    payload: dict[str, Any],
    *,
    eligible: bool | None = None,
    bundled: bool | None = None,
    missing_family: str | None = None,
    limit: int,
) -> list[str]:
    names: list[str] = []
    for skill in payload.get("skills", []):
        if not isinstance(skill, dict):
            continue
        name = str(skill.get("name", "")).strip()
        if not name:
            continue
        if eligible is not None and bool(skill.get("eligible")) != eligible:
            continue
        if bundled is not None and bool(skill.get("bundled")) != bundled:
            continue
        if missing_family is not None and first_missing_family(skill) != missing_family:
            continue
        names.append(name)
    return sorted(names)[:limit]


def is_openclaw_skills_inventory_command(command: str) -> bool:
    normalized = " ".join(command.lower().split())
    return "openclaw skills list" in normalized or "openclaw skills --json" in normalized


def _cli_flag_name(key: str) -> str:
    kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", str(key)).replace("_", "-").strip("-").lower()
    return key if str(key).startswith("-") else f"--{kebab}"


def _trace_args_cli_text(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    tokens: list[str] = []
    for key, value in args.items():
        if value in (None, "", False):
            continue
        flag = _cli_flag_name(str(key))
        if isinstance(value, bool):
            tokens.append(flag)
            continue
        if isinstance(value, (str, int, float)):
            tokens.extend((flag, str(value)))
            continue
        if isinstance(value, list):
            for item in value:
                if item in (None, ""):
                    continue
                tokens.extend((flag, str(item)))
            continue
        tokens.extend((flag, json.dumps(value, ensure_ascii=False, sort_keys=True)))
    return " ".join(tokens)


def trace_openclaw_call_text(event: dict[str, Any]) -> str:
    if event.get("type") != "tool_call":
        return ""
    tool_name = str(event.get("tool", "")).strip()
    args = event.get("args") or {}
    if tool_name == "exec":
        return str(args.get("command", "")).lower()

    base = NATIVE_TOOL_CANONICAL_COMMANDS.get(tool_name)
    if base is None:
        surface = NATIVE_TOOL_SURFACE_MAP.get(tool_name)
        if surface is None:
            return ""
        base = f"openclaw {surface}"
    arg_text = _trace_args_cli_text(args)
    return " ".join(part for part in (base, arg_text) if part).lower()


def trace_used_openclaw_skills_inventory(trace: dict[str, Any]) -> bool:
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        if is_openclaw_skills_inventory_command(trace_openclaw_call_text(event)):
            return True
    return False


def trace_used_openclaw_exec(trace: dict[str, Any], *required_parts: str) -> bool:
    lowered_parts = [part.lower() for part in required_parts]
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        command = trace_openclaw_call_text(event)
        if all(part in command for part in lowered_parts):
            return True
    return False


def trace_used_openclaw_exec_count(trace: dict[str, Any], *required_parts: str) -> int:
    lowered_parts = [part.lower() for part in required_parts]
    count = 0
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        command = trace_openclaw_call_text(event)
        if all(part in command for part in lowered_parts):
            count += 1
    return count


def trace_openclaw_surfaces_used(trace: dict[str, Any]) -> set[str]:
    surfaces: set[str] = set()
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        tool_name = str(event.get("tool", "")).strip()
        mapped_surface = NATIVE_TOOL_SURFACE_MAP.get(tool_name)
        if mapped_surface:
            surfaces.add(mapped_surface)
            continue

        command = trace_openclaw_call_text(event)
        if "openclaw" not in command:
            continue
        for surface in OPENCLAW_SURFACES:
            if f"openclaw {surface}" in command:
                surfaces.add(surface)
    return surfaces


def trace_used_openclaw_surface(trace: dict[str, Any], surface: str) -> bool:
    normalized = str(surface).strip().lower()
    return normalized in trace_openclaw_surfaces_used(trace)


def trace_native_environment_snapshot(trace: dict[str, Any]) -> dict[str, Any] | None:
    audit_state = trace.get("audit_state") or {}
    snapshot = audit_state.get("native_environment")
    return snapshot if isinstance(snapshot, dict) else None


def trace_native_surface_snapshot(trace: dict[str, Any], surface: str) -> dict[str, Any] | None:
    snapshot = trace_native_environment_snapshot(trace)
    if snapshot is None:
        return None
    value = snapshot.get(str(surface).strip())
    return value if isinstance(value, dict) else None


def grade_skills_process(trace: dict[str, Any]) -> float:
    openclaw_calls: list[str] = []
    wrote_output = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        tool_name = event.get("tool")
        if tool_name != "write":
            command = trace_openclaw_call_text(event)
            if command:
                openclaw_calls.append(command)
        if tool_name == "write":
            args = event.get("args") or {}
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_output = True

    used_skills = any(is_openclaw_skills_inventory_command(command) for command in openclaw_calls)
    if used_skills and wrote_output and len(openclaw_calls) <= 2:
        return 1.0
    if used_skills and wrote_output and len(openclaw_calls) <= 4:
        return 0.8
    if used_skills:
        return 0.6
    return 0.2


def parse_configured_channels(text: str) -> list[str]:
    match = re.search(r"multiple channels are configured:\s*([^\n]+)", text, flags=re.IGNORECASE)
    if not match:
        return []
    raw_items = [item.strip() for item in match.group(1).split(",")]
    return sorted(item for item in raw_items if item)


def directory_required_channels(openclaw_bin: str = "openclaw", *, env: dict[str, str] | None = None) -> list[str]:
    result = run_openclaw_command("directory", "self", "--json", openclaw_bin=openclaw_bin, env=env)
    return parse_configured_channels(combined_output(result))


def directory_peers(
    channel: str,
    *,
    limit: int = 3,
    openclaw_bin: str = "openclaw",
    env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    payload = run_openclaw_json(
        "directory",
        "peers",
        "list",
        "--channel",
        channel,
        "--limit",
        str(limit),
        "--json",
        openclaw_bin=openclaw_bin,
        env=env,
    )
    if not isinstance(payload, list):
        raise RuntimeError(f"directory peers payload for channel {channel!r} is not a list")
    return [item for item in payload if isinstance(item, dict)]


def memory_search_output(
    query: str = "test",
    *,
    max_results: int = 3,
    openclaw_bin: str = "openclaw",
    env: dict[str, str] | None = None,
) -> str:
    result = run_openclaw_command(
        "memory",
        "search",
        "--query",
        query,
        "--max-results",
        str(max_results),
        openclaw_bin=openclaw_bin,
        timeout=45,
        env=env,
    )
    return combined_output(result)


def browser_status_output(openclaw_bin: str = "openclaw", *, env: dict[str, str] | None = None) -> str:
    result = run_openclaw_command("browser", "status", "--json", openclaw_bin=openclaw_bin, timeout=45, env=env)
    return combined_output(result)


def cron_list_output(openclaw_bin: str = "openclaw", *, env: dict[str, str] | None = None) -> str:
    result = run_openclaw_command("cron", "list", "--json", openclaw_bin=openclaw_bin, timeout=45, env=env)
    return combined_output(result)


def infer_surface_status(output: str) -> str:
    lowered = output.lower()
    if "gateway closed" in lowered or "gateway connect failed" in lowered:
        return "gateway_closed"
    if extract_json_payload(output) is not None:
        return "ready"
    if "error:" in lowered or "failed" in lowered:
        return "other_failure"
    return "ready" if output.strip() else "other_failure"


def extract_gateway_target(output: str) -> str:
    match = re.search(r"Gateway target:\s*(\S+)", output, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).strip()


def infer_memory_failure_mode(output: str) -> str:
    lowered = output.lower()
    if "unable to open database file" in lowered:
        return "database_unavailable"
    if "index" in lowered and ("missing" in lowered or "not found" in lowered or "unavailable" in lowered):
        return "index_missing"
    if "no matches" in lowered and "sync failed" not in lowered and "error" not in lowered:
        return "ok_empty"
    if "sync failed" in lowered or "error" in lowered:
        return "unknown_failure"
    return "ok_empty"


def message_dry_run_payload(
    *,
    channel: str = "telegram",
    target: str = "@benchmark_target",
    message: str = "hello from benchmark",
    openclaw_bin: str = "openclaw",
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = run_openclaw_json(
        "message",
        "send",
        "--dry-run",
        "--json",
        "--channel",
        channel,
        "--target",
        target,
        "--message",
        message,
        openclaw_bin=openclaw_bin,
        timeout=45,
        env=env,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("payload"), dict):
        raise RuntimeError("OpenClaw message dry-run payload is malformed")
    return payload


def load_agents_inventory(openclaw_bin: str = "openclaw", *, env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    payload = run_openclaw_json("agents", "list", "--json", openclaw_bin=openclaw_bin, timeout=45, env=env)
    if not isinstance(payload, list):
        raise RuntimeError("OpenClaw agents payload is malformed")
    return [item for item in payload if isinstance(item, dict)]


def default_agent_record(payload: list[dict[str, Any]]) -> dict[str, Any] | None:
    for agent in payload:
        if agent.get("isDefault"):
            return agent
    return None


def count_agents_with_model(payload: list[dict[str, Any]], model: str) -> int:
    return sum(1 for agent in payload if str(agent.get("model", "")).strip() == model)


def load_sessions_inventory(openclaw_bin: str = "openclaw", *, env: dict[str, str] | None = None) -> dict[str, Any]:
    payload = run_openclaw_json("sessions", "--json", openclaw_bin=openclaw_bin, timeout=45, env=env)
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
        raise RuntimeError("OpenClaw sessions payload is malformed")
    return payload


def sessions_over_context_limit_keys(payload: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for session in payload.get("sessions", []):
        if not isinstance(session, dict):
            continue
        input_tokens = session.get("inputTokens")
        context_tokens = session.get("contextTokens")
        key = str(session.get("key", "")).strip()
        if not key or not isinstance(input_tokens, int) or not isinstance(context_tokens, int):
            continue
        if input_tokens > context_tokens:
            keys.append(key)
    return sorted(keys)


def largest_input_session(payload: dict[str, Any]) -> dict[str, Any] | None:
    best_session: dict[str, Any] | None = None
    best_tokens = -1
    for session in payload.get("sessions", []):
        if not isinstance(session, dict):
            continue
        input_tokens = session.get("inputTokens")
        if not isinstance(input_tokens, int):
            continue
        if input_tokens > best_tokens:
            best_session = session
            best_tokens = input_tokens
    return best_session


def load_json_file(workspace: str | Path, filename: str) -> tuple[dict[str, Any] | None, str]:
    path = Path(workspace) / filename
    if not path.exists():
        return None, f"missing {filename}"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(raw, dict):
        return None, f"{filename} must contain a JSON object"
    return raw, f"loaded {filename}"


def collect_native_environment_snapshot(
    surfaces: list[str] | tuple[str, ...],
    *,
    openclaw_bin: str = "openclaw",
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    normalized_surfaces = sorted({str(surface).strip() for surface in surfaces if str(surface).strip()})
    snapshot: dict[str, Any] = {
        "version": 1,
        "surfaces": normalized_surfaces,
    }

    for surface in normalized_surfaces:
        try:
            if surface == "skills":
                inventory = load_skills_inventory(openclaw_bin=openclaw_bin, env=env)
                snapshot["skills"] = {
                    "status": "ready",
                    "ready_count": len(eligible_skill_names(inventory)),
                    "missing_count": len(missing_skill_names(inventory)),
                    "workspace_dir": str(inventory.get("workspaceDir", "")),
                    "managed_skills_dir": str(inventory.get("managedSkillsDir", "")),
                    "ready_examples": example_skill_names(inventory, eligible=True, limit=3),
                    "missing_examples": example_skill_names(inventory, eligible=False, limit=3),
                    "ready_list": eligible_skill_names(inventory),
                    "missing_list": missing_skill_names(inventory),
                    "first_missing_family_by_skill": {
                        name: first_missing_family(skill)
                        for name, skill in skills_by_name(inventory).items()
                        if first_missing_family(skill) is not None
                    },
                }
                continue

            if surface == "memory":
                output = memory_search_output(openclaw_bin=openclaw_bin, env=env)
                snapshot["memory"] = {
                    "status": infer_surface_status(output),
                    "failure_mode": infer_memory_failure_mode(output),
                }
                continue

            if surface == "browser":
                output = browser_status_output(openclaw_bin=openclaw_bin, env=env)
                snapshot["browser"] = {
                    "status": infer_surface_status(output),
                    "gateway_target": extract_gateway_target(output),
                }
                continue

            if surface == "cron":
                output = cron_list_output(openclaw_bin=openclaw_bin, env=env)
                snapshot["cron"] = {
                    "status": infer_surface_status(output),
                }
                continue

            if surface == "directory":
                result = run_openclaw_command(
                    "directory",
                    "self",
                    "--json",
                    openclaw_bin=openclaw_bin,
                    timeout=45,
                    env=env,
                )
                output = combined_output(result)
                payload = extract_json_payload(output)
                channels = parse_configured_channels(output)
                snapshot["directory"] = {
                    "status": infer_surface_status(output),
                    "ambiguous_self_lookup": bool(channels),
                    "configured_channels": channels,
                    "self_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
                }
                continue

            if surface == "agents":
                agents = load_agents_inventory(openclaw_bin=openclaw_bin, env=env)
                default_agent = default_agent_record(agents)
                snapshot["agents"] = {
                    "status": "ready",
                    "count": len(agents),
                    "default_model": str(default_agent.get("model", "")) if default_agent else "",
                }
                continue

            if surface == "sessions":
                sessions = load_sessions_inventory(openclaw_bin=openclaw_bin, env=env)
                largest = largest_input_session(sessions)
                snapshot["sessions"] = {
                    "status": "ready",
                    "count": len(sessions.get("sessions", [])),
                    "over_context_limit": sessions_over_context_limit_keys(sessions),
                    "largest_session_key": str(largest.get("key", "")) if largest else "",
                    "largest_session_input_tokens": int(largest.get("inputTokens", 0)) if largest else 0,
                }
                continue

            snapshot[surface] = {
                "status": "unsupported_surface",
            }
        except Exception as exc:
            snapshot[surface] = {
                "status": "error",
                "error": str(exc),
            }

    return snapshot
