"""Typed data models for OpenClawProBench."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Dimension(str, Enum):
    TOOL_USE = "tool_use"
    PLANNING = "planning"
    CONSTRAINTS = "constraints"
    ERROR_RECOVERY = "error_recovery"
    SYNTHESIS = "synthesis"
    SAFETY = "safety"


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


class BenchmarkGroup(str, Enum):
    INTELLIGENCE = "intelligence"
    COVERAGE = "coverage"


class BenchmarkStatus(str, Enum):
    ACTIVE = "active"
    INCUBATING = "incubating"


class SignalSource(str, Enum):
    REPLAY = "replay"
    WORKSPACE_LIVE = "workspace_live"
    OPENCLAW_NATIVE = "openclaw_native"


class CheckCategory(str, Enum):
    SAFETY = "safety"
    CORRECTNESS = "correctness"
    EFFICIENCY = "efficiency"
    PROCESS = "process"


DIFFICULTY_WEIGHTS: dict[Difficulty, float] = {
    Difficulty.EASY: 1.0,
    Difficulty.MEDIUM: 2.0,
    Difficulty.HARD: 4.0,
    Difficulty.EXPERT: 8.0,
}

DIMENSION_WEIGHTS: dict[Dimension, float] = {
    Dimension.TOOL_USE: 0.20,
    Dimension.PLANNING: 0.20,
    Dimension.CONSTRAINTS: 0.15,
    Dimension.ERROR_RECOVERY: 0.15,
    Dimension.SYNTHESIS: 0.15,
    Dimension.SAFETY: 0.15,
}


@dataclass
class CheckSpec:
    check_id: str
    check_type: str
    points: float
    category: CheckCategory
    description: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    severity: str = "major"  # critical / major / minor — used for safety gate grading (P2-1, 2026-03-25)


@dataclass
class Scenario:
    scenario_id: str
    name: str
    dimension: Dimension
    difficulty: Difficulty
    benchmark_group: BenchmarkGroup
    benchmark_status: BenchmarkStatus
    signal_source: SignalSource
    benchmark_core: bool
    weight: float
    timeout_seconds: int
    optimal_steps: int
    prompt: str
    tools: list[str]
    checks: list[CheckSpec]
    source_path: Path
    tags: list[str] = field(default_factory=list)
    openclaw_surfaces: list[str] = field(default_factory=list)
    pass_threshold: float = 0.6
    expected_tools: list[str] = field(default_factory=list)
    ideal_tool_sequence: list[str] = field(default_factory=list)
    mock_responses: dict[str, Any] = field(default_factory=dict)
    fault_injection: list[dict[str, Any]] = field(default_factory=list)
    fixtures: dict[str, str] = field(default_factory=dict)
    workspace_files: list[dict[str, Any] | str] = field(default_factory=list)
    workspace_seed_dir: str | None = None
    setup_script: str | None = None
    teardown_script: str | None = None
    replay_traces: dict[str, Path] = field(default_factory=dict)
    custom_check: str | None = None
    execution_mode: str = "replay"
    efficiency_penalty_cap: float | None = None
    efficiency_penalty_rate: float | None = None

    @property
    def base_difficulty_weight(self) -> float:
        return DIFFICULTY_WEIGHTS[self.difficulty]

    @property
    def effective_weight(self) -> float:
        return self.weight * self.base_difficulty_weight

    @property
    def difficulty_weight(self) -> float:
        return self.effective_weight


@dataclass
class CheckResult:
    check_id: str
    check_type: str
    category: CheckCategory
    points: float
    earned: float
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "check_type": self.check_type,
            "category": self.category.value,
            "points": round(self.points, 4),
            "earned": round(self.earned, 4),
            "passed": self.passed,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CheckResult":
        return cls(
            check_id=str(raw.get("check_id", "")),
            check_type=str(raw.get("check_type", "")),
            category=CheckCategory(str(raw.get("category", "correctness"))),
            points=float(raw.get("points", 0.0)),
            earned=float(raw.get("earned", 0.0)),
            passed=bool(raw.get("passed", False)),
            detail=str(raw.get("detail", "")),
        )


@dataclass
class ScoreBreakdown:
    correctness_score: float
    process_score: float
    capability_score: float
    efficiency_penalty: float
    efficiency_score: float
    safety_gate: float
    final_score: float
    safety_passed: bool
    check_results: list[CheckResult]
    safety_failures: list[str]
    correctness_points_earned: float
    correctness_points_total: float


@dataclass
class TrialExecution:
    mode: str = "replay"
    status: str = "success"
    exit_code: int = 0
    error_detail: str = ""
    agent_id: str = ""
    session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "status": self.status,
            "exit_code": self.exit_code,
            "error_detail": self.error_detail,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TrialExecution":
        raw = raw or {}
        return cls(
            mode=str(raw.get("mode", "replay")),
            status=str(raw.get("status", "success")),
            exit_code=int(raw.get("exit_code", 0) or 0),
            error_detail=str(raw.get("error_detail", "")),
            agent_id=str(raw.get("agent_id", "")),
            session_id=str(raw.get("session_id", "")),
        )


@dataclass
class TrialResult:
    trial_id: int
    score: float
    capability_score: float
    passed: bool
    safety_passed: bool
    checks: list[CheckResult]
    process_score: float
    efficiency_score: float
    efficiency_penalty: float
    latency_ms: float
    token_usage: dict[str, Any]
    transcript: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    audit_state: dict[str, Any]
    execution: TrialExecution = field(default_factory=TrialExecution)
    safety_failures: list[str] = field(default_factory=list)
    workspace_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "score": round(self.score, 4),
            "capability_score": round(self.capability_score, 4),
            "passed": self.passed,
            "safety_passed": self.safety_passed,
            "process_score": round(self.process_score, 4),
            "efficiency_score": round(self.efficiency_score, 4),
            "efficiency_penalty": round(self.efficiency_penalty, 4),
            "latency_ms": round(self.latency_ms, 2),
            "token_usage": dict(self.token_usage),
            "tool_calls": list(self.tool_calls),
            "audit_state": dict(self.audit_state),
            "execution": self.execution.to_dict(),
            "safety_failures": list(self.safety_failures),
            "workspace_path": self.workspace_path,
            "transcript": list(self.transcript),
            "transcript_missing": len(self.transcript) == 0,
            "checks": [check.to_dict() for check in self.checks],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TrialResult":
        return cls(
            trial_id=int(raw.get("trial_id", 0)),
            score=float(raw.get("score", 0.0)),
            capability_score=float(raw.get("capability_score", raw.get("score", 0.0))),
            passed=bool(raw.get("passed", False)),
            safety_passed=bool(raw.get("safety_passed", False)),
            checks=[CheckResult.from_dict(item) for item in raw.get("checks", [])],
            process_score=float(raw.get("process_score", 0.0)),
            efficiency_score=float(raw.get("efficiency_score", 0.0)),
            efficiency_penalty=float(raw.get("efficiency_penalty", 0.0)),
            latency_ms=float(raw.get("latency_ms", 0.0)),
            token_usage=dict(raw.get("token_usage", {})),
            transcript=list(raw.get("transcript", [])),
            tool_calls=list(raw.get("tool_calls", [])),
            audit_state=dict(raw.get("audit_state", {})),
            execution=TrialExecution.from_dict(raw.get("execution", {})),
            safety_failures=list(raw.get("safety_failures", [])),
            workspace_path=raw.get("workspace_path"),
        )


@dataclass
class ScenarioResult:
    scenario_id: str
    name: str
    dimension: Dimension
    difficulty: Difficulty
    benchmark_group: BenchmarkGroup
    benchmark_core: bool
    trials: list[TrialResult]
    avg_score: float
    max_score: float
    capability_score: float
    pass_rate: float
    pass_at_k_any: bool
    pass_count: int
    trial_count: int
    strict_pass_k: bool
    consistency: float
    avg_latency_ms: float
    total_tokens: dict[str, Any]
    cost_estimate_usd: float
    difficulty_weight: float
    execution_mode: str = "replay"
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "dimension": self.dimension.value,
            "difficulty": self.difficulty.value,
            "benchmark_group": self.benchmark_group.value,
            "benchmark_core": self.benchmark_core,
            "avg_score": round(self.avg_score, 4),
            "max_score": round(self.max_score, 4),
            "capability_score": round(self.capability_score, 4),
            "pass_rate": round(self.pass_rate, 4),
            "pass_at_k_any": self.pass_at_k_any,
            "pass_count": self.pass_count,
            "trial_count": self.trial_count,
            "strict_pass_k": self.strict_pass_k,
            "consistency": round(self.consistency, 6),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "total_tokens": dict(self.total_tokens),
            "cost_estimate_usd": round(self.cost_estimate_usd, 8),
            "difficulty_weight": round(self.difficulty_weight, 4),
            "execution_mode": self.execution_mode,
            "stats": dict(self.stats),
            "transcript_missing_trials": sum(1 for t in self.trials if not t.transcript),
            "trials": [trial.to_dict() for trial in self.trials],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ScenarioResult":
        trials = [TrialResult.from_dict(item) for item in raw.get("trials", [])]
        execution_mode = str(raw.get("execution_mode", "")).strip()
        if not execution_mode and trials:
            execution_mode = trials[0].execution.mode
        return cls(
            scenario_id=str(raw.get("scenario_id", "")),
            name=str(raw.get("name", raw.get("scenario_id", ""))),
            dimension=Dimension(str(raw.get("dimension", "tool_use"))),
            difficulty=Difficulty(str(raw.get("difficulty", "medium"))),
            benchmark_group=BenchmarkGroup(str(raw.get("benchmark_group", "intelligence"))),
            benchmark_core=bool(raw.get("benchmark_core", False)),
            trials=trials,
            avg_score=float(raw.get("avg_score", 0.0)),
            max_score=float(raw.get("max_score", raw.get("avg_score", 0.0))),
            capability_score=float(raw.get("capability_score", raw.get("avg_score", 0.0))),
            pass_rate=float(raw.get("pass_rate", 0.0)),
            pass_at_k_any=bool(raw.get("pass_at_k_any", raw.get("pass_rate", 0.0) > 0.0)),
            pass_count=int(raw.get("pass_count", 0)),
            trial_count=int(raw.get("trial_count", len(trials))),
            strict_pass_k=bool(raw.get("strict_pass_k", False)),
            consistency=float(raw.get("consistency", 0.0)),
            avg_latency_ms=float(raw.get("avg_latency_ms", 0.0)),
            total_tokens=dict(raw.get("total_tokens", {})),
            cost_estimate_usd=float(raw.get("cost_estimate_usd", 0.0)),
            difficulty_weight=float(raw.get("difficulty_weight", 1.0)),
            execution_mode=execution_mode or "replay",
            stats=dict(raw.get("stats", {})),
        )


@dataclass
class DimensionScore:
    dimension: Dimension
    score: float
    capability_score: float
    scenario_count: int
    pass_at_1: float
    pass_at_k_any: float
    strict_pass_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "score": round(self.score, 4),
            "capability_score": round(self.capability_score, 4),
            "scenario_count": self.scenario_count,
            "pass_at_1": round(self.pass_at_1, 4),
            "pass_at_k_any": round(self.pass_at_k_any, 4),
            "strict_pass_rate": round(self.strict_pass_rate, 4),
            "weight": DIMENSION_WEIGHTS[self.dimension],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DimensionScore":
        return cls(
            dimension=Dimension(str(raw.get("dimension", "tool_use"))),
            score=float(raw.get("score", 0.0)),
            capability_score=float(raw.get("capability_score", raw.get("score", 0.0))),
            scenario_count=int(raw.get("scenario_count", 0)),
            pass_at_1=float(raw.get("pass_at_1", 0.0)),
            pass_at_k_any=float(raw.get("pass_at_k_any", 0.0)),
            strict_pass_rate=float(raw.get("strict_pass_rate", 0.0)),
        )


@dataclass
class BenchmarkResult:
    model: str
    dimensions: dict[str, DimensionScore]
    overall_score: float
    capability_score: float
    efficiency_score: float
    total_scenarios: int
    passed_scenarios: int
    strict_pass_rate: float
    avg_latency_ms: float
    total_tokens: dict[str, Any]
    cost_estimate_usd: float
    timestamp: str
    scenarios: list[ScenarioResult]
    trials_per_scenario: int
    aggregate_stats: dict[str, Any] = field(default_factory=dict)
    cost_efficiency: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    resume: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "overall_score": round(self.overall_score, 4),
            "capability_score": round(self.capability_score, 4),
            "efficiency_score": round(self.efficiency_score, 4),
            "total_scenarios": self.total_scenarios,
            "passed_scenarios": self.passed_scenarios,
            "strict_pass_rate": round(self.strict_pass_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "total_tokens": dict(self.total_tokens),
            "cost_estimate_usd": round(self.cost_estimate_usd, 8),
            "timestamp": self.timestamp,
            "trials_per_scenario": self.trials_per_scenario,
            "aggregate_stats": dict(self.aggregate_stats),
            "cost_efficiency": dict(self.cost_efficiency),
            "coverage": dict(self.coverage),
            "resume": dict(self.resume),
            "summary": dict(self.summary),
            "dimensions": {
                name: dimension.to_dict() for name, dimension in self.dimensions.items()
            },
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BenchmarkResult":
        return cls(
            model=str(raw.get("model", "")),
            dimensions={
                str(name): DimensionScore.from_dict(value)
                for name, value in dict(raw.get("dimensions", {})).items()
            },
            overall_score=float(raw.get("overall_score", 0.0)),
            capability_score=float(raw.get("capability_score", raw.get("overall_score", 0.0))),
            efficiency_score=float(raw.get("efficiency_score", 0.0)),
            total_scenarios=int(raw.get("total_scenarios", 0)),
            passed_scenarios=int(raw.get("passed_scenarios", 0)),
            strict_pass_rate=float(raw.get("strict_pass_rate", 0.0)),
            avg_latency_ms=float(raw.get("avg_latency_ms", 0.0)),
            total_tokens=dict(raw.get("total_tokens", {})),
            cost_estimate_usd=float(raw.get("cost_estimate_usd", 0.0)),
            timestamp=str(raw.get("timestamp", "")),
            scenarios=[ScenarioResult.from_dict(item) for item in raw.get("scenarios", [])],
            trials_per_scenario=int(raw.get("trials_per_scenario", 0)),
            aggregate_stats=dict(raw.get("aggregate_stats", {})),
            cost_efficiency=dict(raw.get("cost_efficiency", {})),
            coverage=dict(raw.get("coverage", {})),
            resume=dict(raw.get("resume", {})),
            summary=dict(raw.get("summary", {})),
        )
