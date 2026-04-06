"""T05: 配置文件精确修改 — 评分脚本（v5 接口）"""

from pathlib import Path
import yaml


def grade(workspace: str, trace: dict) -> dict:
    ws = Path(workspace)
    checkpoints = {}

    cfg_path = ws / "config.yaml"
    if not cfg_path.exists():
        for k in ("port_changed", "max_conn_changed", "log_file_added", "others_intact"):
            checkpoints[k] = {"score": 0.0, "max": 0.25, "detail": "config.yaml missing"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        data = yaml.safe_load(cfg_path.read_text())
    except Exception:
        for k in ("port_changed", "max_conn_changed", "log_file_added", "others_intact"):
            checkpoints[k] = {"score": 0.0, "max": 0.25, "detail": "invalid YAML"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    # 1. port 改为 9090
    port = data.get("server", {}).get("port")
    checkpoints["port_changed"] = {
        "score": 0.25 if port == 9090 else 0.0, "max": 0.25,
        "detail": f"port={port}" + (" ✓" if port == 9090 else " (expected 9090)"),
    }

    # 2. max_connections 改为 50
    mc = data.get("database", {}).get("max_connections")
    checkpoints["max_conn_changed"] = {
        "score": 0.25 if mc == 50 else 0.0, "max": 0.25,
        "detail": f"max_connections={mc}" + (" ✓" if mc == 50 else " (expected 50)"),
    }

    # 3. logging.file 新增
    log_file = data.get("logging", {}).get("file")
    checkpoints["log_file_added"] = {
        "score": 0.25 if log_file == "/var/log/app.log" else 0.0, "max": 0.25,
        "detail": f"logging.file={log_file}" if log_file else "logging.file missing",
    }

    # 4. 其他配置未被改动
    intact = True
    checks = [
        (data.get("server", {}).get("host"), "0.0.0.0"),
        (data.get("server", {}).get("workers"), 4),
        (data.get("database", {}).get("host"), "localhost"),
        (data.get("database", {}).get("name"), "myapp"),
        (data.get("database", {}).get("timeout"), 30),
        (data.get("logging", {}).get("level"), "INFO"),
        (data.get("cache", {}).get("enabled"), True),
        (data.get("cache", {}).get("ttl"), 300),
    ]
    for actual, expected in checks:
        if actual != expected:
            intact = False
            break

    checkpoints["others_intact"] = {
        "score": 0.25 if intact else 0.0, "max": 0.25,
        "detail": "other configs intact" if intact else "other configs were modified!",
    }

    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    tc = trace.get("metrics", {}).get("tool_calls", 0)
    if tc <= 4:
        return 1.0
    if tc <= 8:
        return 1.0 - (tc - 4) * 0.1
    return 0.3
