"""Trace normalization for OpenClaw JSONL transcripts."""

from __future__ import annotations

import json
import math
import re
from typing import Any

_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_PUNCT_RE = re.compile(r"[^\sA-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
_SYSTEM_PROMPT_CHAR_TOKEN_RATIO = 0.9
_PUNCTUATION_TOKEN_WEIGHT = 0.15


def normalize_trace(
    raw_entries: list[dict[str, Any]],
    session_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    metrics = {
        "assistant_turns": 0,
        "tool_calls": 0,
        "total_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
    }
    audit_state: dict[str, Any] = {}
    tool_name_by_call_id: dict[str, str] = {}

    for index, entry in enumerate(raw_entries):
        if isinstance(entry.get("audit_state"), dict):
            audit_state = dict(entry["audit_state"])

        msg = _message_from_entry(entry)
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            text = _extract_text(content)
            if text:
                events.append({"type": "user_message", "text": text, "seq": index})
            continue

        if role != "assistant":
            continue

        metrics["assistant_turns"] += 1
        usage = _normalize_usage(msg.get("usage") or {})
        metrics["input_tokens"] += usage["input"]
        metrics["output_tokens"] += usage["output"]
        metrics["cache_read_tokens"] += usage["cache_read"]
        metrics["cache_write_tokens"] += usage["cache_write"]
        metrics["total_tokens"] += usage["total"]
        metrics["cost_usd"] += usage["cost_usd"]

        blocks = content if isinstance(content, list) else [content]
        for block in blocks:
            if isinstance(block, str):
                if block:
                    events.append({"type": "assistant_message", "text": block, "seq": index})
                continue
            if not isinstance(block, dict):
                continue

            block_type = block.get("type", "")
            if block_type == "text":
                text = block.get("text", "")
                if text:
                    events.append({"type": "assistant_message", "text": text, "seq": index})
                continue

            if block_type in ("toolCall", "tool_use"):
                tool_name = block.get("name", block.get("tool", ""))
                call_id = block.get("id", block.get("toolCallId", ""))
                if call_id:
                    tool_name_by_call_id[str(call_id)] = tool_name
                metrics["tool_calls"] += 1
                events.append(
                    {
                        "type": "tool_call",
                        "tool": tool_name,
                        "args": block.get("input", block.get("arguments", {})),
                        "call_id": call_id,
                        "seq": index,
                    }
                )
                continue

            if block_type in ("toolResult", "tool_result"):
                call_id = block.get("toolCallId", block.get("id", ""))
                tool_name = block.get("name", tool_name_by_call_id.get(str(call_id), ""))
                status = block.get("status", block.get("statusCode", 200))
                if isinstance(status, str):
                    lowered = status.lower()
                    if lowered in ("completed", "ok", "success"):
                        status = 200
                    elif lowered == "timeout":
                        status = 504
                    elif lowered == "error":
                        status = 500
                events.append(
                    {
                        "type": "tool_result",
                        "tool": tool_name,
                        "result": _extract_text(block.get("content", block.get("result", ""))),
                        "status": int(status),
                        "call_id": call_id,
                        "seq": index,
                    }
                )

    if _should_estimate_usage(metrics):
        estimated_usage = _estimate_usage_from_transcript(raw_entries, session_metadata=session_metadata)
        if estimated_usage["total"] > 0:
            metrics["input_tokens"] = estimated_usage["input"]
            metrics["output_tokens"] = estimated_usage["output"]
            metrics["cache_read_tokens"] = estimated_usage["cache_read"]
            metrics["cache_write_tokens"] = estimated_usage["cache_write"]
            metrics["total_tokens"] = estimated_usage["total"]
            audit_state["usage_fallback"] = {
                "mode": "transcript_estimate",
                "reason": "provider_usage_all_zero",
                "system_prompt_tokens_estimate": estimated_usage["system_prompt_tokens"],
            }

    return {"events": events, "metrics": metrics, "audit_state": audit_state}


def _message_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    if entry.get("type") == "message" and isinstance(entry.get("message"), dict):
        return entry["message"]
    if isinstance(entry, dict) and entry.get("role") in {"user", "assistant", "toolResult"}:
        return entry
    return None


def _as_int(value: Any) -> int:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return 0
        try:
            return int(float(stripped))
        except ValueError:
            return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _first_present(mapping: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current: Any = mapping
        found = True
        for key in path:
            if not isinstance(current, dict) or key not in current:
                found = False
                break
            current = current[key]
        if found and current not in (None, ""):
            return current
    return 0


def _normalize_usage(usage: dict[str, Any]) -> dict[str, Any]:
    input_tokens = _as_int(
        _first_present(
            usage,
            ("input",),
            ("inputTokens",),
            ("input_tokens",),
            ("prompt_tokens",),
            ("promptTokens",),
            ("usage", "input"),
            ("usage", "inputTokens"),
            ("usage", "input_tokens"),
            ("usage", "prompt_tokens"),
            ("usage", "promptTokens"),
        )
    )
    output_tokens = _as_int(
        _first_present(
            usage,
            ("output",),
            ("outputTokens",),
            ("output_tokens",),
            ("completion_tokens",),
            ("completionTokens",),
            ("usage", "output"),
            ("usage", "outputTokens"),
            ("usage", "output_tokens"),
            ("usage", "completion_tokens"),
            ("usage", "completionTokens"),
        )
    )
    cache_read_tokens = _as_int(
        _first_present(
            usage,
            ("cacheRead",),
            ("cache_read",),
            ("cacheReadInputTokens",),
            ("cache_read_input_tokens",),
            ("cached_tokens",),
            ("prompt_tokens_details", "cached_tokens"),
            ("usage", "cacheRead"),
            ("usage", "cache_read"),
            ("usage", "cacheReadInputTokens"),
            ("usage", "cache_read_input_tokens"),
            ("usage", "cached_tokens"),
            ("usage", "prompt_tokens_details", "cached_tokens"),
        )
    )
    cache_write_tokens = _as_int(
        _first_present(
            usage,
            ("cacheWrite",),
            ("cache_write",),
            ("cacheCreationInputTokens",),
            ("cache_creation_input_tokens",),
            ("usage", "cacheWrite"),
            ("usage", "cache_write"),
            ("usage", "cacheCreationInputTokens"),
            ("usage", "cache_creation_input_tokens"),
        )
    )
    total_tokens = _as_int(
        _first_present(
            usage,
            ("totalTokens",),
            ("total",),
            ("total_tokens",),
            ("usage", "totalTokens"),
            ("usage", "total"),
            ("usage", "total_tokens"),
        )
    )
    accounted_total = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    if total_tokens <= 0:
        total_tokens = accounted_total
    cost = usage.get("cost", 0.0)
    cost_usd = 0.0
    if isinstance(cost, dict):
        cost_usd = float(cost.get("total", cost.get("total_usd", 0.0)) or 0.0)
    elif isinstance(cost, (int, float)):
        cost_usd = float(cost)
    return {
        "input": input_tokens,
        "output": output_tokens,
        "cache_read": cache_read_tokens,
        "cache_write": cache_write_tokens,
        "total": total_tokens,
        "cost_usd": cost_usd,
    }


def _should_estimate_usage(metrics: dict[str, Any]) -> bool:
    if int(metrics.get("assistant_turns", 0) or 0) <= 0:
        return False
    token_keys = (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "total_tokens",
    )
    return all(int(metrics.get(key, 0) or 0) <= 0 for key in token_keys)


def _estimate_usage_from_transcript(
    raw_entries: list[dict[str, Any]],
    session_metadata: dict[str, Any] | None = None,
) -> dict[str, int]:
    current_context_tokens = _estimate_system_prompt_tokens(session_metadata or {})
    previous_prompt_tokens = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0

    for entry in raw_entries:
        msg = _message_from_entry(entry)
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "") or "")

        if role in {"user", "toolResult"}:
            current_context_tokens += _estimate_message_tokens(msg)
            continue

        if role != "assistant":
            continue

        prompt_tokens = current_context_tokens
        cacheable_tokens = min(previous_prompt_tokens, prompt_tokens)
        cache_read_tokens += cacheable_tokens
        input_tokens += max(prompt_tokens - cacheable_tokens, 0)

        assistant_tokens = _estimate_message_tokens(msg)
        output_tokens += assistant_tokens
        current_context_tokens += assistant_tokens
        previous_prompt_tokens = prompt_tokens

    total_tokens = input_tokens + output_tokens + cache_read_tokens
    return {
        "input": input_tokens,
        "output": output_tokens,
        "cache_read": cache_read_tokens,
        "cache_write": 0,
        "total": total_tokens,
        "system_prompt_tokens": _estimate_system_prompt_tokens(session_metadata or {}),
    }


def _estimate_system_prompt_tokens(session_metadata: dict[str, Any]) -> int:
    report = session_metadata.get("systemPromptReport", {})
    if not isinstance(report, dict):
        return 0
    system_prompt = report.get("systemPrompt", {})
    chars = 0
    if isinstance(system_prompt, dict):
        chars = _as_int(system_prompt.get("chars", 0))
    if chars <= 0:
        chars = _as_int(report.get("projectContextChars", 0)) + _as_int(report.get("nonProjectContextChars", 0))
    return max(0, int(math.ceil(chars * _SYSTEM_PROMPT_CHAR_TOKEN_RATIO)))


def _estimate_message_tokens(message: dict[str, Any]) -> int:
    return _estimate_content_tokens(message.get("content", ""))


def _estimate_content_tokens(content: Any) -> int:
    text = _content_to_token_text(content)
    if not text:
        return 0
    cjk_tokens = len(_CJK_CHAR_RE.findall(text))
    word_tokens = sum(max(1, math.ceil(len(word) / 4.0)) for word in _WORD_RE.findall(text))
    punctuation_tokens = int(math.ceil(len(_PUNCT_RE.findall(text)) * _PUNCTUATION_TOKEN_WEIGHT))
    return cjk_tokens + word_tokens + punctuation_tokens


def _content_to_token_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _block_to_token_text(content)
    if isinstance(content, list):
        parts = [_content_to_token_text(item) for item in content]
        return "\n".join(part for part in parts if part)
    return str(content)


def _block_to_token_text(block: dict[str, Any]) -> str:
    block_type = str(block.get("type", "") or "")
    if block_type in {"text", "thinking"}:
        return str(block.get("text") or block.get("thinking") or "")
    if block_type in {"toolCall", "tool_use"}:
        name = str(block.get("name") or block.get("tool") or "")
        args = block.get("arguments", block.get("input", {}))
        args_text = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False, sort_keys=True)
        return f"{name} {args_text}".strip()
    if block_type in {"toolResult", "tool_result"}:
        name = str(block.get("name") or block.get("tool") or "")
        result_text = _content_to_token_text(block.get("content", block.get("result", "")))
        return f"{name} {result_text}".strip()
    return _extract_text(block)


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item.get("text", "")))
                elif "content" in item:
                    parts.append(_extract_text(item.get("content")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(part for part in parts if part)
    return str(content)
