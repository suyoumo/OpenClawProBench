"""Constraints 07: 隐藏约束发现 — 改进版评分脚本

严格验证：
1. 发现了所有 5 个隐藏约束
2. 每个约束都有具体证据（文件名 + 行号）
3. 分析了性能影响
4. 提供了优化建议
5. 创建了优化配置文件
"""

from pathlib import Path
import json


def grade(workspace: str, trace: dict) -> dict:
    """严格评分函数"""
    workspace_path = Path(workspace)
    checkpoints = {}

    # 1. 检查是否创建了 constraint_discovery.md
    discovery_file = workspace_path / "constraint_discovery.md"

    if not discovery_file.exists():
        return {
            "checkpoints": {
                "file_exists": {
                    "score": 0.0,
                    "max": 1.0,
                    "detail": "❌ constraint_discovery.md not created",
                }
            }
        }

    content = discovery_file.read_text(encoding="utf-8")

    # 2. 严格检查发现的约束（必须找到所有 5 个）
    required_constraints = {
        "DB_POOL_SIZE": ["连接池", "connection pool", "pool size", "db_pool"],
        "REDIS_TTL": ["缓存", "cache", "ttl", "redis"],
        "MAX_FILE_SIZE": ["文件大小", "file size", "upload limit", "max_file"],
        "RATE_LIMIT": ["速率限制", "rate limit", "api limit", "rate_limit"],
        "MAX_QUERY_ROWS": ["查询限制", "query limit", "max rows", "query_rows"],
    }

    found_constraints = {}
    for constraint_name, keywords in required_constraints.items():
        if any(kw.lower() in content.lower() for kw in keywords):
            # 进一步验证是否提到了具体的值
            if any(val in content for val in ["10", "60", "5", "100", "1000"]):
                found_constraints[constraint_name] = True

    constraint_count = len(found_constraints)
    constraint_score = (constraint_count / 5.0) * 0.3  # 30% 的分数

    checkpoints["found_constraints"] = {
        "score": constraint_score,
        "max": 0.3,
        "detail": f"Found {constraint_count}/5 constraints: {', '.join(found_constraints.keys())}",
    }

    # 3. 严格检查证据（必须有文件名和行号）
    import re

    # 检查是否有文件名引用（如 "main.py", "app.log", "system_code/"）
    file_patterns = [
        r"main\.py",
        r"app\.log",
        r"system_code/",
        r"logs/",
    ]
    has_file_reference = any(re.search(pattern, content) for pattern in file_patterns)

    # 检查是否有行号引用（如 "line 5", "第 10 行", ":10"）
    line_patterns = [
        r"line\s+\d+",
        r"第\s*\d+\s*行",
        r":\d+",
        r"行号",
    ]
    has_line_reference = any(re.search(pattern, content) for pattern in line_patterns)

    evidence_score = 0.0
    if has_file_reference and has_line_reference:
        evidence_score = 0.2  # 20% 的分数
        evidence_detail = "✅ Has file references and line numbers"
    elif has_file_reference:
        evidence_score = 0.1
        evidence_detail = "⚠️ Has file references but missing line numbers"
    else:
        evidence_detail = "❌ Missing evidence (file references and line numbers)"

    checkpoints["evidence_quality"] = {
        "score": evidence_score,
        "max": 0.2,
        "detail": evidence_detail,
    }

    # 4. 检查性能影响分析
    impact_keywords = ["影响", "impact", "性能", "performance", "瓶颈", "bottleneck"]
    has_impact = sum(1 for kw in impact_keywords if kw.lower() in content.lower()) >= 2

    checkpoints["impact_analysis"] = {
        "score": 0.15 if has_impact else 0.0,
        "max": 0.15,
        "detail": "✅ Has impact analysis" if has_impact else "❌ Missing impact analysis",
    }

    # 5. 检查优化建议
    optimization_keywords = ["优化", "optimize", "建议", "recommendation", "改进", "improve"]
    has_optimization = sum(1 for kw in optimization_keywords if kw.lower() in content.lower()) >= 2

    checkpoints["optimization_suggestions"] = {
        "score": 0.15 if has_optimization else 0.0,
        "max": 0.15,
        "detail": "✅ Has optimization suggestions" if has_optimization else "❌ Missing optimization",
    }

    # 6. 检查是否创建了优化配置文件
    optimized_config = workspace_path / "optimized_config.json"

    if optimized_config.exists():
        try:
            with open(optimized_config) as f:
                config_data = json.load(f)

            # 检查配置文件是否包含优化后的值
            has_valid_config = any(key in config_data for key in ["pool_size", "cache_ttl", "max_file_size", "rate_limit", "max_rows"])

            if has_valid_config:
                checkpoints["optimized_config"] = {
                    "score": 0.2,
                    "max": 0.2,
                    "detail": "✅ Created optimized_config.json with valid optimizations",
                }
            else:
                checkpoints["optimized_config"] = {
                    "score": 0.1,
                    "max": 0.2,
                    "detail": "⚠️ Created optimized_config.json but missing key optimizations",
                }
        except:
            checkpoints["optimized_config"] = {
                "score": 0.0,
                "max": 0.2,
                "detail": "❌ optimized_config.json exists but invalid JSON",
            }
    else:
        checkpoints["optimized_config"] = {
            "score": 0.0,
            "max": 0.2,
            "detail": "❌ optimized_config.json not created",
        }

    return {"checkpoints": checkpoints}
