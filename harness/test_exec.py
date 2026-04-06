"""Helpers for running scenario-provided test files during scoring."""

from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class TestRunSummary:
    passed: int
    total: int
    discovered: int


def first_existing_path(root: Path, names: Sequence[str], pattern: str | None = None) -> Path | None:
    for name in names:
        path = root / name
        if path.exists():
            return path
    if pattern is None:
        return None
    for path in root.rglob(pattern):
        return path
    return None


def has_valid_python_syntax(path: Path) -> bool:
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        return True
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False


def count_test_functions(path: Path) -> int:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return len(re.findall(r"^\s*def test_", content, re.MULTILINE))


def summarize_test_file(workspace: Path, test_file: Path, timeout_seconds: int = 30) -> TestRunSummary:
    passed, total = run_test_file(workspace, test_file, timeout_seconds=timeout_seconds)
    discovered = max(total, count_test_functions(test_file))
    return TestRunSummary(passed=passed, total=total, discovered=discovered)


def run_test_file(workspace: Path, test_file: Path, timeout_seconds: int = 30) -> tuple[int, int]:
    commands = (
        [sys.executable, "-m", "pytest", str(test_file), "-v", "--tb=short"],
        [sys.executable, str(test_file)],
    )
    best: tuple[int, int] = (0, 0)
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=str(workspace),
                timeout=timeout_seconds,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

        current = _parse_test_output(result.stdout + result.stderr)
        if current[1] > best[1] or current[0] > best[0]:
            best = current
        if current[1] > 0:
            return current
        if result.returncode == 0:
            return current
    return best


def _parse_test_output(output: str) -> tuple[int, int]:
    unittest_total = _last_int(output, r"Ran (\d+) tests?")
    if unittest_total > 0:
        if "OK" in output and "FAILED" not in output:
            return unittest_total, unittest_total
        failures = _last_int(output, r"failures=(\d+)")
        errors = _last_int(output, r"errors=(\d+)")
        return max(unittest_total - failures - errors, 0), unittest_total

    pytest_total = _last_int(output, r"collected (\d+) items?")
    if pytest_total > 0:
        passed = _sum_ints(output, r"(\d+) passed")
        failed = _sum_ints(output, r"(\d+) failed")
        errors = _sum_ints(output, r"(\d+) errors?")
        if passed == 0 and failed == 0 and errors == 0:
            passed = pytest_total if " passed" in output and "failed" not in output.lower() else 0
        return max(min(passed, pytest_total), 0), pytest_total

    passed = _sum_ints(output, r"(\d+) passed")
    failed = _sum_ints(output, r"(\d+) failed")
    errors = _sum_ints(output, r"(\d+) errors?")
    total = passed + failed + errors
    if total > 0:
        return passed, total
    return 0, 0


def _last_int(text: str, pattern: str) -> int:
    matches = re.findall(pattern, text)
    return int(matches[-1]) if matches else 0


def _sum_ints(text: str, pattern: str) -> int:
    return sum(int(value) for value in re.findall(pattern, text))
