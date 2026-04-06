from __future__ import annotations

from pathlib import Path

SECTIONS = ["## Critical", "## Owners", "## Next Step"]


def grade(workspace_path: str, trace: dict, tool_calls: list[dict]) -> dict:
    target = Path(workspace_path) / "handoff.md"
    content = target.read_text(encoding="utf-8") if target.exists() else ""
    lowered = content.lower()

    section_hits = sum(1 for section in SECTIONS if section in content)
    has_critical = all(token in content for token in ["B-71", "B-88"])
    excludes_low = "B-91" not in content
    owner_patterns = [
        ("B-71: platform-oncall" in lowered) or ("platform-oncall" in lowered and "b-71" in lowered),
        ("B-88: Mina" in content) or ("Mina" in content and "B-88" in content),
    ]
    has_owner_map = all(owner_patterns)
    has_next_step = "b-71" in lowered and "platform-oncall" in lowered and "unassigned" not in lowered

    return {
        "checkpoints": {
            "handoff_exists": {
                "score": 0.2 if target.exists() else 0.0,
                "max": 0.2,
                "detail": "handoff.md exists",
            },
            "required_sections": {
                "score": round(0.2 * (section_hits / len(SECTIONS)), 4),
                "max": 0.2,
                "detail": f"sections={section_hits}/{len(SECTIONS)}",
            },
            "critical_blockers_only": {
                "score": 0.25 if has_critical and excludes_low else 0.0,
                "max": 0.25,
                "detail": content,
            },
            "session_memory_owner_reuse": {
                "score": 0.2 if has_owner_map else 0.0,
                "max": 0.2,
                "detail": content,
            },
            "next_step_is_grounded": {
                "score": 0.15 if has_next_step else 0.0,
                "max": 0.15,
                "detail": content,
            },
        }
    }
