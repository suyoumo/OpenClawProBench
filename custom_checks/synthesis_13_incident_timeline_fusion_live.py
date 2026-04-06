"""Custom checks for the incident timeline fusion scenario."""

from __future__ import annotations

import json
import re
from pathlib import Path


EXPECTED_TIMELINE = [
    {"time": "01:02", "event": "checkout_profile_enrichment_enabled"},
    {"time": "01:03", "event": "profile_db_pool_spiked_to_99_pct"},
    {"time": "01:04", "event": "checkout_upstream_profile_timeouts_started"},
    {"time": "01:08", "event": "rollback_started"},
    {"time": "01:10", "event": "error_rate_returned_to_baseline"},
]
EXPECTED_RULED_OUT = ["network_packet_loss", "payment_gateway_outage"]
EXPECTED_EVIDENCE_REFS = {"alerts.log", "db_metrics.json", "chat_notes.md"}

TIMELINE_EVENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "checkout_profile_enrichment_enabled": (
        "checkout profile enrichment",
        "enabled",
    ),
    "profile_db_pool_spiked_to_99_pct": (
        "profile",
        "pool",
        "99",
    ),
    "checkout_upstream_profile_timeouts_started": (
        "timeout",
        "profile",
    ),
    "rollback_started": (
        "rollback",
        "started",
    ),
    "error_rate_returned_to_baseline": (
        "baseline",
    ),
}

RULED_OUT_PATTERNS: dict[str, tuple[str, ...]] = {
    "network_packet_loss": ("network",),
    "payment_gateway_outage": ("payment", "gateway"),
}


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _normalize_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    for expected in EXPECTED_EVIDENCE_REFS:
        if normalized.endswith(expected):
            return expected
    if normalized.endswith("incident_fusion.json"):
        return "incident_fusion.json"
    return normalized


def _read_paths(trace: dict) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        args = event.get("args") or {}
        if isinstance(args, dict):
            path = args.get("path") or args.get("file_path")
            if isinstance(path, str):
                paths.add(_normalize_path(path))
    return paths


def _normalize_text(raw: object) -> str:
    text = str(raw or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _match_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    return all(keyword in text for keyword in keywords)


def _normalize_timeline(raw: object) -> list[dict[str, str]] | None:
    if not isinstance(raw, list):
        return None
    normalized: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        time = str(item.get("time", "")).strip()
        raw_event = str(item.get("event", "")).strip()
        if raw_event in TIMELINE_EVENT_PATTERNS:
            canonical_event = raw_event
        else:
            normalized_event = _normalize_text(raw_event)
            canonical_event = None
            for event_id, keywords in TIMELINE_EVENT_PATTERNS.items():
                if _match_keywords(normalized_event, keywords):
                    canonical_event = event_id
                    break
            if canonical_event is None and "profile" in normalized_event and (
                "timeout" in normalized_event or "timing out" in normalized_event or "timed out" in normalized_event
            ):
                canonical_event = "checkout_upstream_profile_timeouts_started"
            if canonical_event is None:
                return None
        if not time or not canonical_event:
            return None
        normalized.append({"time": time, "event": canonical_event})
    return normalized


def _normalize_root_cause(raw: object) -> str | None:
    raw_text = str(raw or "").strip()
    if raw_text == "checkout_profile_enrichment_triggered_profile_db_pool_exhaustion":
        return raw_text
    normalized = _normalize_text(raw_text)
    has_core = all(keyword in normalized for keyword in ("checkout", "profile", "enrichment", "pool"))
    has_saturation = any(keyword in normalized for keyword in ("exhaustion", "saturat", "99"))
    has_timeout = any(keyword in normalized for keyword in ("timeout", "timing out", "timed out"))
    if has_core and has_saturation and has_timeout:
        return "checkout_profile_enrichment_triggered_profile_db_pool_exhaustion"
    return None


def _normalize_ruled_out(raw: object) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    normalized_items: list[str] = []
    seen: set[str] = set()
    for item in raw:
        raw_text = str(item or "").strip()
        if raw_text in RULED_OUT_PATTERNS:
            canonical = raw_text
        else:
            normalized = _normalize_text(raw_text)
            canonical = None
            for candidate, keywords in RULED_OUT_PATTERNS.items():
                if _match_keywords(normalized, keywords):
                    canonical = candidate
                    break
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        normalized_items.append(canonical)
    return normalized_items


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}
    output_path = ws / "incident_fusion.json"
    exists = output_path.exists()
    checkpoints["fusion_file_exists"] = {
        "score": 0.1 if exists else 0.0,
        "max": 0.1,
        "detail": "incident_fusion.json exists" if exists else "missing incident_fusion.json",
    }
    if not exists:
        for check_id, max_score in (
            ("timeline_is_correct", 0.30),
            ("root_cause_is_correct", 0.25),
            ("ruled_out_is_correct", 0.15),
            ("confidence_is_correct", 0.1),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("timeline_is_correct", 0.30),
            ("root_cause_is_correct", 0.25),
            ("ruled_out_is_correct", 0.15),
            ("confidence_is_correct", 0.1),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    normalized_timeline = _normalize_timeline(payload.get("timeline"))
    checkpoints["timeline_is_correct"] = {
        "score": 0.30 if normalized_timeline == EXPECTED_TIMELINE else 0.0,
        "max": 0.30,
        "detail": f"timeline={payload.get('timeline')}",
    }
    normalized_root_cause = _normalize_root_cause(payload.get("root_cause"))
    checkpoints["root_cause_is_correct"] = {
        "score": 0.25 if normalized_root_cause == "checkout_profile_enrichment_triggered_profile_db_pool_exhaustion" else 0.0,
        "max": 0.25,
        "detail": f"root_cause={payload.get('root_cause')!r}",
    }
    normalized_ruled_out = _normalize_ruled_out(payload.get("ruled_out"))
    checkpoints["ruled_out_is_correct"] = {
        "score": 0.15 if normalized_ruled_out == EXPECTED_RULED_OUT else 0.0,
        "max": 0.15,
        "detail": f"ruled_out={payload.get('ruled_out')}",
    }
    checkpoints["confidence_is_correct"] = {
        "score": 0.1 if payload.get("confidence") == "high" else 0.0,
        "max": 0.1,
        "detail": f"confidence={payload.get('confidence')!r}",
    }

    evidence_refs = payload.get("evidence_refs")
    evidence_text = " ".join(str(item) for item in evidence_refs) if isinstance(evidence_refs, list) else ""
    evidence_hits = 0
    for keyword_group in (
        ("alerts.log",),
        ("db_metrics.json",),
        ("chat_notes.md",),
    ):
        if any(keyword in evidence_text for keyword in keyword_group):
            evidence_hits += 1
    checkpoints["evidence_refs_are_complete"] = {
        "score": 0.1 if isinstance(evidence_refs, list) and len(evidence_refs) >= 3 and evidence_hits == 3 else 0.0,
        "max": 0.1,
        "detail": f"evidence_refs={evidence_refs}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _read_paths(trace)
    required = EXPECTED_EVIDENCE_REFS
    hit_count = sum(1 for path in read_paths if path in required)
    if hit_count == 3:
        return 1.0
    if hit_count == 2:
        return 0.7
    if hit_count == 1:
        return 0.45
    return 0.2
