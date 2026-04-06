from __future__ import annotations

import importlib.util
import ast
import tempfile
import textwrap
import unittest
from pathlib import Path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OIB5CoreHardeningTests(unittest.TestCase):
    def test_t13_client_surface_selects_best_matching_class(self) -> None:
        module = _load_module(Path("custom_checks/oib5/t13_api_client.py"), "t13_surface_hardening")
        tree = ast.parse(
            textwrap.dedent(
                """
                class WeatherAPIError(Exception):
                    def __init__(self, status_code, message):
                        self.status_code = status_code
                        self.message = message


                class WeatherClient:
                    def __init__(self, api_key, base_url):
                        self.api_key = api_key
                        self.base_url = base_url

                    def get_current(self, city):
                        return city

                    def get_forecast(self, city, days):
                        return city, days

                    def subscribe_alert(self, city, threshold, callback_url):
                        return city, threshold, callback_url
                """
            )
        )

        score, detail = module._class_and_method_score(tree)
        self.assertEqual(score, 0.2)
        self.assertIn("selected_class=WeatherClient", detail)

    def test_t13_client_module_focus_penalizes_embedded_test_suite(self) -> None:
        module = _load_module(Path("custom_checks/oib5/t13_api_client.py"), "t13_focus_hardening")
        polluted_tree = ast.parse(
            textwrap.dedent(
                """
                import unittest

                class WeatherClient:
                    def __init__(self, api_key, base_url):
                        self.api_key = api_key
                        self.base_url = base_url

                    def get_current(self, city):
                        return city

                    def get_forecast(self, city, days):
                        return city, days

                    def subscribe_alert(self, city, threshold, callback_url):
                        return city, threshold, callback_url

                class TestWeatherClient(unittest.TestCase):
                    pass
                """
            )
        )

        focus_score, focus_detail = module._client_module_focus_score(polluted_tree)
        self.assertEqual(focus_score, 0.0)
        self.assertIn("embedded_test_suite", focus_detail)

    def test_t09_hidden_behavior_penalizes_state_pollution(self) -> None:
        module = _load_module(Path("custom_checks/oib5/t09_debug_iteration.py"), "t09_hardening")
        good_impl = textwrap.dedent(
            """
            class Calculator:
                def __init__(self):
                    self.history = []

                def add(self, a, b):
                    result = a + b
                    self.history.append(("add", a, b, result))
                    return result

                def subtract(self, a, b):
                    result = a - b
                    self.history.append(("subtract", a, b, result))
                    return result

                def multiply(self, a, b):
                    result = a * b
                    self.history.append(("multiply", a, b, result))
                    return result

                def divide(self, a, b):
                    if b == 0:
                        raise ValueError("division by zero")
                    result = a / b
                    self.history.append(("divide", a, b, result))
                    return float(result)

                def power(self, base, exp):
                    result = base ** exp
                    self.history.append(("power", base, exp, result))
                    return result

                def get_history(self):
                    return list(self.history)

                def clear_history(self):
                    self.history = []

                def average(self, numbers):
                    if not numbers:
                        raise ValueError("empty")
                    return float(sum(numbers) / len(numbers))

                def factorial(self, n):
                    if n < 0:
                        raise ValueError("negative")
                    result = 1
                    for value in range(1, n + 1):
                        result *= value
                    return result
            """
        ).strip() + "\n"
        polluted_impl = textwrap.dedent(
            """
            class Calculator:
                def __init__(self):
                    self.history = []

                def add(self, a, b):
                    result = a + b
                    self.history.append(("add", a, b, result))
                    return result

                def subtract(self, a, b):
                    result = a - b
                    self.history.append(("subtract", a, b, result))
                    return result

                def multiply(self, a, b):
                    result = a * b
                    self.history.append(("multiply", a, b, result))
                    return result

                def divide(self, a, b):
                    if b == 0:
                        self.history.append(("divide", a, b, "error"))
                        raise ValueError("division by zero")
                    result = a / b
                    self.history.append(("divide", a, b, result))
                    return float(result)

                def power(self, base, exp):
                    result = base ** exp
                    self.history.append(("power", base, exp, result))
                    return result

                def get_history(self):
                    return self.history

                def clear_history(self):
                    self.history = []

                def average(self, numbers):
                    if not numbers:
                        raise ValueError("empty")
                    return float(sum(numbers) / len(numbers))

                def factorial(self, n):
                    if n < 0:
                        raise ValueError("negative")
                    result = 1
                    for value in range(1, n + 1):
                        result *= value
                    return result
            """
        ).strip() + "\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            good_path = Path(tmpdir) / "good_calculator.py"
            bad_path = Path(tmpdir) / "bad_calculator.py"
            good_path.write_text(good_impl, encoding="utf-8")
            bad_path.write_text(polluted_impl, encoding="utf-8")

            good_score, _ = module._hidden_behavior_score(good_path)
            bad_score, _ = module._hidden_behavior_score(bad_path)

        self.assertGreater(good_score, bad_score)
        self.assertGreaterEqual(good_score, 0.3)

    def test_t09_hidden_behavior_penalizes_history_aliasing(self) -> None:
        module = _load_module(Path("custom_checks/oib5/t09_debug_iteration.py"), "t09_history_hardening")
        isolated_impl = textwrap.dedent(
            """
            class Calculator:
                def __init__(self):
                    self.history = []

                def add(self, a, b):
                    result = a + b
                    self.history.append(("add", a, b, result))
                    return result

                def subtract(self, a, b):
                    result = a - b
                    self.history.append(("subtract", a, b, result))
                    return result

                def multiply(self, a, b):
                    result = a * b
                    self.history.append(("multiply", a, b, result))
                    return result

                def divide(self, a, b):
                    if b == 0:
                        raise ValueError("division by zero")
                    result = a / b
                    self.history.append(("divide", a, b, result))
                    return float(result)

                def power(self, base, exp):
                    result = base ** exp
                    self.history.append(("power", base, exp, result))
                    return result

                def get_history(self):
                    return list(self.history)

                def clear_history(self):
                    self.history = []

                def average(self, numbers):
                    if not numbers:
                        raise ValueError("empty")
                    return float(sum(numbers) / len(numbers))

                def factorial(self, n):
                    if n < 0:
                        raise ValueError("negative")
                    result = 1
                    for value in range(1, n + 1):
                        result *= value
                    return result
            """
        ).strip() + "\n"
        aliased_impl = isolated_impl.replace("return list(self.history)", "return self.history")

        with tempfile.TemporaryDirectory() as tmpdir:
            good_path = Path(tmpdir) / "good_calculator.py"
            bad_path = Path(tmpdir) / "bad_calculator.py"
            good_path.write_text(isolated_impl, encoding="utf-8")
            bad_path.write_text(aliased_impl, encoding="utf-8")

            good_score, _ = module._hidden_behavior_score(good_path)
            bad_score, _ = module._hidden_behavior_score(bad_path)

        self.assertGreater(good_score, bad_score)

    def test_t24_regression_resistance_distinguishes_strong_and_weak_tests(self) -> None:
        module = _load_module(Path("custom_checks/oib5/t24_legacy_modernize.py"), "t24_hardening")
        weak_tests = textwrap.dedent(
            """
            import unittest
            from legacy_app import Inventory


            class TestLegacy(unittest.TestCase):
                def test_smoke_01(self):
                    self.assertIsNotNone(Inventory())

                def test_smoke_02(self):
                    inventory = Inventory()
                    inventory.add_item("Widget", 10.0, 1)
                    self.assertIsNotNone(inventory.get_item("Widget"))

                def test_smoke_03(self):
                    self.assertTrue(True)

                def test_smoke_04(self):
                    self.assertTrue(True)

                def test_smoke_05(self):
                    self.assertTrue(True)

                def test_smoke_06(self):
                    self.assertTrue(True)

                def test_smoke_07(self):
                    self.assertTrue(True)

                def test_smoke_08(self):
                    self.assertTrue(True)

                def test_smoke_09(self):
                    self.assertTrue(True)

                def test_smoke_10(self):
                    self.assertTrue(True)
            """
        ).strip() + "\n"
        strong_tests = textwrap.dedent(
            """
            import unittest
            from legacy_app import Inventory, InventoryItem


            class TestLegacy(unittest.TestCase):
                def setUp(self):
                    self.inventory = Inventory()
                    self.inventory.add_item("Widget", 10.0, 2)
                    self.inventory.add_item("Cable", 5.0, 1)
                    self.inventory.add_item("Adapter", 2.5, 8)

                def test_add_item_merges_quantity(self):
                    self.inventory.add_item("Widget", 99.0, 3)
                    self.assertEqual(self.inventory.get_item("Widget").quantity, 5)
                    self.assertEqual(self.inventory.get_item("Widget").price, 10.0)

                def test_remove_item_deletes_zero_stock(self):
                    self.inventory.remove_item("Cable", 1)
                    self.assertIsNone(self.inventory.get_item("Cable"))

                def test_remove_item_insufficient_stock_raises(self):
                    with self.assertRaises(Exception):
                        self.inventory.remove_item("Cable", 2)
                    self.assertEqual(self.inventory.get_item("Cable").quantity, 1)

                def test_total_value(self):
                    self.assertAlmostEqual(self.inventory.total_value(), 45.0)

                def test_low_stock_default(self):
                    self.assertEqual([item.name for item in self.inventory.low_stock_items()], ["Cable"])

                def test_low_stock_threshold(self):
                    self.assertEqual(sorted(item.name for item in self.inventory.low_stock_items(threshold=9)), ["Adapter", "Cable"])

                def test_search_case_insensitive(self):
                    self.assertEqual([item.name for item in self.inventory.search("wid")], ["Widget"])

                def test_apply_discount(self):
                    self.inventory.apply_discount("Widget", 10)
                    self.assertAlmostEqual(self.inventory.get_item("Widget").price, 9.0)

                def test_generate_report_sorted(self):
                    report = self.inventory.generate_report()
                    self.assertLess(report.index("Adapter"), report.index("Cable"))

                def test_remove_zero_is_noop(self):
                    before = self.inventory.get_item("Widget").quantity
                    self.inventory.remove_item("Widget", 0)
                    self.assertEqual(self.inventory.get_item("Widget").quantity, before)

                def test_search_empty_returns_all(self):
                    self.assertEqual(
                        sorted(item.name for item in self.inventory.search("")),
                        ["Adapter", "Cable", "Widget"],
                    )

                def test_search_midstring_returns_all_matches(self):
                    self.inventory.add_item("Gadget", 4.0, 1)
                    self.assertEqual(
                        sorted(item.name for item in self.inventory.search("get")),
                        ["Gadget", "Widget"],
                    )

                def test_generate_report_empty_inventory(self):
                    inventory = Inventory()
                    self.assertEqual(
                        inventory.generate_report(),
                        "=== Inventory Report ===\\nTotal: $0.00",
                    )

                def test_inventory_item_helpers(self):
                    item = InventoryItem("Probe", 1.25, 4)
                    self.assertTrue(item.is_low_stock(threshold=5))
                    self.assertAlmostEqual(item.total_value(), 5.0)
            """
        ).strip() + "\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            weak_path = Path(tmpdir) / "weak_tests.py"
            strong_path = Path(tmpdir) / "strong_tests.py"
            weak_path.write_text(weak_tests, encoding="utf-8")
            strong_path.write_text(strong_tests, encoding="utf-8")

            weak_score, _ = module._test_regression_resistance_score(weak_path)
            strong_score, _ = module._test_regression_resistance_score(strong_path)

        self.assertLess(weak_score, strong_score)
        self.assertGreaterEqual(strong_score, 0.16)

    def test_t25_variant_generalization_rejects_hardcoded_pipeline(self) -> None:
        module = _load_module(Path("custom_checks/oib5/t25_etl_pipeline.py"), "t25_hardening")
        hardcoded_etl = textwrap.dedent(
            """
            import csv
            import json
            from pathlib import Path

            output = Path("output")
            output.mkdir(exist_ok=True)
            rows = [
                {"sale_id": "S001", "product_name": "Widget Pro", "region_name": "North America", "amount": "150.00", "date": "2024-03-01"},
                {"sale_id": "S002", "product_name": "Gadget X", "region_name": "Europe", "amount": "89.50", "date": "2024-03-02"},
                {"sale_id": "S003", "product_name": "Widget Pro", "region_name": "North America", "amount": "150.00", "date": "2024-03-01"},
                {"sale_id": "S005", "product_name": "Gadget X", "region_name": "North America", "amount": "200.00", "date": "2024-03-04"},
                {"sale_id": "S006", "product_name": "Widget Pro", "region_name": "Europe", "amount": "75.00", "date": "2024-03-05"},
                {"sale_id": "S007", "product_name": "DataHub", "region_name": "Asia Pacific", "amount": "320.00", "date": "2024-03-05"},
                {"sale_id": "S009", "product_name": "Widget Pro", "region_name": "Europe", "amount": "180.00", "date": "2024-03-07"},
                {"sale_id": "S010", "product_name": "DataHub", "region_name": "North America", "amount": "95.00", "date": "2024-03-08"},
                {"sale_id": "S011", "product_name": "Gadget X", "region_name": "Asia Pacific", "amount": "110.00", "date": "2024-03-08"},
                {"sale_id": "S012", "product_name": "Widget Pro", "region_name": "North America", "amount": "250.00", "date": "2024-03-09"},
                {"sale_id": "S013", "product_name": "DataHub", "region_name": "Europe", "amount": "145.00", "date": "2024-03-10"},
            ]
            with (output / "clean_sales.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["sale_id", "product_name", "region_name", "amount", "date"])
                writer.writeheader()
                writer.writerows(rows)
            (output / "quality_report.json").write_text(json.dumps({
                "total_raw_rows": 15,
                "total_clean_rows": 11,
                "duplicates_removed": 2,
                "nulls_removed": 2,
                "date_format_fixed": 3,
            }), encoding="utf-8")
            """
        ).strip() + "\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            etl_path = Path(tmpdir) / "etl.py"
            etl_path.write_text(hardcoded_etl, encoding="utf-8")

            variant_rows, variant_report, _ = module._run_variant_validation(
                etl_path,
                products_csv=module.VARIANT_PRODUCTS,
                regions_data=module.VARIANT_REGIONS,
                sales_csv=module.VARIANT_SALES,
                expected_rows=module.VARIANT_EXPECTED_ROWS,
                expected_report=module.VARIANT_EXPECTED_REPORT,
            )

        self.assertEqual(variant_rows[0], 0)
        self.assertEqual(variant_report[0], 0)

    def test_t25_edge_variant_rejects_dedupe_before_null_filter(self) -> None:
        module = _load_module(Path("custom_checks/oib5/t25_etl_pipeline.py"), "t25_edge_variant_hardening")
        order_bug_etl = textwrap.dedent(
            """
            import csv
            import json
            from datetime import datetime
            from pathlib import Path


            def normalize_date(raw):
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
                    try:
                        return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
                    except ValueError:
                        continue
                return raw.strip()


            with open("raw_sales.csv", newline="", encoding="utf-8") as handle:
                sales = list(csv.DictReader(handle))
            with open("raw_products.csv", newline="", encoding="utf-8") as handle:
                products = {row["product_id"]: row["product_name"] for row in csv.DictReader(handle)}
            with open("raw_regions.json", encoding="utf-8") as handle:
                regions = json.load(handle)

            seen = set()
            deduped = []
            for row in sales:
                if row["sale_id"] in seen:
                    continue
                seen.add(row["sale_id"])
                deduped.append(row)

            clean_rows = []
            nulls_removed = 0
            date_format_fixed = 0
            for row in deduped:
                if not row["amount"] or not row["amount"].strip():
                    nulls_removed += 1
                    continue
                normalized = normalize_date(row["date"])
                if normalized != row["date"]:
                    date_format_fixed += 1
                clean_rows.append(
                    {
                        "sale_id": row["sale_id"],
                        "product_name": products[row["product_id"]],
                        "region_name": regions[row["region_code"]],
                        "amount": row["amount"],
                        "date": normalized,
                    }
                )

            output = Path("output")
            output.mkdir(exist_ok=True)
            with (output / "clean_sales.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["sale_id", "product_name", "region_name", "amount", "date"])
                writer.writeheader()
                writer.writerows(clean_rows)
            (output / "quality_report.json").write_text(
                json.dumps(
                    {
                        "total_raw_rows": len(sales),
                        "total_clean_rows": len(clean_rows),
                        "duplicates_removed": len(sales) - len(deduped),
                        "nulls_removed": nulls_removed,
                        "date_format_fixed": date_format_fixed,
                    }
                ),
                encoding="utf-8",
            )
            """
        ).strip() + "\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            etl_path = Path(tmpdir) / "etl.py"
            etl_path.write_text(order_bug_etl, encoding="utf-8")

            variant_rows, variant_report, _ = module._run_variant_validation(
                etl_path,
                products_csv=module.EDGE_VARIANT_PRODUCTS,
                regions_data=module.EDGE_VARIANT_REGIONS,
                sales_csv=module.EDGE_VARIANT_SALES,
                expected_rows=module.EDGE_VARIANT_EXPECTED_ROWS,
                expected_report=module.EDGE_VARIANT_EXPECTED_REPORT,
            )

        self.assertLess(variant_rows[0], variant_rows[1])
        self.assertLess(variant_report[0], variant_report[1])

    def test_t25_repeatability_rejects_append_mode_pipeline(self) -> None:
        module = _load_module(Path("custom_checks/oib5/t25_etl_pipeline.py"), "t25_repeatability_hardening")
        append_mode_etl = textwrap.dedent(
            """
            import csv
            import json
            from pathlib import Path


            output = Path("output")
            output.mkdir(exist_ok=True)

            clean_path = output / "clean_sales.csv"
            mode = "a" if clean_path.exists() else "w"
            with clean_path.open(mode, newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                if mode == "w":
                    writer.writerow(["sale_id", "product_name", "region_name", "amount", "date"])
                writer.writerow(["R1", "Repeatable", "Anywhere", "1.00", "2024-01-01"])

            report_path = output / "quality_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "total_raw_rows": 1,
                        "total_clean_rows": 1,
                        "duplicates_removed": 0,
                        "nulls_removed": 0,
                        "date_format_fixed": 0,
                    }
                ),
                encoding="utf-8",
            )
            """
        ).strip() + "\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            etl_path = Path(tmpdir) / "etl.py"
            etl_path.write_text(append_mode_etl, encoding="utf-8")

            ok, detail = module._run_repeatability_validation(
                etl_path,
                products_csv=module.VARIANT_PRODUCTS,
                regions_data=module.VARIANT_REGIONS,
                sales_csv=module.VARIANT_SALES,
            )

        self.assertFalse(ok)
        self.assertIn("changed artifacts", detail)

    def test_t25_stress_variant_penalizes_blank_row_and_placeholder_handling(self) -> None:
        module = _load_module(Path("custom_checks/oib5/t25_etl_pipeline.py"), "t25_stress_variant_hardening")
        order_bug_etl = textwrap.dedent(
            """
            import csv
            import json
            from datetime import datetime
            from pathlib import Path


            def normalize_date(raw):
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
                    try:
                        return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
                    except ValueError:
                        continue
                return raw.strip()


            with open("raw_sales.csv", newline="", encoding="utf-8") as handle:
                sales = list(csv.DictReader(handle))
            with open("raw_products.csv", newline="", encoding="utf-8") as handle:
                products = {row["product_id"]: row["product_name"] for row in csv.DictReader(handle)}
            with open("raw_regions.json", encoding="utf-8") as handle:
                regions = json.load(handle)

            seen = set()
            deduped = []
            for row in sales:
                if row["sale_id"] in seen:
                    continue
                seen.add(row["sale_id"])
                deduped.append(row)

            clean_rows = []
            nulls_removed = 0
            date_format_fixed = 0
            for row in deduped:
                if not row["amount"] or not row["amount"].strip():
                    nulls_removed += 1
                    continue
                normalized = normalize_date(row["date"])
                if normalized != row["date"]:
                    date_format_fixed += 1
                clean_rows.append(
                    {
                        "sale_id": row["sale_id"],
                        "product_name": products[row["product_id"]],
                        "region_name": regions[row["region_code"]],
                        "amount": row["amount"],
                        "date": normalized,
                    }
                )

            output = Path("output")
            output.mkdir(exist_ok=True)
            with (output / "clean_sales.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["sale_id", "product_name", "region_name", "amount", "date"])
                writer.writeheader()
                writer.writerows(clean_rows)
            (output / "quality_report.json").write_text(
                json.dumps(
                    {
                        "total_raw_rows": len(sales),
                        "total_clean_rows": len(clean_rows),
                        "duplicates_removed": len(sales) - len(deduped),
                        "nulls_removed": nulls_removed,
                        "date_format_fixed": date_format_fixed,
                    }
                ),
                encoding="utf-8",
            )
            """
        ).strip() + "\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            etl_path = Path(tmpdir) / "etl.py"
            etl_path.write_text(order_bug_etl, encoding="utf-8")

            variant_rows, variant_report, _ = module._run_variant_validation(
                etl_path,
                products_csv=module.STRESS_VARIANT_PRODUCTS,
                regions_data=module.STRESS_VARIANT_REGIONS,
                sales_csv=module.STRESS_VARIANT_SALES,
                expected_rows=module.STRESS_VARIANT_EXPECTED_ROWS,
                expected_report=module.STRESS_VARIANT_EXPECTED_REPORT,
            )

        self.assertLess(variant_rows[0], variant_rows[1])
        self.assertLess(variant_report[0], variant_report[1])


if __name__ == "__main__":
    unittest.main()
