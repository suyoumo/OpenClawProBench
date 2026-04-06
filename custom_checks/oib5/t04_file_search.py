"""T04: 文件搜索与聚合 — 评分脚本（v5 接口）

预期答案：worker.log=5, app.log=3, auth.log=1
"""

import json
from pathlib import Path

EXPECTED = {"worker.log": 5, "app.log": 3, "auth.log": 1}


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    out = ws / "error_summary.json"
    exists = out.exists()
    checkpoints["file_exists"] = {
        "score": 0.15 if exists else 0.0, "max": 0.15,
        "detail": "error_summary.json exists" if exists else "missing",
    }
    if not exists:
        checkpoints["valid_json"] = {"score": 0.0, "max": 0.1, "detail": "skipped"}
        checkpoints["correct_counts"] = {"score": 0.0, "max": 0.5, "detail": "skipped"}
        checkpoints["correct_order"] = {"score": 0.0, "max": 0.25, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        data = json.loads(out.read_text())
        valid = isinstance(data, dict)
    except Exception:
        data, valid = {}, False

    checkpoints["valid_json"] = {
        "score": 0.1 if valid else 0.0, "max": 0.1,
        "detail": "valid JSON dict" if valid else "invalid JSON",
    }
    if not valid:
        checkpoints["correct_counts"] = {"score": 0.0, "max": 0.5, "detail": "skipped"}
        checkpoints["correct_order"] = {"score": 0.0, "max": 0.25, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # 检查计数（允许 key 带或不带路径前缀）
    correct = 0
    for expected_file, expected_count in EXPECTED.items():
        for key, val in data.items():
            if expected_file in key:
                try:
                    if int(val) == expected_count:
                        correct += 1
                except (ValueError, TypeError):
                    pass
                break

    checkpoints["correct_counts"] = {
        "score": round(correct / len(EXPECTED) * 0.5, 4), "max": 0.5,
        "detail": f"{correct}/{len(EXPECTED)} correct",
    }

    # 检查排序（降序）
    values = list(data.values())
    try:
        int_values = [int(v) for v in values]
        sorted_desc = all(int_values[i] >= int_values[i+1] for i in range(len(int_values)-1))
    except (ValueError, TypeError):
        sorted_desc = False

    checkpoints["correct_order"] = {
        "score": 0.25 if sorted_desc and correct == len(EXPECTED) else 0.0, "max": 0.25,
        "detail": "sorted descending" if sorted_desc else "not sorted",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    tc = trace.get("metrics", {}).get("tool_calls", 0)
    if tc <= 6:
        return 1.0
    if tc <= 12:
        return 1.0 - (tc - 6) * 0.1
    return 0.3
