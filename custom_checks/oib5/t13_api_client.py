"""T13: API 客户端生成 — 更严格的契约校验。"""

from __future__ import annotations

import ast
from pathlib import Path

from harness.test_exec import has_valid_python_syntax, summarize_test_file


def _class_and_method_score(tree: ast.AST) -> tuple[float, str]:
    client_classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    if not client_classes:
        return 0.0, "no client class found"
    required = {
        "__init__": ["self", "api_key", "base_url"],
        "get_current": ["self", "city"],
        "get_forecast": ["self", "city", "days"],
        "subscribe_alert": ["self", "city", "threshold", "callback_url"],
    }
    target = max(
        client_classes,
        key=lambda node: sum(
            1
            for child in node.body
            if isinstance(child, ast.FunctionDef) and child.name in required
        ),
    )
    methods = {
        node.name: node
        for node in target.body
        if isinstance(node, ast.FunctionDef)
    }
    matched = 0
    details: list[str] = [f"selected_class={target.name}"]
    for method_name, expected_args in required.items():
        node = methods.get(method_name)
        if node is None:
            details.append(f"{method_name}=missing")
            continue
        arg_names = [arg.arg for arg in node.args.args]
        score_hit = all(any(expected in actual for actual in arg_names) for expected in expected_args)
        if score_hit:
            matched += 1
        details.append(f"{method_name} args={arg_names}")
    return round(matched / len(required) * 0.2, 4), "; ".join(details)


def _client_module_focus_score(tree: ast.AST) -> tuple[float, str]:
    """Client file should contain the client/support code, not an embedded test suite."""
    unittest_imported = False
    test_case_classes: list[str] = []
    has_unittest_main = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "unittest" for alias in node.names):
                unittest_imported = True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "unittest" or node.module == "unittest.mock":
                unittest_imported = True
        elif isinstance(node, ast.ClassDef):
            base_names = {
                getattr(base, "id", None) or getattr(base, "attr", None)
                for base in node.bases
            }
            if node.name.startswith("Test") or "TestCase" in base_names:
                test_case_classes.append(node.name)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "main":
                owner = getattr(func.value, "id", None)
                if owner == "unittest":
                    has_unittest_main = True

    embedded = unittest_imported or bool(test_case_classes) or has_unittest_main
    detail = (
        f"embedded_test_suite imported_unittest={unittest_imported} "
        f"test_classes={test_case_classes} unittest_main={has_unittest_main}"
    )
    return (0.0, detail) if embedded else (0.2, "client module is focused on production code only")


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    client = ws / "weather_client.py"
    if not client.exists():
        for check_id in (
            "client_syntax",
            "client_surface",
            "endpoint_contract",
            "error_handling",
            "tests_exist",
            "tests_pass",
        ):
            checkpoints[check_id] = {"score": 0.0, "max": 0.1, "detail": "weather_client.py missing"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    content = client.read_text(encoding="utf-8")
    syntax_ok = has_valid_python_syntax(client)
    checkpoints["client_syntax"] = {
        "score": 0.1 if syntax_ok else 0.0,
        "max": 0.1,
        "detail": "valid syntax" if syntax_ok else "syntax error",
    }

    surface_score = 0.0
    surface_detail = "syntax error"
    focus_score = 0.0
    focus_detail = "syntax error"
    if syntax_ok:
        tree = ast.parse(content)
        surface_score, surface_detail = _class_and_method_score(tree)
        focus_score, focus_detail = _client_module_focus_score(tree)
    checkpoints["client_surface"] = {
        "score": round(surface_score / 0.2 * 0.15, 4) if surface_score else 0.0,
        "max": 0.15,
        "detail": surface_detail,
    }
    checkpoints["client_module_focus"] = {
        "score": focus_score,
        "max": 0.2,
        "detail": focus_detail,
    }

    contract_tokens = [
        "/current",
        "/forecast",
        "/alert",
        "X-API-Key",
        "city",
        "days",
        "threshold_temp_c",
        "callback_url",
    ]
    contract_hits = sum(1 for token in contract_tokens if token in content)
    checkpoints["endpoint_contract"] = {
        "score": round(contract_hits / len(contract_tokens) * 0.2, 4),
        "max": 0.2,
        "detail": f"{contract_hits}/{len(contract_tokens)} contract tokens found",
    }

    error_tokens = ["400", "401", "404", "429", "raise", "status_code"]
    error_hits = sum(1 for token in error_tokens if token in content)
    checkpoints["error_handling"] = {
        "score": round(min(error_hits / 5, 1.0) * 0.1, 4),
        "max": 0.1,
        "detail": f"{error_hits} error-handling markers found",
    }

    test_file = ws / "test_weather_client.py"
    if test_file.exists():
        try:
            if not has_valid_python_syntax(test_file):
                raise SyntaxError("test syntax error")
            test_summary = summarize_test_file(ws, test_file, timeout_seconds=30)
            checkpoints["tests_exist"] = {
                "score": 0.1 if test_summary.discovered >= 6 else round(min(test_summary.discovered / 6, 1.0) * 0.1, 4),
                "max": 0.1,
                "detail": f"{test_summary.discovered} tests (need >= 6)",
            }
            checkpoints["tests_pass"] = {
                "score": round(min(test_summary.passed / max(test_summary.total, 1), 1.0) * 0.15, 4),
                "max": 0.15,
                "detail": f"{test_summary.passed}/{test_summary.total} passed",
            }
        except Exception as exc:
            checkpoints["tests_exist"] = {"score": 0.0, "max": 0.1, "detail": f"error: {exc}"}
            checkpoints["tests_pass"] = {"score": 0.0, "max": 0.15, "detail": "skipped"}
    else:
        checkpoints["tests_exist"] = {"score": 0.0, "max": 0.1, "detail": "no test file"}
        checkpoints["tests_pass"] = {"score": 0.0, "max": 0.15, "detail": "skipped"}

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    events = trace.get("events", [])
    read_spec = any(e.get("type") == "tool_call" and "spec" in str(e.get("args", {})) for e in events)
    wrote = any(e.get("type") == "tool_call" and e.get("tool") in ("write", "Write") for e in events)
    ran_test = any(e.get("type") == "tool_call" and "test" in str(e.get("args", {}).get("command", "")) for e in events)
    score = 0.2
    if read_spec: score += 0.3
    if wrote: score += 0.25
    if ran_test: score += 0.25
    return min(score, 1.0)
