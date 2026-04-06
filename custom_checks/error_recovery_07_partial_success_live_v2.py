"""Grounded scoring for Error Recovery 07: partial-success recovery."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path


EXPECTED_ROOT_CAUSE = "db_connection_pool_exhaustion"
EXPECTED_SUCCESSFUL = 700
EXPECTED_FAILED = 282
EXPECTED_PARTIAL = 18
EXPECTED_RETRY = 300
EXPECTED_CLEANUP = 18
EXPECTED_CLEANUP_EXAMPLES = [f"file_{i:04d}.dat" for i in range(701, 704)]
EXPECTED_RETRY_EXAMPLES = [f"file_{i:04d}.dat" for i in range(701, 706)]


def _extract_summary(content: str) -> dict | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _check_input_artifacts(workspace_path: Path) -> tuple[bool, str]:
    file_list_path = workspace_path / "file_list.txt"
    processed_path = workspace_path / "processed_files.csv"
    log_path = workspace_path / "process.log"
    if not file_list_path.exists() or not processed_path.exists() or not log_path.exists():
        return False, "missing one or more seeded input artifacts"

    file_list = file_list_path.read_text(encoding="utf-8").splitlines()
    if len(file_list) != 1000 or file_list[0] != "file_0001.dat" or file_list[-1] != "file_1000.dat":
        return False, "file_list.txt no longer matches the seeded 1000-file inventory"

    with processed_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 718:
        return False, "processed_files.csv row count drifted from the seeded truth"

    success_rows = [row for row in rows if row["db_state"] == "committed"]
    partial_rows = [row for row in rows if row["db_state"] == "partial"]
    if len(success_rows) != EXPECTED_SUCCESSFUL or len(partial_rows) != EXPECTED_PARTIAL:
        return False, "processed_files.csv status split is inconsistent"

    log_text = log_path.read_text(encoding="utf-8")
    if log_text.count(" SUCCESS ") != EXPECTED_SUCCESSFUL:
        return False, "process.log success count is inconsistent"
    if log_text.count(" PARTIAL ") != EXPECTED_PARTIAL:
        return False, "process.log partial count is inconsistent"
    if log_text.count(" FAILED ") != EXPECTED_FAILED:
        return False, "process.log failed count is inconsistent"
    if "db_connection_timeout active=32 limit=32" not in log_text:
        return False, "process.log no longer shows the seeded timeout burst"
    return True, "seeded inputs are present and unchanged"


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict] = {}

    output_file = workspace_path / "recovery_plan.md"
    if not output_file.exists():
        return {
            "checkpoints": {
                "file": {"score": 0.0, "max": 1.0, "detail": "recovery_plan.md not created"}
            }
        }

    inputs_ok, inputs_detail = _check_input_artifacts(workspace_path)
    checkpoints["inputs_are_present"] = {
        "score": 0.1 if inputs_ok else 0.0,
        "max": 0.1,
        "detail": inputs_detail,
    }

    content = output_file.read_text(encoding="utf-8")
    summary = _extract_summary(content)
    if summary is None:
        checkpoints["summary_block_is_valid_json"] = {
            "score": 0.0,
            "max": 0.2,
            "detail": "missing or invalid fenced json summary block",
        }
        checkpoints["counts_are_correct"] = {
            "score": 0.0,
            "max": 0.3,
            "detail": "summary block required for exact recovery counts",
        }
        checkpoints["examples_are_grounded"] = {
            "score": 0.0,
            "max": 0.15,
            "detail": "summary block required for cleanup/retry examples",
        }
        checkpoints["strategy_is_bounded"] = {
            "score": 0.0,
            "max": 0.1,
            "detail": "summary block required for retry strategy fields",
        }
    else:
        checkpoints["summary_block_is_valid_json"] = {
            "score": 0.2,
            "max": 0.2,
            "detail": "fenced json summary block parsed successfully",
        }

        counts_ok = (
            summary.get("root_cause") == EXPECTED_ROOT_CAUSE
            and summary.get("successful_files") == EXPECTED_SUCCESSFUL
            and summary.get("failed_files") == EXPECTED_FAILED
            and summary.get("partial_files") == EXPECTED_PARTIAL
            and summary.get("retry_files_total") == EXPECTED_RETRY
            and summary.get("cleanup_files_total") == EXPECTED_CLEANUP
        )
        checkpoints["counts_are_correct"] = {
            "score": 0.3 if counts_ok else 0.0,
            "max": 0.3,
            "detail": "exact recovery counts and root cause match the seeded truth"
            if counts_ok
            else "root cause or recovery counts do not match the seeded truth",
        }

        examples_ok = (
            summary.get("cleanup_examples") == EXPECTED_CLEANUP_EXAMPLES
            and summary.get("retry_examples") == EXPECTED_RETRY_EXAMPLES
        )
        checkpoints["examples_are_grounded"] = {
            "score": 0.15 if examples_ok else 0.0,
            "max": 0.15,
            "detail": "cleanup/retry examples match the required sorted prefixes"
            if examples_ok
            else "cleanup/retry examples are missing, unsorted, or not grounded",
        }

        batch_size = summary.get("batch_size")
        max_retries = summary.get("max_retries")
        backoff = summary.get("backoff_seconds")
        strategy_ok = (
            isinstance(batch_size, int)
            and 25 <= batch_size <= 75
            and isinstance(max_retries, int)
            and 2 <= max_retries <= 5
            and isinstance(backoff, list)
            and len(backoff) == 3
            and all(isinstance(item, int) and item > 0 for item in backoff)
            and backoff == sorted(backoff)
            and len(set(backoff)) == len(backoff)
        )
        checkpoints["strategy_is_bounded"] = {
            "score": 0.1 if strategy_ok else 0.0,
            "max": 0.1,
            "detail": "retry strategy fields are bounded and monotonic"
            if strategy_ok
            else "retry strategy fields are missing or unreasonable",
        }

    body = re.sub(r"```json\s*\{.*?\}\s*```", "", content, flags=re.DOTALL).lower()
    evidence_terms = ["pool", "timeout", "32", "processed_files.csv", "process.log", "file_list.txt"]
    verification_terms = ["checksum", "duplicate", "row count", "count(*)", "验证", "校验"]
    cleanup_terms = ["cleanup", "清理", "partial", "部分"]
    body_ok = (
        sum(term in body for term in evidence_terms) >= 3
        and sum(term in body for term in verification_terms) >= 1
        and sum(term in body for term in cleanup_terms) >= 2
    )
    checkpoints["plan_body_is_grounded"] = {
        "score": 0.15 if body_ok else 0.0,
        "max": 0.15,
        "detail": "body explains evidence, cleanup, and verification"
        if body_ok
        else "body is missing grounded evidence / cleanup / verification detail",
    }

    return {"checkpoints": checkpoints}


def grade_process(trace: dict) -> float:
    read_count = 0
    wrote_output = False
    for e in trace.get("events", []):
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        if tool in ("read", "Read"):
            read_count += 1
        if tool in ("write", "Write"):
            path = str(args.get("path", "") or args.get("file_path", ""))
            if any(path.endswith(ext) for ext in (".json", ".csv", ".md", ".txt")):
                wrote_output = True
    if read_count >= 3 and wrote_output:
        return 1.0
    if read_count >= 2 and wrote_output:
        return 0.7
    if wrote_output:
        return 0.4
    return 0.2
