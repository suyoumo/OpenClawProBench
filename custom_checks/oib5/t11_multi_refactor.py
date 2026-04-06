"""T11: 多文件重构 — 提取公共函数 — 更严格的隐藏校验。"""

from __future__ import annotations

import ast
import importlib
import os
import sys
from pathlib import Path


def _import_workspace_modules(workspace: Path):
    old_cwd = Path.cwd()
    sys.path.insert(0, str(workspace))
    os.chdir(workspace)
    try:
        for name in ("common", "user_manager", "order_manager"):
            sys.modules.pop(name, None)
        common = importlib.import_module("common")
        user_manager = importlib.import_module("user_manager")
        order_manager = importlib.import_module("order_manager")
        return common, user_manager, order_manager
    finally:
        os.chdir(old_cwd)
        if sys.path and sys.path[0] == str(workspace):
            sys.path.pop(0)


def _behavior_score(workspace: Path) -> tuple[float, str]:
    try:
        _common, user_manager, order_manager = _import_workspace_modules(workspace)
    except Exception as exc:
        return 0.0, f"import failed: {exc}"

    checks = 0
    passed = 0

    sample_users = [
        {"id": 1, "name": "Ada", "email": "ada@example.com"},
        {"id": 2, "name": "Bob", "email": "bob@example.com"},
    ]
    checks += 1
    try:
        user_manager.save_users(sample_users)
        loaded_users = user_manager.load_users()
        if loaded_users == sample_users:
            passed += 1
    except Exception:
        pass

    checks += 1
    try:
        found_user = user_manager.find_user(sample_users, 2)
        if found_user == sample_users[1]:
            passed += 1
    except Exception:
        pass

    checks += 1
    try:
        if user_manager.validate_email("qa@example.com") and not user_manager.validate_email("broken-email"):
            passed += 1
    except Exception:
        pass

    sample_orders = [
        {"id": "O-1", "amount": 20},
        {"id": "O-2", "amount": 55},
    ]
    checks += 1
    try:
        order_manager.save_orders(sample_orders)
        loaded_orders = order_manager.load_orders()
        if loaded_orders == sample_orders:
            passed += 1
    except Exception:
        pass

    checks += 1
    try:
        found_order = order_manager.find_order(sample_orders, "O-1")
        if found_order == sample_orders[0]:
            passed += 1
    except Exception:
        pass

    checks += 1
    try:
        if order_manager.validate_amount(10) and not order_manager.validate_amount(0):
            passed += 1
    except Exception:
        pass

    return round(passed / checks * 0.3, 4), f"{passed}/{checks} hidden behavior checks"


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    common = ws / "common.py"
    common_ok = False
    if common.exists():
        try:
            ast.parse(common.read_text(encoding="utf-8"))
            common_ok = True
        except SyntaxError:
            pass
    checkpoints["common_exists"] = {
        "score": 0.1 if common_ok else 0.0,
        "max": 0.1,
        "detail": "common.py valid" if common_ok else "common.py missing or syntax error",
    }

    has_funcs = 0
    common_content = common.read_text(encoding="utf-8") if common_ok else ""
    for func in ("load_json", "save_json", "find_by_id"):
        if f"def {func}" in common_content:
            has_funcs += 1
    checkpoints["common_functions"] = {
        "score": round(has_funcs / 3 * 0.15, 4),
        "max": 0.15,
        "detail": f"{has_funcs}/3 helpers present",
    }

    um = ws / "user_manager.py"
    om = ws / "order_manager.py"
    um_content = um.read_text(encoding="utf-8") if um.exists() else ""
    om_content = om.read_text(encoding="utf-8") if om.exists() else ""
    um_imports_common = "from common import" in um_content or "import common" in um_content
    om_imports_common = "from common import" in om_content or "import common" in om_content
    checkpoints["user_manager_refactored"] = {
        "score": 0.1 if um_imports_common else 0.0,
        "max": 0.1,
        "detail": f"imports_common={um_imports_common}",
    }
    checkpoints["order_manager_refactored"] = {
        "score": 0.1 if om_imports_common else 0.0,
        "max": 0.1,
        "detail": f"imports_common={om_imports_common}",
    }

    um_has_validate = "def validate_email" in um_content
    om_has_validate = "def validate_amount" in om_content
    checkpoints["validates_preserved"] = {
        "score": 0.1 if um_has_validate and om_has_validate else 0.0,
        "max": 0.1,
        "detail": f"validate_email={um_has_validate} validate_amount={om_has_validate}",
    }

    inline_json_refs = sum(
        1
        for content in (um_content, om_content)
        if "json.load(" in content or "json.dump(" in content
    )
    dedup_score = 0.15 if inline_json_refs == 0 and um_imports_common and om_imports_common else 0.0
    checkpoints["dedup_achieved"] = {
        "score": dedup_score,
        "max": 0.15,
        "detail": "shared helpers used" if dedup_score else f"inline json refs={inline_json_refs}",
    }

    behavior_score, behavior_detail = _behavior_score(ws)
    checkpoints["hidden_behavior"] = {
        "score": behavior_score,
        "max": 0.3,
        "detail": behavior_detail,
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    """应该先读两个文件，再创建 common，再修改两个文件"""
    events = trace.get("events", [])
    read_count = 0
    write_count = 0
    for e in events:
        if e.get("type") == "tool_call":
            tool = e.get("tool", "")
            if tool in ("read", "Read"):
                read_count += 1
            if tool in ("write", "Write", "edit", "Edit"):
                write_count += 1
    if read_count >= 2 and write_count >= 3:
        return 1.0
    if read_count >= 1 and write_count >= 2:
        return 0.7
    return 0.4
