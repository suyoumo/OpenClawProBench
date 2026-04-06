"""T12: 日志分析与报告生成 — 评分脚本

预期：20 lines, INFO=6, WARN=5, ERROR=9
Services: PaymentService=3, UserService=2, OrderService=2, EmailService=1, AuthService=1
"""

import json
import re
from pathlib import Path


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    # 1. error_report.md 存在且有内容
    report = ws / "error_report.md"
    report_ok = report.exists() and len(report.read_text().strip()) > 50
    checkpoints["report_exists"] = {
        "score": 0.1 if report_ok else 0.0, "max": 0.1,
        "detail": "error_report.md exists" if report_ok else "missing or empty",
    }

    # 2. report 按服务分组
    if report_ok:
        content = report.read_text()
        services_mentioned = sum(1 for s in ["PaymentService", "UserService", "OrderService", "EmailService", "AuthService"]
                                 if s in content)
        checkpoints["report_grouped"] = {
            "score": round(services_mentioned / 5 * 0.15, 4), "max": 0.15,
            "detail": f"{services_mentioned}/5 services in report",
        }
    else:
        checkpoints["report_grouped"] = {"score": 0.0, "max": 0.15, "detail": "skipped"}

    # 3. metrics.json
    metrics_path = ws / "metrics.json"
    if not metrics_path.exists():
        for k in ("total_lines", "by_level", "error_services", "has_warnings"):
            checkpoints[k] = {"score": 0.0, "max": 0.15, "detail": "metrics.json missing"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        data = json.loads(metrics_path.read_text())
    except Exception:
        for k in ("total_lines", "by_level", "error_services", "has_warnings"):
            checkpoints[k] = {"score": 0.0, "max": 0.15, "detail": "invalid JSON"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # total_lines
    total = data.get("total_lines", 0)
    checkpoints["total_lines"] = {
        "score": 0.15 if int(total) == 20 else 0.0, "max": 0.15,
        "detail": f"total={total} (expected 20)",
    }

    # by_level
    levels = data.get("by_level", {})
    level_ok = (int(levels.get("INFO", 0)) == 6 and
                int(levels.get("WARN", 0)) == 5 and
                int(levels.get("ERROR", 0)) == 9)
    checkpoints["by_level"] = {
        "score": 0.2 if level_ok else 0.0, "max": 0.2,
        "detail": f"INFO={levels.get('INFO')} WARN={levels.get('WARN')} ERROR={levels.get('ERROR')}",
    }

    # error_services
    svc = data.get("error_services", {})
    expected_svc = {"PaymentService": 3, "UserService": 2, "OrderService": 2, "EmailService": 1, "AuthService": 1}
    svc_correct = sum(1 for k, v in expected_svc.items() if int(svc.get(k, 0)) == v)
    checkpoints["error_services"] = {
        "score": round(svc_correct / len(expected_svc) * 0.2, 4), "max": 0.2,
        "detail": f"{svc_correct}/{len(expected_svc)} services correct",
    }

    # warnings list
    warnings = data.get("warnings", [])
    checkpoints["has_warnings"] = {
        "score": 0.2 if len(warnings) >= 4 else round(min(len(warnings), 5) / 5 * 0.2, 4), "max": 0.2,
        "detail": f"{len(warnings)} warnings listed",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    tc = trace.get("metrics", {}).get("tool_calls", 0)
    if tc <= 8:
        return 1.0
    if tc <= 15:
        return 1.0 - (tc - 8) * 0.08
    return 0.3
