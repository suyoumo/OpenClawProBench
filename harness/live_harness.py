"""Real OpenClaw execution harness for OpenClawProBench live scenarios."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
import os
from queue import Queue
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

from .openclaw_native import extract_json_payload
from .trace import _normalize_usage, normalize_trace


DEFAULT_LIVE_PREFLIGHT_TIMEOUT_SECONDS = 90
DEFAULT_LIVE_PREFLIGHT_ATTEMPTS = 3
DEFAULT_GATEWAY_STARTUP_TIMEOUT_SECONDS = 60


@dataclass
class LiveRunResult:
    status: str = "pending"
    exit_code: int = -1
    error_detail: str = ""
    stdout: str = ""
    stderr: str = ""
    trace: dict[str, Any] = field(default_factory=dict)
    raw_transcript: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    workspace_path: str = ""
    agent_id: str = ""
    session_id: str = ""


@dataclass
class AuthProfileCopyResult:
    source_exists: bool
    requested_providers: set[str]
    copied_profile_count: int = 0
    target_path: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_exists": self.source_exists,
            "requested_providers": sorted(self.requested_providers),
            "copied_profile_count": self.copied_profile_count,
            "target_path": self.target_path,
            "reason": self.reason,
        }


@dataclass
class LivePreflightResult:
    ok: bool
    exit_code: int = 0
    error_detail: str = ""
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "error_detail": self.error_detail,
            "duration_seconds": round(self.duration_seconds, 4),
        }


@dataclass
class AgentPoolSlot:
    slot_id: str
    workspace_path: Path
    harness: Any = None


class OpenClawLiveHarness:
    _DEEPSEEK_V4_MODELS: list[dict[str, Any]] = [
        {
            "id": "deepseek-v4-pro",
            "name": "deepseek-v4-pro",
            "reasoning": True,
            "input": ["text"],
            "contextWindow": 1_048_576,
            "maxTokens": 262_144,
            "compat": {
                "supportsReasoningEffort": True,
                "supportsUsageInStreaming": True,
            },
        },
        {
            "id": "deepseek-v4-flash",
            "name": "deepseek-v4-flash",
            "reasoning": True,
            "input": ["text"],
            "contextWindow": 1_048_576,
            "maxTokens": 262_144,
            "compat": {
                "supportsReasoningEffort": True,
                "supportsUsageInStreaming": True,
            },
        },
    ]

    def __init__(
        self,
        openclaw_bin: str = "openclaw",
        cleanup_agents: bool = False,
        use_local_agent: bool = False,
        openclaw_profile: str | None = None,
        openclaw_state_dir: str | None = None,
        openclaw_config_path: str | None = None,
        openclaw_gateway_port: int | None = None,
        progress_callback: Callable[[str], None] | None = None,
        progress_interval_seconds: int = 60,
        agent_pool_size: int = 0,
    ) -> None:
        self.openclaw_bin = openclaw_bin
        self.cleanup_agents = cleanup_agents
        self.use_local_agent = use_local_agent
        self.openclaw_profile = str(openclaw_profile or "").strip() or None
        self.openclaw_state_dir = str(openclaw_state_dir or "").strip() or None
        self.openclaw_config_path = str(openclaw_config_path or "").strip() or None
        self.openclaw_gateway_port = int(openclaw_gateway_port) if openclaw_gateway_port else None
        self.progress_callback = progress_callback
        self.progress_interval_seconds = max(progress_interval_seconds, 1)
        self.agent_pool_size = max(int(agent_pool_size or 0), 0)
        self._derived_openclaw_profile = self._derive_isolated_profile()
        self.command_env = self._build_command_env()
        self._gateway_process: subprocess.Popen[str] | None = None
        self._state_seed_lock = threading.Lock()
        self._agent_registry_lock = threading.RLock()
        self._agent_pool_lock = threading.Lock()
        self._agent_pool_queue: Queue = Queue()
        self._agent_pool_model: str | None = None
        self._agent_pool_slots: list[AgentPoolSlot] = []
        self._pooled_runtime_agent_ids: set[str] = set()

    def preflight(
        self,
        timeout: int | None = None,
        max_attempts: int | None = None,
    ) -> LivePreflightResult:
        timeout = self._configured_positive_int(
            "OPENCLAW_LIVE_PREFLIGHT_TIMEOUT_SECONDS",
            DEFAULT_LIVE_PREFLIGHT_TIMEOUT_SECONDS if timeout is None else timeout,
        )
        max_attempts = self._configured_positive_int(
            "OPENCLAW_LIVE_PREFLIGHT_ATTEMPTS",
            DEFAULT_LIVE_PREFLIGHT_ATTEMPTS if max_attempts is None else max_attempts,
        )
        self._ensure_isolated_state_seeded()
        start = time.monotonic()
        last_stdout = ""
        last_stderr = ""
        last_exit_code = -1
        final_error_detail = ""
        attempt_summaries: list[str] = []
        gateway_bootstrap_attempted = False
        for attempt in range(1, max(max_attempts, 1) + 1):
            attempt_start = time.monotonic()
            stdout = ""
            stderr = ""
            exit_code = -1
            try:
                stdout, stderr, exit_code, payload = self._run_preflight_agents_list(timeout=timeout)
                ok = exit_code == 0
                error_detail = self._build_error_detail(
                    status="success" if ok else "error",
                    exit_code=exit_code,
                    stderr=stderr,
                    stdout=stdout,
                    payload=payload,
                )
                attempt_summaries.append(
                    f"attempt={attempt} exit_code={exit_code} duration_s={time.monotonic() - attempt_start:.2f}"
                )
                final_error_detail = error_detail
                if ok:
                    return LivePreflightResult(
                        ok=True,
                        exit_code=exit_code,
                        error_detail="; ".join(attempt_summaries) if attempt > 1 else error_detail,
                        stdout=stdout,
                        stderr=stderr,
                        duration_seconds=time.monotonic() - start,
                    )
                if (
                    not gateway_bootstrap_attempted
                    and self._should_attempt_gateway_bootstrap(stderr=stderr, stdout=stdout, payload=payload)
                ):
                    gateway_bootstrap_attempted = True
                    bootstrap_ok = self._ensure_gateway_ready(startup_timeout=min(timeout, 20))
                    attempt_summaries.append(
                        f"attempt={attempt} gateway_bootstrap={'ok' if bootstrap_ok else 'failed'}"
                    )
                    if bootstrap_ok:
                        retry_result = subprocess.run(
                            [self.openclaw_bin, "agents", "list", "--json"],
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=timeout,
                            env=self.command_env,
                        )
                        stdout = retry_result.stdout
                        stderr = retry_result.stderr
                        stdout, stderr = self._clean_openclaw_command_streams(stdout, stderr)
                        exit_code = int(retry_result.returncode or 0)
                        payload = self._parse_json_payload(stdout)
                        ok = exit_code == 0
                        error_detail = self._build_error_detail(
                            status="success" if ok else "error",
                            exit_code=exit_code,
                            stderr=stderr,
                            stdout=stdout,
                            payload=payload,
                        )
                        final_error_detail = error_detail
                        if ok:
                            attempt_summaries.append(
                                f"attempt={attempt} post_bootstrap_exit_code={exit_code} duration_s={time.monotonic() - attempt_start:.2f}"
                            )
                            return LivePreflightResult(
                                ok=True,
                                exit_code=exit_code,
                                error_detail="; ".join(attempt_summaries),
                                stdout=stdout,
                                stderr=stderr,
                                duration_seconds=time.monotonic() - start,
                            )
                last_stdout = stdout
                last_stderr = stderr
                last_exit_code = exit_code
            except subprocess.TimeoutExpired as exc:
                attempt_summaries.append(
                    f"attempt={attempt} timeout_s={timeout} duration_s={time.monotonic() - attempt_start:.2f}"
                )
                last_stdout = self._timeout_stream_text(exc.output) or stdout
                last_stderr = self._timeout_stream_text(exc.stderr) or stderr
                last_exit_code = -1
                if not gateway_bootstrap_attempted and self._should_attempt_gateway_bootstrap_after_timeout():
                    gateway_bootstrap_attempted = True
                    bootstrap_timeout = self._configured_positive_int(
                        "OPENCLAW_GATEWAY_STARTUP_TIMEOUT_SECONDS",
                        max(DEFAULT_GATEWAY_STARTUP_TIMEOUT_SECONDS, timeout),
                    )
                    bootstrap_ok = self._ensure_gateway_ready(startup_timeout=bootstrap_timeout)
                    attempt_summaries.append(
                        f"attempt={attempt} gateway_bootstrap_after_timeout={'ok' if bootstrap_ok else 'failed'}"
                    )
                    if bootstrap_ok:
                        try:
                            stdout, stderr, exit_code, payload = self._run_preflight_agents_list(timeout=timeout)
                            ok = exit_code == 0
                            error_detail = self._build_error_detail(
                                status="success" if ok else "error",
                                exit_code=exit_code,
                                stderr=stderr,
                                stdout=stdout,
                                payload=payload,
                            )
                            final_error_detail = error_detail
                            attempt_summaries.append(
                                f"attempt={attempt} post_timeout_bootstrap_exit_code={exit_code} "
                                f"duration_s={time.monotonic() - attempt_start:.2f}"
                            )
                            last_stdout = stdout
                            last_stderr = stderr
                            last_exit_code = exit_code
                            if ok:
                                return LivePreflightResult(
                                    ok=True,
                                    exit_code=exit_code,
                                    error_detail="; ".join(attempt_summaries),
                                    stdout=stdout,
                                    stderr=stderr,
                                    duration_seconds=time.monotonic() - start,
                                )
                        except subprocess.TimeoutExpired as retry_exc:
                            attempt_summaries.append(
                                f"attempt={attempt} post_timeout_bootstrap_timeout_s={timeout} "
                                f"duration_s={time.monotonic() - attempt_start:.2f}"
                            )
                            last_stdout = self._timeout_stream_text(retry_exc.output) or last_stdout
                            last_stderr = self._timeout_stream_text(retry_exc.stderr) or last_stderr
            except Exception as exc:  # pragma: no cover - integration failure path
                attempt_summaries.append(
                    f"attempt={attempt} exception={str(exc)} duration_s={time.monotonic() - attempt_start:.2f}"
                )
                last_stdout = stdout
                last_stderr = str(exc)
                last_exit_code = -1
            if attempt < max_attempts:
                time.sleep(1)
        detail = final_error_detail or "OpenClaw live preflight timed out"
        if attempt_summaries and "timed out" in detail.lower():
            detail = f"{detail}; {'; '.join(attempt_summaries)}"
        return LivePreflightResult(
            ok=False,
            exit_code=last_exit_code,
            error_detail=detail,
            stdout=last_stdout,
            stderr=last_stderr,
            duration_seconds=time.monotonic() - start,
        )

    def _run_preflight_agents_list(self, *, timeout: int) -> tuple[str, str, int, dict[str, Any] | None]:
        result = subprocess.run(
            [self.openclaw_bin, "agents", "list", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=self.command_env,
        )
        stdout, stderr = self._clean_openclaw_command_streams(result.stdout, result.stderr)
        exit_code = int(result.returncode or 0)
        payload = self._parse_json_payload(stdout)
        return stdout, stderr, exit_code, payload

    def _configured_positive_int(self, env_key: str, default: int) -> int:
        raw = str(self.command_env.get(env_key, "")).strip()
        if not raw:
            return max(int(default), 1)
        try:
            return max(int(raw), 1)
        except ValueError:
            return max(int(default), 1)

    @staticmethod
    def _timeout_stream_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return str(value)

    def close(self) -> None:
        self._close_agent_pool()
        if self._gateway_process is None:
            return
        proc = self._gateway_process
        self._gateway_process = None
        if proc.poll() is not None:
            return
        self._kill_process_group(proc)

    def execute_turn(
        self,
        model: str,
        prompt: str,
        workspace_path: Path,
        timeout: int = 300,
        expected_workspace_files: list[str] | None = None,
        repair_workspace: Callable[[Path], None] | None = None,
        use_local_agent: bool | None = None,
    ) -> LiveRunResult:
        agent_id = self._make_agent_id(model)
        execution_workspace = workspace_path
        pool_slot: AgentPoolSlot | None = None
        runtime_harness: OpenClawLiveHarness = self
        requested_session_id = f"ocb6-{uuid4().hex[:12]}"
        resolved_session_id = requested_session_id
        effective_local_agent = self.use_local_agent if use_local_agent is None else use_local_agent
        start = time.monotonic()
        stdout = ""
        stderr = ""
        exit_code = -1
        status = "pending"
        error_detail = ""
        raw_transcript: list[dict[str, Any]] = []
        trace: dict[str, Any] = {"events": [], "metrics": {}}
        proc: subprocess.Popen[str] | None = None
        payload: dict[str, Any] | None = None
        command_started = False
        auth_copy_result = AuthProfileCopyResult(source_exists=False, requested_providers=set(), reason="not_started")
        lifecycle_state: dict[str, Any] = {"ensure_ready_phase": "not_started"}
        pooled_runtime_agent_created = False
        workspace_guard: dict[str, Any] = {
            "expected_file_count": len(expected_workspace_files or []),
            "expected_files_sample": list((expected_workspace_files or [])[:10]),
            "initial_workspace_files_sample": self._workspace_file_manifest(workspace_path)[:20],
            "repair_attempts": [],
        }

        try:
            pool_slot = self._acquire_agent_pool_slot(model)
            if pool_slot is not None:
                execution_workspace = pool_slot.workspace_path
                runtime_harness = pool_slot.harness or self
                self._replace_workspace_contents(workspace_path, execution_workspace)
                agent_id = runtime_harness._make_agent_id(model)
                with self._agent_pool_lock:
                    self._pooled_runtime_agent_ids.add(agent_id)
                with runtime_harness._agent_registry_lock:
                    auth_copy_result = runtime_harness._create_agent(agent_id, model, execution_workspace)
                    pooled_runtime_agent_created = True
                    lifecycle_state = runtime_harness._ensure_agent_ready(agent_id)
                lifecycle_state.update(
                    {
                        "ready_signal": "fresh_pool_agent",
                        "agent_pool_size": self.agent_pool_size,
                        "pool_slot_id": pool_slot.slot_id,
                        "pool_workspace": str(execution_workspace),
                        "pool_state_dir": str(runtime_harness._state_dir_path()),
                    }
                )
            else:
                with self._agent_registry_lock:
                    auth_copy_result = self._create_agent(agent_id, model, workspace_path)
                    lifecycle_state = self._ensure_agent_ready(agent_id)
            workspace_guard["repair_attempts"].append(
                self._guard_workspace_visibility(
                    execution_workspace,
                    expected_workspace_files or [],
                    repair_workspace=repair_workspace,
                    phase="post_create",
                )
            )
            self._emit_progress(
                f"live-start agent={agent_id} timeout={timeout}s workspace={execution_workspace}"
            )
            command = self._agent_command(agent_id, prompt, timeout, requested_session_id)
            if effective_local_agent:
                command.append("--local")

            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(execution_workspace),
                text=True,
                preexec_fn=os.setsid,
                env=runtime_harness.command_env,
            )
            command_started = True
            stdout, stderr = self._communicate_with_heartbeat(proc, timeout=timeout, agent_id=agent_id)
            stdout, stderr = self._clean_openclaw_command_streams(stdout, stderr)
            payload = self._parse_command_payload(stdout, stderr)
            if self._is_unknown_agent_error(stderr, stdout, payload):
                with runtime_harness._agent_registry_lock:
                    auth_copy_result = runtime_harness._create_agent(agent_id, model, execution_workspace)
                    pooled_runtime_agent_created = pooled_runtime_agent_created or pool_slot is not None
                    lifecycle_state = runtime_harness._ensure_agent_ready(agent_id)
                workspace_guard["repair_attempts"].append(
                    self._guard_workspace_visibility(
                        execution_workspace,
                        expected_workspace_files or [],
                        repair_workspace=repair_workspace,
                        phase="post_recreate",
                    )
                )
                proc = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(execution_workspace),
                    text=True,
                    preexec_fn=os.setsid,
                    env=runtime_harness.command_env,
                )
                stdout, stderr = self._communicate_with_heartbeat(proc, timeout=timeout, agent_id=agent_id)
                stdout, stderr = self._clean_openclaw_command_streams(stdout, stderr)
                payload = self._parse_command_payload(stdout, stderr)
            resolved_session_id = self._payload_session_id(payload) or requested_session_id
            exit_code = int(proc.returncode or 0)
            status = "success" if exit_code in (0, 255, -1) else "error"
            error_detail = self._build_error_detail(
                status=status,
                exit_code=exit_code,
                stderr=stderr,
                stdout=stdout,
                payload=payload,
            )
        except subprocess.TimeoutExpired:
            self._kill_process_group(proc)
            status = "timeout"
            exit_code = int(proc.returncode) if proc and proc.returncode is not None else -1
            stderr = "OpenClaw agent timed out"
            error_detail = stderr
        except Exception as exc:  # pragma: no cover - integration failure path
            self._kill_process_group(proc)
            status = "error"
            stderr = str(exc)
            error_detail = stderr
        finally:
            duration = time.monotonic() - start
            if command_started:
                raw_transcript = runtime_harness._wait_and_load_transcript(agent_id, resolved_session_id)
            if raw_transcript:
                trace = normalize_trace(
                    raw_transcript,
                    session_metadata=runtime_harness._load_session_metadata(agent_id, resolved_session_id),
                )
            else:
                trace = {"events": [], "metrics": {}, "audit_state": {}}
            metrics = trace.setdefault("metrics", {})
            metrics.setdefault("duration_seconds", round(duration, 2))
            metrics.setdefault("wall_time_s", round(duration, 2))
            self._merge_stdout_payload(trace, payload or self._parse_command_payload(stdout, stderr))
            audit_state = trace.setdefault("audit_state", {})
            audit_state.setdefault("live_runtime", {})
            audit_state["live_runtime"].update(
                {
                    "requested_model": model,
                    "auth_profile_providers": sorted(auth_copy_result.requested_providers),
                    "auth_profile_copy": auth_copy_result.to_dict(),
                    "local_agent": {
                        "default": self.use_local_agent,
                        "override": use_local_agent,
                        "effective": effective_local_agent,
                    },
                    "workspace_guard": workspace_guard,
                    "agent_pool": {
                        "enabled": pool_slot is not None,
                        "pool_size": self.agent_pool_size,
                        "slot_id": pool_slot.slot_id if pool_slot is not None else "",
                        "workspace": str(execution_workspace) if pool_slot is not None else "",
                        "fresh_agent_per_turn": pool_slot is not None,
                    },
                }
            )
            audit_state["agent_lifecycle"] = dict(lifecycle_state)
            model_error = self._model_error_detail(raw_transcript, payload)
            if model_error:
                status = "error"
                if exit_code in (0, 255, -1):
                    exit_code = 1
                error_detail = model_error
            elif self._is_empty_success_trace(status, trace):
                status = "error"
                if exit_code in (0, 255, -1):
                    exit_code = 1
                error_detail = "empty live transcript/tool trace"
            elif self._should_normalize_terminated_exit(status, exit_code, error_detail, trace):
                status = "success"
                exit_code = 0
                error_detail = ""
                audit_state["live_runtime"]["normalized_terminated_exit"] = True
            elif not error_detail:
                error_detail = self._build_error_detail(
                    status=status,
                    exit_code=exit_code,
                    stderr=stderr,
                    stdout=stdout,
                    payload=payload,
                )
            if command_started:
                self._emit_progress(
                    f"live-finish agent={agent_id} status={status} elapsed={duration:.1f}s"
                )
            if pool_slot is not None:
                try:
                    self._replace_workspace_contents(execution_workspace, workspace_path)
                except Exception as exc:
                    status = "error"
                    if exit_code in (0, 255, -1):
                        exit_code = 1
                    error_detail = f"failed to copy pooled workspace back: {exc}"
                finally:
                    if pooled_runtime_agent_created and self.cleanup_agents:
                        runtime_harness._delete_agent(agent_id)
                    self._release_agent_pool_slot(pool_slot)

        return LiveRunResult(
            status=status,
            exit_code=exit_code,
            error_detail=error_detail,
            stdout=stdout,
            stderr=stderr,
            trace=trace,
            raw_transcript=raw_transcript,
            duration_seconds=duration,
            workspace_path=str(workspace_path),
            agent_id=agent_id,
            session_id=resolved_session_id,
        )

    def _workspace_file_manifest(self, workspace_path: Path) -> list[str]:
        if not workspace_path.exists():
            return []
        return sorted(
            str(path.relative_to(workspace_path))
            for path in workspace_path.rglob("*")
            if path.is_file()
        )

    def _acquire_agent_pool_slot(self, model: str) -> AgentPoolSlot | None:
        if self.agent_pool_size <= 0:
            return None
        self._ensure_agent_pool(model)
        return self._agent_pool_queue.get()

    def _release_agent_pool_slot(self, slot: AgentPoolSlot) -> None:
        self._agent_pool_queue.put(slot)

    def _ensure_agent_pool(self, model: str) -> None:
        with self._agent_pool_lock:
            if self._agent_pool_slots:
                if self._agent_pool_model != model:
                    raise RuntimeError(
                        f"OpenClaw agent pool already initialized for {self._agent_pool_model}, not {model}"
                    )
                return

            state_root = self._state_dir_path()
            pool_root = state_root / "agent-pool-workspaces"
            worker_state_root = state_root / "agent-pool-states"
            pool_root.mkdir(parents=True, exist_ok=True)
            worker_state_root.mkdir(parents=True, exist_ok=True)
            base_port_raw = str(self.command_env.get("OPENCLAW_GATEWAY_PORT", "")).strip()
            base_port = int(base_port_raw) if base_port_raw.isdigit() else 0
            slots: list[AgentPoolSlot] = []
            for index in range(1, self.agent_pool_size + 1):
                workspace_path = pool_root / f"worker-{index}"
                workspace_path.mkdir(parents=True, exist_ok=True)
                worker_state_dir = worker_state_root / f"worker-{index}"
                worker_port = base_port + index if base_port else None
                worker_harness = OpenClawLiveHarness(
                    openclaw_bin=self.openclaw_bin,
                    cleanup_agents=self.cleanup_agents,
                    use_local_agent=self.use_local_agent,
                    openclaw_state_dir=str(worker_state_dir),
                    openclaw_config_path=str(worker_state_dir / "openclaw.json"),
                    openclaw_gateway_port=worker_port,
                    progress_callback=self.progress_callback,
                    progress_interval_seconds=self.progress_interval_seconds,
                    agent_pool_size=0,
                )
                worker_harness._ensure_isolated_state_seeded()
                worker_harness._sync_isolated_model_runtime(model)
                worker_harness._ensure_gateway_ready(startup_timeout=15)
                slots.append(
                    AgentPoolSlot(
                        slot_id=f"worker-{index}",
                        workspace_path=workspace_path,
                        harness=worker_harness,
                    )
                )

            for slot in slots:
                self._agent_pool_queue.put(slot)
            self._agent_pool_slots = slots
            self._agent_pool_model = model

    def _close_agent_pool(self) -> None:
        with self._agent_pool_lock:
            for slot in self._agent_pool_slots:
                if slot.harness is not None:
                    slot.harness.close()
            self._agent_pool_slots = []
            self._agent_pool_model = None
            self._agent_pool_queue = Queue()
            self._pooled_runtime_agent_ids = set()

    def _make_pool_agent_id(self, model: str, index: int) -> str:
        slug = model.replace("/", "-").replace(":", "-").replace("_", "-").replace(".", "-").lower()
        state_token = hashlib.sha1(str(self._state_dir_path()).encode("utf-8")).hexdigest()[:8]
        return f"ocb6-{slug}-pool-{state_token}-{index}"

    def _replace_workspace_contents(self, source: Path, target: Path) -> None:
        source = source.resolve(strict=False)
        target = target.resolve(strict=False)
        if source == target:
            return
        if not source.exists():
            raise FileNotFoundError(source)
        target.mkdir(parents=True, exist_ok=True)
        for child in target.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        shutil.copytree(source, target, dirs_exist_ok=True)

    def _guard_workspace_visibility(
        self,
        workspace_path: Path,
        expected_workspace_files: list[str],
        *,
        repair_workspace: Callable[[Path], None] | None,
        phase: str,
    ) -> dict[str, Any]:
        attempt: dict[str, Any] = {
            "phase": phase,
            "expected_file_count": len(expected_workspace_files),
            "workspace_files_before_sample": self._workspace_file_manifest(workspace_path)[:20],
            "missing_before_restore": [],
            "repair_applied": False,
            "repair_error": "",
            "workspace_files_after_sample": [],
            "missing_after_restore": [],
        }
        if not expected_workspace_files:
            attempt["workspace_files_after_sample"] = list(attempt["workspace_files_before_sample"])
            return attempt
        missing_before = [
            relative_path
            for relative_path in expected_workspace_files
            if not (workspace_path / relative_path).exists()
        ]
        attempt["missing_before_restore"] = missing_before
        if missing_before and repair_workspace is not None:
            try:
                repair_workspace(workspace_path)
                attempt["repair_applied"] = True
            except Exception as exc:  # pragma: no cover - integration failure path
                attempt["repair_error"] = str(exc)
        attempt["workspace_files_after_sample"] = self._workspace_file_manifest(workspace_path)[:20]
        attempt["missing_after_restore"] = [
            relative_path
            for relative_path in expected_workspace_files
            if not (workspace_path / relative_path).exists()
        ]
        return attempt

    def delete_agent(self, agent_id: str) -> None:
        if not agent_id:
            return
        with self._agent_pool_lock:
            if agent_id in self._pooled_runtime_agent_ids:
                return
        self._delete_agent(agent_id)

    def probe_agent_lifecycle(self, model: str, workspace_path: Path) -> tuple[bool, str]:
        agent_id = self._make_agent_id(model, suffix="probe")
        try:
            self._create_agent(agent_id, model, workspace_path)
            return True, ""
        except Exception as exc:  # pragma: no cover - exercised through runner tests
            return False, str(exc)
        finally:
            self._delete_agent(agent_id)

    def _communicate_with_heartbeat(
        self,
        proc: subprocess.Popen[str],
        *,
        timeout: int,
        agent_id: str,
    ) -> tuple[str, str]:
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            remaining = timeout - elapsed
            if remaining <= 0:
                raise subprocess.TimeoutExpired(proc.args, timeout)
            try:
                return proc.communicate(timeout=min(self.progress_interval_seconds, remaining))
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    raise subprocess.TimeoutExpired(proc.args, timeout)
                self._emit_progress(
                    f"live-heartbeat agent={agent_id} elapsed={elapsed:.0f}s timeout={timeout}s"
                )

    def _emit_progress(self, message: str) -> None:
        if self.progress_callback is None:
            return
        self.progress_callback(message)

    def _home_dir(self, env: dict[str, str] | None = None) -> Path:
        source_env = env or getattr(self, "command_env", os.environ)
        configured = str(source_env.get("OPENCLAW_HOME", "")).strip()
        if configured:
            return Path(configured).expanduser()
        configured = str(source_env.get("HOME", "")).strip()
        if configured:
            return Path(configured).expanduser()
        return Path.home()

    def _expand_configured_path(self, raw: str, *, env: dict[str, str] | None = None) -> Path:
        value = str(raw or "").strip()
        if not value:
            return Path()
        if value == "~":
            return self._home_dir(env)
        if value.startswith("~/") or value.startswith("~\\"):
            return (self._home_dir(env) / value[2:]).resolve(strict=False)
        return Path(value).expanduser().resolve(strict=False)

    def _state_dir_path(self, env: dict[str, str] | None = None) -> Path:
        source_env = env or self.command_env
        configured_state_dir = str(source_env.get("OPENCLAW_STATE_DIR", "")).strip()
        if configured_state_dir:
            return self._expand_configured_path(configured_state_dir, env=source_env)
        configured_config_path = str(source_env.get("OPENCLAW_CONFIG_PATH", "")).strip()
        if configured_config_path:
            return self._expand_configured_path(configured_config_path, env=source_env).parent
        profile = str(source_env.get("OPENCLAW_PROFILE", "")).strip()
        suffix = ""
        if profile and profile.lower() != "default":
            suffix = f"-{profile}"
        return (self._home_dir(source_env) / f".openclaw{suffix}").resolve(strict=False)

    def isolation_metadata(self) -> dict[str, Any]:
        profile = str(self.command_env.get("OPENCLAW_PROFILE", "")).strip()
        config_path = str(self.command_env.get("OPENCLAW_CONFIG_PATH", "")).strip()
        gateway_port_raw = str(self.command_env.get("OPENCLAW_GATEWAY_PORT", "")).strip()
        return {
            "profile": profile,
            "state_dir": str(self._state_dir_path()),
            "config_path": config_path or str((self._state_dir_path() / "openclaw.json").resolve(strict=False)),
            "gateway_port": int(gateway_port_raw) if gateway_port_raw.isdigit() else None,
        }

    def _default_state_dir_path(self) -> Path:
        return (self._home_dir(self.command_env) / ".openclaw").resolve(strict=False)

    def _config_path(self, env: dict[str, str] | None = None) -> Path:
        source_env = env or self.command_env
        configured = str(source_env.get("OPENCLAW_CONFIG_PATH", "")).strip()
        if configured:
            return self._expand_configured_path(configured, env=source_env)
        return (self._state_dir_path(source_env) / "openclaw.json").resolve(strict=False)

    def _default_config_path(self) -> Path:
        return (self._default_state_dir_path() / "openclaw.json").resolve(strict=False)

    def _default_main_auth_profiles_path(self) -> Path:
        return self._default_state_dir_path() / "agents" / "main" / "agent" / "auth-profiles.json"

    def _derive_isolated_profile(self) -> str | None:
        if self.openclaw_profile:
            return self.openclaw_profile
        if not (self.openclaw_state_dir or self.openclaw_config_path):
            return None
        source = self.openclaw_state_dir or str(Path(self.openclaw_config_path).expanduser().resolve(strict=False).parent)
        normalized_source = str(source).strip()
        if not normalized_source:
            return None
        base_name = Path(normalized_source).name.strip().lower() or "isolated"
        slug = re.sub(r"[^a-z0-9]+", "-", base_name).strip("-") or "isolated"
        digest = hashlib.sha1(normalized_source.encode("utf-8")).hexdigest()[:10]
        return f"bench-{slug}-{digest}"

    def _uses_isolated_state(self) -> bool:
        target_state = self._state_dir_path()
        target_config = self._config_path()
        default_state = self._default_state_dir_path()
        default_config = self._default_config_path()
        return target_state != default_state or target_config != default_config

    def _read_json_file(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _write_json_file(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _isolated_log_file_path(self, env: dict[str, str] | None = None) -> Path:
        return (self._state_dir_path(env) / "logs" / "openclaw.log").resolve(strict=False)

    def _ensure_isolated_logging_config(
        self,
        payload: dict[str, Any],
        *,
        env: dict[str, str] | None = None,
    ) -> bool:
        if not isinstance(payload, dict):
            return False
        logging_config = payload.get("logging")
        if not isinstance(logging_config, dict):
            logging_config = {}
            payload["logging"] = logging_config
        desired_file = str(self._isolated_log_file_path(env))
        if logging_config.get("file") == desired_file:
            return False
        logging_config["file"] = desired_file
        return True

    def _sanitize_isolated_benchmark_config(self, payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False

        changed = False

        plugins = payload.get("plugins")
        if isinstance(plugins, dict):
            allow = plugins.get("allow")
            if isinstance(allow, list):
                next_allow = [item for item in allow if str(item).strip().lower() != "openclaw-lark"]
                if next_allow != allow:
                    plugins["allow"] = next_allow
                    changed = True

            entries = plugins.get("entries")
            if isinstance(entries, dict) and "openclaw-lark" in entries:
                next_entries = dict(entries)
                next_entries.pop("openclaw-lark", None)
                plugins["entries"] = next_entries
                changed = True

            installs = plugins.get("installs")
            if isinstance(installs, dict) and "openclaw-lark" in installs:
                next_installs = dict(installs)
                next_installs.pop("openclaw-lark", None)
                plugins["installs"] = next_installs
                changed = True

        channels = payload.get("channels")
        if isinstance(channels, dict):
            feishu = channels.get("feishu")
            if isinstance(feishu, dict) and feishu.get("enabled") is not False:
                next_feishu = dict(feishu)
                next_feishu["enabled"] = False
                channels["feishu"] = next_feishu
                changed = True

        messages = payload.get("messages")
        if isinstance(messages, dict) and "logging" in messages:
            next_messages = dict(messages)
            next_messages.pop("logging", None)
            if next_messages:
                payload["messages"] = next_messages
            else:
                payload.pop("messages", None)
            changed = True

        gateway = payload.get("gateway")
        if isinstance(gateway, dict):
            tailscale = gateway.get("tailscale")
            if isinstance(tailscale, dict) and tailscale.get("mode") != "off":
                next_tailscale = dict(tailscale)
                next_tailscale["mode"] = "off"
                gateway["tailscale"] = next_tailscale
                changed = True

        hooks = payload.get("hooks")
        if isinstance(hooks, dict):
            internal = hooks.get("internal")
            if isinstance(internal, dict):
                entries = internal.get("entries")
                if isinstance(entries, dict):
                    command_logger = entries.get("command-logger")
                    if isinstance(command_logger, dict) and command_logger.get("enabled") is not False:
                        next_entries = dict(entries)
                        next_command_logger = dict(command_logger)
                        next_command_logger["enabled"] = False
                        next_entries["command-logger"] = next_command_logger
                        internal["entries"] = next_entries
                        changed = True

        agents = payload.get("agents")
        if isinstance(agents, dict) and agents.get("list") != [{"id": "main"}]:
            agents["list"] = [{"id": "main"}]
            changed = True

        cron_dir = self._state_dir_path() / "cron"
        jobs_path = cron_dir / "jobs.json"
        if jobs_path.exists():
            jobs_path.unlink()
            changed = True
        runs_dir = cron_dir / "runs"
        if runs_dir.exists():
            for path in sorted(runs_dir.rglob("*"), reverse=True):
                if path.is_file() or path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            changed = True

        return changed

    def _target_config_needs_seed(self, payload: dict[str, Any] | None) -> bool:
        if not isinstance(payload, dict):
            return True
        models = payload.get("models")
        auth = payload.get("auth")
        providers = models.get("providers") if isinstance(models, dict) else None
        profiles = auth.get("profiles") if isinstance(auth, dict) else None
        return not isinstance(providers, dict) or not providers or not isinstance(profiles, dict) or not profiles

    def _build_seeded_config(
        self,
        source_payload: dict[str, Any],
        target_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        seeded = json.loads(json.dumps(source_payload))
        target_payload = target_payload if isinstance(target_payload, dict) else {}
        target_agents = target_payload.get("agents") if isinstance(target_payload.get("agents"), dict) else {}
        seeded_agents = seeded.get("agents") if isinstance(seeded.get("agents"), dict) else {}
        preserved_defaults = target_agents.get("defaults") if isinstance(target_agents.get("defaults"), dict) else None
        seeded_defaults = seeded_agents.get("defaults") if isinstance(seeded_agents.get("defaults"), dict) else None
        if preserved_defaults:
            agent_defaults = preserved_defaults
        elif seeded_defaults:
            agent_defaults = seeded_defaults
        else:
            agent_defaults = {}
        preserved_list = target_agents.get("list")
        if isinstance(preserved_list, list) and preserved_list:
            agent_list = preserved_list
        else:
            agent_list = [{"id": "main"}]
        seeded["agents"] = {
            "defaults": agent_defaults,
            "list": agent_list,
        }
        for key in ("meta", "messages", "commands"):
            target_value = target_payload.get(key)
            if isinstance(target_value, dict) and target_value:
                seeded[key] = target_value
        return seeded

    def _ensure_isolated_state_seeded(self) -> None:
        if not self._uses_isolated_state():
            return
        with self._state_seed_lock:
            target_state_dir = self._state_dir_path()
            target_config_path = self._config_path()
            source_config_path = self._default_config_path()
            source_auth_profiles_path = self._default_main_auth_profiles_path()
            target_auth_profiles_path = self._global_main_auth_profiles_path()

            target_state_dir.mkdir(parents=True, exist_ok=True)
            target_config_path.parent.mkdir(parents=True, exist_ok=True)
            target_auth_profiles_path.parent.mkdir(parents=True, exist_ok=True)

            target_payload = self._read_json_file(target_config_path)
            source_payload = self._read_json_file(source_config_path)
            config_changed = False
            if self._target_config_needs_seed(target_payload) and source_payload is not None:
                seeded_payload = self._build_seeded_config(source_payload, target_payload)
                target_payload = seeded_payload
                config_changed = True
            if isinstance(target_payload, dict):
                target_state_dir.joinpath("logs").mkdir(parents=True, exist_ok=True)
                config_changed = self._ensure_isolated_logging_config(target_payload) or config_changed
                config_changed = self._sanitize_isolated_benchmark_config(target_payload) or config_changed
            if config_changed and isinstance(target_payload, dict):
                self._write_json_file(target_config_path, target_payload)

            if not target_auth_profiles_path.exists() and source_auth_profiles_path.exists():
                target_auth_profiles_path.write_text(
                    source_auth_profiles_path.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )

    def _resolve_provider_config(
        self,
        config_payload: dict[str, Any] | None,
        provider: str,
    ) -> tuple[str, dict[str, Any]] | None:
        if not isinstance(config_payload, dict):
            return None
        models = config_payload.get("models")
        providers = models.get("providers") if isinstance(models, dict) else None
        if not isinstance(providers, dict):
            return None
        exact = providers.get(provider)
        if isinstance(exact, dict):
            return provider, exact
        normalized_provider = provider.strip().lower()
        for candidate_key, candidate_value in providers.items():
            if not isinstance(candidate_value, dict):
                continue
            if str(candidate_key).strip().lower() == normalized_provider:
                return str(candidate_key), candidate_value
        return None

    def _benchmark_provider_profile_type(
        self,
        provider_config: dict[str, Any],
        existing_profile: dict[str, Any] | None,
    ) -> str:
        existing_type = str(existing_profile.get("type", "")).strip().lower() if isinstance(existing_profile, dict) else ""
        if existing_type in {"api_key", "token"}:
            return existing_type
        provider_auth = str(provider_config.get("auth", "")).strip().lower()
        if provider_auth == "token":
            return "token"
        return "api_key"

    def _resolve_provider_api_key_value(self, raw_api_key: Any) -> str:
        if not isinstance(raw_api_key, str):
            return ""
        candidate = raw_api_key.strip()
        if not candidate:
            return ""
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", candidate):
            env_value = str(self.command_env.get(candidate, "")).strip()
            if env_value:
                return env_value
        return candidate

    def _bootstrap_missing_provider_config(self, provider: str, model: str) -> dict[str, Any] | None:
        normalized_provider = provider.strip().lower()
        normalized_model = model.strip().lower()
        if normalized_provider != "deepseek" or not normalized_model.startswith("deepseek/"):
            return None
        return {
            "baseUrl": "https://api.deepseek.com",
            "apiKey": "DEEPSEEK_API_KEY",
            "api": "openai-completions",
            "models": json.loads(json.dumps(self._DEEPSEEK_V4_MODELS)),
        }

    def _cli_backend_config_for_model(self, model: str) -> tuple[str, dict[str, Any]] | None:
        provider = model.split("/", 1)[0].strip().lower()
        if provider != "codex-cli":
            return None
        command = shutil.which("codex", path=self.command_env.get("PATH")) or "codex"
        return (
            provider,
            {
                "command": command,
                "args": [
                    "exec",
                    "--json",
                    "--config",
                    'model_reasoning_effort="xhigh"',
                    "--color",
                    "never",
                    "--sandbox",
                    "workspace-write",
                    "--skip-git-repo-check",
                ],
                "output": "jsonl",
                "input": "arg",
                "env": {"CODEX_HOME": str(self._home_dir(self.command_env) / ".codex")},
                "modelArg": "--model",
                "sessionMode": "none",
                "sessionIdFields": ["thread_id"],
                "imageArg": "--image",
                "imageMode": "repeat",
                "serialize": False,
            },
        )

    def _ensure_cli_backend_config(self, defaults: dict[str, Any], model: str) -> bool:
        backend = self._cli_backend_config_for_model(model)
        if backend is None:
            return False
        provider, backend_config = backend
        cli_backends = defaults.get("cliBackends")
        changed = False
        if not isinstance(cli_backends, dict):
            cli_backends = {}
            defaults["cliBackends"] = cli_backends
            changed = True
        existing = cli_backends.get(provider)
        if not isinstance(existing, dict):
            cli_backends[provider] = backend_config
            return True
        for key, value in backend_config.items():
            if key == "env" and isinstance(existing.get("env"), dict):
                existing_env = existing["env"]
                for env_key, env_value in value.items():
                    if env_key not in existing_env:
                        existing_env[env_key] = env_value
                        changed = True
                continue
            if key not in existing:
                existing[key] = value
                changed = True
        return changed

    def _sync_isolated_model_runtime(self, model: str) -> None:
        if not self._uses_isolated_state():
            return
        with self._state_seed_lock:
            config_path = self._config_path()
            config_payload = self._read_json_file(config_path)
            if not isinstance(config_payload, dict):
                return

            changed = False
            agents = config_payload.get("agents")
            if not isinstance(agents, dict):
                agents = {}
                config_payload["agents"] = agents
                changed = True

            defaults = agents.get("defaults")
            if not isinstance(defaults, dict):
                defaults = {}
                agents["defaults"] = defaults
                changed = True

            model_config = defaults.get("model")
            if isinstance(model_config, dict):
                next_model_config = dict(model_config)
            else:
                next_model_config = {}
                changed = True
            if next_model_config.get("primary") != model:
                next_model_config["primary"] = model
                changed = True
            if next_model_config.get("fallbacks") != []:
                next_model_config["fallbacks"] = []
                changed = True
            defaults["model"] = next_model_config

            configured_models = defaults.get("models")
            if not isinstance(configured_models, dict):
                configured_models = {}
                defaults["models"] = configured_models
                changed = True
            if model not in configured_models:
                configured_models[model] = {}
                changed = True

            if self._ensure_cli_backend_config(defaults, model):
                changed = True

            provider = model.split("/", 1)[0].strip()
            models_block = config_payload.get("models")
            if not isinstance(models_block, dict):
                models_block = {}
                config_payload["models"] = models_block
                changed = True
            providers_block = models_block.get("providers")
            if not isinstance(providers_block, dict):
                providers_block = {}
                models_block["providers"] = providers_block
                changed = True

            auth_providers = sorted(self._auth_profile_providers_for_model(model))
            auth_provider = auth_providers[0] if auth_providers else provider
            provider_match = self._resolve_provider_config(config_payload, provider)
            if provider_match is None:
                bootstrap_provider_config = self._bootstrap_missing_provider_config(provider, model)
                if bootstrap_provider_config is not None:
                    providers_block[provider] = bootstrap_provider_config
                    provider_match = (provider, bootstrap_provider_config)
                    changed = True
            if provider_match is not None:
                provider_key, provider_config = provider_match
                provider_api_key = self._resolve_provider_api_key_value(provider_config.get("apiKey"))
                if provider_api_key:
                    auth_store_path = self._global_main_auth_profiles_path()
                    auth_store = self._read_json_file(auth_store_path) or {"version": 1, "profiles": {}}
                    profiles = auth_store.get("profiles")
                    if not isinstance(profiles, dict):
                        profiles = {}
                        auth_store["profiles"] = profiles

                    last_good = auth_store.get("lastGood")
                    if not isinstance(last_good, dict):
                        last_good = {}
                        auth_store["lastGood"] = last_good

                    existing_profile_id = str(last_good.get(auth_provider, "")).strip()
                    existing_profile = profiles.get(existing_profile_id)
                    if not isinstance(existing_profile, dict):
                        existing_profile_id = ""
                        existing_profile = None
                    if not existing_profile_id:
                        for candidate_id, candidate_value in profiles.items():
                            if not isinstance(candidate_value, dict):
                                continue
                            if str(candidate_value.get("provider", "")).strip() == auth_provider:
                                existing_profile_id = str(candidate_id)
                                existing_profile = candidate_value
                                break

                    profile_id = existing_profile_id or f"{provider_key}:manual"
                    profile_type = self._benchmark_provider_profile_type(provider_config, existing_profile)
                    updated_profile: dict[str, Any] = {
                        "provider": auth_provider,
                        "type": profile_type,
                    }
                    if isinstance(existing_profile, dict):
                        for field in ("email", "displayName", "metadata"):
                            if field in existing_profile:
                                updated_profile[field] = existing_profile[field]
                    if profile_type == "token":
                        updated_profile["token"] = provider_api_key
                    else:
                        updated_profile["key"] = provider_api_key

                    if profiles.get(profile_id) != updated_profile:
                        profiles[profile_id] = updated_profile
                        changed = True
                    if last_good.get(auth_provider) != profile_id:
                        last_good[auth_provider] = profile_id
                        changed = True

                    usage_stats = auth_store.get("usageStats")
                    if isinstance(usage_stats, dict) and profile_id in usage_stats:
                        del usage_stats[profile_id]
                        changed = True
                        if not usage_stats:
                            auth_store.pop("usageStats", None)

                    auth_config = config_payload.get("auth")
                    if not isinstance(auth_config, dict):
                        auth_config = {}
                        config_payload["auth"] = auth_config
                        changed = True
                    auth_profiles = auth_config.get("profiles")
                    if not isinstance(auth_profiles, dict):
                        auth_profiles = {}
                        auth_config["profiles"] = auth_profiles
                        changed = True
                    expected_profile_config = {
                        "provider": auth_provider,
                        "mode": "token" if profile_type == "token" else "api_key",
                    }
                    if auth_profiles.get(profile_id) != expected_profile_config:
                        auth_profiles[profile_id] = expected_profile_config
                        changed = True

                    if changed:
                        self._write_json_file(auth_store_path, auth_store)

            if changed:
                self._write_json_file(config_path, config_payload)

    def _sync_isolated_agent_runtime(self, agent_id: str, model: str) -> None:
        if not self._uses_isolated_state():
            return
        target_agent_ids = set(self._agent_id_candidates(agent_id))
        if not target_agent_ids:
            return
        with self._state_seed_lock:
            config_path = self._config_path()
            config_payload = self._read_json_file(config_path)
            if not isinstance(config_payload, dict):
                return

            agents = config_payload.get("agents")
            agent_list = agents.get("list") if isinstance(agents, dict) else None
            if not isinstance(agent_list, list):
                return

            changed = False
            for entry in agent_list:
                if not isinstance(entry, dict):
                    continue
                if not (target_agent_ids & self._agent_entry_candidates(entry)):
                    continue
                entry_model = entry.get("model")
                next_model = dict(entry_model) if isinstance(entry_model, dict) else {}
                if next_model.get("primary") != model:
                    next_model["primary"] = model
                    changed = True
                if next_model.get("fallbacks") != []:
                    next_model["fallbacks"] = []
                    changed = True
                if entry.get("model") != next_model:
                    entry["model"] = next_model
                    changed = True

            if changed:
                self._write_json_file(config_path, config_payload)

    def _global_main_auth_profiles_path(self) -> Path:
        return self._state_dir_path() / "agents" / "main" / "agent" / "auth-profiles.json"

    def _auth_profile_providers_for_model(self, model: str) -> set[str]:
        provider = model.split("/", 1)[0].strip().lower()
        if not provider:
            return set()
        if provider.endswith("-cli"):
            return set()
        aliases = {
            "glm": {"zai"},
        }
        return aliases.get(provider, {provider})

    def _copy_auth_profiles(self, agent_id: str, *, providers: set[str] | None = None) -> AuthProfileCopyResult:
        requested_providers = {provider.strip() for provider in (providers or set()) if provider.strip()}
        source = self._global_main_auth_profiles_path()
        if not source.exists():
            return AuthProfileCopyResult(
                source_exists=False,
                requested_providers=requested_providers,
                reason="source_missing",
            )
        normalized = agent_id.strip().lower()
        if not normalized:
            return AuthProfileCopyResult(
                source_exists=True,
                requested_providers=requested_providers,
                reason="invalid_agent_id",
            )
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return AuthProfileCopyResult(
                source_exists=True,
                requested_providers=requested_providers,
                reason="invalid_source_json",
            )
        copied_profile_count = 0
        if requested_providers:
            profiles = payload.get("profiles") if isinstance(payload, dict) else None
            if isinstance(profiles, dict):
                filtered_profiles = {
                    key: value
                    for key, value in profiles.items()
                    if isinstance(value, dict) and str(value.get("provider", "")).strip() in requested_providers
                }
                copied_profile_count = len(filtered_profiles)
                payload = dict(payload)
                payload["profiles"] = filtered_profiles
                last_good = payload.get("lastGood")
                if isinstance(last_good, dict):
                    payload["lastGood"] = {
                        key: value for key, value in last_good.items() if key in requested_providers
                    }
                usage_stats = payload.get("usageStats")
                if isinstance(usage_stats, dict):
                    payload["usageStats"] = {
                        key: value
                        for key, value in usage_stats.items()
                        if isinstance(filtered_profiles.get(key), dict)
                    }
                order = payload.get("order")
                if isinstance(order, dict):
                    filtered_order: dict[str, list[str]] = {}
                    for order_key, order_value in order.items():
                        if not isinstance(order_value, list):
                            continue
                        remaining = [profile_id for profile_id in order_value if profile_id in filtered_profiles]
                        if remaining:
                            filtered_order[str(order_key)] = remaining
                    payload["order"] = filtered_order
                if copied_profile_count == 0:
                    return AuthProfileCopyResult(
                        source_exists=True,
                        requested_providers=requested_providers,
                        copied_profile_count=0,
                        reason="filtered_profiles_empty",
                    )
        target_dir = self._state_dir_path() / "agents" / normalized / "agent"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "auth-profiles.json"
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return AuthProfileCopyResult(
            source_exists=True,
            requested_providers=requested_providers,
            copied_profile_count=copied_profile_count,
            target_path=str(target),
            reason="copied",
        )

    def _build_command_env(self) -> dict[str, str]:
        env = os.environ.copy()
        effective_profile = self._derived_openclaw_profile
        if effective_profile:
            env["OPENCLAW_PROFILE"] = effective_profile
        if (effective_profile or self.openclaw_state_dir or self.openclaw_config_path) and not str(env.get("OPENCLAW_HOME", "")).strip():
            env["OPENCLAW_HOME"] = str(self._home_dir(env))
        if self.openclaw_config_path:
            env["OPENCLAW_CONFIG_PATH"] = self.openclaw_config_path
        if self.openclaw_state_dir:
            env["OPENCLAW_STATE_DIR"] = self.openclaw_state_dir
        elif effective_profile and not str(env.get("OPENCLAW_STATE_DIR", "")).strip():
            env["OPENCLAW_STATE_DIR"] = str(self._state_dir_path(env))
        if not str(env.get("OPENCLAW_CONFIG_PATH", "")).strip() and (
            effective_profile or self.openclaw_state_dir or self.openclaw_config_path
        ):
            env["OPENCLAW_CONFIG_PATH"] = str((self._state_dir_path(env) / "openclaw.json").resolve(strict=False))
        if self.openclaw_gateway_port is not None:
            env["OPENCLAW_GATEWAY_PORT"] = str(self.openclaw_gateway_port)
        elif effective_profile and effective_profile.lower() == "dev" and not str(env.get("OPENCLAW_GATEWAY_PORT", "")).strip():
            env["OPENCLAW_GATEWAY_PORT"] = "19001"
        candidates: list[str] = []
        if env.get("NVM_BIN"):
            candidates.append(env["NVM_BIN"])

        nvm_versions = self._home_dir(env) / ".nvm" / "versions" / "node"
        if nvm_versions.exists():
            preferred = sorted(nvm_versions.glob("v22*/bin"), reverse=True)
            fallback = sorted(nvm_versions.glob("v24*/bin"), reverse=True)
            for path in preferred + fallback:
                candidates.append(str(path))

        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists():
                env["PATH"] = f"{candidate}{os.pathsep}{env.get('PATH', '')}"
                break
        return env

    def _make_agent_id(self, model: str, *, suffix: str = "") -> str:
        slug = model.replace("/", "-").replace(":", "-").replace("_", "-").replace(".", "-").lower()
        token = uuid4().hex[:12]
        suffix_part = f"-{suffix}" if suffix else ""
        return f"ocb6-{slug}-{token}{suffix_part}"

    def _create_agent(self, agent_id: str, model: str, workspace_path: Path) -> AuthProfileCopyResult:
        self._ensure_isolated_state_seeded()
        self._sync_isolated_model_runtime(model)
        subprocess.run(
            [self.openclaw_bin, "agents", "delete", agent_id, "--force"],
            capture_output=True,
            text=True,
            check=False,
            env=self.command_env,
        )
        result = subprocess.run(
            [
                self.openclaw_bin,
                "agents",
                "add",
                agent_id,
                "--model",
                model,
                "--workspace",
                str(workspace_path),
                "--non-interactive",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=self.command_env,
        )
        stdout, stderr = self._clean_openclaw_command_streams(result.stdout, result.stderr)
        if result.returncode != 0:
            detail = stderr.strip() or stdout.strip() or "failed to create agent"
            raise RuntimeError(detail)
        self._sync_isolated_agent_runtime(agent_id, model)
        auth_providers = self._auth_profile_providers_for_model(model)
        copy_result = self._copy_auth_profiles(agent_id, providers=auth_providers)
        if auth_providers and copy_result.reason == "filtered_profiles_empty":
            requested = ", ".join(sorted(auth_providers))
            raise RuntimeError(f"No auth profiles found for providers: {requested}")
        return copy_result

    def _delete_agent(self, agent_id: str) -> None:
        with self._agent_registry_lock:
            subprocess.run(
                [self.openclaw_bin, "agents", "delete", agent_id, "--force"],
                capture_output=True,
                text=True,
                check=False,
                env=self.command_env,
            )

    def _agent_command(self, agent_id: str, prompt: str, timeout: int, session_id: str) -> list[str]:
        return [
            self.openclaw_bin,
            "agent",
            "--agent",
            agent_id,
            "--session-id",
            session_id,
            "--message",
            prompt,
            "--json",
            "--timeout",
            str(timeout),
        ]

    def _run_agents_list(self) -> tuple[int, str, str, list[dict[str, Any]] | None]:
        result = subprocess.run(
            [self.openclaw_bin, "agents", "list", "--json"],
            capture_output=True,
            text=True,
            check=False,
            env=self.command_env,
        )
        stdout, stderr = self._clean_openclaw_command_streams(result.stdout, result.stderr)
        payload = self._parse_agents_list(stdout) if result.returncode == 0 else None
        return result.returncode, stdout, stderr, payload

    def _agent_entry_candidates(self, item: dict[str, Any]) -> set[str]:
        candidates: set[str] = set()
        for key in ("id", "agentId", "name"):
            value = item.get(key)
            if isinstance(value, str):
                candidates.update(self._agent_id_candidates(value))
        return candidates

    def _agent_state_ready(self, agent_id: str) -> tuple[bool, bool]:
        sessions_dir = self._agent_sessions_dir(agent_id)
        sessions_exists = sessions_dir.exists()
        workspace_exists = False
        if sessions_exists:
            workspace_candidate = sessions_dir.parent / "workspace"
            workspace_exists = workspace_candidate.exists()
        return sessions_exists, workspace_exists

    def _ensure_agent_ready(self, agent_id: str, max_wait_seconds: float = 15.0) -> dict[str, Any]:
        candidate_ids = set(self._agent_id_candidates(agent_id))
        deadline = time.monotonic() + max(max_wait_seconds, 0.0)
        last_observation = {
            "requested_agent_id": agent_id,
            "agent_id_candidates": sorted(candidate_ids),
            "agents_list_exit_code": -1,
            "agents_list_count": 0,
            "agents_list_ids_sample": [],
            "ensure_ready_phase": "checking",
            "ready_signal": "none",
            "state_dir_exists": False,
            "workspace_exists": False,
        }
        while True:
            exit_code, stdout, stderr, payload = self._run_agents_list()
            state_dir_exists, workspace_exists = self._agent_state_ready(agent_id)
            if exit_code != 0:
                detail = stderr.strip() or stdout.strip() or "failed to inspect agents"
                raise RuntimeError(detail)
            if payload is None:
                raise RuntimeError("OpenClaw agents payload is malformed")
            observed_ids: list[str] = []
            for item in payload:
                observed_ids.extend(
                    value for value in (item.get("id"), item.get("agentId"), item.get("name")) if isinstance(value, str)
                )
                if candidate_ids & self._agent_entry_candidates(item):
                    return {
                        "requested_agent_id": agent_id,
                        "agent_id_candidates": sorted(candidate_ids),
                        "agents_list_exit_code": exit_code,
                        "agents_list_count": len(payload),
                        "agents_list_ids_sample": observed_ids[:10],
                        "ensure_ready_phase": "ready",
                        "ready_signal": "registry",
                        "state_dir_exists": state_dir_exists,
                        "workspace_exists": workspace_exists,
                    }
            last_observation = {
                "requested_agent_id": agent_id,
                "agent_id_candidates": sorted(candidate_ids),
                "agents_list_exit_code": exit_code,
                "agents_list_count": len(payload),
                "agents_list_ids_sample": observed_ids[:10],
                "ensure_ready_phase": "waiting",
                "ready_signal": "none",
                "state_dir_exists": state_dir_exists,
                "workspace_exists": workspace_exists,
            }
            if time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        raise RuntimeError(f"OpenClaw agent not ready: {agent_id}")

    def _parse_agents_list(self, stdout: str) -> list[dict[str, Any]] | None:
        payload = extract_json_payload(stdout)
        if not isinstance(payload, list):
            return None
        return [item for item in payload if isinstance(item, dict)]

    def _is_unknown_agent_error(self, stderr: str, stdout: str, payload: dict[str, Any] | None) -> bool:
        for candidate in (stderr, stdout, self._payload_error_detail(payload)):
            text = str(candidate or "").lower()
            if "unknown agent id" in text:
                return True
        return False

    def _should_attempt_gateway_bootstrap(
        self,
        *,
        stderr: str,
        stdout: str,
        payload: dict[str, Any] | None,
    ) -> bool:
        for candidate in (stderr, stdout, self._payload_error_detail(payload)):
            text = str(candidate or "").lower()
            if "gateway closed" in text or "gateway connect failed" in text or "econnrefused" in text:
                return True
        return False

    def _should_attempt_gateway_bootstrap_after_timeout(self) -> bool:
        if str(self.command_env.get("OPENCLAW_GATEWAY_PORT", "")).strip():
            return True
        return self._uses_isolated_state()

    def _ensure_gateway_ready(self, startup_timeout: int = 20) -> bool:
        if self._gateway_process is not None and self._gateway_process.poll() is None:
            return True
        command = [
            self.openclaw_bin,
            "gateway",
            "run",
            "--allow-unconfigured",
            "--force",
        ]
        gateway_port = str(self.command_env.get("OPENCLAW_GATEWAY_PORT", "")).strip()
        if gateway_port:
            command.extend(["--port", gateway_port])
        self._gateway_process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            preexec_fn=os.setsid,
            env=self.command_env,
        )
        deadline = time.monotonic() + max(startup_timeout, 1)
        while time.monotonic() < deadline:
            if self._gateway_process.poll() is not None:
                return False
            try:
                result = subprocess.run(
                    [self.openclaw_bin, "agents", "list", "--json"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=min(max(startup_timeout, 1), 5),
                    env=self.command_env,
                )
            except subprocess.TimeoutExpired:
                time.sleep(0.5)
                continue
            if int(result.returncode or 0) == 0:
                return True
            time.sleep(0.5)
        return False

    def _agent_id_candidates(self, agent_id: str) -> list[str]:
        raw = str(agent_id or "").strip()
        if not raw:
            return []
        candidates: list[str] = []
        for candidate in (
            raw,
            raw.lower(),
            raw.replace("_", "-").replace(".", "-").replace(":", "-").replace("/", "-").lower(),
        ):
            normalized = candidate.strip()
            if normalized and normalized not in candidates:
                candidates.append(normalized)
        return candidates

    def _agent_sessions_dir(self, agent_id: str) -> Path:
        agents_root = self._state_dir_path() / "agents"
        for candidate_agent_id in self._agent_id_candidates(agent_id):
            direct = agents_root / candidate_agent_id / "sessions"
            if direct.exists():
                return direct
        candidate_ids = set(self._agent_id_candidates(agent_id))
        for path in agents_root.glob("*/sessions"):
            parent_candidates = set(self._agent_id_candidates(path.parent.name))
            if candidate_ids & parent_candidates:
                return path
        return agents_root / str(agent_id).strip() / "sessions"

    def _is_empty_success_trace(self, status: str, trace: dict[str, Any]) -> bool:
        if status != "success":
            return False
        events = trace.get("events", [])
        if any(event.get("type") in {"assistant_message", "tool_call", "tool_result"} for event in events):
            return False
        metrics = trace.get("metrics", {}) if isinstance(trace, dict) else {}
        empty_metric_keys = (
            "input_tokens",
            "output_tokens",
            "tool_calls",
            "assistant_turns",
            "total_tokens",
        )
        return all(int(metrics.get(key, 0) or 0) == 0 for key in empty_metric_keys)

    def _should_normalize_terminated_exit(
        self,
        status: str,
        exit_code: int,
        error_detail: str,
        trace: dict[str, Any],
    ) -> bool:
        if status != "error" or exit_code != 1:
            return False
        if str(error_detail).strip().lower() != "terminated":
            return False
        events = trace.get("events", []) if isinstance(trace, dict) else []
        if not any(event.get("type") == "assistant_message" and str(event.get("text", "")).strip() for event in events):
            return False
        return any(event.get("type") in {"assistant_message", "tool_call", "tool_result"} for event in events)

    def _wait_and_load_transcript(
        self,
        agent_id: str,
        session_id: str,
        max_wait_seconds: int = 12,
        startup_grace_seconds: float = 2.0,
    ) -> list[dict[str, Any]]:
        if not self._wait_for_session_artifacts(agent_id, session_id, startup_grace_seconds):
            return []
        deadline = time.monotonic() + max(max_wait_seconds - startup_grace_seconds, 0)
        transcript = self._load_transcript(agent_id, session_id)
        if transcript:
            return transcript
        while time.monotonic() < deadline:
            transcript = self._load_transcript(agent_id, session_id)
            if transcript:
                return transcript
            time.sleep(1)
        return []

    def _wait_for_session_artifacts(self, agent_id: str, session_id: str, max_wait_seconds: float) -> bool:
        if self._session_artifacts_ready(agent_id, session_id):
            return True
        if max_wait_seconds <= 0:
            return False
        deadline = time.monotonic() + max_wait_seconds
        while time.monotonic() < deadline:
            time.sleep(0.25)
            if self._session_artifacts_ready(agent_id, session_id):
                return True
        return False

    def _session_artifacts_ready(self, agent_id: str, session_id: str) -> bool:
        sessions_dir = self._agent_sessions_dir(agent_id)
        if not sessions_dir.exists():
            return False
        if self._resolve_transcript_path(sessions_dir, session_id) is not None:
            return True
        return (sessions_dir / "sessions.json").exists()

    def _load_transcript(self, agent_id: str, session_id: str) -> list[dict[str, Any]]:
        sessions_dir = self._agent_sessions_dir(agent_id)
        transcript_path = self._resolve_transcript_path(sessions_dir, session_id)
        if transcript_path is None:
            return []
        return self._parse_jsonl(transcript_path)

    def _load_session_metadata(self, agent_id: str, session_id: str) -> dict[str, Any]:
        sessions_dir = self._agent_sessions_dir(agent_id)
        sessions_path = sessions_dir / "sessions.json"
        if not sessions_path.exists():
            return {}
        try:
            raw = json.loads(sessions_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(raw, dict):
            return {}

        latest_entry: tuple[int, dict[str, Any]] | None = None
        requested = str(session_id or "").strip()
        for value in raw.values():
            if not isinstance(value, dict):
                continue
            updated_at = int(value.get("updatedAt", 0) or 0)
            if latest_entry is None or updated_at > latest_entry[0]:
                latest_entry = (updated_at, value)
            candidate_ids = {
                str(value.get("sessionId") or "").strip(),
                str(value.get("systemPromptReport", {}).get("sessionId") or "").strip()
                if isinstance(value.get("systemPromptReport"), dict)
                else "",
            }
            session_file = value.get("sessionFile")
            if session_file:
                candidate_ids.add(Path(str(session_file)).stem)
            if requested and requested in candidate_ids:
                return value
        return latest_entry[1] if latest_entry is not None else {}

    def _parse_jsonl(self, path: Path) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def _resolve_transcript_path(self, sessions_dir: Path, session_id: str) -> Path | None:
        if not sessions_dir.exists():
            return None

        ordered_session_ids = [session_id, *self._session_ids_from_metadata(sessions_dir)]
        seen_session_ids: set[str] = set()
        for candidate_session_id in ordered_session_ids:
            normalized = str(candidate_session_id or "").strip()
            if not normalized or normalized in seen_session_ids:
                continue
            seen_session_ids.add(normalized)
            transcript_path = sessions_dir / f"{normalized}.jsonl"
            if transcript_path.exists():
                return transcript_path

        sessions_path = sessions_dir / "sessions.json"
        if sessions_path.exists():
            try:
                raw = json.loads(sessions_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw = None
            if isinstance(raw, dict):
                latest_file: tuple[int, Path] | None = None
                for value in raw.values():
                    if not isinstance(value, dict):
                        continue
                    session_file = value.get("sessionFile")
                    if not isinstance(session_file, str) or not session_file.strip():
                        continue
                    path = Path(session_file)
                    if not path.exists():
                        continue
                    updated_at = int(value.get("updatedAt", 0) or 0)
                    if latest_file is None or updated_at > latest_file[0]:
                        latest_file = (updated_at, path)
                if latest_file is not None:
                    return latest_file[1]

        candidates = sorted(sessions_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0] if candidates else None

    def _session_ids_from_metadata(self, sessions_dir: Path) -> list[str]:
        sessions_path = sessions_dir / "sessions.json"
        if not sessions_path.exists():
            return []
        try:
            raw = json.loads(sessions_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, dict):
            return []

        entries: list[tuple[int, str]] = []
        for value in raw.values():
            if not isinstance(value, dict):
                continue
            updated_at = int(value.get("updatedAt", 0) or 0)
            for candidate in (
                value.get("sessionId"),
                Path(str(value.get("sessionFile", ""))).stem if value.get("sessionFile") else None,
                value.get("systemPromptReport", {}).get("sessionId") if isinstance(value.get("systemPromptReport"), dict) else None,
            ):
                session_id = str(candidate or "").strip()
                if session_id:
                    entries.append((updated_at, session_id))

        entries.sort(key=lambda item: item[0], reverse=True)
        deduped: list[str] = []
        for _, session_id in entries:
            if session_id not in deduped:
                deduped.append(session_id)
        return deduped

    def _merge_stdout_payload(self, trace: dict[str, Any], payload: dict[str, Any] | None) -> None:
        if payload is None:
            return

        metrics = trace.setdefault("metrics", {})
        usage = self._payload_usage(payload)
        metrics["input_tokens"] = max(int(metrics.get("input_tokens", 0)), int(usage.get("input", 0) or 0))
        metrics["output_tokens"] = max(int(metrics.get("output_tokens", 0)), int(usage.get("output", 0) or 0))
        metrics["cache_read_tokens"] = max(int(metrics.get("cache_read_tokens", 0)), int(usage.get("cacheRead", 0) or 0))
        metrics["cache_write_tokens"] = max(int(metrics.get("cache_write_tokens", 0)), int(usage.get("cacheWrite", 0) or 0))
        total_tokens = int(usage.get("total", 0) or 0)
        if total_tokens:
            metrics["total_tokens"] = max(int(metrics.get("total_tokens", 0)), total_tokens)

        duration_ms = self._payload_duration_ms(payload)
        if duration_ms:
            metrics["wall_time_s"] = max(float(metrics.get("wall_time_s", 0.0)), round(duration_ms / 1000.0, 2))
            metrics["duration_seconds"] = metrics["wall_time_s"]

        if not any(event.get("type") == "assistant_message" for event in trace.get("events", [])):
            text = self._payload_text(payload)
            if text:
                trace.setdefault("events", []).append(
                    {"type": "assistant_message", "text": text, "seq": len(trace.get("events", []))}
                )

    def _parse_json_payload(self, stdout: str) -> dict[str, Any] | None:
        payload = extract_json_payload(stdout)
        return payload if isinstance(payload, dict) else None

    def _parse_command_payload(self, stdout: str, stderr: str) -> dict[str, Any] | None:
        return (
            self._parse_json_payload(stdout)
            or self._parse_json_payload(stderr)
            or self._parse_json_payload(f"{stdout}\n{stderr}")
        )

    def _payload_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result")
        return result if isinstance(result, dict) else payload

    def _strip_known_openclaw_log_pollution(self, text: str) -> str:
        cleaned_lines = [
            line
            for line in str(text or "").splitlines()
            if not line.startswith("[openclaw] log file size cap reached; suppressing writes file=")
        ]
        return "\n".join(cleaned_lines).strip()

    def _clean_openclaw_command_streams(self, stdout: str, stderr: str) -> tuple[str, str]:
        return stdout, self._strip_known_openclaw_log_pollution(stderr)

    def _payload_session_id(self, payload: dict[str, Any] | None) -> str | None:
        if payload is None:
            return None
        result = self._payload_result(payload)
        meta = result.get("meta", {}) if isinstance(result.get("meta"), dict) else {}
        return (
            meta.get("agentMeta", {}).get("sessionId") if isinstance(meta.get("agentMeta"), dict) else None
        ) or (
            meta.get("systemPromptReport", {}).get("sessionId") if isinstance(meta.get("systemPromptReport"), dict) else None
        ) or (
            meta.get("sessionId")
        )

    def _payload_usage(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._payload_result(payload)
        meta = result.get("meta", {}) if isinstance(result, dict) else {}
        agent_meta = meta.get("agentMeta", {}) if isinstance(meta, dict) else {}
        payloads = result.get("payloads", []) if isinstance(result, dict) else []
        candidates: list[dict[str, Any]] = []
        for candidate in (
            payload.get("usage"),
            result.get("usage") if isinstance(result, dict) else None,
            meta.get("usage") if isinstance(meta, dict) else None,
            agent_meta.get("usage") if isinstance(agent_meta, dict) else None,
            agent_meta.get("lastCallUsage") if isinstance(agent_meta, dict) else None,
            result.get("message", {}).get("usage") if isinstance(result.get("message"), dict) else None,
            payload.get("message", {}).get("usage") if isinstance(payload.get("message"), dict) else None,
        ):
            if isinstance(candidate, dict):
                candidates.append(candidate)
        for item in payloads:
            if isinstance(item, dict):
                if isinstance(item.get("usage"), dict):
                    candidates.append(item["usage"])
                if isinstance(item.get("meta"), dict) and isinstance(item["meta"].get("usage"), dict):
                    candidates.append(item["meta"]["usage"])

        merged = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}
        for candidate in candidates:
            normalized = _normalize_usage(candidate)
            merged["input"] = max(merged["input"], int(normalized["input"] or 0))
            merged["output"] = max(merged["output"], int(normalized["output"] or 0))
            merged["cacheRead"] = max(merged["cacheRead"], int(normalized["cache_read"] or 0))
            merged["cacheWrite"] = max(merged["cacheWrite"], int(normalized["cache_write"] or 0))
            merged["total"] = max(merged["total"], int(normalized["total"] or 0))

        if merged["total"] <= 0:
            merged["total"] = merged["input"] + merged["output"] + merged["cacheRead"] + merged["cacheWrite"]
        return merged

    def _payload_duration_ms(self, payload: dict[str, Any]) -> float:
        result = self._payload_result(payload)
        meta = result.get("meta", {}) if isinstance(result, dict) else {}
        if isinstance(meta, dict):
            return float(meta.get("durationMs", 0.0) or 0.0)
        return 0.0

    def _payload_text(self, payload: dict[str, Any]) -> str:
        result = self._payload_result(payload)
        payloads = result.get("payloads", []) if isinstance(result, dict) else []
        for item in payloads:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    return text
        for key in ("reply", "text", "message", "response"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return ""

    def _payload_error_detail(self, payload: dict[str, Any] | None) -> str:
        if payload is None:
            return ""

        result = self._payload_result(payload)
        meta = result.get("meta", {}) if isinstance(result, dict) else {}
        candidates = [
            payload.get("error"),
            result.get("error") if isinstance(result, dict) else None,
            meta.get("error") if isinstance(meta, dict) else None,
            payload.get("message"),
            result.get("message") if isinstance(result, dict) else None,
        ]
        for candidate in candidates:
            detail = self._stringify_detail(candidate)
            if detail:
                return detail
        return ""

    def _model_error_detail(self, raw_transcript: list[dict[str, Any]], payload: dict[str, Any] | None) -> str:
        for entry in reversed(raw_transcript):
            if not isinstance(entry, dict):
                continue
            message = entry.get("message") if entry.get("type") == "message" else entry
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            stop_reason = str(message.get("stopReason", "")).strip().lower()
            error_message = self._stringify_detail(message.get("errorMessage"))
            if stop_reason == "error" and error_message:
                return error_message
        if payload is None:
            return ""
        result = self._payload_result(payload)
        message = result.get("message") if isinstance(result.get("message"), dict) else payload.get("message")
        if isinstance(message, dict):
            stop_reason = str(message.get("stopReason", "")).strip().lower()
            error_message = self._stringify_detail(message.get("errorMessage"))
            if stop_reason == "error" and error_message:
                return error_message
        return ""

    def _build_error_detail(
        self,
        *,
        status: str,
        exit_code: int,
        stderr: str,
        stdout: str,
        payload: dict[str, Any] | None,
    ) -> str:
        if status == "success":
            return ""
        cleaned_stderr = self._strip_known_openclaw_log_pollution(stderr)
        for candidate in (cleaned_stderr, self._payload_error_detail(payload), stdout):
            detail = self._stringify_detail(candidate)
            if detail:
                return detail
        if status == "timeout":
            return "OpenClaw agent timed out"
        return f"OpenClaw agent exited with code {exit_code}"

    def _stringify_detail(self, value: Any) -> str:
        if isinstance(value, str):
            detail = value.strip()
            return detail[:500]
        if isinstance(value, dict):
            try:
                return json.dumps(value, ensure_ascii=False)[:500]
            except TypeError:
                return ""
        return ""

    def _kill_process_group(self, proc: subprocess.Popen[str] | None) -> None:
        if proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
