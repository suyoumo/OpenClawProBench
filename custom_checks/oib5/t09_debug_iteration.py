"""T09: 代码调试迭代 — 更严格的行为与边界校验。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from harness.test_exec import has_valid_python_syntax, summarize_test_file

EXPECTED_TEST_FILE = (
    Path(__file__).resolve().parents[2] / "datasets" / "oib5" / "t09_debug_iteration" / "fixtures" / "test_calculator.py"
).read_text(encoding="utf-8")


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("calculator_eval", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hidden_behavior_score(calc_path: Path) -> tuple[float, str]:
    try:
        module = _load_module(calc_path)
    except Exception as exc:
        return 0.0, f"import failed: {exc}"

    if not hasattr(module, "Calculator"):
        return 0.0, "Calculator missing"

    checks = 0
    passed = 0
    try:
        calc = module.Calculator()

        checks += 1
        subtract_result = calc.subtract(5.5, 2.0)
        if abs(subtract_result - 3.5) < 1e-9 and calc.get_history()[-1] == ("subtract", 5.5, 2.0, subtract_result):
            passed += 1

        checks += 1
        divide_exact = calc.divide(4, 2)
        if divide_exact == 2.0 and isinstance(divide_exact, float):
            passed += 1

        checks += 1
        divide_negative = calc.divide(-9, 2)
        if abs(divide_negative + 4.5) < 1e-9:
            passed += 1

        checks += 1
        history_before_error = list(calc.get_history())
        try:
            calc.divide(10, 0)
            zero_guard = False
        except ValueError:
            zero_guard = True
        if zero_guard and list(calc.get_history()) == history_before_error:
            passed += 1

        checks += 1
        numbers = [1.5, 2.5, 3.0]
        average_result = calc.average(numbers)
        if abs(average_result - (7.0 / 3.0)) < 1e-9 and isinstance(average_result, float) and numbers == [1.5, 2.5, 3.0]:
            passed += 1

        checks += 1
        try:
            calc.average([])
            average_guard = False
        except ValueError:
            average_guard = True
        if average_guard:
            passed += 1

        checks += 1
        calc.add(1, 2)
        calc.clear_history()
        if calc.get_history() == []:
            passed += 1

        checks += 1
        if calc.factorial(1) == 1 and calc.factorial(6) == 720:
            passed += 1

        checks += 1
        calc.add(8, 1)
        history_snapshot = calc.get_history()
        second_snapshot = calc.get_history()
        if history_snapshot is not second_snapshot:
            passed += 1

        checks += 1
        before_mutation = list(calc.get_history())
        leaked_history = calc.get_history()
        if hasattr(leaked_history, "append"):
            leaked_history.append(("tamper", 0, 0, 0))
        if list(calc.get_history()) == before_mutation:
            passed += 1

        # --- additional grounded boundary checks ---

        # power with negative exponent should return float (e.g. 2^-1 = 0.5)
        checks += 1
        calc2 = module.Calculator()
        power_neg = calc2.power(2, -1)
        if abs(power_neg - 0.5) < 1e-9 and isinstance(power_neg, float):
            passed += 1

        # factorial of large number must be exact integer
        checks += 1
        if calc2.factorial(20) == 2432902008176640000:
            passed += 1

        # divide should return float even for non-exact division
        checks += 1
        calc3 = module.Calculator()
        div_result = calc3.divide(7, 3)
        if abs(div_result - 7 / 3) < 1e-9 and isinstance(div_result, float):
            passed += 1

        # failed average([]) should not pollute history
        checks += 1
        calc4 = module.Calculator()
        calc4.add(1, 1)
        history_before_avg = list(calc4.get_history())
        try:
            calc4.average([])
        except (ValueError, ZeroDivisionError):
            pass
        if list(calc4.get_history()) == history_before_avg:
            passed += 1

        # factorial negative should raise ValueError, not pollute history
        checks += 1
        calc5 = module.Calculator()
        calc5.add(5, 5)
        history_before_fact = list(calc5.get_history())
        try:
            calc5.factorial(-3)
        except ValueError:
            pass
        if list(calc5.get_history()) == history_before_fact:
            passed += 1

    except Exception as exc:
        return 0.0, f"behavior error: {exc}"

    return round(passed / checks * 0.35, 4), f"{passed}/{checks} hidden behavior checks"


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    calc_path = ws / "calculator.py"
    test_path = ws / "test_calculator.py"

    if not calc_path.exists():
        for key in ("no_syntax_error", "test_file_unchanged", "tests_pass", "hidden_behavior"):
            checkpoints[key] = {"score": 0.0, "max": {"no_syntax_error": 0.05, "test_file_unchanged": 0.1, "tests_pass": 0.5, "hidden_behavior": 0.35}[key], "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    syntax_ok = has_valid_python_syntax(calc_path)
    checkpoints["no_syntax_error"] = {
        "score": 0.05 if syntax_ok else 0.0, "max": 0.05,
        "detail": "no syntax errors" if syntax_ok else "syntax error",
    }

    test_content = test_path.read_text(encoding="utf-8") if test_path.exists() else ""
    unchanged = test_content == EXPECTED_TEST_FILE
    checkpoints["test_file_unchanged"] = {
        "score": 0.1 if unchanged else 0.0, "max": 0.1,
        "detail": "test file intact" if unchanged else "test file modified",
    }

    if not syntax_ok:
        checkpoints["tests_pass"] = {"score": 0.0, "max": 0.5, "detail": "skipped"}
        checkpoints["hidden_behavior"] = {"score": 0.0, "max": 0.35, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        summary = summarize_test_file(ws, test_path, timeout_seconds=30)
    except Exception as e:
        checkpoints["tests_pass"] = {"score": 0.0, "max": 0.5, "detail": f"error: {e}"}
        checkpoints["hidden_behavior"] = {"score": 0.0, "max": 0.35, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    visible_total = max(summary.total, summary.discovered, 1)
    visible_score = round(min(summary.passed / visible_total, 1.0) * 0.5, 4)
    checkpoints["tests_pass"] = {"score": visible_score, "max": 0.5, "detail": f"{summary.passed}/{visible_total} visible tests passed"}

    hidden_score, hidden_detail = _hidden_behavior_score(calc_path)
    checkpoints["hidden_behavior"] = {"score": hidden_score, "max": 0.35, "detail": hidden_detail}

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    """调试任务：应该先运行测试看哪些失败，再修改代码，再运行测试验证"""
    events = trace.get("events", [])
    exec_count = 0
    for e in events:
        if e.get("type") == "tool_call" and e.get("tool") in ("exec", "Bash", "bash"):
            cmd = e.get("args", {}).get("command", "")
            if "test_calculator" in cmd or "pytest" in cmd or "unittest" in cmd:
                exec_count += 1

    # 至少运行了 2 次测试（修改前 + 修改后）说明有迭代
    if exec_count >= 2:
        return 1.0
    if exec_count == 1:
        return 0.7
    return 0.4
