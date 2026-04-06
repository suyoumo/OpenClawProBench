"""T25: ETL 数据管道 — 必须可复跑且输出精确。"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED_REPORT = {
    "total_raw_rows": 15,
    "total_clean_rows": 11,
    "duplicates_removed": 2,
    "nulls_removed": 2,
    "date_format_fixed": 3,
}
EXPECTED_ROWS = {
    "S001": ("Widget Pro", "North America", "150.00", "2024-03-01"),
    "S002": ("Gadget X", "Europe", "89.50", "2024-03-02"),
    "S003": ("Widget Pro", "North America", "150.00", "2024-03-01"),
    "S005": ("Gadget X", "North America", "200.00", "2024-03-04"),
    "S006": ("Widget Pro", "Europe", "75.00", "2024-03-05"),
    "S007": ("DataHub", "Asia Pacific", "320.00", "2024-03-05"),
    "S009": ("Widget Pro", "Europe", "180.00", "2024-03-07"),
    "S010": ("DataHub", "North America", "95.00", "2024-03-08"),
    "S011": ("Gadget X", "Asia Pacific", "110.00", "2024-03-08"),
    "S012": ("Widget Pro", "North America", "250.00", "2024-03-09"),
    "S013": ("DataHub", "Europe", "145.00", "2024-03-10"),
}
VARIANT_PRODUCTS = """product_id,product_name,category
Q01,Atlas Lens,Hardware
Q02,Nimbus Cable,Accessories
Q03,Delta Cloud,Software
"""
VARIANT_REGIONS = {"Z1": "Latin America", "Z2": "EMEA", "Z3": "Oceania"}
VARIANT_SALES = """sale_id,product_id,region_code,amount,date
V001,Q01,Z1,10.00,2024-04-01
V002,Q02,Z2,20.50,04/02/2024
V003,Q03,Z1,,2024-04-03
V004,Q03,Z3,18.75,2024-04-04
V001,Q01,Z1,10.00,2024-04-01
V005,Q02,Z1,5.00,04/05/2024
V006,Q01,Z2,7.25,2024-04-06
"""
VARIANT_EXPECTED_REPORT = {
    "total_raw_rows": 7,
    "total_clean_rows": 5,
    "duplicates_removed": 1,
    "nulls_removed": 1,
    "date_format_fixed": 2,
}
VARIANT_EXPECTED_ROWS = {
    "V001": ("Atlas Lens", "Latin America", "10.00", "2024-04-01"),
    "V002": ("Nimbus Cable", "EMEA", "20.50", "2024-04-02"),
    "V004": ("Delta Cloud", "Oceania", "18.75", "2024-04-04"),
    "V005": ("Nimbus Cable", "Latin America", "5.00", "2024-04-05"),
    "V006": ("Atlas Lens", "EMEA", "7.25", "2024-04-06"),
}
EDGE_VARIANT_PRODUCTS = """product_id,product_name,category
N01,Orbit Sensor,Hardware
N02,Vector Desk,Furniture
N03,Helix Suite,Software
"""
EDGE_VARIANT_REGIONS = {"Y1": "Americas", "Y2": "EMEA", "Y3": "APAC"}
EDGE_VARIANT_SALES = """sale_id,product_id,region_code,amount,date
E001,N01,Y1,,2024-05-01
E001,N01,Y1,12.00,2024-05-01
E002,N02,Y2,8.50,05/02/2024
E002,N02,Y2,8.50,05/02/2024
E003,N03,Y3,   ,2024/05/03
E003,N03,Y3,9.00,2024/05/03
E004,N02,Y1,0.00,2024-05-04
E005,N03,Y3,7.25,2024-05-05
"""
EDGE_VARIANT_EXPECTED_REPORT = {
    "total_raw_rows": 8,
    "total_clean_rows": 5,
    "duplicates_removed": 1,
    "nulls_removed": 2,
    "date_format_fixed": 2,
}
EDGE_VARIANT_EXPECTED_ROWS = {
    "E001": ("Orbit Sensor", "Americas", "12.00", "2024-05-01"),
    "E002": ("Vector Desk", "EMEA", "8.50", "2024-05-02"),
    "E003": ("Helix Suite", "APAC", "9.00", "2024-05-03"),
    "E004": ("Vector Desk", "Americas", "0.00", "2024-05-04"),
    "E005": ("Helix Suite", "APAC", "7.25", "2024-05-05"),
}
STRESS_VARIANT_PRODUCTS = """product_id,product_name,category
R01,Pulse Hub,Hardware
R02,Signal Dock,Accessories
R03,Echo Board,Software
"""
STRESS_VARIANT_REGIONS = {"X1": "US Central", "X2": "Western Europe", "X3": "Southeast Asia"}
STRESS_VARIANT_SALES = """sale_id,product_id,region_code,amount,date
T001,R01,X1,,2024-06-01
T001,R01,X1,14.20,2024-06-01
T002,R02,X2,8.00,06/02/2024
T002,R02,X2,8.00,06/02/2024
 , , , ,
