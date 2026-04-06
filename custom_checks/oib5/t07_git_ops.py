"""T07: Git 操作 — 评分脚本"""

import re
from pathlib import Path


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    # 1. README.md 存在
    readme = ws / "README.md"
    readme_ok = readme.exists() and "MyProject" in (readme.read_text() if readme.exists() else "")
    checkpoints["readme_created"] = {
        "score": 0.2 if readme_ok else 0.0, "max": 0.2,
        "detail": "README.md with MyProject" if readme_ok else "missing or no MyProject",
    }

    # 2. git_log.txt 存在
    log_file = ws / "git_log.txt"
    log_ok = log_file.exists()
    checkpoints["log_saved"] = {
        "score": 0.15 if log_ok else 0.0, "max": 0.15,
        "detail": "git_log.txt exists" if log_ok else "missing",
    }

    # 3. log 中包含 "Add README.md" 提交
    has_commit = False
    if log_ok:
        content = log_file.read_text()
        has_commit = "Add README" in content or "add readme" in content.lower()
    checkpoints["commit_message"] = {
        "score": 0.25 if has_commit else 0.0, "max": 0.25,
        "detail": "commit message found" if has_commit else "commit message not in log",
    }

    # 4. 从 trace 检查是否创建了分支
    branch_created = False
    for event in trace.get("events", []):
        if event.get("type") == "tool_call":
            cmd = event.get("args", {}).get("command", "")
            if "branch" in cmd and "feature" in cmd:
                branch_created = True
                break
            if "checkout -b" in cmd and "feature" in cmd:
                branch_created = True
                break
    checkpoints["branch_created"] = {
        "score": 0.2 if branch_created else 0.0, "max": 0.2,
        "detail": "feature branch created" if branch_created else "no branch creation found",
    }

    # 5. log 中有 2 条提交
    two_commits = False
    if log_ok:
        content = log_file.read_text()
        commit_count = len(re.findall(r"commit [0-9a-f]{7,}", content))
        two_commits = commit_count >= 2
    checkpoints["two_commits_in_log"] = {
        "score": 0.2 if two_commits else 0.0, "max": 0.2,
        "detail": f"{commit_count if log_ok else 0} commits in log" + (" ✓" if two_commits else ""),
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    tc = trace.get("metrics", {}).get("tool_calls", 0)
    return 1.0 if tc <= 8 else max(0.3, 1.0 - (tc - 8) * 0.1)
