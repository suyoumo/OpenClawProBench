"""T23: 全栈项目 — TODO API — 评分脚本（v5 接口）"""

import re
from pathlib import Path

from harness.test_exec import first_existing_path, has_valid_python_syntax, summarize_test_file


def _check_endpoints(content: str) -> int:
    count = 0
    patterns = [
        (r"(route.*todos.*GET|\.get\(.*todos)", "GET /todos"),
        (r"(route.*todos.*POST|\.post\(.*todos)", "POST /todos"),
        (r"(route.*todos/<|\.get\(.*todos/\{|\.get\(.*todos/<)", "GET /todos/<id>"),
        (r"(PUT|\.put\()", "PUT"),
        (r"(DELETE|\.delete\()", "DELETE"),
    ]
    for pat, _ in patterns:
        if re.search(pat, content, re.IGNORECASE):
            count += 1
    return count


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    app_file = first_existing_path(ws, ["app.py", "main.py", "server.py", "api.py"], "app.py")
    app_ok = app_file is not None and has_valid_python_syntax(app_file)
    checkpoints["app_exists"] = {
        "score": 0.05 if app_ok else 0.0, "max": 0.05,
        "detail": f"app at {app_file.name}" if app_ok else "no valid app file",
    }

    if app_file:
        content = app_file.read_text()
        ep_count = _check_endpoints(content)
        ep_score = round(ep_count / 5 * 0.2, 4)
        sqlite_used = "sqlite" in content.lower() or "todos.db" in content
        has_404 = "404" in content
        has_400 = "400" in content
        has_created_at = "created_at" in content
        has_priority = "priority" in content
    else:
        content = ""
        ep_count, ep_score, sqlite_used = 0, 0.0, False
        has_404 = has_400 = has_created_at = has_priority = False

    checkpoints["crud_endpoints"] = {"score": ep_score, "max": 0.2, "detail": f"{ep_count}/5 endpoints"}
    checkpoints["sqlite_used"] = {"score": 0.05 if sqlite_used else 0.0, "max": 0.05, "detail": "SQLite" if sqlite_used else "no SQLite"}

    test_file = first_existing_path(ws, ["test_api.py", "test_app.py", "tests.py"], "test_*.py")
    if test_file and has_valid_python_syntax(test_file):
        test_summary = summarize_test_file(ws, test_file, timeout_seconds=30)
        checkpoints["test_count"] = {
            "score": 0.1 if test_summary.discovered >= 8 else round(min(test_summary.discovered / 8, 1.0) * 0.1, 4), "max": 0.1,
            "detail": f"{test_summary.discovered} tests (need >= 8)",
        }
        checkpoints["tests_pass"] = {
            "score": round(min(test_summary.passed / max(test_summary.total, 1) * 0.3, 0.3), 4), "max": 0.3,
            "detail": f"{test_summary.passed}/{test_summary.total} passed",
        }
    else:
        checkpoints["test_count"] = {"score": 0.0, "max": 0.1, "detail": "no test file"}
        checkpoints["tests_pass"] = {"score": 0.0, "max": 0.3, "detail": "no test file"}

    err_score = 0.1 if (has_404 and has_400) else 0.05 if (has_404 or has_400) else 0.0
    checkpoints["error_handling"] = {"score": err_score, "max": 0.1, "detail": f"404={'Y' if has_404 else 'N'} 400={'Y' if has_400 else 'N'}"}

    readme = first_existing_path(ws, ["README.md", "readme.md"])
    readme_ok = False
    if readme is not None:
        try:
            readme_ok = len(readme.read_text(encoding="utf-8", errors="replace").strip()) > 20
        except Exception:
            readme_ok = False
    checkpoints["readme"] = {"score": 0.05 if readme_ok else 0.0, "max": 0.05, "detail": "README exists" if readme_ok else "no README"}

    quality = 0.15 if (has_created_at and has_priority) else 0.08 if (has_created_at or has_priority) else 0.0
    checkpoints["data_model"] = {"score": quality, "max": 0.15, "detail": f"created_at={'Y' if has_created_at else 'N'} priority={'Y' if has_priority else 'N'}"}

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    """L4 全栈：应该先读 spec，再写代码，再写测试，再运行测试"""
    events = trace.get("events", [])
    phases = {"read_spec": False, "write_code": False, "run_test": False}
    for e in events:
        if e.get("type") == "tool_call":
            tool = e.get("tool", "")
            args = e.get("args", {})
            if tool in ("read", "Read") and "spec" in str(args):
                phases["read_spec"] = True
            if tool in ("write", "Write", "edit", "Edit"):
                phases["write_code"] = True
            if tool in ("exec", "Bash", "bash"):
                cmd = args.get("command", "")
                if "test" in cmd or "pytest" in cmd:
                    phases["run_test"] = True

    completed = sum(1 for v in phases.values() if v)
    if completed == 3:
        return 1.0
    if completed == 2:
        return 0.7
    return 0.4
