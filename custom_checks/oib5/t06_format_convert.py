"""T06: JSON→CSV 格式转换 — 评分脚本"""

import csv
from pathlib import Path

EXPECTED_ROWS = 7
EXPECTED_HEADERS = ["id", "name", "category", "price", "in_stock"]


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    out = ws / "data.csv"
    exists = out.exists()
    checkpoints["file_exists"] = {"score": 0.15 if exists else 0.0, "max": 0.15, "detail": "data.csv exists" if exists else "missing"}

    if not exists:
        for k in ("correct_headers", "correct_rows", "price_format", "bool_convert"):
            checkpoints[k] = {"score": 0.0, "max": 0.2, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        rows = list(csv.DictReader(open(out)))
    except Exception:
        rows = []

    headers = list(csv.DictReader(open(out)).fieldnames or [])
    checkpoints["correct_headers"] = {
        "score": 0.2 if headers == EXPECTED_HEADERS else 0.0, "max": 0.2,
        "detail": f"headers={headers}",
    }

    checkpoints["correct_rows"] = {
        "score": 0.2 if len(rows) == EXPECTED_ROWS else 0.0, "max": 0.2,
        "detail": f"{len(rows)} rows (expected {EXPECTED_ROWS})",
    }

    # price 两位小数
    price_ok = True
    for r in rows:
        p = r.get("price", "")
        if "." in p:
            decimals = len(p.split(".")[-1])
            if decimals != 2:
                price_ok = False
                break
    checkpoints["price_format"] = {
        "score": 0.2 if price_ok and rows else 0.0, "max": 0.2,
        "detail": "all 2 decimal places" if price_ok else "price format wrong",
    }

    # in_stock → yes/no
    bool_ok = all(r.get("in_stock", "").lower() in ("yes", "no") for r in rows) if rows else False
    checkpoints["bool_convert"] = {
        "score": 0.25 if bool_ok else 0.0, "max": 0.25,
        "detail": "yes/no format" if bool_ok else "not converted to yes/no",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    tc = trace.get("metrics", {}).get("tool_calls", 0)
    return 1.0 if tc <= 5 else max(0.3, 1.0 - (tc - 5) * 0.1)
