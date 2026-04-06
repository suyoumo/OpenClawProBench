"""Custom checks for the manifest reconstruction tool-use scenario."""

from __future__ import annotations

from pathlib import Path

from harness.custom_check_helpers import (
    file_exists_checkpoint,
    load_json_output,
    skip_checkpoints,
)


EXPECTED_SERVICES = [
    {"name": "billing", "version": "v5", "source": "patch_01"},
    {"name": "checkout", "version": "v15", "source": "hotfix_override"},
    {"name": "profile", "version": "v8", "source": "base_manifest"},
    {"name": "search", "version": "v3", "source": "base_manifest"},
]
DEPENDENT_CHECKS = (
    ("services_are_correct", 0.40),
    ("service_count_is_correct", 0.1),
    ("changed_services_are_correct", 0.15),
    ("removed_services_are_correct", 0.15),
    ("evidence_is_complete", 0.1),
)


def _canonical_source(value: object) -> str:
    text = str(value).strip().lower()
    if not text:
        return ""
    if "patch_01" in text:
        return "patch_01"
    if "hotfix" in text:
        return "hotfix_override"
    if "base_manifest" in text:
        return "base_manifest"
    return text


def _canonical_services(services: object) -> list[dict[str, str]] | None:
    if not isinstance(services, list):
        return None
    normalized: list[dict[str, str]] = []
    for item in services:
        if not isinstance(item, dict):
            return None
        normalized.append(
            {
                "name": str(item.get("name", "")),
                "version": str(item.get("version", "")),
                "source": _canonical_source(item.get("source", "")),
            }
        )
    return normalized


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}
    output_path = ws / "release_manifest.json"
    exists = file_exists_checkpoint(
        checkpoints,
        "manifest_file_exists",
        output_path,
        max_score=0.1,
    )
    if not exists:
        skip_checkpoints(checkpoints, DEPENDENT_CHECKS)
        return {"checkpoints": checkpoints, "safety_violations": []}

    payload, detail = load_json_output(output_path)
    if payload is None:
        skip_checkpoints(checkpoints, DEPENDENT_CHECKS, detail=detail)
        return {"checkpoints": checkpoints, "safety_violations": []}

    normalized_services = _canonical_services(payload.get("services"))
    checkpoints["services_are_correct"] = {
        "score": 0.40 if normalized_services == EXPECTED_SERVICES else 0.0,
        "max": 0.40,
        "detail": f"services={payload.get('services')}",
    }
    services = payload.get("services")
    checkpoints["service_count_is_correct"] = {
        "score": 0.1 if isinstance(services, list) and len(services) == 4 else 0.0,
        "max": 0.1,
        "detail": f"service_count={len(services) if isinstance(services, list) else 0}",
    }
    checkpoints["changed_services_are_correct"] = {
        "score": 0.15 if payload.get("changed_services") == ["billing", "checkout"] else 0.0,
        "max": 0.15,
        "detail": f"changed_services={payload.get('changed_services')}",
    }
    checkpoints["removed_services_are_correct"] = {
        "score": 0.15 if payload.get("removed_services") == ["notifications"] else 0.0,
        "max": 0.15,
        "detail": f"removed_services={payload.get('removed_services')}",
    }

    evidence = payload.get("evidence")
    evidence_text = " ".join(str(item) for item in evidence) if isinstance(evidence, list) else ""
    evidence_hits = 0
    for keyword_group in (
        ("base_manifest", "base_manifest.json"),
        ("patch_01", "patch_01.md"),
        ("hotfixes", "hotfixes.txt"),
        ("rollback", "rollback_notes.md"),
    ):
        if any(keyword in evidence_text for keyword in keyword_group):
            evidence_hits += 1
    checkpoints["evidence_is_complete"] = {
        "score": 0.1 if isinstance(evidence, list) and len(evidence) >= 3 and evidence_hits >= 3 else 0.0,
        "max": 0.1,
        "detail": f"evidence_count={len(evidence) if isinstance(evidence, list) else 0} hits={evidence_hits}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths: set[str] = set()
    for event in trace.get("events", []):
        if event.get("type") != "tool_call" or event.get("tool") != "read":
            continue
        args = event.get("args", {})
        if not isinstance(args, dict):
            continue
        for key in ("path", "file", "file_path"):
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                read_paths.add(_canonical_read_path(value))

    required = {
        "brief.md",
        "manifests/base_manifest.json",
        "patches/patch_01.md",
        "hotfixes.txt",
        "rollback_notes.md",
    }
    hit_count = sum(1 for path in read_paths if path in required)
    if hit_count >= 5:
        return 1.0
    if hit_count == 4:
        return 0.8
    if hit_count == 3:
        return 0.6
    return 0.3


def _canonical_read_path(path: str) -> str:
    normalized = str(path).replace("\\", "/")
    for expected in (
        "brief.md",
        "manifests/base_manifest.json",
        "patches/patch_01.md",
        "hotfixes.txt",
        "rollback_notes.md",
    ):
        if normalized.endswith(expected):
            return expected
    return normalized
