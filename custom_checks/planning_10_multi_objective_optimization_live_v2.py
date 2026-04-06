"""Planning 10 Multi Objective Optimization — 严格评分脚本

严格验证：
1. 检查关键内容：目标, objective, 冲突\n2. 检查关键内容：目标, objective, 冲突\n3. 检查关键内容：目标, objective, 冲突
"""

from pathlib import Path
import json

def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints = {}
    
    # 1. 检查输出文件是否存在
    output_file = workspace_path / "optimization_decision.md"
    
    if not output_file.exists():
        return {"checkpoints": {"file": {"score": 0.0, "max": 1.0, "detail": "❌ optimization_decision.md not created"}}}
    
    content = output_file.read_text(encoding="utf-8").lower()
    
    # 2. 检查关键内容
    keywords = ['目标', 'objective', '冲突', 'conflict', '权衡', 'tradeoff', '帕累托', 'pareto']
    found_keywords = sum(1 for kw in keywords if kw.lower() in content)
    
    quality_score = min(found_keywords / len(keywords), 1.0) * 0.6
    
    checkpoints["content_quality"] = {
        "score": quality_score,
        "max": 0.6,
        "detail": f"Found {found_keywords}/{len(keywords)} key concepts",
    }
    
    # 3. 检查内容长度（至少 500 字符）
    if len(content) > 500:
        checkpoints["content_length"] = {
            "score": 0.2,
            "max": 0.2,
            "detail": "✅ Sufficient content length",
        }
    else:
        checkpoints["content_length"] = {
            "score": 0.1,
            "max": 0.2,
            "detail": "⚠️ Content too short",
        }
    
    # 4. 检查是否有推理过程
    reasoning_keywords = ["分析", "analysis", "推理", "reasoning", "结论", "conclusion"]
    has_reasoning = any(kw in content for kw in reasoning_keywords)
    
    checkpoints["reasoning"] = {
        "score": 0.2 if has_reasoning else 0.0,
        "max": 0.2,
        "detail": "✅ Has reasoning process" if has_reasoning else "❌ Missing reasoning",
    }
    
    return {"checkpoints": checkpoints}
