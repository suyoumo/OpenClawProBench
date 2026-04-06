"""T02: Shell 命令执行与输出解析 — 评分脚本（v5 接口）"""

import re
from pathlib import Path

EXPECTED_TOTAL = 119
EXPECTED_LARGEST = "handlers.py"
EXPECTED_LARGEST_LINES = 21
EXPECTED_IMPORT_COUNT = 7


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    stats_path = ws / "stats.txt"
    file_exists = stats_path.exists()
    checkpoints["file_exists"] = {
        "score": 0.1 if file_exists else 0.0, "max": 0.1,
        "detail": "stats.txt exists" if file_exists else "file not found",
    }
    if not file_exists:
        for key in ("total_lines", "largest_file", "import_count"):
            checkpoints[key] = {"score": 0.0, "max": 0.3, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    content = stats_path.read_text()

    m = re.search(r"total_lines:\s*(\d+)", content)
    actual_total = int(m.group(1)) if m else None
    total_ok = actual_total is not None and abs(actual_total - EXPECTED_TOTAL) <= 2
    checkpoints["total_lines"] = {
        "score": 0.3 if total_ok else 0.0, "max": 0.3,
        "detail": f"expected ~{EXPECTED_TOTAL}, got {actual_total}",
    }

    m_name = re.search(r"largest_file:\s*(\S+)", content)
    m_lines = re.search(r"largest_file_lines:\s*(\d+)", content)
    actual_name = m_name.group(1) if m_name else None
    actual_lines = int(m_lines.group(1)) if m_lines else None
    largest_ok = actual_name == EXPECTED_LARGEST and actual_lines is not None and abs(actual_lines - EXPECTED_LARGEST_LINES) <= 1
    checkpoints["largest_file"] = {
        "score": 0.3 if largest_ok else 0.0, "max": 0.3,
        "detail": f"expected {EXPECTED_LARGEST}({EXPECTED_LARGEST_LINES}), got {actual_name}({actual_lines})",
    }

    m = re.search(r"files_with_imports:\s*(\d+)", content)
    actual_imports = int(m.group(1)) if m else None
    checkpoints["import_count"] = {
        "score": 0.3 if actual_imports == EXPECTED_IMPORT_COUNT else 0.0, "max": 0.3,
        "detail": f"expected {EXPECTED_IMPORT_COUNT}, got {actual_imports}",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    tc = trace.get("metrics", {}).get("tool_calls", 0)
    if tc <= 6:
        return 1.0
    if tc <= 12:
        return 1.0 - (tc - 6) * 0.1
    return 0.3
