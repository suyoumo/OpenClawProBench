"""T21: 矛盾信息处理 — 评分脚本（v5 接口）

三个数据源有冲突：
- 价格：299(官方) vs 249(零售) vs 279(评价)
- 库存：150(官方) vs 0(零售) vs 有货(评价)
- 评分：4.5(官方) vs 3.8(零售) vs 4.2(评价)

好的回答应该：以最新数据为准，识别冲突，给出理由。
"""

import json
from pathlib import Path


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    out = ws / "analysis.json"
    exists = out.exists()
    checkpoints["file_exists"] = {
        "score": 0.1 if exists else 0.0, "max": 0.1,
        "detail": "analysis.json exists" if exists else "missing",
    }
    if not exists:
        for k in ("has_structure", "price_reasonable", "conflicts_identified", "has_reasoning"):
            checkpoints[k] = {"score": 0.0, "max": 0.2, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        data = json.loads(out.read_text())
    except Exception:
        for k in ("has_structure", "price_reasonable", "conflicts_identified", "has_reasoning"):
            checkpoints[k] = {"score": 0.0, "max": 0.2, "detail": "invalid JSON"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # 1. 结构正确
    has_price = "price" in data and isinstance(data["price"], dict)
    has_stock = "stock" in data and isinstance(data["stock"], dict)
    has_rating = "rating" in data and isinstance(data["rating"], dict)
    has_conflicts = "conflicts_found" in data and isinstance(data["conflicts_found"], list)
    struct_score = sum([has_price, has_stock, has_rating, has_conflicts])
    checkpoints["has_structure"] = {
        "score": round(struct_score / 4 * 0.2, 4), "max": 0.2,
        "detail": f"{struct_score}/4 fields present",
    }

    # 2. 价格判断合理（应该用最新的，249 或 279 都可以接受）
    price_val = data.get("price", {}).get("value", 0)
    try:
        price_num = float(price_val)
        price_ok = 240 <= price_num <= 290  # 249 或 279 都合理
    except (ValueError, TypeError):
        price_ok = False
    checkpoints["price_reasonable"] = {
        "score": 0.25 if price_ok else 0.0, "max": 0.25,
        "detail": f"price={price_val}" + (" (reasonable)" if price_ok else " (should be 249-279)"),
    }

    # 3. 识别了冲突
    conflicts = data.get("conflicts_found", [])
    conflict_text = " ".join(str(c).lower() for c in conflicts)
    found_price_conflict = any(x in conflict_text for x in ["price", "价格", "299", "249", "279"])
    found_stock_conflict = any(x in conflict_text for x in ["stock", "库存", "out of stock", "有货", "无货"])
    found_rating_conflict = any(x in conflict_text for x in ["rating", "评分", "4.5", "3.8", "4.2"])
    conflict_count = sum([found_price_conflict, found_stock_conflict, found_rating_conflict])
    checkpoints["conflicts_identified"] = {
        "score": round(conflict_count / 3 * 0.25, 4), "max": 0.25,
        "detail": f"{conflict_count}/3 conflicts identified (price={found_price_conflict} stock={found_stock_conflict} rating={found_rating_conflict})",
    }

    # 4. 有推理理由（reason 字段非空）
    reasons = []
    for field in ("price", "stock", "rating"):
        r = data.get(field, {}).get("reason", "")
        if r and len(str(r)) > 5:
            reasons.append(field)
    checkpoints["has_reasoning"] = {
        "score": round(len(reasons) / 3 * 0.2, 4), "max": 0.2,
        "detail": f"{len(reasons)}/3 fields have reasoning",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    """应该读取所有三个文件"""
    events = trace.get("events", [])
    files_read = set()
    for e in events:
        if e.get("type") == "tool_call" and e.get("tool") in ("read", "Read"):
            path = str(e.get("args", {}))
            for name in ("official", "retailer", "reviews"):
                if name in path.lower():
                    files_read.add(name)
    if len(files_read) >= 3:
        return 1.0
    if len(files_read) == 2:
        return 0.6
    return 0.3
