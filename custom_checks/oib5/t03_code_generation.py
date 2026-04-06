"""T03: 代码生成 — 合并区间 — 评分脚本（v5 接口）"""

from pathlib import Path

from harness.test_exec import has_valid_python_syntax, run_test_file


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    sol_path = ws / "solution.py"
    exists = sol_path.exists()
    checkpoints["file_exists"] = {
        "score": 0.1 if exists else 0.0, "max": 0.1,
        "detail": "solution.py exists" if exists else "file not found",
    }
    if not exists:
        checkpoints["syntax_valid"] = {"score": 0.0, "max": 0.1, "detail": "skipped"}
        checkpoints["tests_pass"] = {"score": 0.0, "max": 0.8, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    syntax_ok = has_valid_python_syntax(sol_path)
    checkpoints["syntax_valid"] = {
        "score": 0.1 if syntax_ok else 0.0, "max": 0.1,
        "detail": "valid syntax" if syntax_ok else "syntax error",
    }
    if not syntax_ok:
        checkpoints["tests_pass"] = {"score": 0.0, "max": 0.8, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    test_path = ws / "test_solution.py"
    if not test_path.exists():
        checkpoints["tests_pass"] = {"score": 0.0, "max": 0.8, "detail": "test file missing"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    passed = _run_tests(ws, test_path)
    total_tests = 10
    score = min(passed / total_tests * 0.8, 0.8)
    checkpoints["tests_pass"] = {
        "score": round(score, 4), "max": 0.8,
        "detail": f"{passed}/{total_tests} tests passed",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def _run_tests(ws: Path, test_path: Path) -> int:
    passed, _ = run_test_file(ws, test_path, timeout_seconds=30)
    return passed


def grade_process(trace: dict) -> float:
    """L1 代码生成：5 步以内满分"""
    tc = trace.get("metrics", {}).get("tool_calls", 0)
    if tc <= 6:
        return 1.0
    if tc <= 12:
        return 1.0 - (tc - 6) * 0.1
    return 0.3
