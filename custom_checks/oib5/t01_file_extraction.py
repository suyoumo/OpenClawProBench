"""T01: 文件内容提取与转换 — 评分脚本（v5 接口）"""

import json
from pathlib import Path

EXPECTED = [
    {"name": "Henry Sun", "department": "Engineering", "salary": 115000, "start_date": "2017-08-30"},
    {"name": "Tina Wei", "department": "Engineering", "salary": 105000, "start_date": "2018-09-25"},
    {"name": "Eva Liu", "department": "Engineering", "salary": 102000, "start_date": "2018-05-03"},
    {"name": "Nathan Ren", "department": "Engineering", "salary": 98000, "start_date": "2018-12-11"},
    {"name": "Alice Wang", "department": "Engineering", "salary": 95000, "start_date": "2021-03-15"},
    {"name": "Kate Xu", "department": "Engineering", "salary": 92000, "start_date": "2019-04-18"},
    {"name": "Wendy Pan", "department": "Engineering", "salary": 91000, "start_date": "2019-06-22"},
    {"name": "Carol Li", "department": "Engineering", "salary": 88000, "start_date": "2019-11-20"},
    {"name": "Quinn He", "department": "Engineering", "salary": 87000, "start_date": "2019-07-09"},
    {"name": "Yuki Tang", "department": "Sales", "salary": 86000, "start_date": "2020-05-10"},
    {"name": "Leo Ma", "department": "Marketing", "salary": 84000, "start_date": "2020-10-05"},
    {"name": "Rachel Jiang", "department": "Marketing", "salary": 82000, "start_date": "2021-01-30"},
    {"name": "Grace Zhao", "department": "Sales", "salary": 81000, "start_date": "2020-03-22"},
]


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    json_path = ws / "high_earners.json"
    file_exists = json_path.exists()
    checkpoints["file_exists"] = {
        "score": 0.2 if file_exists else 0.0, "max": 0.2,
        "detail": "high_earners.json exists" if file_exists else "file not found",
    }

    if not file_exists:
        for key in ("valid_json", "correct_records", "correct_order", "fields_complete"):
            checkpoints[key] = {"score": 0.0, "max": 0.2, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        data = json.loads(json_path.read_text())
        valid = isinstance(data, list)
    except Exception:
        data, valid = None, False

    checkpoints["valid_json"] = {
        "score": 0.2 if valid else 0.0, "max": 0.2,
        "detail": "valid JSON array" if valid else "invalid JSON",
    }
    if not valid:
        for key in ("correct_records", "correct_order", "fields_complete"):
            checkpoints[key] = {"score": 0.0, "max": 0.2, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    expected_names = {e["name"] for e in EXPECTED}
    actual_names = {item.get("name", "") for item in data if isinstance(item, dict)}
    correct = expected_names == actual_names
    checkpoints["correct_records"] = {
        "score": 0.3 if correct else 0.0, "max": 0.3,
        "detail": f"expected {len(EXPECTED)}, got {len(data)}, match={correct}",
    }

    salaries = [item.get("salary", 0) for item in data if isinstance(item, dict)]
    sorted_desc = all(salaries[i] >= salaries[i + 1] for i in range(len(salaries) - 1)) if len(salaries) > 1 else True
    checkpoints["correct_order"] = {
        "score": 0.2 if sorted_desc and len(salaries) == len(EXPECTED) else 0.0, "max": 0.2,
        "detail": "sorted descending" if sorted_desc else "not sorted",
    }

    required = {"name", "department", "salary", "start_date"}
    all_fields = all(required.issubset(item.keys()) for item in data if isinstance(item, dict))
    checkpoints["fields_complete"] = {
        "score": 0.1 if all_fields else 0.0, "max": 0.1,
        "detail": "all fields present" if all_fields else "missing fields",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    """L1 任务：3 步以内满分，超过 6 步开始扣分"""
    tool_calls = trace.get("metrics", {}).get("tool_calls", 0)
    if tool_calls <= 5:
        return 1.0
    if tool_calls <= 10:
        return 1.0 - (tool_calls - 5) * 0.1
    return 0.3
