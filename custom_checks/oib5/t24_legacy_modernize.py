"""T24: 遗留代码现代化 — 隐藏行为校验。"""

from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import tempfile
import textwrap
from pathlib import Path
import subprocess
import sys

from harness.test_exec import has_valid_python_syntax, summarize_test_file


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("legacy_app_eval", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hidden_behavior_score(app: Path) -> tuple[float, str]:
    try:
        module = _load_module(app)
    except Exception as exc:
        return 0.0, f"import failed: {exc}"

    checks = 0
    passed = 0
    try:
        inventory = module.Inventory()
        inventory.add_item("Widget", 10.0, 2)
        inventory.add_item("Widget", 99.0, 3)
        inventory.add_item("Cable", 5.0, 1)
        inventory.add_item("Adapter", 2.5, 8)

        checks += 1
        widget = inventory.get_item("Widget")
        if widget is not None and widget.quantity == 5 and round(widget.price, 2) == 10.0:
            passed += 1

        checks += 1
        if round(inventory.total_value(), 2) == 75.0:
            passed += 1

        checks += 1
        low_stock = sorted(item.name for item in inventory.low_stock_items())
        if low_stock == ["Cable"]:
            passed += 1

        checks += 1
        high_threshold = sorted(item.name for item in inventory.low_stock_items(threshold=9))
        if high_threshold == ["Adapter", "Cable"]:
            passed += 1

        checks += 1
        if [item.name for item in inventory.search("wid")] == ["Widget"]:
            passed += 1

        checks += 1
        if [item.name for item in inventory.search("WID")] == ["Widget"]:
            passed += 1

        checks += 1
        if [item.name for item in inventory.search("get")] == ["Widget"]:
            passed += 1

        checks += 1
        search_inventory = module.Inventory()
        search_inventory.add_item("Widget", 10.0, 1)
        search_inventory.add_item("Gadget", 20.0, 1)
        if sorted(item.name for item in search_inventory.search("get")) == ["Gadget", "Widget"]:
            passed += 1

        checks += 1
        inventory.apply_discount("Widget", 15)
        if round(inventory.get_item("Widget").price, 2) == 8.5:
            passed += 1

        checks += 1
        total_before_missing_discount = round(inventory.total_value(), 2)
        try:
            inventory.apply_discount("Missing", 10)
            missing_discount_guard = False
        except Exception:
            missing_discount_guard = True
        if missing_discount_guard and round(inventory.total_value(), 2) == total_before_missing_discount:
            passed += 1

        checks += 1
        adapter = inventory.get_item("Adapter")
        inventory.remove_item("Adapter", 3)
        if adapter is not None and inventory.get_item("Adapter").quantity == 5:
            passed += 1

        checks += 1
        cable_before = inventory.get_item("Cable").quantity
        try:
            inventory.remove_item("Cable", 2)
            stock_guard = False
        except Exception:
            stock_guard = True
        if stock_guard and inventory.get_item("Cable").quantity == cable_before:
            passed += 1

        checks += 1
        inventory.remove_item("Cable", 1)
        if inventory.get_item("Cable") is None:
            passed += 1

        checks += 1
        probe = module.InventoryItem("Probe", 1.25, 4)
        if round(probe.total_value(), 2) == 5.0 and probe.is_low_stock(threshold=5) is True:
            passed += 1

        checks += 1
        report = inventory.generate_report()
        if "Total: $55.00" in report and report.index("Adapter") < report.index("Widget"):
            passed += 1
    except Exception as exc:
        return 0.0, f"behavior error: {exc}"

    return round(passed / checks * 0.4, 4), f"{passed}/{checks} hidden behavior checks"


def _referenced_symbols(test_file: Path) -> set[str]:
    try:
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _test_method_coverage_score(test_file: Path) -> tuple[float, str]:
    required = {
        "Inventory",
        "InventoryItem",
        "add_item",
        "remove_item",
        "get_item",
        "total_value",
        "low_stock_items",
        "search",
        "apply_discount",
        "generate_report",
        "is_low_stock",
    }
    referenced = _referenced_symbols(test_file)
    covered = sum(1 for item in required if item in referenced)
    score = round((covered / len(required)) * 0.05, 4)
    return score, f"{covered}/{len(required)} required symbols referenced"


REFERENCE_MODULE = (
    textwrap.dedent(
        """
        class InventoryItem:
            def __init__(self, name, price, quantity):
                self.name = name
                self.price = price
                self.quantity = quantity

            def __repr__(self):
                return f"InventoryItem({self.name}, {self.price}, {self.quantity})"

            def total_value(self):
                return self.price * self.quantity

            def is_low_stock(self, threshold=5):
                return self.quantity < threshold


        class Inventory:
            def __init__(self):
                self.items = {}

            def add_item(self, name, price, quantity):
                if name in self.items:
                    self.items[name].quantity += quantity
                else:
                    self.items[name] = InventoryItem(name, price, quantity)

            def remove_item(self, name, quantity):
                if name not in self.items:
                    raise Exception(f"Item not found: {name}")
                item = self.items[name]
                if item.quantity < quantity:
                    raise Exception(f"Not enough stock for {name}")
                item.quantity -= quantity
                if item.quantity == 0:
                    del self.items[name]

            def get_item(self, name):
                return self.items.get(name)

            def total_value(self):
                return sum(item.total_value() for item in self.items.values())

            def low_stock_items(self, threshold=5):
                return [item for item in self.items.values() if item.is_low_stock(threshold)]

            def search(self, query):
                return [item for item in self.items.values() if query.lower() in item.name.lower()]

            def apply_discount(self, name, percent):
                if name not in self.items:
                    raise Exception("Item not found")
                item = self.items[name]
                item.price = item.price * (100 - percent) / 100

            def generate_report(self):
                lines = ["=== Inventory Report ==="]
                for name in sorted(self.items):
                    item = self.items[name]
                    lines.append(f"{name}: ${item.price:.2f} x {item.quantity} = ${item.total_value():.2f}")
                lines.append(f"Total: ${self.total_value():.2f}")
                return "\\n".join(lines)
        """
    ).strip()
    + "\n"
)


def _mutate_module(source: str, before: str, after: str) -> str:
    if before not in source:
        raise ValueError(f"mutant anchor not found: {before!r}")
    return source.replace(before, after, 1)


MUTANT_MODULES = (
    _mutate_module(
        REFERENCE_MODULE,
        "            self.items[name].quantity += quantity\n",
        "            self.items[name].quantity += quantity\n            self.items[name].price = price\n",
    ),
    _mutate_module(
        REFERENCE_MODULE,
        "            raise Exception(f\"Not enough stock for {name}\")\n",
        "            item.quantity = 0\n            raise Exception(f\"Not enough stock for {name}\")\n",
    ),
    _mutate_module(
        REFERENCE_MODULE,
        "        return self.quantity < threshold\n",
        "        return self.quantity <= threshold\n",
    ),
    _mutate_module(
        REFERENCE_MODULE,
        "        return [item for item in self.items.values() if query.lower() in item.name.lower()]\n",
        "        return [item for item in self.items.values() if query in item.name]\n",
    ),
    _mutate_module(
        REFERENCE_MODULE,
        "        item.price = item.price * (100 - percent) / 100\n",
        "        item.price = item.price * (100 + percent) / 100\n",
    ),
    _mutate_module(
        REFERENCE_MODULE,
        "        for name in sorted(self.items):\n",
        "        for name in self.items:\n",
    ),
    _mutate_module(
        REFERENCE_MODULE,
        "        if item.quantity < quantity:\n",
        "        if quantity == 0:\n            del self.items[name]\n            return\n        if item.quantity < quantity:\n",
    ),
    _mutate_module(
        REFERENCE_MODULE,
        "        return [item for item in self.items.values() if query.lower() in item.name.lower()]\n",
        "        if query == \"\":\n            return []\n        return [item for item in self.items.values() if query.lower() in item.name.lower()]\n",
    ),
    _mutate_module(
        REFERENCE_MODULE,
        "        lines.append(f\"Total: ${self.total_value():.2f}\")\n",
        "        if self.items:\n            lines.append(f\"Total: ${self.total_value():.2f}\")\n",
    ),
    _mutate_module(
        REFERENCE_MODULE,
        "        return [item for item in self.items.values() if query.lower() in item.name.lower()]\n",
        "        if query == \"\":\n            return list(self.items.values())\n        return [item for item in self.items.values() if item.name.lower().startswith(query.lower())]\n",
    ),
    _mutate_module(
        REFERENCE_MODULE,
        "        return [item for item in self.items.values() if query.lower() in item.name.lower()]\n",
        "        lowered = query.lower()\n        if lowered == \"\":\n            return list(self.items.values())\n        for item in self.items.values():\n            if lowered in item.name.lower():\n                return [item]\n        return []\n",
    ),
)


def _run_tests_against_module_source(test_file: Path, module_source: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir)
        (sandbox / "legacy_app.py").write_text(module_source, encoding="utf-8")
        shutil.copy2(test_file, sandbox / "test_legacy_app.py")
        try:
            summary = summarize_test_file(sandbox, sandbox / "test_legacy_app.py", timeout_seconds=25)
        except Exception as exc:
            return False, f"error: {exc}"
        if summary.total <= 0:
            return False, "mutant run discovered 0 tests"
        killed = summary.passed < summary.total
        return killed, f"{summary.passed}/{summary.total} passed against mutant"


def _test_regression_resistance_score(test_file: Path) -> tuple[float, str]:
    killed = 0
    details: list[str] = []
    for index, mutant in enumerate(MUTANT_MODULES, start=1):
        mutant_killed, detail = _run_tests_against_module_source(test_file, mutant)
        if mutant_killed:
            killed += 1
        details.append(f"m{index}={detail}")
    return round((killed / len(MUTANT_MODULES)) * 0.25, 4), f"{killed}/{len(MUTANT_MODULES)} mutants killed ({'; '.join(details)})"


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    app = ws / "legacy_app.py"
    if not app.exists():
        for check_id, max_score in (
            ("syntax_valid", 0.05),
            ("no_py2_syntax", 0.05),
            ("no_print_stmt", 0.05),
            ("tests_exist", 0.05),
            ("tests_pass", 0.1),
            ("tests_method_coverage", 0.05),
            ("tests_regression_resistance", 0.25),
            ("hidden_behavior", 0.4),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "legacy_app.py missing"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    content = app.read_text(encoding="utf-8")
    syntax_ok = has_valid_python_syntax(app)
    checkpoints["syntax_valid"] = {
        "score": 0.05 if syntax_ok else 0.0,
        "max": 0.05,
        "detail": "valid Python 3" if syntax_ok else "syntax error",
    }

    py2_patterns = [
        r"\.has_key\(",
        r"\.iteritems\(",
        r"\.itervalues\(",
        r"raise\s+\w+\s*,",
        r"print\s+[\"']",
    ]
    py2_found = [pattern for pattern in py2_patterns if re.search(pattern, content)]
    checkpoints["no_py2_syntax"] = {
        "score": 0.05 if not py2_found else 0.0,
        "max": 0.05,
        "detail": "no py2 syntax" if not py2_found else f"py2 remnants: {py2_found}",
    }

    has_print_stmt = bool(re.search(r"^\s*print\s+[^(]", content, re.MULTILINE))
    has_print_call = bool(re.search(r"\bprint\s*\(", content))
    checkpoints["no_print_stmt"] = {
        "score": 0.05 if not has_print_stmt and not has_print_call else 0.0,
        "max": 0.05,
        "detail": "no print usage" if not has_print_stmt and not has_print_call else "print usage still present",
    }

    test_file = ws / "test_legacy_app.py"
    if test_file.exists():
        try:
            if not has_valid_python_syntax(test_file):
                raise SyntaxError("test syntax error")
            test_summary = summarize_test_file(ws, test_file, timeout_seconds=30)
            checkpoints["tests_exist"] = {
                "score": 0.05 if test_summary.discovered >= 10 else round(min(test_summary.discovered / 10, 1.0) * 0.05, 4),
                "max": 0.05,
                "detail": f"{test_summary.discovered} tests (need >= 10)",
            }
            checkpoints["tests_pass"] = {
                "score": round(min(test_summary.passed / max(test_summary.total, 1), 1.0) * 0.1, 4),
                "max": 0.1,
                "detail": f"{test_summary.passed}/{test_summary.total} passed",
            }
            coverage_score, coverage_detail = _test_method_coverage_score(test_file)
            checkpoints["tests_method_coverage"] = {
                "score": coverage_score,
                "max": 0.05,
                "detail": coverage_detail,
            }
            regression_score, regression_detail = _test_regression_resistance_score(test_file)
            checkpoints["tests_regression_resistance"] = {
                "score": regression_score,
                "max": 0.25,
                "detail": regression_detail,
            }
        except Exception as exc:
            checkpoints["tests_exist"] = {"score": 0.0, "max": 0.05, "detail": f"error: {exc}"}
            checkpoints["tests_pass"] = {"score": 0.0, "max": 0.1, "detail": "skipped"}
            checkpoints["tests_method_coverage"] = {"score": 0.0, "max": 0.05, "detail": "skipped"}
            checkpoints["tests_regression_resistance"] = {"score": 0.0, "max": 0.25, "detail": "skipped"}
    else:
        checkpoints["tests_exist"] = {"score": 0.0, "max": 0.05, "detail": "no test file"}
        checkpoints["tests_pass"] = {"score": 0.0, "max": 0.1, "detail": "skipped"}
        checkpoints["tests_method_coverage"] = {"score": 0.0, "max": 0.05, "detail": "skipped"}
        checkpoints["tests_regression_resistance"] = {"score": 0.0, "max": 0.25, "detail": "skipped"}

    behavior_score, behavior_detail = _hidden_behavior_score(app)
    checkpoints["hidden_behavior"] = {
        "score": behavior_score,
        "max": 0.4,
        "detail": behavior_detail,
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    events = trace.get("events", [])
    read_first = False
    wrote = False
    ran_tests = False
    for e in events:
        if e.get("type") == "tool_call":
            tool = e.get("tool", "")
            args = e.get("args", {})
            if tool in ("read", "Read") and not wrote:
                read_first = True
            if tool in ("write", "Write", "edit", "Edit"):
                wrote = True
            cmd = args.get("command", "")
            if "test" in cmd:
                ran_tests = True
    score = 0.3
    if read_first:
        score += 0.3
    if wrote:
        score += 0.2
    if ran_tests:
        score += 0.2
    return min(score, 1.0)
