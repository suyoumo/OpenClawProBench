"""
统一验证框架

提供多层验证支持，避免每个场景都写重复的验证逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ValidationResult:
    """验证结果"""

    score: float
    max_score: float
    detail: str
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "max": self.max_score,
            "detail": self.detail,
            "metadata": self.metadata or {},
        }


class Validator:
    """验证器基类"""

    def validate(
        self,
        trace: dict,
        workspace: Path,
        tool_calls: List[dict],
    ) -> ValidationResult:
        """执行验证"""
        raise NotImplementedError


class FormatValidator(Validator):
    """格式验证器"""

    def __init__(
        self,
        required_files: Optional[List[str]] = None,
        required_patterns: Optional[List[str]] = None,
        max_score: float = 0.2,
    ):
        self.required_files = required_files or []
        self.required_patterns = required_patterns or []
        self.max_score = max_score

    def validate(
        self,
        trace: dict,
        workspace: Path,
        tool_calls: List[dict],
    ) -> ValidationResult:
        """验证格式"""
        checks = []
        total_score = 0.0

        # 检查必需文件
        for file_path in self.required_files:
            file = workspace / file_path
            if file.exists():
                checks.append(f"✓ {file_path} exists")
                total_score += self.max_score / (len(self.required_files) + len(self.required_patterns))
            else:
                checks.append(f"✗ {file_path} not found")

        # 检查必需模式
        for pattern in self.required_patterns:
            found = False
            for file in workspace.rglob("*"):
                if file.is_file():
                    try:
                        content = file.read_text(encoding="utf-8")
                        if pattern in content:
                            found = True
                            break
                    except Exception:
                        pass

            if found:
                checks.append(f"✓ Pattern '{pattern}' found")
                total_score += self.max_score / (len(self.required_files) + len(self.required_patterns))
            else:
                checks.append(f"✗ Pattern '{pattern}' not found")

        return ValidationResult(
            score=min(total_score, self.max_score),
            max_score=self.max_score,
            detail="\n".join(checks),
        )


class BehaviorValidator(Validator):
    """行为验证器"""

    def __init__(
        self,
        required_tool_calls: Optional[List[str]] = None,
        required_file_reads: Optional[List[str]] = None,
        required_file_writes: Optional[List[str]] = None,
        max_score: float = 0.3,
    ):
        self.required_tool_calls = required_tool_calls or []
        self.required_file_reads = required_file_reads or []
        self.required_file_writes = required_file_writes or []
        self.max_score = max_score

    def validate(
        self,
        trace: dict,
        workspace: Path,
        tool_calls: List[dict],
    ) -> ValidationResult:
        """验证行为"""
        checks = []
        total_score = 0.0

        # 检查必需的工具调用
        tools_used = [tc.get("name", "") for tc in tool_calls]
        for tool in self.required_tool_calls:
            if tool in tools_used:
                checks.append(f"✓ Tool '{tool}' used")
                total_score += self.max_score / (len(self.required_tool_calls) + len(self.required_file_reads) + len(self.required_file_writes))
            else:
                checks.append(f"✗ Tool '{tool}' not used")

        # 检查必需的文件读取
        files_read = [
            str(tc.get("args", {}).get("path", tc.get("args", {}).get("file_path", "")))
            for tc in tool_calls
            if tc.get("name") in ["read", "cat"]
        ]

        for file_path in self.required_file_reads:
            if any(file_path in f for f in files_read):
                checks.append(f"✓ File '{file_path}' read")
                total_score += self.max_score / (len(self.required_tool_calls) + len(self.required_file_reads) + len(self.required_file_writes))
            else:
                checks.append(f"✗ File '{file_path}' not read")

        # 检查必需的文件写入
        files_written = [
            str(tc.get("args", {}).get("path", tc.get("args", {}).get("file_path", "")))
            for tc in tool_calls
            if tc.get("name") in ["write", "edit"]
        ]

        for file_path in self.required_file_writes:
            if any(file_path in f for f in files_written):
                checks.append(f"✓ File '{file_path}' written")
                total_score += self.max_score / (len(self.required_tool_calls) + len(self.required_file_reads) + len(self.required_file_writes))
            else:
                checks.append(f"✗ File '{file_path}' not written")

        return ValidationResult(
            score=min(total_score, self.max_score),
            max_score=self.max_score,
            detail="\n".join(checks),
        )


class ReasoningValidator(Validator):
    """推理验证器"""

    def __init__(
        self,
        required_keywords: Optional[List[str]] = None,
        required_concepts: Optional[List[str]] = None,
        min_reasoning_steps: int = 3,
        max_score: float = 0.3,
    ):
        self.required_keywords = required_keywords or []
        self.required_concepts = required_concepts or []
        self.min_reasoning_steps = min_reasoning_steps
        self.max_score = max_score

    def validate(
        self,
        trace: dict,
        workspace: Path,
        tool_calls: List[dict],
    ) -> ValidationResult:
        """验证推理过程"""
        checks = []
        total_score = 0.0

        # 提取所有文本内容
        all_text = ""
        for event in trace.get("events", []):
            if event.get("type") == "assistant_message":
                all_text += event.get("text", "") + " "

        # 检查必需关键词
        for keyword in self.required_keywords:
            if keyword.lower() in all_text.lower():
                checks.append(f"✓ Keyword '{keyword}' found")
                total_score += self.max_score * 0.5 / max(len(self.required_keywords), 1)
            else:
                checks.append(f"✗ Keyword '{keyword}' not found")

        # 检查推理步骤数量
        reasoning_indicators = ["因为", "所以", "因此", "由于", "基于", "because", "so", "therefore", "since"]
        reasoning_steps = sum(1 for indicator in reasoning_indicators if indicator in all_text.lower())

        if reasoning_steps >= self.min_reasoning_steps:
            checks.append(f"✓ Found {reasoning_steps} reasoning steps (min: {self.min_reasoning_steps})")
            total_score += self.max_score * 0.5
        else:
            checks.append(f"✗ Only {reasoning_steps} reasoning steps (min: {self.min_reasoning_steps})")

        return ValidationResult(
            score=min(total_score, self.max_score),
            max_score=self.max_score,
            detail="\n".join(checks),
        )


class ValidationFramework:
    """统一验证框架"""

    def __init__(self):
        self.layers: List[Dict[str, Any]] = []

    def add_layer(
        self,
        name: str,
        validator: Validator,
        weight: float,
    ) -> "ValidationFramework":
        """添加验证层"""
        self.layers.append({
            "name": name,
            "validator": validator,
            "weight": weight,
        })
        return self

    def validate(
        self,
        trace: dict,
        workspace: str,
        tool_calls: List[dict],
    ) -> dict:
        """执行所有验证层"""
        checkpoints = {}
        total_score = 0.0

        ws = Path(workspace)

        for layer in self.layers:
            result = layer["validator"].validate(trace, ws, tool_calls)
            checkpoints[layer["name"]] = {
                "score": result.score,
                "max": layer["weight"],
                "detail": result.detail,
            }
            total_score += result.score

        return {
            "checkpoints": checkpoints,
            "total_score": min(total_score, 1.0),
        }


# 便捷函数
def create_simple_framework(
    format_weight: float = 0.2,
    behavior_weight: float = 0.3,
    reasoning_weight: float = 0.3,
    output_weight: float = 0.2,
) -> ValidationFramework:
    """创建简单的验证框架"""
    framework = ValidationFramework()
    framework.add_layer("format", FormatValidator(), format_weight)
    framework.add_layer("behavior", BehaviorValidator(), behavior_weight)
    framework.add_layer("reasoning", ReasoningValidator(), reasoning_weight)
    # output 需要自定义验证器
    return framework
