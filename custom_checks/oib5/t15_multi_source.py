"""T15: 多源信息整合 — 评分脚本（v5 接口）

三个信息源有时间差和冲突：
- project_status.txt: 迁移 70%，预计 3/18
- team_chat.txt: 迁移 85%，预计周一完成（更新）
- email_from_boss.txt: 要求周二前完成

好的周报应该用最新数据（chat），而不是过时的（status report）。
"""

import re
from pathlib import Path


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    report_path = ws / "weekly_report.md"
    exists = report_path.exists()
    checkpoints["file_exists"] = {
        "score": 0.1 if exists else 0.0, "max": 0.1,
        "detail": "weekly_report.md exists" if exists else "missing",
    }

    if not exists:
        for key in ("has_sections", "uses_all_sources", "uses_latest_data", "mentions_risks"):
            checkpoints[key] = {"score": 0.0, "max": 0.2, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    content = report_path.read_text().lower()

    # 1. 有三个必要章节（进度、风险、计划）
    has_progress = bool(re.search(r"(进度|progress|status)", content))
    has_risk = bool(re.search(r"(风险|risk)", content))
    has_plan = bool(re.search(r"(计划|plan|下周|next)", content))
    sections = sum([has_progress, has_risk, has_plan])
    checkpoints["has_sections"] = {
        "score": round(sections / 3 * 0.2, 4), "max": 0.2,
        "detail": f"{sections}/3 sections (progress={has_progress} risk={has_risk} plan={has_plan})",
    }

    # 2. 使用了所有三个源的信息
    from_email = bool(re.search(r"(客户演示|200ms|80%|周二|boss|老板)", content))
    from_status = bool(re.search(r"(alpha|phoenix|350ms|180ms|72%)", content))
    from_chat = bool(re.search(r"(索引|85%|76%|195ms|280ms|缓存|cdn|供应商)", content))
    sources = sum([from_email, from_status, from_chat])
    checkpoints["uses_all_sources"] = {
        "score": round(sources / 3 * 0.25, 4), "max": 0.25,
        "detail": f"{sources}/3 sources (email={from_email} status={from_status} chat={from_chat})",
    }

    # 3. 使用了最新数据（chat 中的 85% 而不是 status 中的 70%）
    uses_latest = bool(re.search(r"85%", content)) or bool(re.search(r"周一|monday", content))
    checkpoints["uses_latest_data"] = {
        "score": 0.25 if uses_latest else 0.0, "max": 0.25,
        "detail": "uses latest migration data (85%)" if uses_latest else "may be using stale data",
    }

    # 4. 提到了关键风险
    risk_keywords = ["支付", "payment", "超时", "timeout", "人手", "前端", "演示", "demo"]
    risk_count = sum(1 for kw in risk_keywords if kw in content)
    checkpoints["mentions_risks"] = {
        "score": round(min(risk_count / 3, 1.0) * 0.2, 4), "max": 0.2,
        "detail": f"{risk_count} risk keywords found",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    """应该读取所有三个文件"""
    events = trace.get("events", [])
    files_read = set()
    for e in events:
        if e.get("type") == "tool_call" and e.get("tool") in ("read", "Read"):
            path = str(e.get("args", {}).get("file_path", e.get("args", {}).get("path", "")))
            for name in ("email", "project", "team", "chat", "status"):
                if name in path.lower():
                    files_read.add(name)
    if len(files_read) >= 3:
        return 1.0
    if len(files_read) == 2:
        return 0.7
    if len(files_read) == 1:
        return 0.4
    return 0.2
