"""T08: 文本处理 — 日志分析 — 评分脚本

预期：12 requests, 200→8, 201→1, 403→1, 404→1, 500→1
top_ips: 192.168.1.100→5, 10.0.0.50→4, 172.16.0.1→3
errors: 3 lines (404, 403, 500)
"""

import json
from pathlib import Path


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    out = ws / "report.json"
    exists = out.exists()
    checkpoints["file_exists"] = {"score": 0.1 if exists else 0.0, "max": 0.1, "detail": "report.json" if exists else "missing"}

    if not exists:
        for k in ("total_correct", "status_codes", "top_ips", "errors"):
            checkpoints[k] = {"score": 0.0, "max": 0.2, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        data = json.loads(out.read_text())
    except Exception:
        for k in ("total_correct", "status_codes", "top_ips", "errors"):
            checkpoints[k] = {"score": 0.0, "max": 0.2, "detail": "invalid JSON"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # total
    total = data.get("total_requests", 0)
    checkpoints["total_correct"] = {
        "score": 0.2 if int(total) == 12 else 0.0, "max": 0.2,
        "detail": f"total={total} (expected 12)",
    }

    # status codes
    codes = data.get("status_codes", {})
    expected_codes = {"200": 8, "201": 1, "403": 1, "404": 1, "500": 1}
    code_correct = sum(1 for k, v in expected_codes.items() if int(codes.get(k, codes.get(int(k), 0))) == v)
    checkpoints["status_codes"] = {
        "score": round(code_correct / len(expected_codes) * 0.25, 4), "max": 0.25,
        "detail": f"{code_correct}/{len(expected_codes)} codes correct",
    }

    # top ips
    top_ips = data.get("top_ips", [])
    ip_ok = False
    if top_ips and isinstance(top_ips, list) and len(top_ips) >= 3:
        first = top_ips[0]
        if isinstance(first, dict):
            ip_ok = first.get("ip") == "192.168.1.100" and int(first.get("count", 0)) == 5
        elif isinstance(first, list):
            ip_ok = first[0] == "192.168.1.100"
    checkpoints["top_ips"] = {
        "score": 0.25 if ip_ok else 0.0, "max": 0.25,
        "detail": "top IP correct and sorted" if ip_ok else f"top_ips issue: {top_ips[:1]}",
    }

    # errors
    errors = data.get("error_requests", [])
    checkpoints["errors"] = {
        "score": 0.2 if len(errors) == 3 else round(min(len(errors), 3) / 3 * 0.2, 4), "max": 0.2,
        "detail": f"{len(errors)} error lines (expected 3)",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    tc = trace.get("metrics", {}).get("tool_calls", 0)
    return 1.0 if tc <= 5 else max(0.3, 1.0 - (tc - 5) * 0.1)
