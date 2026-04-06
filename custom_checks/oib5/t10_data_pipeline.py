"""T10: 数据分析管道 — 评分脚本（v5 接口）

预期答案（去重 by order_id，跳过空 amount）：
- User LTV: Eva=1478, Alice=1378, Carol=1361, David=1053, Bob=487
- Category: Electronics=4083, Furniture=1600, Stationery=74
- Monthly: 2024-01=3, 2024-02=5, 2024-03=7
"""

import csv
import json
from pathlib import Path

EXPECTED_LTV = {5: 1478, 1: 1378, 3: 1361, 4: 1053, 2: 487}
EXPECTED_LTV_ORDER = [5, 1, 3, 4, 2]
EXPECTED_CATEGORY = {"Electronics": 4083, "Furniture": 1600, "Stationery": 74}
EXPECTED_MONTHLY = {"2024-01": 3, "2024-02": 5, "2024-03": 7}


def _parse_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    analysis_exists = (ws / "analysis.py").exists()
    checkpoints["analysis_exists"] = {
        "score": 0.05 if analysis_exists else 0.0, "max": 0.05,
        "detail": "analysis.py exists" if analysis_exists else "missing",
    }

    # user_ltv.csv
    ltv_rows = _parse_csv(ws / "user_ltv.csv")
    ltv_score, ltv_detail = _check_ltv(ltv_rows)
    checkpoints["user_ltv"] = {"score": ltv_score, "max": 0.25, "detail": ltv_detail}

    # category_sales.json
    cat_score, cat_detail = _check_category(ws / "category_sales.json")
    checkpoints["category_sales"] = {"score": cat_score, "max": 0.25, "detail": cat_detail}

    # monthly_orders.csv
    monthly_rows = _parse_csv(ws / "monthly_orders.csv")
    monthly_score, monthly_detail = _check_monthly(monthly_rows)
    checkpoints["monthly_orders"] = {"score": monthly_score, "max": 0.25, "detail": monthly_detail}

    cleaning_ok = ltv_score >= 0.18 and cat_score >= 0.15
    checkpoints["data_cleaning"] = {
        "score": 0.2 if cleaning_ok else 0.0, "max": 0.2,
        "detail": "dedup and null handling correct" if cleaning_ok else "data cleaning issues",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def _check_ltv(rows):
    if not rows:
        return 0.0, "user_ltv.csv missing or empty"
    correct = 0
    for row in rows:
        uid = _get_int(row, ("user_id", "id"))
        amt = _get_int(row, ("total_amount", "amount", "ltv", "total"))
        if uid and amt and EXPECTED_LTV.get(uid) == amt:
            correct += 1
    uids = [_get_int(row, ("user_id", "id")) for row in rows]
    order_ok = uids == EXPECTED_LTV_ORDER
    if correct == len(EXPECTED_LTV) and order_ok:
        return 0.25, "all correct and sorted"
    if correct == len(EXPECTED_LTV):
        return 0.18, "values correct, order wrong"
    if correct >= 3:
        return 0.12, f"{correct}/{len(EXPECTED_LTV)} correct"
    return 0.0, f"only {correct}/{len(EXPECTED_LTV)} correct"


def _check_category(path):
    if not path.exists():
        return 0.0, "category_sales.json missing"
    try:
        data = json.loads(path.read_text())
        correct = sum(1 for cat, exp in EXPECTED_CATEGORY.items()
                      if cat in data and round(float(data[cat])) == exp)
        if correct == len(EXPECTED_CATEGORY):
            return 0.25, "all correct"
        if correct >= 2:
            return 0.15, f"{correct}/{len(EXPECTED_CATEGORY)} correct"
        return 0.0, f"only {correct}/{len(EXPECTED_CATEGORY)} correct"
    except Exception as e:
        return 0.0, f"parse error: {e}"


def _check_monthly(rows):
    if not rows:
        return 0.0, "monthly_orders.csv missing or empty"
    correct = 0
    for row in rows:
        month = row.get("month", "")
        count = _get_int(row, ("order_count", "count", "orders"))
        if month in EXPECTED_MONTHLY and count == EXPECTED_MONTHLY[month]:
            correct += 1
    months = [row.get("month", "") for row in rows]
    sorted_ok = months == sorted(months)
    if correct == len(EXPECTED_MONTHLY) and sorted_ok:
        return 0.25, "all correct and sorted"
    if correct == len(EXPECTED_MONTHLY):
        return 0.18, "counts correct, order wrong"
    if correct >= 2:
        return 0.12, f"{correct}/{len(EXPECTED_MONTHLY)} correct"
    return 0.0, f"only {correct}/{len(EXPECTED_MONTHLY)} correct"


def _get_int(row, keys):
    for k in keys:
        if k in row:
            try:
                return round(float(row[k]))
            except (ValueError, TypeError):
                pass
    return None


def grade_process(trace: dict) -> float:
    """数据管道：应该先探索数据再写代码"""
    tc = trace.get("metrics", {}).get("tool_calls", 0)
    if tc <= 10:
        return 1.0
    if tc <= 20:
        return 1.0 - (tc - 10) * 0.05
    return 0.3
