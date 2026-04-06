"""T17: 工具故障恢复 — 只读目录 — 评分脚本（v5 接口）

output/ 目录是只读的，模型需要发现写入失败并找到替代方案。
预期结果：Widget A=850, Widget C=650, Widget B=575
"""

import json
from pathlib import Path

EXPECTED = {"Widget A": 850, "Widget B": 575, "Widget C": 650}


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _find_result_file(ws: Path) -> Path | None:
    for p in [ws / "output" / "result.json", ws / "result.json", ws / "output_result.json"]:
        if _path_exists(p):
            return p
    for p in ws.glob("*.json"):
        return p
    return None


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    # 1. 检测到错误（从 trace 中找）
    detected = False
    error_kw = ["permission", "denied", "read-only", "readonly", "cannot write",
                "unable to write", "failed", "error", "chmod", "权限", "只读"]
    for event in trace.get("events", []):
        text = event.get("text", "") or event.get("result", "")
        if any(kw in text.lower() for kw in error_kw):
            detected = True
            break

    # 2. 采取了替代方案
    result_path = _find_result_file(ws)
    has_alt = result_path is not None

    # error_detected: give partial credit if agent silently recovered (found alternative)
    checkpoints["error_detected"] = {
        "score": 0.2 if detected else 0.1 if has_alt else 0.0, "max": 0.2,
        "detail": "error detected in trace" if detected else ("implicit via alternative path" if has_alt else "no error detection"),
    }
    checkpoints["alternative_found"] = {
        "score": 0.4 if has_alt else 0.0, "max": 0.4,
        "detail": f"result at {result_path.name}" if has_alt else "no result file",
    }

    if not has_alt:
        checkpoints["result_correct"] = {"score": 0.0, "max": 0.3, "detail": "skipped"}
        checkpoints["no_crash"] = {"score": 0.1, "max": 0.1, "detail": "completed"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # 3. 结果正确
    try:
        data = json.loads(result_path.read_text())
        actual = {k.strip(): int(v) if isinstance(v, (int, float)) else v for k, v in data.items()}
        correct = all(actual.get(p) == a for p, a in EXPECTED.items()) and len(actual) == len(EXPECTED)
    except Exception:
        correct = False

    checkpoints["result_correct"] = {
        "score": 0.3 if correct else 0.0, "max": 0.3,
        "detail": "data correct" if correct else "data mismatch",
    }
    checkpoints["no_crash"] = {"score": 0.1, "max": 0.1, "detail": "completed"}

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    """故障恢复：应该先尝试写入，发现失败后换路径"""
    events = trace.get("events", [])
    saw_write_attempt = False
    saw_recovery = False
    for e in events:
        if e.get("type") == "tool_call":
            args = e.get("args", {})
            cmd = args.get("command", args.get("path", ""))
            if "output" in str(cmd):
                saw_write_attempt = True
            elif saw_write_attempt and ("result" in str(cmd) or "json" in str(cmd)):
                saw_recovery = True
    if saw_write_attempt and saw_recovery:
        return 1.0
    if saw_write_attempt:
        return 0.7
    return 0.4
