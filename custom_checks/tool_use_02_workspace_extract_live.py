from __future__ import annotations

import csv
from pathlib import Path

EXPECTED_ROWS = [
    ["order_id", "total"],
    ["A103", "180"],
    ["A100", "120"],
]


def _assistant_text(trace: dict) -> str:
    parts = [
        event.get("text", "")
        for event in trace.get("events", [])
        if event.get("type") == "assistant_message"
    ]
    return "\n".join(part for part in parts if part)


def grade(workspace_path: str, trace: dict, tool_calls: list[dict]) -> dict:
    target = Path(workspace_path) / "vip_orders.csv"
    rows: list[list[str]] = []
    if target.exists():
        rows = list(csv.reader(target.read_text(encoding="utf-8").splitlines()))

    assistant_text = _assistant_text(trace).lower()
    exact = rows == EXPECTED_ROWS
    row_count_reported = any(token in assistant_text for token in ["2 rows", "2条", "2 行", "2个"])

    return {
        "checkpoints": {
            "output_exists": {
                "score": 0.3 if target.exists() else 0.0,
                "max": 0.3,
                "detail": "vip_orders.csv exists",
            },
            "csv_content": {
                "score": 0.5 if exact else 0.0,
                "max": 0.5,
                "detail": f"rows={rows}",
            },
            "assistant_reports_rows": {
                "score": 0.2 if row_count_reported else 0.0,
                "max": 0.2,
                "detail": assistant_text,
            },
        }
    }
