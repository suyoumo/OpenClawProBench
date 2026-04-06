from __future__ import annotations

from pathlib import Path


SECTIONS = ["## Critical", "## Owners", "## Next Step"]


def grade(workspace_path: str, trace: dict, tool_calls: list[dict]) -> dict:
    target = Path(workspace_path) / "handoff.md"
    content = target.read_text(encoding="utf-8") if target.exists() else ""
    lowered = content.lower()

    section_hits = sum(1 for section in SECTIONS if section in content)
    has_critical = all(token in content for token in ["B-17", "B-33"])
    excludes_low = "B-21" not in content
    owner_patterns = [
        ("B-17: Unassigned" in content) or ("Unassigned" in content and "B-17" in content),
        ("B-33: Mina" in content) or ("Mina" in content and "B-33" in content),
    ]
    has_owner_map = all(owner_patterns)
    has_next_step = "platform-oncall" in lowered and "b-17" in lowered

    return {
        "checkpoints": {
            "handoff_exists": {
                "score": 0.2 if target.exists() else 0.0,
                "max": 0.2,
                "detail": "handoff.md exists",
            },
            "required_sections": {
                "score": round(0.3 * (section_hits / len(SECTIONS)), 4),
                "max": 0.3,
                "detail": f"sections={section_hits}/{len(SECTIONS)}",
            },
            "critical_blockers_only": {
                "score": 0.3 if has_critical and excludes_low else 0.0,
                "max": 0.3,
                "detail": content,
            },
            "owner_mapping": {
                "score": 0.1 if has_owner_map else 0.0,
                "max": 0.1,
                "detail": content,
            },
            "next_step": {
                "score": 0.1 if has_next_step else 0.0,
                "max": 0.1,
                "detail": content,
            },
        }
    }