T003,R03,X3,11.50,2024/06/03
T004,R01,X1,0.00,2024-06-04
T005,R03,X2,,06/05/2024
T006,R02,X1,5.75,2024/06/06
"""
STRESS_VARIANT_EXPECTED_REPORT = {
    "total_raw_rows": 9,
    "total_clean_rows": 5,
    "duplicates_removed": 1,
    "nulls_removed": 3,
    "date_format_fixed": 3,
}
STRESS_VARIANT_EXPECTED_ROWS = {
    "T001": ("Pulse Hub", "US Central", "14.20", "2024-06-01"),
    "T002": ("Signal Dock", "Western Europe", "8.00", "2024-06-02"),
    "T003": ("Echo Board", "Southeast Asia", "11.50", "2024-06-03"),
    "T004": ("Pulse Hub", "US Central", "0.00", "2024-06-04"),
    "T006": ("Signal Dock", "US Central", "5.75", "2024-06-06"),
}


def _load_clean_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _run_etl(workspace: Path) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [sys.executable, "etl.py"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"rerun failed: {exc}"

    clean = workspace / "output" / "clean_sales.csv"
    report = workspace / "output" / "quality_report.json"
    if completed.returncode == 0 and clean.exists() and report.exists():
        return True, "rerun created output/ artifacts"
    return False, (completed.stdout + completed.stderr).strip() or "rerun did not create required output/"


def _rerun_etl(workspace: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir)
        for name in ("etl.py", "raw_sales.csv", "raw_products.csv", "raw_regions.json"):
            source = workspace / name
            if source.exists():
                shutil.copy2(source, sandbox / name)
        return _run_etl(sandbox)


def _validate_exact_rows(rows: list[dict], expected_rows: dict[str, tuple[str, str, str, str]]) -> int:
    actual = {
        row.get("sale_id", ""): (
            row.get("product_name", ""),
            row.get("region_name", ""),
            row.get("amount", ""),
            row.get("date", ""),
        )
        for row in rows
    }
    return sum(1 for sale_id, expected in expected_rows.items() if actual.get(sale_id) == expected)


def _validate_report(report_path: Path, expected_report: dict[str, int]) -> tuple[int, str]:
    if not report_path.exists():
        return 0, "missing output/quality_report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return 0, f"invalid JSON: {exc}"
    matched = sum(1 for key, value in expected_report.items() if report.get(key) == value)
    return matched, f"{matched}/{len(expected_report)} quality fields exact"


def _run_variant_validation(
    etl_source: Path,
    *,
    products_csv: str,
    regions_data: dict[str, str],
    sales_csv: str,
    expected_rows: dict[str, tuple[str, str, str, str]],
    expected_report: dict[str, int],
) -> tuple[tuple[int, int], tuple[int, int], str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir)
        shutil.copy2(etl_source, sandbox / "etl.py")
        (sandbox / "raw_products.csv").write_text(products_csv, encoding="utf-8")
        (sandbox / "raw_regions.json").write_text(json.dumps(regions_data, ensure_ascii=False), encoding="utf-8")
        (sandbox / "raw_sales.csv").write_text(sales_csv, encoding="utf-8")

        ok, detail = _run_etl(sandbox)
        if not ok:
            return (0, len(expected_rows)), (0, len(expected_report)), detail

        clean_rows = _load_clean_rows(sandbox / "output" / "clean_sales.csv")
        exact_rows = _validate_exact_rows(clean_rows, expected_rows)
        matched_report, report_detail = _validate_report(sandbox / "output" / "quality_report.json", expected_report)
        return (
            (exact_rows, len(expected_rows)),
            (matched_report, len(expected_report)),
            f"{detail}; {report_detail}",
        )


def _run_repeatability_validation(
    etl_source: Path,
    *,
    products_csv: str,
    regions_data: dict[str, str],
    sales_csv: str,
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir)
        shutil.copy2(etl_source, sandbox / "etl.py")
        (sandbox / "raw_products.csv").write_text(products_csv, encoding="utf-8")
        (sandbox / "raw_regions.json").write_text(json.dumps(regions_data, ensure_ascii=False), encoding="utf-8")
        (sandbox / "raw_sales.csv").write_text(sales_csv, encoding="utf-8")

        first_ok, first_detail = _run_etl(sandbox)
        if not first_ok:
            return False, f"initial run failed: {first_detail}"

        clean_path = sandbox / "output" / "clean_sales.csv"
        report_path = sandbox / "output" / "quality_report.json"
        first_clean = clean_path.read_text(encoding="utf-8")
        first_report = report_path.read_text(encoding="utf-8")

        second_ok, second_detail = _run_etl(sandbox)
        if not second_ok:
            return False, f"second run failed: {second_detail}"

        second_clean = clean_path.read_text(encoding="utf-8")
        second_report = report_path.read_text(encoding="utf-8")
        if first_clean != second_clean or first_report != second_report:
            return False, "rerun with existing output changed artifacts"
        return True, "rerun with existing output preserved exact artifacts"


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    etl = ws / "etl.py"
    checkpoints["etl_exists"] = {
        "score": 0.01 if etl.exists() else 0.0,
        "max": 0.01,
        "detail": "etl.py exists" if etl.exists() else "missing etl.py",
    }

    rerun_ok, rerun_detail = _rerun_etl(ws) if etl.exists() else (False, "missing etl.py")
    checkpoints["rerun_success"] = {
        "score": 0.02 if rerun_ok else 0.0,
        "max": 0.02,
        "detail": rerun_detail,
    }

    repeatable_ok = False
    repeatable_detail = "missing etl.py"
    if etl.exists():
        try:
            repeatable_ok, repeatable_detail = _run_repeatability_validation(
                etl,
                products_csv=(ws / "raw_products.csv").read_text(encoding="utf-8"),
                regions_data=json.loads((ws / "raw_regions.json").read_text(encoding="utf-8")),
                sales_csv=(ws / "raw_sales.csv").read_text(encoding="utf-8"),
            )
        except Exception as exc:
            repeatable_ok = False
            repeatable_detail = f"repeatability validation failed: {exc}"
    checkpoints["repeatable_with_existing_output"] = {
        "score": 0.03 if repeatable_ok else 0.0,
        "max": 0.03,
        "detail": repeatable_detail,
    }

    clean = ws / "output" / "clean_sales.csv"
    report_path = ws / "output" / "quality_report.json"
    rows = _load_clean_rows(clean) if clean.exists() else []

    exact_rows = 0
    required_columns = {"sale_id", "product_name", "region_name", "amount", "date"}
    if rows:
        exact_rows = _validate_exact_rows(rows, EXPECTED_ROWS)
        has_columns = required_columns.issubset(rows[0].keys())
    else:
        has_columns = False
    checkpoints["clean_rows_exact"] = {
        "score": round(exact_rows / len(EXPECTED_ROWS) * 0.06, 4),
        "max": 0.06,
        "detail": f"{exact_rows}/{len(EXPECTED_ROWS)} clean rows match expected values",
    }

    joins_and_dates_ok = False
    if rows:
        joins_and_dates_ok = has_columns and all("/" not in row.get("date", "") for row in rows)
    checkpoints["joins_and_normalization"] = {
        "score": 0.06 if joins_and_dates_ok else 0.0,
        "max": 0.06,
        "detail": "joined names and normalized dates" if joins_and_dates_ok else "missing joined columns or mixed date formats",
    }

    no_dupes = False
    if rows:
        sale_ids = [row.get("sale_id", "") for row in rows]
        no_dupes = len(rows) == len(EXPECTED_ROWS) and len(set(sale_ids)) == len(sale_ids)
    checkpoints["no_duplicates"] = {
        "score": 0.05 if no_dupes else 0.0,
        "max": 0.05,
        "detail": "unique sale_ids only" if no_dupes else "duplicate or missing sale_ids detected",
    }

    matched_report_fields, report_detail = _validate_report(report_path, EXPECTED_REPORT)
    checkpoints["quality_report"] = {
        "score": round(matched_report_fields / len(EXPECTED_REPORT) * 0.05, 4),
        "max": 0.05,
        "detail": report_detail,
    }

    variant_rows, variant_report, variant_detail = (
        _run_variant_validation(
            etl,
            products_csv=VARIANT_PRODUCTS,
            regions_data=VARIANT_REGIONS,
            sales_csv=VARIANT_SALES,
            expected_rows=VARIANT_EXPECTED_ROWS,
            expected_report=VARIANT_EXPECTED_REPORT,
        )
        if etl.exists()
        else ((0, len(VARIANT_EXPECTED_ROWS)), (0, len(VARIANT_EXPECTED_REPORT)), "missing etl.py")
    )
    checkpoints["variant_generalization"] = {
        "score": round((variant_rows[0] / max(variant_rows[1], 1)) * 0.12, 4),
        "max": 0.12,
        "detail": f"{variant_rows[0]}/{variant_rows[1]} hidden-variant rows exact ({variant_detail})",
    }
    checkpoints["variant_quality_report"] = {
        "score": round((variant_report[0] / max(variant_report[1], 1)) * 0.08, 4),
        "max": 0.08,
        "detail": f"{variant_report[0]}/{variant_report[1]} hidden-variant quality fields exact",
    }

    edge_variant_rows, edge_variant_report, edge_variant_detail = (
        _run_variant_validation(
            etl,
            products_csv=EDGE_VARIANT_PRODUCTS,
            regions_data=EDGE_VARIANT_REGIONS,
            sales_csv=EDGE_VARIANT_SALES,
            expected_rows=EDGE_VARIANT_EXPECTED_ROWS,
            expected_report=EDGE_VARIANT_EXPECTED_REPORT,
        )
        if etl.exists()
        else ((0, len(EDGE_VARIANT_EXPECTED_ROWS)), (0, len(EDGE_VARIANT_EXPECTED_REPORT)), "missing etl.py")
    )
    checkpoints["edge_variant_generalization"] = {
        "score": round((edge_variant_rows[0] / max(edge_variant_rows[1], 1)) * 0.12, 4),
        "max": 0.12,
        "detail": f"{edge_variant_rows[0]}/{edge_variant_rows[1]} hidden edge-variant rows exact ({edge_variant_detail})",
    }
    checkpoints["edge_variant_quality_report"] = {
        "score": round((edge_variant_report[0] / max(edge_variant_report[1], 1)) * 0.16, 4),
        "max": 0.16,
        "detail": f"{edge_variant_report[0]}/{edge_variant_report[1]} hidden edge-variant quality fields exact",
    }

    stress_variant_rows, stress_variant_report, stress_variant_detail = (
        _run_variant_validation(
            etl,
            products_csv=STRESS_VARIANT_PRODUCTS,
            regions_data=STRESS_VARIANT_REGIONS,
            sales_csv=STRESS_VARIANT_SALES,
            expected_rows=STRESS_VARIANT_EXPECTED_ROWS,
            expected_report=STRESS_VARIANT_EXPECTED_REPORT,
        )
        if etl.exists()
        else ((0, len(STRESS_VARIANT_EXPECTED_ROWS)), (0, len(STRESS_VARIANT_EXPECTED_REPORT)), "missing etl.py")
    )
    checkpoints["stress_variant_generalization"] = {
        "score": round((stress_variant_rows[0] / max(stress_variant_rows[1], 1)) * 0.10, 4),
        "max": 0.10,
        "detail": f"{stress_variant_rows[0]}/{stress_variant_rows[1]} hidden stress-variant rows exact ({stress_variant_detail})",
    }
    checkpoints["stress_variant_quality_report"] = {
        "score": round((stress_variant_report[0] / max(stress_variant_report[1], 1)) * 0.15, 4),
        "max": 0.15,
        "detail": f"{stress_variant_report[0]}/{stress_variant_report[1]} hidden stress-variant quality fields exact",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    events = trace.get("events", [])
    read_count = sum(1 for e in events if e.get("type") == "tool_call" and e.get("tool") in ("read", "Read"))
    wrote = any(e.get("type") == "tool_call" and e.get("tool") in ("write", "Write") for e in events)
    ran = any(e.get("type") == "tool_call" and "python" in str(e.get("args", {}).get("command", "")) for e in events)
    score = 0.2
    if read_count >= 3:
        score += 0.3
    if wrote:
        score += 0.25
    if ran:
        score += 0.25
    return min(score, 1.0)
