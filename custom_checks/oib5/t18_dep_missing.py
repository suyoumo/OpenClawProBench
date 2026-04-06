"""T18: 依赖缺失恢复 — 必须真正改写并可复跑。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED = {"Electronics": 1347, "Books": 75, "Clothing": 254}


def _load_result(path: Path) -> dict[str, int] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): int(value) for key, value in payload.items()}
    except Exception:
        return None


def _rerun_script(workspace: Path) -> tuple[bool, str]:
    analyze = workspace / "analyze.py"
    data = workspace / "data.csv"
    if not analyze.exists() or not data.exists():
        return False, "missing analyze.py or data.csv"

    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir)
        shutil.copy2(analyze, sandbox / "analyze.py")
        shutil.copy2(data, sandbox / "data.csv")
        try:
            completed = subprocess.run(
                [sys.executable, "analyze.py"],
                cwd=sandbox,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"rerun failed: {exc}"
        rerun_result = _load_result(sandbox / "result.json")
        if completed.returncode == 0 and rerun_result == EXPECTED:
            return True, "rerun produced correct result"
        return False, (completed.stdout + completed.stderr).strip() or "rerun mismatch"


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    result_path = ws / "result.json"
    result = _load_result(result_path)
    checkpoints["result_exists"] = {
        "score": 0.1 if result is not None else 0.0,
        "max": 0.1,
        "detail": "result.json exists" if result is not None else "missing or invalid result.json",
    }

    correct = 0
    if result is not None:
        for category, expected_amount in EXPECTED.items():
            if result.get(category) == expected_amount:
                correct += 1
    checkpoints["correct_values"] = {
        "score": round(correct / len(EXPECTED) * 0.25, 4),
        "max": 0.25,
        "detail": f"{correct}/{len(EXPECTED)} category sums correct",
    }

    analyze = ws / "analyze.py"
    analyze_text = analyze.read_text(encoding="utf-8") if analyze.exists() else ""
    rewritten = analyze.exists() and "pandas" not in analyze_text.lower() and "csv" in analyze_text
    checkpoints["analyze_rewritten"] = {
        "score": 0.15 if rewritten else 0.0,
        "max": 0.15,
        "detail": "stdlib rewrite detected" if rewritten else "analyze.py still depends on pandas or is missing",
    }

    rerun_ok, rerun_detail = _rerun_script(ws)
    checkpoints["rerun_success"] = {
        "score": 0.25 if rerun_ok else 0.0,
        "max": 0.25,
        "detail": rerun_detail,
    }

    installed_pandas = False
    for event in trace.get("events", []):
        if event.get("type") != "tool_call":
            continue
        cmd = str(event.get("args", {}).get("command", ""))
        if "pip install" in cmd and "pandas" in cmd:
            installed_pandas = True
            break
    checkpoints["no_pandas_install"] = {
        "score": 0.0 if installed_pandas else 0.1,
        "max": 0.1,
        "detail": "installed pandas" if installed_pandas else "no pandas install attempt",
    }

    error_found = False
    for event in trace.get("events", []):
        text = f"{event.get('text', '')} {event.get('result', '')}".lower()
        if "modulenotfounderror" in text or "no module named" in text:
            error_found = True
            break
    checkpoints["error_detected"] = {
        "score": 0.15 if error_found else 0.0,
        "max": 0.15,
        "detail": "detected dependency failure" if error_found else "no dependency failure observed",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    """应该先运行 analyze.py 发现失败，再用标准库重写"""
    events = trace.get("events", [])
    ran_original = False
    wrote_new = False
    for e in events:
        if e.get("type") == "tool_call":
            tool = e.get("tool", "")
            args = e.get("args", {})
            cmd = args.get("command", "")
            if "analyze.py" in cmd or "python" in cmd:
                ran_original = True
            if tool in ("write", "Write", "edit", "Edit"):
                wrote_new = True
    if ran_original and wrote_new:
        return 1.0
    if wrote_new:
        return 0.6
    return 0.3
