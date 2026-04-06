from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness.live_harness import OpenClawLiveHarness


class LiveHarnessTests(unittest.TestCase):
    def test_profile_isolation_populates_state_dir_config_path_and_dev_port(self) -> None:
        harness = OpenClawLiveHarness(openclaw_profile="dev")

        expected_state_dir = (Path.home() / ".openclaw-dev").resolve(strict=False)
        expected_config_path = (expected_state_dir / "openclaw.json").resolve(strict=False)

        self.assertEqual(harness.command_env["OPENCLAW_PROFILE"], "dev")
        self.assertEqual(harness.command_env["OPENCLAW_STATE_DIR"], str(expected_state_dir))
        self.assertEqual(harness.command_env["OPENCLAW_CONFIG_PATH"], str(expected_config_path))
        self.assertEqual(harness.command_env["OPENCLAW_GATEWAY_PORT"], "19001")

    def test_auth_and_session_paths_use_configured_state_dir(self) -> None:
        harness = OpenClawLiveHarness(openclaw_state_dir="/tmp/openclaw-bench-a")
        expected_root = Path("/tmp/openclaw-bench-a").resolve(strict=False)

        self.assertEqual(
            harness._global_main_auth_profiles_path(),
            expected_root / "agents" / "main" / "agent" / "auth-profiles.json",
        )
        self.assertEqual(
            harness._agent_sessions_dir("agent-1"),
            expected_root / "agents" / "agent-1" / "sessions",
        )

    def test_ensure_isolated_state_seeded_copies_default_models_and_main_auth(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as target_dir:
            home_path = Path(home_dir)
            default_state_dir = home_path / ".openclaw"
            default_state_dir.mkdir(parents=True)
            (default_state_dir / "agents" / "main" / "agent").mkdir(parents=True)

            source_config = {
                "auth": {
                    "profiles": {
                        "zai:default": {"provider": "zai", "mode": "api_key"},
                    }
                },
                "models": {
                    "providers": {
                        "glm": {
                            "baseUrl": "https://example.invalid",
                            "models": [{"id": "GLM-5", "name": "GLM-5"}],
                        }
                    }
                },
                "agents": {
                    "defaults": {"maxConcurrent": 4},
                    "list": [{"id": "main"}, {"id": "legacy-agent"}],
                },
                "messages": {"ackReactionScope": "group-mentions"},
                "commands": {"native": "auto"},
            }
            (default_state_dir / "openclaw.json").write_text(json.dumps(source_config), encoding="utf-8")
            (default_state_dir / "agents" / "main" / "agent" / "auth-profiles.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "profiles": {
                            "zai:default": {"provider": "zai", "type": "api_key", "key": "zai-test-key"}
                        },
                        "lastGood": {"zai": "zai:default"},
                    }
                ),
                encoding="utf-8",
            )

            target_state_dir = Path(target_dir)
            target_config_path = target_state_dir / "openclaw.json"
            target_state_dir.mkdir(parents=True, exist_ok=True)
            target_config_path.write_text(
                json.dumps(
                    {
                        "agents": {
                            "defaults": {"maxConcurrent": 2},
                            "list": [{"id": "main"}],
                        },
                        "messages": {"ackReactionScope": "group-mentions"},
                        "commands": {"native": "auto"},
                    }
                ),
                encoding="utf-8",
            )

            harness = OpenClawLiveHarness(openclaw_state_dir=str(target_state_dir))
            harness.command_env["HOME"] = str(home_path)

            harness._ensure_isolated_state_seeded()

            seeded_config = json.loads(target_config_path.read_text(encoding="utf-8"))
            self.assertIn("models", seeded_config)
            self.assertEqual(
                seeded_config["models"]["providers"]["glm"]["models"][0]["id"],
                "GLM-5",
            )
            self.assertEqual(seeded_config["auth"]["profiles"]["zai:default"]["provider"], "zai")
            self.assertEqual(seeded_config["agents"]["list"], [{"id": "main"}])
            self.assertEqual(seeded_config["agents"]["defaults"]["maxConcurrent"], 2)

            target_auth_profiles = target_state_dir / "agents" / "main" / "agent" / "auth-profiles.json"
            self.assertTrue(target_auth_profiles.exists())
            copied_auth = json.loads(target_auth_profiles.read_text(encoding="utf-8"))
            self.assertEqual(copied_auth["profiles"]["zai:default"]["provider"], "zai")

    def test_sync_isolated_model_runtime_pins_primary_model_and_refreshes_provider_token(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as target_dir:
            home_path = Path(home_dir)
            target_state_dir = Path(target_dir)
            target_config_path = target_state_dir / "openclaw.json"
            target_auth_path = target_state_dir / "agents" / "main" / "agent" / "auth-profiles.json"
            target_auth_path.parent.mkdir(parents=True, exist_ok=True)
            target_config_path.write_text(
                json.dumps(
                    {
                        "auth": {"profiles": {}},
                        "models": {
                            "providers": {
                                "tencent-token-plan": {
                                    "apiKey": "sk-tp-new",
                                    "models": [{"id": "hunyuan-2.0-thinking"}],
                                }
                            }
                        },
                        "agents": {
                            "defaults": {
                                "model": {
                                    "primary": "tencent-token-plan/glm-5",
                                    "fallbacks": ["kimi/kimi-code", "volcengine-plan/ark-code-latest"],
                                },
                                "models": {"tencent-token-plan/glm-5": {}},
                            },
                            "list": [{"id": "main"}],
                        },
                    }
                ),
                encoding="utf-8",
            )
            target_auth_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "profiles": {
                            "tencent-token-plan:manual": {
                                "provider": "tencent-token-plan",
                                "type": "token",
                                "token": "sk-tp-old",
                            }
                        },
                        "lastGood": {"tencent-token-plan": "tencent-token-plan:manual"},
                        "usageStats": {
                            "tencent-token-plan:manual": {
                                "cooldownUntil": 123,
                                "errorCount": 2,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            harness = OpenClawLiveHarness(openclaw_state_dir=str(target_state_dir))
            harness.command_env["HOME"] = str(home_path)

            harness._sync_isolated_model_runtime("tencent-token-plan/hunyuan-2.0-thinking")

            updated_config = json.loads(target_config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                updated_config["agents"]["defaults"]["model"]["primary"],
                "tencent-token-plan/hunyuan-2.0-thinking",
            )
            self.assertEqual(updated_config["agents"]["defaults"]["model"]["fallbacks"], [])
            self.assertIn(
                "tencent-token-plan/hunyuan-2.0-thinking",
                updated_config["agents"]["defaults"]["models"],
            )
            self.assertEqual(
                updated_config["auth"]["profiles"]["tencent-token-plan:manual"],
                {"provider": "tencent-token-plan", "mode": "token"},
            )

            updated_auth = json.loads(target_auth_path.read_text(encoding="utf-8"))
            self.assertEqual(
                updated_auth["profiles"]["tencent-token-plan:manual"]["token"],
                "sk-tp-new",
            )
            self.assertNotIn("usageStats", updated_auth)

    def test_sync_isolated_model_runtime_updates_zai_auth_profile_for_glm_alias(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as target_dir:
            home_path = Path(home_dir)
            target_state_dir = Path(target_dir)
            target_config_path = target_state_dir / "openclaw.json"
            target_auth_path = target_state_dir / "agents" / "main" / "agent" / "auth-profiles.json"
            target_auth_path.parent.mkdir(parents=True, exist_ok=True)
            target_config_path.write_text(
                json.dumps(
                    {
                        "auth": {"profiles": {}},
                        "models": {
                            "providers": {
                                "glm": {
                                    "apiKey": "glm-new-key",
                                    "models": [{"id": "GLM-5"}],
                                }
                            }
                        },
                        "agents": {
                            "defaults": {
                                "model": {"primary": "glm/GLM-4.7", "fallbacks": ["openai/gpt-4o"]},
                                "models": {},
                            },
                            "list": [{"id": "main"}],
                        },
                    }
                ),
                encoding="utf-8",
            )
            target_auth_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "profiles": {
                            "zai:default": {
                                "provider": "zai",
                                "type": "api_key",
                                "key": "glm-old-key",
                            }
                        },
                        "lastGood": {"zai": "zai:default"},
                    }
                ),
                encoding="utf-8",
            )

            harness = OpenClawLiveHarness(openclaw_state_dir=str(target_state_dir))
            harness.command_env["HOME"] = str(home_path)

            harness._sync_isolated_model_runtime("glm/GLM-5")

            updated_config = json.loads(target_config_path.read_text(encoding="utf-8"))
            self.assertEqual(updated_config["agents"]["defaults"]["model"]["primary"], "glm/GLM-5")
            self.assertEqual(updated_config["agents"]["defaults"]["model"]["fallbacks"], [])
            self.assertEqual(
                updated_config["auth"]["profiles"]["zai:default"],
                {"provider": "zai", "mode": "api_key"},
            )

            updated_auth = json.loads(target_auth_path.read_text(encoding="utf-8"))
            self.assertEqual(updated_auth["profiles"]["zai:default"]["provider"], "zai")
            self.assertEqual(updated_auth["profiles"]["zai:default"]["key"], "glm-new-key")

    def test_sync_isolated_agent_runtime_pins_agent_model_and_disables_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as target_dir:
            target_state_dir = Path(target_dir)
            target_config_path = target_state_dir / "openclaw.json"
            target_config_path.write_text(
                json.dumps(
                    {
                        "agents": {
                            "defaults": {
                                "model": {
                                    "primary": "tencent-token-plan/glm-5",
                                    "fallbacks": ["kimi/kimi-code"],
                                }
                            },
                            "list": [
                                {"id": "main"},
                                {
                                    "id": "agent-1",
                                    "name": "agent-1",
                                    "workspace": "/tmp/workspace",
                                    "model": "tencent-token-plan/hunyuan-2.0-thinking",
                                },
                                {
                                    "id": "agent-2",
                                    "model": {
                                        "primary": "glm/GLM-5",
                                        "fallbacks": ["openai/gpt-4.1"],
                                    },
                                },
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            harness = OpenClawLiveHarness(openclaw_state_dir=str(target_state_dir))

            harness._sync_isolated_agent_runtime("agent-1", "tencent-token-plan/hunyuan-2.0-thinking")

            updated_config = json.loads(target_config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                updated_config["agents"]["list"][1]["model"],
                {
                    "primary": "tencent-token-plan/hunyuan-2.0-thinking",
                    "fallbacks": [],
                },
            )
            self.assertEqual(
                updated_config["agents"]["list"][2]["model"],
                {
                    "primary": "glm/GLM-5",
                    "fallbacks": ["openai/gpt-4.1"],
                },
            )

    def test_ensure_agent_ready_retries_until_agent_appears(self) -> None:
        harness = OpenClawLiveHarness()
        first = mock.Mock(returncode=0, stdout='[]', stderr='')
        second = mock.Mock(returncode=0, stdout='[{"id":"ocb6-glm-glm-5-abc123"}]', stderr='')
        with mock.patch("harness.live_harness.subprocess.run", side_effect=[first, second]):
            state = harness._ensure_agent_ready("ocb6-glm-glm-5-abc123", max_wait_seconds=0.3)

        self.assertEqual(state["ensure_ready_phase"], "ready")
        self.assertEqual(state["agents_list_count"], 1)

    def test_ensure_agent_ready_matches_normalized_list_id_fields(self) -> None:
        harness = OpenClawLiveHarness()
        completed = mock.Mock(returncode=0, stdout='[{"agentId":"ocb6.glm.glm.5.abc123"}]', stderr='')
        with mock.patch("harness.live_harness.subprocess.run", return_value=completed):
            state = harness._ensure_agent_ready("ocb6-glm-glm-5-abc123", max_wait_seconds=0)

        self.assertEqual(state["ensure_ready_phase"], "ready")
        self.assertIn("ocb6.glm.glm.5.abc123", state["agents_list_ids_sample"])

    def test_ensure_agent_ready_accepts_sessions_dir_fallback(self) -> None:
        harness = OpenClawLiveHarness()
        completed = mock.Mock(returncode=0, stdout='[]', stderr='')
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "agents" / "ocb6-glm-glm-5-abc123" / "sessions"
            sessions_dir.mkdir(parents=True)
            with (
                mock.patch("harness.live_harness.subprocess.run", return_value=completed),
                mock.patch.object(harness, "_agent_sessions_dir", return_value=sessions_dir),
            ):
                state = harness._ensure_agent_ready("ocb6-glm-glm-5-abc123", max_wait_seconds=0)

        self.assertEqual(state["ensure_ready_phase"], "ready")
        self.assertEqual(state["ready_signal"], "sessions_dir")
        self.assertTrue(state["state_dir_exists"])

    def test_ensure_agent_ready_raises_when_registry_and_state_are_missing(self) -> None:
        harness = OpenClawLiveHarness()
        completed = mock.Mock(returncode=0, stdout='[]', stderr='')
        missing_dir = Path("/tmp/nonexistent-agent-sessions")
        with (
            mock.patch("harness.live_harness.subprocess.run", return_value=completed),
            mock.patch.object(harness, "_agent_sessions_dir", return_value=missing_dir),
        ):
            with self.assertRaisesRegex(RuntimeError, "OpenClaw agent not ready"):
                harness._ensure_agent_ready("ocb6-glm-glm-5-abc123", max_wait_seconds=0)

        harness = OpenClawLiveHarness()

        self.assertEqual(harness._auth_profile_providers_for_model("glm/GLM-5"), {"zai"})
        self.assertEqual(harness._auth_profile_providers_for_model("minimax/MiniMax-M2.7"), {"minimax"})

    def test_create_agent_copies_minimax_auth_profiles(self) -> None:
        harness = OpenClawLiveHarness()
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            completed = mock.Mock(returncode=0, stdout="", stderr="")
            copy_result = mock.Mock(reason="copied")
            with (
                mock.patch("harness.live_harness.subprocess.run", return_value=completed),
                mock.patch.object(harness, "_copy_auth_profiles", return_value=copy_result) as copy_auth,
                mock.patch.object(harness, "_sync_isolated_agent_runtime") as sync_agent_runtime,
            ):
                result = harness._create_agent("agent-1", "minimax/MiniMax-M2.7", workspace)

        self.assertIs(result, copy_result)
        sync_agent_runtime.assert_called_once_with("agent-1", "minimax/MiniMax-M2.7")
        copy_auth.assert_called_once_with("agent-1", providers={"minimax"})

    def test_create_agent_fails_when_filtered_auth_profiles_are_empty(self) -> None:
        harness = OpenClawLiveHarness()
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            completed = mock.Mock(returncode=0, stdout="", stderr="")
            with (
                mock.patch("harness.live_harness.subprocess.run", return_value=completed),
                mock.patch.object(
                    harness,
                    "_copy_auth_profiles",
                    return_value=mock.Mock(reason="filtered_profiles_empty", requested_providers={"minimax"}),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "No auth profiles found for providers: minimax"):
                    harness._create_agent("agent-1", "minimax/MiniMax-M2.7", workspace)

    def test_resolve_transcript_path_uses_sessions_metadata_when_requested_id_is_not_real_session_id(self) -> None:
        harness = OpenClawLiveHarness()
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)
            (sessions_dir / "sessions.json").write_text(
                json.dumps(
                    {
                        "agent:test:main": {
                            "sessionId": "real-session-id",
                            "updatedAt": 200,
                        }
                    }
                ),
                encoding="utf-8",
            )
            transcript_path = sessions_dir / "real-session-id.jsonl"
            transcript_path.write_text('{"type":"message"}\n', encoding="utf-8")

            resolved = harness._resolve_transcript_path(sessions_dir, "requested-session-id")

        self.assertEqual(resolved, transcript_path)

    def test_resolve_transcript_path_falls_back_to_latest_transcript_file(self) -> None:
        harness = OpenClawLiveHarness()
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)
            older = sessions_dir / "older.jsonl"
            newer = sessions_dir / "newer.jsonl"
            older.write_text('{"type":"message"}\n', encoding="utf-8")
            newer.write_text('{"type":"message"}\n', encoding="utf-8")
            older.touch()
            newer.touch()

            resolved = harness._resolve_transcript_path(sessions_dir, "missing-session-id")

        self.assertEqual(resolved, newer)

    def test_wait_and_load_transcript_returns_early_without_session_artifacts(self) -> None:
        harness = OpenClawLiveHarness()
        with (
            mock.patch.object(harness, "_session_artifacts_ready", return_value=False),
            mock.patch.object(harness, "_load_transcript") as load_transcript,
        ):
            transcript = harness._wait_and_load_transcript(
                "agent-id",
                "session-id",
                max_wait_seconds=12,
                startup_grace_seconds=0,
            )

        self.assertEqual(transcript, [])
        load_transcript.assert_not_called()

    def test_execute_turn_skips_transcript_wait_when_agent_creation_fails(self) -> None:
        harness = OpenClawLiveHarness()
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            with (
                mock.patch.object(harness, "_create_agent", side_effect=RuntimeError("agent add failed")),
                mock.patch.object(harness, "_wait_and_load_transcript") as wait_for_transcript,
            ):
                result = harness.execute_turn(
                    model="mock/default",
                    prompt="hello",
                    workspace_path=workspace,
                    timeout=1,
                )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_detail, "agent add failed")
        wait_for_transcript.assert_not_called()

    def test_preflight_retries_after_timeout_then_succeeds(self) -> None:
        harness = OpenClawLiveHarness()
        completed = mock.Mock(returncode=0, stdout='[]', stderr='')
        with mock.patch(
            "harness.live_harness.subprocess.run",
            side_effect=[subprocess.TimeoutExpired(["openclaw", "agents", "list"], 45), completed],
        ):
            result = harness.preflight(timeout=45, max_attempts=2)

        self.assertTrue(result.ok)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("attempt=1 timeout_s=45", result.error_detail)

    def test_preflight_seeds_isolated_state_before_agents_list(self) -> None:
        harness = OpenClawLiveHarness(openclaw_state_dir="/tmp/openclaw-bench-a")
        completed = mock.Mock(returncode=0, stdout='[]', stderr='')
        with (
            mock.patch.object(harness, "_ensure_isolated_state_seeded") as ensure_seed,
            mock.patch("harness.live_harness.subprocess.run", return_value=completed),
        ):
            result = harness.preflight(timeout=45, max_attempts=1)

        self.assertTrue(result.ok)
        ensure_seed.assert_called_once()

    def test_preflight_reports_timeout_after_all_attempts(self) -> None:
        harness = OpenClawLiveHarness()
        with mock.patch(
            "harness.live_harness.subprocess.run",
            side_effect=[
                subprocess.TimeoutExpired(["openclaw", "agents", "list"], 45),
                subprocess.TimeoutExpired(["openclaw", "agents", "list"], 45),
            ],
        ):
            result = harness.preflight(timeout=45, max_attempts=2)

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, -1)
        self.assertIn("OpenClaw live preflight timed out", result.error_detail)
        self.assertIn("attempt=2 timeout_s=45", result.error_detail)

    def test_preflight_surfaces_cli_runtime_error(self) -> None:
        harness = OpenClawLiveHarness()
        completed = mock.Mock(returncode=1, stdout="", stderr="missing gaxios")
        with mock.patch("harness.live_harness.subprocess.run", return_value=completed):
            result = harness.preflight(timeout=1, max_attempts=1)

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.error_detail, "missing gaxios")

    def test_preflight_bootstraps_gateway_for_isolated_instance_then_succeeds(self) -> None:
        harness = OpenClawLiveHarness(openclaw_state_dir="/tmp/openclaw-bench-a", openclaw_gateway_port=19021)
        failed = mock.Mock(
            returncode=1,
            stdout="",
            stderr="Failed to start CLI: gateway closed (1006 abnormal closure)",
        )
        succeeded = mock.Mock(returncode=0, stdout="[]", stderr="")
        with (
            mock.patch("harness.live_harness.subprocess.run", side_effect=[failed, succeeded]),
            mock.patch.object(harness, "_ensure_gateway_ready", return_value=True) as ensure_gateway,
        ):
            result = harness.preflight(timeout=5, max_attempts=1)

        self.assertTrue(result.ok)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("gateway_bootstrap=ok", result.error_detail)
        ensure_gateway.assert_called_once()

    def test_close_terminates_bootstrapped_gateway_process(self) -> None:
        harness = OpenClawLiveHarness(openclaw_state_dir="/tmp/openclaw-bench-a", openclaw_gateway_port=19021)
        proc = mock.Mock()
        proc.poll.return_value = None
        harness._gateway_process = proc

        with mock.patch.object(harness, "_kill_process_group") as kill_process_group:
            harness.close()

        kill_process_group.assert_called_once_with(proc)
        self.assertIsNone(harness._gateway_process)

    def test_communicate_with_heartbeat_emits_progress_message(self) -> None:
        messages: list[str] = []
        harness = OpenClawLiveHarness(progress_callback=messages.append, progress_interval_seconds=1)
        proc = mock.Mock()
        proc.args = ["openclaw", "agent"]
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired(proc.args, 1),
            ('{"result": {}}', ""),
        ]

        stdout, stderr = harness._communicate_with_heartbeat(proc, timeout=2, agent_id="agent-1")

        self.assertEqual(stdout, '{"result": {}}')
        self.assertEqual(stderr, "")
        self.assertTrue(any("live-heartbeat agent=agent-1" in message for message in messages))
    def test_execute_turn_converts_empty_success_trace_to_error(self) -> None:
        harness = OpenClawLiveHarness()
        completed_stdout = '{"result": {"meta": {"agentMeta": {"sessionId": "real-session-id"}}}}'
        proc = mock.Mock()
        proc.returncode = 0
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            with (
                mock.patch.object(
                    harness,
                    "_create_agent",
                    return_value=mock.Mock(requested_providers={"zai"}, to_dict=lambda: {"reason": "copied"}),
                ),
                mock.patch.object(harness, "_ensure_agent_ready"),
                mock.patch("harness.live_harness.subprocess.Popen", return_value=proc),
                mock.patch.object(harness, "_communicate_with_heartbeat", return_value=(completed_stdout, "")),
                mock.patch.object(harness, "_wait_and_load_transcript", return_value=[]),
            ):
                result = harness.execute_turn(
                    model="glm/GLM-5",
                    prompt="hello",
                    workspace_path=workspace,
                    timeout=1,
                )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_detail, "empty live transcript/tool trace")
        self.assertNotEqual(result.exit_code, 0)

        harness = OpenClawLiveHarness()
        completed_stdout = '{"result": {"meta": {"agentMeta": {"sessionId": "real-session-id"}}}}'
        proc = mock.Mock()
        proc.returncode = 0
        transcript = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "stopReason": "error",
                    "errorMessage": "No API key for provider: glm",
                    "usage": {"input": 0, "output": 0, "totalTokens": 0},
                },
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            with (
                mock.patch.object(harness, "_create_agent"),
                mock.patch.object(harness, "_ensure_agent_ready"),
                mock.patch("harness.live_harness.subprocess.Popen", return_value=proc),
                mock.patch.object(harness, "_communicate_with_heartbeat", return_value=(completed_stdout, "")),
                mock.patch.object(harness, "_wait_and_load_transcript", return_value=transcript),
            ):
                result = harness.execute_turn(
                    model="glm/GLM-5",
                    prompt="hello",
                    workspace_path=workspace,
                    timeout=1,
                )

        self.assertEqual(result.status, "error")
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(result.error_detail, "No API key for provider: glm")

    def test_execute_turn_recreates_agent_once_on_unknown_agent_id(self) -> None:
        harness = OpenClawLiveHarness()
        proc_first = mock.Mock()
        proc_first.returncode = 1
        proc_second = mock.Mock()
        proc_second.returncode = 0
        payload_success = '{"result": {"meta": {"agentMeta": {"sessionId": "real-session-id"}}, "payloads": [{"text": "done", "usage": {"input": 10, "output": 5, "total": 15}}]}}'
        transcript = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                    "usage": {"input": 10, "output": 5, "totalTokens": 15},
                },
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            with (
                mock.patch.object(harness, "_create_agent") as create_agent,
                mock.patch.object(harness, "_ensure_agent_ready"),
                mock.patch("harness.live_harness.subprocess.Popen", side_effect=[proc_first, proc_second]),
                mock.patch.object(harness, "_communicate_with_heartbeat", side_effect=[('{"error":"Unknown agent id \\\"agent-1\\\""}', "Unknown agent id \"agent-1\""), (payload_success, "")]),
                mock.patch.object(harness, "_wait_and_load_transcript", return_value=transcript),
            ):
                result = harness.execute_turn(
                    model="glm/GLM-5",
                    prompt="hello",
                    workspace_path=workspace,
                    timeout=1,
                )

        self.assertEqual(create_agent.call_count, 2)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.exit_code, 0)

    def test_execute_turn_repairs_missing_workspace_files_after_agent_create(self) -> None:
        harness = OpenClawLiveHarness()
        completed_stdout = '{"result": {"meta": {"agentMeta": {"sessionId": "real-session-id"}}}}'
        proc = mock.Mock()
        proc.returncode = 0
        transcript = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                    "usage": {"input": 10, "output": 5, "totalTokens": 15},
                },
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            seeded = workspace / "seed.txt"
            seeded.write_text("seeded\n", encoding="utf-8")

            def create_agent(*_args: object, **_kwargs: object) -> mock.Mock:
                seeded.unlink()
                return mock.Mock(
                    requested_providers={"zai"},
                    to_dict=lambda: {"reason": "copied"},
                )

            def repair_workspace(target_workspace: Path) -> None:
                (target_workspace / "seed.txt").write_text("seeded\n", encoding="utf-8")

            with (
                mock.patch.object(harness, "_create_agent", side_effect=create_agent),
                mock.patch.object(harness, "_ensure_agent_ready", return_value={"ensure_ready_phase": "ready"}),
                mock.patch("harness.live_harness.subprocess.Popen", return_value=proc),
                mock.patch.object(harness, "_communicate_with_heartbeat", return_value=(completed_stdout, "")),
                mock.patch.object(harness, "_wait_and_load_transcript", return_value=transcript),
            ):
                result = harness.execute_turn(
                    model="glm/GLM-5",
                    prompt="hello",
                    workspace_path=workspace,
                    timeout=1,
                    expected_workspace_files=["seed.txt"],
                    repair_workspace=repair_workspace,
                )
            guard = result.trace["audit_state"]["live_runtime"]["workspace_guard"]
            self.assertTrue((workspace / "seed.txt").exists())
            self.assertEqual(len(guard["repair_attempts"]), 1)
            self.assertEqual(guard["repair_attempts"][0]["missing_before_restore"], ["seed.txt"])
            self.assertEqual(guard["repair_attempts"][0]["missing_after_restore"], [])
            self.assertTrue(guard["repair_attempts"][0]["repair_applied"])

    def test_execute_turn_normalizes_benign_terminated_exit_when_trace_is_complete(self) -> None:
        harness = OpenClawLiveHarness()
        completed_stdout = '{"result": {"meta": {"agentMeta": {"sessionId": "real-session-id"}}}}'
        proc = mock.Mock()
        proc.returncode = 1
        transcript = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                    "usage": {"input": 10, "output": 5, "totalTokens": 15},
                },
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            with (
                mock.patch.object(
                    harness,
                    "_create_agent",
                    return_value=mock.Mock(requested_providers={"zai"}, to_dict=lambda: {"reason": "copied"}),
                ),
                mock.patch.object(harness, "_ensure_agent_ready", return_value={"ensure_ready_phase": "ready"}),
                mock.patch("harness.live_harness.subprocess.Popen", return_value=proc),
                mock.patch.object(harness, "_communicate_with_heartbeat", return_value=(completed_stdout, "terminated")),
                mock.patch.object(harness, "_wait_and_load_transcript", return_value=transcript),
            ):
                result = harness.execute_turn(
                    model="glm/GLM-5",
                    prompt="hello",
                    workspace_path=workspace,
                    timeout=1,
                )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.error_detail, "")
        self.assertTrue(result.trace["audit_state"]["live_runtime"]["normalized_terminated_exit"])

    def test_payload_usage_merges_multiple_common_locations(self) -> None:
        harness = OpenClawLiveHarness()
        payload = {
            "result": {
                "meta": {
                    "usage": {"prompt_tokens": "100", "completion_tokens": "20"},
                    "agentMeta": {
                        "lastCallUsage": {"cacheRead": 30, "cacheWrite": 40, "total": 190}
                    },
                }
            }
        }

        usage = harness._payload_usage(payload)

        self.assertEqual(usage["input"], 100)
        self.assertEqual(usage["output"], 20)
        self.assertEqual(usage["cacheRead"], 30)
        self.assertEqual(usage["cacheWrite"], 40)
        self.assertEqual(usage["total"], 190)

    def test_merge_stdout_payload_backfills_metrics_without_overwriting_larger_transcript_values(self) -> None:
        harness = OpenClawLiveHarness()
        trace = {
            "events": [{"type": "assistant_message", "text": "done", "seq": 0}],
            "metrics": {
                "input_tokens": 150,
                "output_tokens": 25,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 175,
            },
        }
        payload = {
            "result": {
                "meta": {
                    "agentMeta": {
                        "usage": {"input": 120, "output": 30, "total": 150},
                        "lastCallUsage": {"cacheRead": 10, "cacheWrite": 5},
                    }
                }
            }
        }

        harness._merge_stdout_payload(trace, payload)

        self.assertEqual(trace["metrics"]["input_tokens"], 150)
        self.assertEqual(trace["metrics"]["output_tokens"], 30)
        self.assertEqual(trace["metrics"]["cache_read_tokens"], 10)
        self.assertEqual(trace["metrics"]["cache_write_tokens"], 5)
        self.assertEqual(trace["metrics"]["total_tokens"], 175)

    def test_execute_turn_passes_session_metadata_into_trace_normalization(self) -> None:
        harness = OpenClawLiveHarness()
        completed_stdout = '{"result": {"meta": {"agentMeta": {"sessionId": "real-session-id"}}}}'
        proc = mock.Mock()
        proc.returncode = 0
        transcript = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                    "usage": {"input": 0, "output": 0, "totalTokens": 0},
                },
            }
        ]
        session_metadata = {"systemPromptReport": {"systemPrompt": {"chars": 1234}}}

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            with (
                mock.patch.object(harness, "_create_agent"),
                mock.patch.object(harness, "_ensure_agent_ready", return_value={"ensure_ready_phase": "ready"}),
                mock.patch("harness.live_harness.subprocess.Popen", return_value=proc),
                mock.patch.object(harness, "_communicate_with_heartbeat", return_value=(completed_stdout, "")),
                mock.patch.object(harness, "_wait_and_load_transcript", return_value=transcript),
                mock.patch.object(harness, "_load_session_metadata", return_value=session_metadata),
                mock.patch(
                    "harness.live_harness.normalize_trace",
                    return_value={"events": [{"type": "assistant_message", "text": "done", "seq": 0}], "metrics": {}, "audit_state": {}},
                ) as normalize,
            ):
                result = harness.execute_turn(
                    model="glm/GLM-5",
                    prompt="hello",
                    workspace_path=workspace,
                    timeout=1,
                )

        self.assertEqual(result.status, "success")
        normalize.assert_called_once_with(transcript, session_metadata=session_metadata)


if __name__ == "__main__":
    unittest.main()
