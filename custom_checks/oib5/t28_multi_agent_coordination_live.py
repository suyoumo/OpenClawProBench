"""T28: 多Agent协调 — 资源受限的并行任务调度 — 评分脚本（修复版）

修复内容：
1. 支持 task_assignments 字段（模型生成的格式）
2. 修复 JSON 读取逻辑
3. 增强错误处理
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

# 导入统一验证框架
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "frameworks"))
from validation import (
    ValidationFramework,
    ValidationResult,
    Validator,
)


def get_assignments(schedule: dict) -> List[dict]:
    """从 schedule 中获取任务分配，支持多种字段名"""
    # 优先使用 task_assignments（模型生成的格式）
    if "task_assignments" in schedule:
        return schedule["task_assignments"]
    # 兼容 assignments
    elif "assignments" in schedule:
        return schedule["assignments"]
    else:
        return []


class TaskCompletenessValidator(Validator):
    """任务完整性验证器"""

    def __init__(self, max_score: float = 0.15):
        self.max_score = max_score

    def validate(
        self,
        trace: dict,
        workspace: Path,
        tool_calls: List[dict],
    ) -> ValidationResult:
        """验证所有任务都被分配"""
        schedule_file = workspace / "schedule.json"
        tasks_file = workspace / "tasks.json"
        
        if not schedule_file.exists():
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail="Schedule file not found",
            )
        
        if not tasks_file.exists():
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail="Tasks file not found",
            )
        
        try:
            with open(schedule_file) as f:
                schedule = json.load(f)
            with open(tasks_file) as f:
                tasks_data = json.load(f)
            
            # 获取任务列表（支持 tasks 字段或直接数组）
            if isinstance(tasks_data, dict):
                tasks = tasks_data.get("tasks", [])
            elif isinstance(tasks_data, list):
                tasks = tasks_data
            else:
                return ValidationResult(
                    score=0.0,
                    max_score=self.max_score,
                    detail="Invalid tasks file format",
                )
            
            # 获取任务分配
            assignments = get_assignments(schedule)
            
            # 提取已分配的任务 ID
            scheduled_task_ids = set()
            for assignment in assignments:
                task_id = assignment.get("task_id")
                if task_id:
                    scheduled_task_ids.add(task_id)
            
            # 提取需要分配的任务 ID
            required_task_ids = set()
            for task in tasks:
                if isinstance(task, dict):
                    task_id = task.get("id")
                    if task_id:
                        required_task_ids.add(task_id)
            
            if not required_task_ids:
                return ValidationResult(
                    score=0.0,
                    max_score=self.max_score,
                    detail="No tasks found in tasks file",
                )
            
            # 计算覆盖率
            coverage = len(scheduled_task_ids & required_task_ids) / len(required_task_ids)
            missing = required_task_ids - scheduled_task_ids
            
            if missing:
                detail = f"Missing {len(missing)} tasks: {', '.join(list(missing)[:3])}"
            else:
                detail = f"All {len(required_task_ids)} tasks assigned"
            
            return ValidationResult(
                score=self.max_score * coverage,
                max_score=self.max_score,
                detail=detail,
            )
        except Exception as e:
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail=f"Error: {str(e)}",
            )


class DependencyValidator(Validator):
    """依赖关系验证器"""

    def __init__(self, max_score: float = 0.2):
        self.max_score = max_score

    def validate(
        self,
        trace: dict,
        workspace: Path,
        tool_calls: List[dict],
    ) -> ValidationResult:
        """验证任务执行顺序符合依赖关系"""
        schedule_file = workspace / "schedule.json"
        dependencies_file = workspace / "dependencies.json"
        
        if not schedule_file.exists() or not dependencies_file.exists():
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail="Required files not found",
            )
        
        try:
            with open(schedule_file) as f:
                schedule = json.load(f)
            with open(dependencies_file) as f:
                deps_data = json.load(f)
            
            # 获取依赖关系列表
            if isinstance(deps_data, dict):
                dependencies = deps_data.get("dependencies", [])
            elif isinstance(deps_data, list):
                dependencies = deps_data
            else:
                return ValidationResult(
                    score=0.0,
                    max_score=self.max_score,
                    detail="Invalid dependencies file format",
                )
            
            # 获取任务分配
            assignments = get_assignments(schedule)
            
            # 构建任务开始时间映射
            task_times = {}
            for assignment in assignments:
                if isinstance(assignment, dict):
                    task_id = assignment.get("task_id")
                    start_time = assignment.get("start_time", 0)
                    if task_id:
                        task_times[task_id] = start_time
            
            # 检查依赖关系
            violations = []
            checked = 0
            
            for dep in dependencies:
                if not isinstance(dep, dict):
                    continue
                
                task_id = dep.get("task_id")
                depends_on = dep.get("depends_on", [])
                
                if task_id not in task_times:
                    continue
                
                checked += 1
                task_start = task_times[task_id]
                
                for prereq in depends_on:
                    if prereq in task_times:
                        prereq_start = task_times[prereq]
                        if prereq_start >= task_start:
                            violations.append(f"{task_id} starts before {prereq}")
            
            if checked == 0:
                score = 0.0
                detail = "No dependencies checked"
            elif violations:
                score = self.max_score * (1 - len(violations) / checked)
                detail = f"{len(violations)} dependency violations"
            else:
                score = self.max_score
                detail = f"All {checked} dependencies respected"
            
            return ValidationResult(
                score=score,
                max_score=self.max_score,
                detail=detail,
            )
        except Exception as e:
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail=f"Error: {str(e)}",
            )


class ResourceConstraintValidator(Validator):
    """资源约束验证器"""

    def __init__(self, max_score: float = 0.2):
        self.max_score = max_score

    def validate(
        self,
        trace: dict,
        workspace: Path,
        tool_calls: List[dict],
    ) -> ValidationResult:
        """验证资源使用不超过限制"""
        schedule_file = workspace / "schedule.json"
        resources_file = workspace / "resources.json"
        tasks_file = workspace / "tasks.json"
        
        if not all(f.exists() for f in [schedule_file, resources_file, tasks_file]):
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail="Required files not found",
            )
        
        try:
            with open(schedule_file) as f:
                schedule = json.load(f)
            with open(resources_file) as f:
                resources = json.load(f)
            with open(tasks_file) as f:
                tasks_data = json.load(f)
            
            # 获取任务列表
            if isinstance(tasks_data, dict):
                tasks = tasks_data.get("tasks", [])
            elif isinstance(tasks_data, list):
                tasks = tasks_data
            else:
                return ValidationResult(
                    score=0.0,
                    max_score=self.max_score,
                    detail="Invalid tasks file format",
                )
            
            # 构建任务资源需求映射
            task_resources = {}
            for task in tasks:
                if isinstance(task, dict):
                    task_id = task.get("id")
                    if task_id:
                        task_resources[task_id] = task.get("resources", {})
            
            # 获取任务分配
            assignments = get_assignments(schedule)
            
            # 检查每个时间点的资源使用
            time_slots = {}
            for assignment in assignments:
                if not isinstance(assignment, dict):
                    continue
                
                start = assignment.get("start_time", 0)
                duration = assignment.get("duration", 1)
                task_id = assignment.get("task_id")
                
                for t in range(start, start + duration):
                    if t not in time_slots:
                        time_slots[t] = {"cpu": 0, "memory": 0, "bandwidth": 0}
                    
                    task_res = task_resources.get(task_id, {})
                    time_slots[t]["cpu"] += task_res.get("cpu", 0)
                    time_slots[t]["memory"] += task_res.get("memory", 0)
                    time_slots[t]["bandwidth"] += task_res.get("bandwidth", 0)
            
            # 检查是否超过限制
            violations = []
            max_limits = {
                "cpu": resources.get("max_cpu", 100),
                "memory": resources.get("max_memory", 100),
                "bandwidth": resources.get("max_bandwidth", 100),
            }
            
            for time, usage in time_slots.items():
                for resource, value in usage.items():
                    limit = max_limits.get(resource, 100)
                    if value > limit:
                        violations.append(f"t={time}: {resource}={value}>{limit}")
            
            if violations:
                score = max(0, self.max_score * (1 - len(violations) / len(time_slots)))
                detail = f"{len(violations)} resource violations"
            else:
                score = self.max_score
                detail = f"All {len(time_slots)} time slots within limits"
            
            return ValidationResult(
                score=score,
                max_score=self.max_score,
                detail=detail,
            )
        except Exception as e:
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail=f"Error: {str(e)}",
            )


class AgentCapabilityValidator(Validator):
    """Agent能力验证器"""

    def __init__(self, max_score: float = 0.15):
        self.max_score = max_score

    def validate(
        self,
        trace: dict,
        workspace: Path,
        tool_calls: List[dict],
    ) -> ValidationResult:
        """验证任务分配给有能力的agent"""
        schedule_file = workspace / "schedule.json"
        agents_file = workspace / "agents.json"
        tasks_file = workspace / "tasks.json"
        
        if not all(f.exists() for f in [schedule_file, agents_file, tasks_file]):
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail="Required files not found",
            )
        
        try:
            with open(schedule_file) as f:
                schedule = json.load(f)
            with open(agents_file) as f:
                agents_data = json.load(f)
            with open(tasks_file) as f:
                tasks_data = json.load(f)
            
            # 获取 agents 列表
            if isinstance(agents_data, dict):
                agents = agents_data.get("agents", [])
            elif isinstance(agents_data, list):
                agents = agents_data
            else:
                return ValidationResult(
                    score=0.0,
                    max_score=self.max_score,
                    detail="Invalid agents file format",
                )
            
            # 获取 tasks 列表
            if isinstance(tasks_data, dict):
                tasks = tasks_data.get("tasks", [])
            elif isinstance(tasks_data, list):
                tasks = tasks_data
            else:
                return ValidationResult(
                    score=0.0,
                    max_score=self.max_score,
                    detail="Invalid tasks file format",
                )
            
            # 构建能力映射
            agent_caps = {}
            for agent in agents:
                if isinstance(agent, dict):
                    agent_id = agent.get("id")
                    if agent_id:
                        # 支持 agent_id 格式 "agent_001 (Alpha)"
                        agent_id_clean = agent_id.split()[0] if " " in agent_id else agent_id
                        agent_caps[agent_id_clean] = set(agent.get("capabilities", []))
            
            # 构建任务需求映射
            task_reqs = {}
            for task in tasks:
                if isinstance(task, dict):
                    task_id = task.get("id")
                    if task_id:
                        task_reqs[task_id] = set(task.get("required_capabilities", []))
            
            # 获取任务分配
            assignments = get_assignments(schedule)
            
            # 检查能力匹配
            mismatches = []
            total = 0
            
            for assignment in assignments:
                if not isinstance(assignment, dict):
                    continue
                
                task_id = assignment.get("task_id")
                agent_id = assignment.get("assigned_agent", assignment.get("agent_id"))
                
                if task_id in task_reqs and agent_id:
                    # 清理 agent_id 格式
                    agent_id_clean = agent_id.split()[0] if " " in agent_id else agent_id
                    
                    if agent_id_clean in agent_caps:
                        total += 1
                        required = task_reqs[task_id]
                        available = agent_caps[agent_id_clean]
                        
                        if not required.issubset(available):
                            missing = required - available
                            mismatches.append(f"{task_id}→{agent_id}: missing {missing}")
            
            if total == 0:
                score = 0.0
                detail = "No assignments found"
            elif mismatches:
                score = self.max_score * (1 - len(mismatches) / total)
                detail = f"{len(mismatches)} capability mismatches"
            else:
                score = self.max_score
                detail = f"All {total} assignments have required capabilities"
            
            return ValidationResult(
                score=score,
                max_score=self.max_score,
                detail=detail,
            )
        except Exception as e:
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail=f"Error: {str(e)}",
            )


class ScheduleOptimizationValidator(Validator):
    """调度优化验证器"""

    def __init__(self, max_score: float = 0.15):
        self.max_score = max_score

    def validate(
        self,
        trace: dict,
        workspace: Path,
        tool_calls: List[dict],
    ) -> ValidationResult:
        """验证调度方案的优化程度"""
        schedule_file = workspace / "schedule.json"
        
        if not schedule_file.exists():
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail="Schedule file not found",
            )
        
        try:
            with open(schedule_file) as f:
                schedule = json.load(f)
            
            # 从 metadata 中获取 makespan（如果存在）
            if "metadata" in schedule:
                makespan = schedule["metadata"].get("makespan", 0)
                if makespan > 0:
                    # 评分：完成时间越短越好
                    if makespan <= 10:
                        score = self.max_score
                        detail = f"Excellent: {makespan} time units"
                    elif makespan <= 15:
                        score = self.max_score * 0.8
                        detail = f"Good: {makespan} time units"
                    elif makespan <= 20:
                        score = self.max_score * 0.6
                        detail = f"Acceptable: {makespan} time units"
                    else:
                        score = self.max_score * 0.4
                        detail = f"Slow: {makespan} time units"
                    
                    return ValidationResult(
                        score=score,
                        max_score=self.max_score,
                        detail=detail,
                    )
            
            # 如果没有 metadata，从任务分配中计算
            assignments = get_assignments(schedule)
            
            max_end_time = 0
            task_count = 0
            
            for assignment in assignments:
                if isinstance(assignment, dict):
                    start = assignment.get("start_time", 0)
                    duration = assignment.get("duration", 1)
                    end = start + duration
                    max_end_time = max(max_end_time, end)
                    task_count += 1
            
            if task_count == 0:
                return ValidationResult(
                    score=0.0,
                    max_score=self.max_score,
                    detail="No tasks scheduled",
                )
            
            # 评分
            if max_end_time <= 10:
                score = self.max_score
                detail = f"Excellent: {max_end_time} time units"
            elif max_end_time <= 15:
                score = self.max_score * 0.8
                detail = f"Good: {max_end_time} time units"
            elif max_end_time <= 20:
                score = self.max_score * 0.6
                detail = f"Acceptable: {max_end_time} time units"
            else:
                score = self.max_score * 0.4
                detail = f"Slow: {max_end_time} time units"
            
            return ValidationResult(
                score=score,
                max_score=self.max_score,
                detail=detail,
            )
        except Exception as e:
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail=f"Error: {str(e)}",
            )


class LoadBalanceValidator(Validator):
    """负载均衡验证器"""

    def __init__(self, max_score: float = 0.15):
        self.max_score = max_score

    def validate(
        self,
        trace: dict,
        workspace: Path,
        tool_calls: List[dict],
    ) -> ValidationResult:
        """验证agent负载分布"""
        schedule_file = workspace / "schedule.json"
        agents_file = workspace / "agents.json"
        
        if not all(f.exists() for f in [schedule_file, agents_file]):
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail="Required files not found",
            )
        
        try:
            with open(schedule_file) as f:
                schedule = json.load(f)
            with open(agents_file) as f:
                agents_data = json.load(f)
            
            # 获取 agents 列表
            if isinstance(agents_data, dict):
                agents = agents_data.get("agents", [])
            elif isinstance(agents_data, list):
                agents = agents_data
            else:
                return ValidationResult(
                    score=0.0,
                    max_score=self.max_score,
                    detail="Invalid agents file format",
                )
            
            # 统计每个agent的任务数量
            agent_load = {}
            for agent in agents:
                if isinstance(agent, dict):
                    agent_id = agent.get("id")
                    if agent_id:
                        agent_load[agent_id] = 0
            
            # 获取任务分配
            assignments = get_assignments(schedule)
            
            for assignment in assignments:
                if isinstance(assignment, dict):
                    agent_id = assignment.get("assigned_agent", assignment.get("agent_id"))
                    if agent_id:
                        # 清理 agent_id 格式
                        agent_id_clean = agent_id.split()[0] if " " in agent_id else agent_id
                        if agent_id_clean in agent_load:
                            agent_load[agent_id_clean] += 1
            
            if not agent_load:
                return ValidationResult(
                    score=0.0,
                    max_score=self.max_score,
                    detail="No agent assignments",
                )
            
            # 计算负载均衡度（标准差）
            loads = list(agent_load.values())
            avg_load = sum(loads) / len(loads)
            
            if avg_load == 0:
                score = 0.0
                detail = "No tasks assigned"
            else:
                variance = sum((l - avg_load) ** 2 for l in loads) / len(loads)
                std_dev = variance ** 0.5
                cv = std_dev / avg_load  # 变异系数
                
                # 评分：变异系数越小越好
                if cv <= 0.2:
                    score = self.max_score
                    detail = f"Excellent balance (CV={cv:.2f})"
                elif cv <= 0.4:
                    score = self.max_score * 0.7
                    detail = f"Good balance (CV={cv:.2f})"
                elif cv <= 0.6:
                    score = self.max_score * 0.5
                    detail = f"Fair balance (CV={cv:.2f})"
                else:
                    score = self.max_score * 0.3
                    detail = f"Poor balance (CV={cv:.2f})"
            
            return ValidationResult(
                score=score,
                max_score=self.max_score,
                detail=detail,
            )
        except Exception as e:
            return ValidationResult(
                score=0.0,
                max_score=self.max_score,
                detail=f"Error: {str(e)}",
            )


def grade(workspace: str, trace: dict) -> dict:
    """主评分函数 - 使用统一验证框架"""

    # 创建验证框架
    framework = ValidationFramework()

    # 第一层：任务完整性 (0-0.15)
    framework.add_layer(
        "task_completeness",
        TaskCompletenessValidator(max_score=0.15),
        weight=0.15,
    )

    # 第二层：依赖关系 (0-0.2)
    framework.add_layer(
        "dependencies",
        DependencyValidator(max_score=0.2),
        weight=0.2,
    )

    # 第三层：资源约束 (0-0.2)
    framework.add_layer(
        "resource_constraints",
        ResourceConstraintValidator(max_score=0.2),
        weight=0.2,
    )

    # 第四层：Agent能力 (0-0.15)
    framework.add_layer(
        "agent_capabilities",
        AgentCapabilityValidator(max_score=0.15),
        weight=0.15,
    )

    # 第五层：调度优化 (0-0.15)
    framework.add_layer(
        "schedule_optimization",
        ScheduleOptimizationValidator(max_score=0.15),
        weight=0.15,
    )

    # 第六层：负载均衡 (0-0.15)
    framework.add_layer(
        "load_balance",
        LoadBalanceValidator(max_score=0.15),
        weight=0.15,
    )

    # 执行验证
    result = framework.validate(trace, workspace, [])

    return {
        "checkpoints": result["checkpoints"],
        "safety_violations": [],
    }


def grade_process(trace: dict) -> float:
    read_count = 0
    wrote_json = False
    for e in trace.get("events", []):
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args") or {}
        if tool in ("read", "Read"):
            read_count += 1
        if tool in ("write", "Write"):
            path = str(args.get("path", "") or args.get("file_path", ""))
            if path.endswith(".json"):
                wrote_json = True
    if read_count >= 3 and wrote_json:
        return 1.0
    if read_count >= 1 and wrote_json:
        return 0.7
    return 0.3
