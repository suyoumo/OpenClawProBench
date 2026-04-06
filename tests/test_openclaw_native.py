from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.custom_checks import run_custom_checks
from harness.loader import load_scenario, scenarios_root
from harness.openclaw_native import (
    collect_native_environment_snapshot,
    extract_gateway_target,
    extract_json_payload,
    grade_skills_process,
    infer_surface_status,
    parse_configured_channels,
    run_openclaw_command,
    run_openclaw_json,
    trace_openclaw_surfaces_used,
    trace_used_openclaw_exec,
)


SKILLS_FIXTURE = {
    "workspaceDir": "/Users/test/clawd",
    "managedSkillsDir": "/Users/test/.openclaw/skills",
    "skills": [
        {
            "name": "feishu-calendar",
            "eligible": True,
            "bundled": False,
            "missing": {"bins": [], "anyBins": [], "env": [], "config": [], "os": []},
        },
        {
            "name": "tmux",
            "eligible": True,
            "bundled": True,
            "missing": {"bins": [], "anyBins": [], "env": [], "config": [], "os": []},
        },
        {
            "name": "weather",
            "eligible": True,
            "bundled": True,
            "missing": {"bins": [], "anyBins": [], "env": [], "config": [], "os": []},
        },
        {
            "name": "1password",
            "eligible": False,
            "bundled": True,
            "missing": {"bins": ["op"], "anyBins": [], "env": [], "config": [], "os": []},
        },
        {
            "name": "slack",
            "eligible": False,
            "bundled": True,
            "missing": {"bins": [], "anyBins": [], "env": ["SLACK_BOT_TOKEN"], "config": [], "os": []},
        },
        {
            "name": "zeta",
            "eligible": False,
            "bundled": False,
            "missing": {"bins": ["zeta"], "anyBins": [], "env": [], "config": [], "os": []},
        },
    ],
}

DIRECTORY_CHANNELS = ["feishu", "telegram"]
DIRECTORY_PEERS = {
    "feishu": [{"kind": "user", "id": "ou_abc"}],
    "telegram": [],
}
MEMORY_OUTPUT = """
No matches.
[memory] sync failed (session-start): Error: unable to open database file
[memory] sync failed (search): Error: unable to open database file
""".strip()
GATEWAY_OUTPUT = """
gateway connect failed: Error: gateway closed (1000):
Error: gateway closed (1000 normal closure): no close reason
Gateway target: ws://127.0.0.1:18789
""".strip()
MESSAGE_DRY_RUN_FIXTURE = {
    "action": "send",
    "channel": "telegram",
    "dryRun": True,
    "handledBy": "core",
    "payload": {
        "channel": "telegram",
        "to": "telegram:@benchmark_target",
        "via": "direct",
        "mediaUrl": None,
        "dryRun": True,
    },
}
AGENTS_FIXTURE = [
    {
        "id": "main",
        "workspace": "/Users/test/clawd",
        "model": "glm/GLM-5",
        "bindings": 0,
        "isDefault": True,
    },
    {
        "id": "bench-helper",
        "workspace": "/tmp/openclawbench/helper",
        "model": "glm/GLM-5",
        "bindings": 0,
        "isDefault": False,
    },
    {
        "id": "judge",
        "workspace": "/tmp/openclawbench/judge",
        "model": "openrouter/anthropic/claude-opus-4.5",
        "bindings": 0,
        "isDefault": False,
    },
]
SESSIONS_FIXTURE = {
    "path": "/Users/test/.openclaw/agents/main/sessions/sessions.json",
    "count": 2,
    "sessions": [
        {
            "key": "agent:main:main",
            "inputTokens": 255678,
            "contextTokens": 200000,
            "model": "GLM-5",
        },
        {
            "key": "agent:main:sidecar",
            "inputTokens": 12000,
            "contextTokens": 200000,
            "model": "GLM-5",
        },
    ],
}


def _trace(*commands: str, audit_state: dict | None = None) -> dict:
    events = []
    for index, command in enumerate(commands):
        events.append(
            {
                "type": "tool_call",
                "tool": "exec",
                "args": {"command": command},
                "seq": index,
            }
        )
    events.append(
        {
            "type": "tool_call",
            "tool": "write",
            "args": {"path": "report.json"},
            "seq": len(events),
        }
    )
    trace = {"events": events}
    if audit_state is not None:
        trace["audit_state"] = audit_state
    return trace


def _tool_trace(*calls: tuple[str, dict[str, object]], audit_state: dict | None = None, append_write: bool = True) -> dict:
    events = []
    for index, (tool_name, args) in enumerate(calls):
        events.append(
            {
                "type": "tool_call",
                "tool": tool_name,
                "args": args,
                "seq": index,
            }
        )
    if append_write:
        events.append(
            {
                "type": "tool_call",
                "tool": "write",
                "args": {"path": "report.json"},
                "seq": len(events),
            }
        )
    trace = {"events": events}
    if audit_state is not None:
        trace["audit_state"] = audit_state
    return trace


class OpenClawNativeTests(unittest.TestCase):
    def test_extract_json_payload_prefers_full_document_before_nested_objects(self) -> None:
        payload = extract_json_payload('{"workspaceDir": "/tmp/ws", "skills": [{"name": "tmux", "eligible": true}, {"name": "slack", "eligible": false}]}')
        self.assertEqual(payload["workspaceDir"], "/tmp/ws")
        self.assertEqual(len(payload["skills"]), 2)

    def test_run_openclaw_json_accepts_large_json_stdout(self) -> None:
        stdout = json.dumps(
            {
                "workspaceDir": "/tmp/ws",
                "managedSkillsDir": "/tmp/skills",
                "skills": [
                    {"name": "tmux", "eligible": True},
                    {"name": "slack", "eligible": False},
                ],
            }
        )
        result = subprocess.CompletedProcess(
            args=["openclaw", "skills", "list", "--json"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )
        with patch("harness.openclaw_native.run_openclaw_command", return_value=result):
            payload = run_openclaw_json("skills", "list", "--json")
        self.assertEqual(payload["managedSkillsDir"], "/tmp/skills")
        self.assertEqual(len(payload["skills"]), 2)

        result = subprocess.CompletedProcess(
            args=["openclaw", "skills", "list", "--json"],
            returncode=0,
            stdout="",
            stderr='{"ok": true}\n[plugins] registered',
        )
        with patch("harness.openclaw_native.run_openclaw_command", return_value=result):
            payload = run_openclaw_json("skills", "list", "--json")
        self.assertEqual(payload, {"ok": True})

    def test_run_openclaw_command_prefers_env_binary_when_default_requested(self) -> None:
        with patch.dict(os.environ, {"OPENCLAW_BINARY": "/tmp/openclaw.mjs"}, clear=False):
            with patch("harness.openclaw_native.subprocess.run") as mocked_run:
                mocked_run.return_value = subprocess.CompletedProcess(
                    args=["/tmp/openclaw.mjs", "skills", "list", "--json"],
                    returncode=0,
                    stdout="{}",
                    stderr="",
                )
                run_openclaw_command("skills", "list", "--json")
        mocked_run.assert_called_once()
        invoked = mocked_run.call_args.args[0]
        self.assertEqual(invoked[0], "/tmp/openclaw.mjs")

    def test_parse_configured_channels_extracts_error_payload(self) -> None:
        channels = parse_configured_channels(
            "Error: Channel is required when multiple channels are configured: telegram, feishu"
        )
        self.assertEqual(channels, ["feishu", "telegram"])

    def test_infer_surface_status_detects_gateway_closed(self) -> None:
        self.assertEqual(infer_surface_status(GATEWAY_OUTPUT), "gateway_closed")

    def test_extract_gateway_target_parses_runtime_error(self) -> None:
        self.assertEqual(extract_gateway_target(GATEWAY_OUTPUT), "ws://127.0.0.1:18789")

    def test_grade_skills_process_rewards_direct_inventory_lookup(self) -> None:
        score = grade_skills_process(_trace("openclaw skills list --json"))
        self.assertEqual(score, 1.0)

    def test_grade_skills_process_accepts_skills_json_alias(self) -> None:
        score = grade_skills_process(_trace("openclaw skills --json"))
        self.assertEqual(score, 1.0)

    def test_collect_native_environment_snapshot_collects_surface_scoped_fingerprint(self) -> None:
        env = {"OPENCLAW_STATE_DIR": "/tmp/openclaw-bench-a", "OPENCLAW_GATEWAY_PORT": "19011"}
        with (
            patch("harness.openclaw_native.load_skills_inventory", return_value=SKILLS_FIXTURE) as load_skills_inventory,
            patch("harness.openclaw_native.load_agents_inventory", return_value=AGENTS_FIXTURE) as load_agents_inventory,
            patch("harness.openclaw_native.load_sessions_inventory", return_value=SESSIONS_FIXTURE) as load_sessions_inventory,
        ):
            snapshot = collect_native_environment_snapshot(["skills", "agents", "sessions"], env=env)

        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(snapshot["surfaces"], ["agents", "sessions", "skills"])
        self.assertEqual(snapshot["skills"]["ready_count"], 3)
        self.assertEqual(snapshot["skills"]["missing_count"], 3)
        self.assertEqual(snapshot["skills"]["ready_list"], ["feishu-calendar", "tmux", "weather"])
        self.assertEqual(snapshot["skills"]["first_missing_family_by_skill"]["slack"], "env")
        self.assertEqual(snapshot["agents"]["count"], 3)
        self.assertEqual(snapshot["agents"]["default_model"], "glm/GLM-5")
        self.assertEqual(snapshot["sessions"]["count"], 2)
        self.assertEqual(snapshot["sessions"]["over_context_limit"], ["agent:main:main"])
        self.assertEqual(snapshot["sessions"]["largest_session_key"], "agent:main:main")
        load_skills_inventory.assert_called_once_with(openclaw_bin="openclaw", env=env)
        load_agents_inventory.assert_called_once_with(openclaw_bin="openclaw", env=env)
        load_sessions_inventory.assert_called_once_with(openclaw_bin="openclaw", env=env)

    def test_trace_used_openclaw_exec_accepts_native_tool_aliases(self) -> None:
        trace = _tool_trace(
            ("agents_list", {}),
            ("sessions_list", {}),
            ("message_send", {"dryRun": True, "channel": "telegram", "target": "@benchmark_target"}),
            append_write=False,
        )
        self.assertTrue(trace_used_openclaw_exec(trace, "openclaw", "agents", "list", "--json"))
        self.assertTrue(trace_used_openclaw_exec(trace, "openclaw", "sessions", "--json"))
        self.assertTrue(trace_used_openclaw_exec(trace, "openclaw", "message", "send", "--dry-run", "--channel", "telegram"))
        self.assertEqual(trace_openclaw_surfaces_used(trace), {"agents", "message", "sessions"})

    def test_inventory_custom_check_scores_full(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "14_openclaw_skill_inventory_live.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            return_value=SKILLS_FIXTURE,
        ):
            Path(tmpdir, "skills_inventory_report.json").write_text(
                """
{"ready_count": 3, "missing_count": 3, "workspace_dir": "/Users/test/clawd", "managed_skills_dir": "/Users/test/.openclaw/skills", "ready_examples": ["feishu-calendar", "tmux", "weather"], "missing_examples": ["1password", "slack", "zeta"]}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace("openclaw skills list --json"),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_openclaw_skills_cli"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["counts_are_correct"]["score"], 0.25)
        self.assertEqual(result["checkpoints"]["paths_are_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["example_lists_are_correct"]["score"], 0.25)
        self.assertEqual(result["process_score"], 1.0)

    def test_inventory_custom_check_prefers_trace_snapshot_and_native_tool(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "14_openclaw_skill_inventory_live.yaml")
        audit_state = {
            "native_environment": {
                "version": 1,
                "surfaces": ["skills"],
                "skills": {
                    "status": "ready",
                    "ready_count": 3,
                    "missing_count": 3,
                    "workspace_dir": "/Users/test/clawd",
                    "managed_skills_dir": "/Users/test/.openclaw/skills",
                    "ready_examples": ["feishu-calendar", "tmux", "weather"],
                    "missing_examples": ["1password", "slack", "zeta"],
                    "ready_list": ["feishu-calendar", "tmux", "weather"],
                    "missing_list": ["1password", "slack", "zeta"],
                    "first_missing_family_by_skill": {"1password": "bins", "slack": "env", "zeta": "bins"},
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            side_effect=AssertionError("should use trace snapshot"),
        ):
            Path(tmpdir, "skills_inventory_report.json").write_text(
                """
{"ready_count": 3, "missing_count": 3, "workspace_dir": "/Users/test/clawd", "managed_skills_dir": "/Users/test/.openclaw/skills", "ready_examples": ["feishu-calendar", "tmux", "weather"], "missing_examples": ["1password", "slack", "zeta"]}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _tool_trace(("skills_list", {}), audit_state=audit_state),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_openclaw_skills_cli"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["counts_are_correct"]["score"], 0.25)
        self.assertEqual(result["checkpoints"]["paths_are_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["example_lists_are_correct"]["score"], 0.25)
        self.assertEqual(result["process_score"], 1.0)

    def test_routing_custom_check_scores_full(self) -> None:
        scenario = load_scenario(scenarios_root() / "planning" / "13_openclaw_skill_routing_live.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            return_value=SKILLS_FIXTURE,
        ):
            Path(tmpdir, "skill_routing_report.json").write_text(
                """
{"skill_by_request": {"feishu_calendar_event": "feishu-calendar", "weather_lookup": "weather", "slack_messaging": "slack"}, "supported_now": ["feishu_calendar_event", "weather_lookup"], "blocked_now": ["slack_messaging"], "blocked_reasons": {"slack_messaging": "env"}}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace("openclaw skills list --json"),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_openclaw_skills_cli"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["skill_mapping_is_correct"]["score"], 0.25)
        self.assertEqual(result["checkpoints"]["support_partition_is_correct"]["score"], 0.25)
        self.assertEqual(result["checkpoints"]["blocked_reasons_are_correct"]["score"], 0.2)
        self.assertEqual(result["process_score"], 1.0)

    def test_routing_custom_check_prefers_snapshot_and_native_tool(self) -> None:
        scenario = load_scenario(scenarios_root() / "planning" / "13_openclaw_skill_routing_live.yaml")
        audit_state = {
            "native_environment": {
                "version": 1,
                "surfaces": ["skills"],
                "skills": {
                    "status": "ready",
                    "ready_count": 3,
                    "missing_count": 3,
                    "workspace_dir": "/Users/test/clawd",
                    "managed_skills_dir": "/Users/test/.openclaw/skills",
                    "ready_examples": ["feishu-calendar", "tmux", "weather"],
                    "missing_examples": ["1password", "slack", "zeta"],
                    "ready_list": ["feishu-calendar", "tmux", "weather"],
                    "missing_list": ["1password", "slack", "zeta"],
                    "first_missing_family_by_skill": {"1password": "bins", "slack": "env", "zeta": "bins"},
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            side_effect=AssertionError("should use trace snapshot"),
        ):
            Path(tmpdir, "skill_routing_report.json").write_text(
                """
{"skill_by_request": {"feishu_calendar_event": "feishu-calendar", "weather_lookup": "weather", "slack_messaging": "slack"}, "supported_now": ["feishu_calendar_event", "weather_lookup"], "blocked_now": ["slack_messaging"], "blocked_reasons": {"slack_messaging": "env"}}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _tool_trace(("skills_list", {}), audit_state=audit_state),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_openclaw_skills_cli"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["skill_mapping_is_correct"]["score"], 0.25)
        self.assertEqual(result["checkpoints"]["support_partition_is_correct"]["score"], 0.25)
        self.assertEqual(result["checkpoints"]["blocked_reasons_are_correct"]["score"], 0.2)
        self.assertEqual(result["process_score"], 1.0)

    def test_source_audit_custom_check_scores_full(self) -> None:
        scenario = load_scenario(scenarios_root() / "synthesis" / "15_openclaw_skill_source_audit_live.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            return_value=SKILLS_FIXTURE,
        ):
            Path(tmpdir, "skill_source_audit.json").write_text(
                """
{"ready_bundled_count": 2, "ready_external_count": 1, "missing_due_to_bins_count": 2, "ready_bundled_examples": ["tmux", "weather"], "ready_external_examples": ["feishu-calendar"], "missing_due_to_bins_examples": ["1password", "zeta"]}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace("openclaw skills list --json"),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_openclaw_skills_cli"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["count_summary_is_correct"]["score"], 0.35)
        self.assertEqual(result["checkpoints"]["example_buckets_are_correct"]["score"], 0.35)
        self.assertEqual(result["process_score"], 1.0)

    def test_source_audit_partial_credit_accepts_cli_alias_and_field_level_counts(self) -> None:
        scenario = load_scenario(scenarios_root() / "synthesis" / "15_openclaw_skill_source_audit_live.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            return_value=SKILLS_FIXTURE,
        ):
            Path(tmpdir, "skill_source_audit.json").write_text(
                """
{"ready_bundled_count": 2, "ready_external_count": 1, "missing_due_to_bins_count": 99, "ready_bundled_examples": ["tmux", "weather"], "ready_external_examples": ["feishu-calendar", "wrong"], "missing_due_to_bins_examples": ["1password", "zeta"]}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace("openclaw skills list"),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_openclaw_skills_cli"]["score"], 0.2)
        self.assertAlmostEqual(result["checkpoints"]["count_summary_is_correct"]["score"], 0.2333, places=4)
        self.assertAlmostEqual(result["checkpoints"]["example_buckets_are_correct"]["score"], 0.2333, places=4)

    def test_skill_gap_remediation_custom_check_scores_full_on_overlapping_missing_families(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "intel_h01_skill_gap_remediation.yaml")
        skills_fixture = {
            "workspaceDir": "/Users/test/clawd",
            "managedSkillsDir": "/Users/test/.openclaw/skills",
            "skills": [
                {
                    "name": "ready",
                    "eligible": True,
                    "bundled": False,
                    "missing": {"bins": [], "anyBins": [], "env": [], "config": [], "os": []},
                },
                {
                    "name": "combo",
                    "eligible": False,
                    "bundled": True,
                    "missing": {
                        "bins": ["combo-cli"],
                        "anyBins": [],
                        "env": ["COMBO_TOKEN"],
                        "config": [],
                        "os": [],
                    },
                },
                {
                    "name": "env-only",
                    "eligible": False,
                    "bundled": True,
                    "missing": {
                        "bins": [],
                        "anyBins": [],
                        "env": ["ENV_ONLY_TOKEN"],
                        "config": [],
                        "os": [],
                    },
                },
                {
                    "name": "config-only",
                    "eligible": False,
                    "bundled": True,
                    "missing": {
                        "bins": [],
                        "anyBins": [],
                        "env": [],
                        "config": ["channels.discord.token"],
                        "os": [],
                    },
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            return_value=skills_fixture,
        ):
            Path(tmpdir, "gap_analysis.json").write_text(
                """
{"total_missing": 3, "by_family": {"bins": 1, "env": 2, "config": 1}, "most_common_family": "env", "skills_missing_bins": ["combo"], "skills_missing_env": ["combo", "env-only"], "remediation_priority": [{"family": "env", "count": 2, "affected_skills": ["combo", "env-only"], "fix_suggestion": "Set the missing environment variables."}, {"family": "bins", "count": 1, "affected_skills": ["combo"], "fix_suggestion": "Install the missing CLI binary."}, {"family": "config", "count": 1, "affected_skills": ["config-only"], "fix_suggestion": "Add the missing OpenClaw config entry."}]}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace("openclaw skills --json"),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_cli"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["file_exists"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["total_missing_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["by_family_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["most_common_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["skill_lists_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["priority_order_correct"]["score"], 0.15)
        self.assertEqual(result["process_score"], 1.0)

    def test_directory_probe_custom_check_scores_full(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "15_openclaw_directory_probe_live.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.directory_required_channels",
            return_value=DIRECTORY_CHANNELS,
        ), patch(
            "harness.openclaw_native.directory_peers",
            side_effect=lambda channel, limit=3: DIRECTORY_PEERS[channel],
        ):
            Path(tmpdir, "directory_probe.json").write_text(
                """
{"ambiguous_self_lookup": true, "channels_requiring_explicit_selection": ["feishu", "telegram"], "peer_counts": {"feishu": 1, "telegram": 0}, "non_empty_channels": ["feishu"], "first_non_empty_channel": "feishu"}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace(
                    "openclaw directory self --json",
                    "openclaw directory peers list --channel feishu --limit 3 --json",
                    "openclaw directory peers list --channel telegram --limit 3 --json",
                ),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_directory_self_probe"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["used_directory_peers_probe"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["ambiguity_summary_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["channels_are_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["peer_counts_are_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["non_empty_summary_is_correct"]["score"], 0.1)
        self.assertEqual(result["process_score"], 1.0)

    def test_memory_diagnosis_custom_check_scores_full(self) -> None:
        scenario = load_scenario(scenarios_root() / "error_recovery" / "13_openclaw_memory_search_diagnosis_live.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.memory_search_output",
            return_value=MEMORY_OUTPUT,
        ):
            Path(tmpdir, "memory_search_diagnosis.json").write_text(
                """
{"reported_no_matches": true, "search_is_reliable": false, "failure_mode": "database_unavailable", "error_signals": ["sync failed", "unable to open database file"], "recommended_action": "Fix the memory database/index before trusting this zero-result search."}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace("openclaw memory search --query test --max-results 3"),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_memory_search_cli"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["no_match_signal_is_interpreted_correctly"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["failure_mode_is_correct"]["score"], 0.25)
        self.assertEqual(result["checkpoints"]["reliability_flag_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["error_signals_are_grounded"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["recommended_action_is_grounded"]["score"], 0.1)
        self.assertEqual(result["process_score"], 1.0)

    def test_runtime_surface_matrix_custom_check_scores_full(self) -> None:
        scenario = load_scenario(scenarios_root() / "synthesis" / "16_openclaw_runtime_surface_matrix_live.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.directory_required_channels",
            return_value=DIRECTORY_CHANNELS,
        ), patch(
            "harness.openclaw_native.directory_peers",
            side_effect=lambda channel, limit=3: DIRECTORY_PEERS[channel],
        ), patch(
            "harness.openclaw_native.memory_search_output",
            return_value=MEMORY_OUTPUT,
        ):
            Path(tmpdir, "runtime_surface_matrix.json").write_text(
                """
{"directory_surface": {"status": "needs_explicit_channel", "channels": ["feishu", "telegram"], "non_empty_channels": ["feishu"]}, "memory_surface": {"status": "degraded", "reported_no_matches": true, "trust_zero_results": false}, "safer_surface_for_live_lookup": "directory", "notes": ["Directory still works if I choose a channel explicitly, and Feishu currently has peers.", "Memory search reports no matches but also shows database errors, so zero results are not trustworthy."]}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace(
                    "openclaw directory self --json",
                    "openclaw directory peers list --channel feishu --limit 3 --json",
                    "openclaw memory search --query test --max-results 3",
                ),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_directory_surface"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["used_memory_surface"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["directory_summary_is_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["memory_summary_is_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["safer_surface_is_correct"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["notes_are_grounded"]["score"], 0.1)
        self.assertEqual(result["process_score"], 1.0)

    def test_intel_e01_skill_inventory_partial_credit_is_per_field(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "intel_e01_skill_inventory.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            return_value=SKILLS_FIXTURE,
        ):
            Path(tmpdir, "skill_report.json").write_text(
                """
{"total_skills": 5, "ready_count": 3, "missing_count": 1, "ready_list": ["feishu-calendar", "tmux", "weather"], "missing_list": ["1password", "slack", "zeta"]}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace("openclaw skills list --json"),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_openclaw_skills_cli"]["score"], 0.2)
        self.assertAlmostEqual(result["checkpoints"]["counts_correct"]["score"], 0.1167, places=4)
        self.assertEqual(result["checkpoints"]["lists_correct"]["score"], 0.35)

    def test_intel_m06_session_health_check_uses_snapshot_and_native_tools(self) -> None:
        scenario = load_scenario(scenarios_root() / "synthesis" / "intel_m06_session_health_check.yaml")
        audit_state = {
            "native_environment": {
                "version": 1,
                "surfaces": ["agents", "sessions"],
                "agents": {"status": "ready", "count": 3, "default_model": "glm/GLM-5"},
                "sessions": {
                    "status": "ready",
                    "count": 2,
                    "over_context_limit": ["agent:main:main"],
                    "largest_session_key": "agent:main:main",
                    "largest_session_input_tokens": 255678,
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_sessions_inventory",
            side_effect=AssertionError("should use trace snapshot"),
        ), patch(
            "harness.openclaw_native.load_agents_inventory",
            side_effect=AssertionError("should use trace snapshot"),
        ):
            Path(tmpdir, "health_report.json").write_text(
                """
{"total_sessions": 2, "over_context_limit": ["agent:main:main"], "largest_session_key": "agent:main:main", "largest_session_input_tokens": 255678, "total_agents": 3, "default_agent_model": "glm/GLM-5", "health_summary": "warning"}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _tool_trace(("sessions_list", {}), ("agents_list", {}), audit_state=audit_state),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_sessions_cli"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["used_agents_cli"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["session_fields_correct"]["score"], 0.25)
        self.assertEqual(result["checkpoints"]["agent_fields_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["health_summary_correct"]["score"], 0.25)
        self.assertEqual(result["process_score"], 1.0)

    def test_intel_x01_full_system_audit_uses_snapshot_and_native_tools(self) -> None:
        scenario = load_scenario(scenarios_root() / "planning" / "intel_x01_full_system_audit.yaml")
        audit_state = {
            "native_environment": {
                "version": 1,
                "surfaces": ["agents", "browser", "cron", "directory", "memory", "sessions", "skills"],
                "skills": {
                    "status": "ready",
                    "ready_count": 3,
                    "missing_count": 3,
                    "workspace_dir": "/Users/test/clawd",
                    "managed_skills_dir": "/Users/test/.openclaw/skills",
                    "ready_examples": ["feishu-calendar", "tmux", "weather"],
                    "missing_examples": ["1password", "slack", "zeta"],
                    "ready_list": ["feishu-calendar", "tmux", "weather"],
                    "missing_list": ["1password", "slack", "zeta"],
                    "first_missing_family_by_skill": {"1password": "bins", "slack": "env", "zeta": "bins"},
                },
                "memory": {"status": "other_failure", "failure_mode": "database_unavailable"},
                "browser": {"status": "gateway_closed", "gateway_target": "ws://127.0.0.1:18789"},
                "cron": {"status": "gateway_closed"},
                "directory": {
                    "status": "ready",
                    "ambiguous_self_lookup": True,
                    "configured_channels": ["feishu", "telegram"],
                    "self_keys": ["channel", "id", "kind"],
                },
                "agents": {"status": "ready", "count": 3, "default_model": "glm/GLM-5"},
                "sessions": {
                    "status": "ready",
                    "count": 2,
                    "over_context_limit": ["agent:main:main"],
                    "largest_session_key": "agent:main:main",
                    "largest_session_input_tokens": 255678,
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            side_effect=AssertionError("should use trace snapshot"),
        ), patch(
            "harness.openclaw_native.memory_search_output",
            side_effect=AssertionError("should use trace snapshot"),
        ), patch(
            "harness.openclaw_native.load_agents_inventory",
            side_effect=AssertionError("should use trace snapshot"),
        ), patch(
            "harness.openclaw_native.load_sessions_inventory",
            side_effect=AssertionError("should use trace snapshot"),
        ):
            Path(tmpdir, "audit_report.json").write_text(
                """
{"surface_status": {"skills": {"ready_count": 3, "missing_count": 3}, "memory": {"status": "error"}, "agents": {"count": 3, "default_model": "glm/GLM-5"}, "sessions": {"count": 2, "over_limit": ["agent:main:main"]}}, "risks": [{"severity": "high", "description": "Memory surface is degraded because the database is unavailable.", "remediation": "Repair the memory database before trusting search results."}, {"severity": "medium", "description": "One session is already over the configured context limit.", "remediation": "Start a fresh session for large tasks."}, {"severity": "low", "description": "Browser and cron remain gateway-blocked on the current workstation.", "remediation": "Leave them out of live workflows until gateway connectivity is restored."}], "overall_health": "degraded", "health_score": 0.56}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _tool_trace(
                    ("skills_list", {}),
                    ("memory_search", {"query": "test", "maxResults": 3}),
                    ("browser_status", {}),
                    ("cron", {"action": "list"}),
                    ("directory_self", {}),
                    ("agents_list", {}),
                    ("sessions_list", {}),
                    audit_state=audit_state,
                ),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["probed_7_surfaces"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["skills_status_correct"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["memory_status_correct"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["agents_correct"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["sessions_correct"]["score"], 0.1)
        self.assertEqual(result["process_score"], 1.0)

    def test_intel_h03_temporal_constraint_scheduling_uses_snapshot(self) -> None:
        scenario = load_scenario(scenarios_root() / "constraints" / "intel_h03_temporal_constraint_scheduling.yaml")
        audit_state = {
            "native_environment": {
                "version": 1,
                "surfaces": ["skills"],
                "skills": {
                    "status": "ready",
                    "ready_count": 2,
                    "missing_count": 3,
                    "workspace_dir": "/Users/test/clawd",
                    "managed_skills_dir": "/Users/test/.openclaw/skills",
                    "ready_examples": ["tmux", "weather"],
                    "missing_examples": ["1password", "docker", "slack"],
                    "ready_list": ["tmux", "weather"],
                    "missing_list": ["1password", "docker", "slack"],
                    "first_missing_family_by_skill": {"1password": "bins", "docker": "bins", "slack": "env"},
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            side_effect=AssertionError("should use trace snapshot"),
        ):
            Path(tmpdir, "schedule_input.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "s1",
                                "duration_hours": 2,
                                "earliest_start": "2026-04-01T08:00:00Z",
                                "deadline": "2026-04-01T10:00:00Z",
                                "requires_skill": "tmux",
                            },
                            {
                                "id": "s2",
                                "duration_hours": 3,
                                "earliest_start": "2026-04-01T09:00:00Z",
                                "deadline": "2026-04-01T14:00:00Z",
                                "requires_skill": "weather",
                            },
                            {
                                "id": "s3",
                                "duration_hours": 1,
                                "earliest_start": "2026-04-01T08:00:00Z",
                                "deadline": "2026-04-01T10:00:00Z",
                                "requires_skill": "tmux",
                            },
                            {
                                "id": "s4",
                                "duration_hours": 2,
                                "earliest_start": "2026-04-01T11:00:00Z",
                                "deadline": "2026-04-01T14:00:00Z",
                                "requires_skill": "weather",
                            },
                            {
                                "id": "s5",
                                "duration_hours": 2,
                                "earliest_start": "2026-04-01T13:00:00Z",
                                "deadline": "2026-04-01T17:00:00Z",
                                "requires_skill": "tmux",
                            },
                            {
                                "id": "s6",
                                "duration_hours": 2,
                                "earliest_start": "2026-04-01T08:00:00Z",
                                "deadline": "2026-04-01T11:00:00Z",
                                "requires_skill": "slack",
                            },
                            {
                                "id": "s7",
                                "duration_hours": 1,
                                "earliest_start": "2026-04-01T10:00:00Z",
                                "deadline": "2026-04-01T12:00:00Z",
                                "requires_skill": "1password",
                            },
                            {
                                "id": "s8",
                                "duration_hours": 2,
                                "earliest_start": "2026-04-01T12:00:00Z",
                                "deadline": "2026-04-01T16:00:00Z",
                                "requires_skill": "docker",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            Path(tmpdir, "schedule.json").write_text(
                json.dumps(
                    {
                        "scheduled": [
                            {
                                "task_id": "s3",
                                "start": "2026-04-01T08:00:00Z",
                                "end": "2026-04-01T09:00:00Z",
                            },
                            {
                                "task_id": "s2",
                                "start": "2026-04-01T09:00:00Z",
                                "end": "2026-04-01T12:00:00Z",
                            },
                            {
                                "task_id": "s4",
                                "start": "2026-04-01T12:00:00Z",
                                "end": "2026-04-01T14:00:00Z",
                            },
                            {
                                "task_id": "s5",
                                "start": "2026-04-01T14:00:00Z",
                                "end": "2026-04-01T16:00:00Z",
                            }
                        ],
                        "blocked": [
                            {"task_id": "s6", "reason": "skill_unavailable", "required_skill": "slack"},
                            {"task_id": "s7", "reason": "skill_unavailable", "required_skill": "1password"},
                            {"task_id": "s8", "reason": "skill_unavailable", "required_skill": "docker"},
                        ],
                        "unschedulable": [{"task_id": "s1", "reason": "time_conflict"}],
                        "total_scheduled_hours": 8,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _tool_trace(
                    ("skills_list", {}),
                    ("read", {"path": "schedule_input.json"}),
                    audit_state=audit_state,
                ),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_skills_cli"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["blocked_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["schedule_is_feasible"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["optimal_schedule_selected"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["unschedulable_is_correct"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["total_hours_is_optimal"]["score"], 0.1)
        self.assertEqual(result["process_score"], 1.0)

    def test_intel_h03_rejects_suboptimal_schedule(self) -> None:
        scenario = load_scenario(scenarios_root() / "constraints" / "intel_h03_temporal_constraint_scheduling.yaml")
        audit_state = {
            "native_environment": {
                "version": 1,
                "surfaces": ["skills"],
                "skills": {
                    "status": "ready",
                    "ready_count": 2,
                    "missing_count": 3,
                    "workspace_dir": "/Users/test/clawd",
                    "managed_skills_dir": "/Users/test/.openclaw/skills",
                    "ready_examples": ["tmux", "weather"],
                    "missing_examples": ["1password", "docker", "slack"],
                    "ready_list": ["tmux", "weather"],
                    "missing_list": ["1password", "docker", "slack"],
                    "first_missing_family_by_skill": {"1password": "bins", "docker": "bins", "slack": "env"},
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            side_effect=AssertionError("should use trace snapshot"),
        ):
            Path(tmpdir, "schedule_input.json").write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "s1",
                                "duration_hours": 2,
                                "earliest_start": "2026-04-01T08:00:00Z",
                                "deadline": "2026-04-01T10:00:00Z",
                                "requires_skill": "tmux",
                            },
                            {
                                "id": "s2",
                                "duration_hours": 3,
                                "earliest_start": "2026-04-01T09:00:00Z",
                                "deadline": "2026-04-01T14:00:00Z",
                                "requires_skill": "weather",
                            },
                            {
                                "id": "s3",
                                "duration_hours": 1,
                                "earliest_start": "2026-04-01T08:00:00Z",
                                "deadline": "2026-04-01T10:00:00Z",
                                "requires_skill": "tmux",
                            },
                            {
                                "id": "s4",
                                "duration_hours": 2,
                                "earliest_start": "2026-04-01T11:00:00Z",
                                "deadline": "2026-04-01T14:00:00Z",
                                "requires_skill": "weather",
                            },
                            {
                                "id": "s5",
                                "duration_hours": 2,
                                "earliest_start": "2026-04-01T13:00:00Z",
                                "deadline": "2026-04-01T17:00:00Z",
                                "requires_skill": "tmux",
                            },
                            {
                                "id": "s6",
                                "duration_hours": 2,
                                "earliest_start": "2026-04-01T08:00:00Z",
                                "deadline": "2026-04-01T11:00:00Z",
                                "requires_skill": "slack",
                            },
                            {
                                "id": "s7",
                                "duration_hours": 1,
                                "earliest_start": "2026-04-01T10:00:00Z",
                                "deadline": "2026-04-01T12:00:00Z",
                                "requires_skill": "1password",
                            },
                            {
                                "id": "s8",
                                "duration_hours": 2,
                                "earliest_start": "2026-04-01T12:00:00Z",
                                "deadline": "2026-04-01T16:00:00Z",
                                "requires_skill": "docker",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            Path(tmpdir, "schedule.json").write_text(
                json.dumps(
                    {
                        "scheduled": [
                            {"task_id": "s1", "start": "2026-04-01T08:00:00Z", "end": "2026-04-01T10:00:00Z"},
                            {"task_id": "s2", "start": "2026-04-01T10:00:00Z", "end": "2026-04-01T13:00:00Z"},
                            {"task_id": "s5", "start": "2026-04-01T13:00:00Z", "end": "2026-04-01T15:00:00Z"},
                        ],
                        "blocked": [
                            {"task_id": "s6", "reason": "skill_unavailable", "required_skill": "slack"},
                            {"task_id": "s7", "reason": "skill_unavailable", "required_skill": "1password"},
                            {"task_id": "s8", "reason": "skill_unavailable", "required_skill": "docker"},
                        ],
                        "unschedulable": [
                            {"task_id": "s3", "reason": "time_conflict"},
                            {"task_id": "s4", "reason": "time_conflict"},
                        ],
                        "total_scheduled_hours": 7,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _tool_trace(
                    ("skills_list", {}),
                    ("read", {"path": "schedule_input.json"}),
                    audit_state=audit_state,
                ),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["blocked_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["schedule_is_feasible"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["optimal_schedule_selected"]["score"], 0.0)
        self.assertEqual(result["checkpoints"]["unschedulable_is_correct"]["score"], 0.0)
        self.assertEqual(result["checkpoints"]["total_hours_is_optimal"]["score"], 0.0)

    def test_intel_x02_adversarial_multi_step_uses_snapshot(self) -> None:
        scenario = load_scenario(scenarios_root() / "constraints" / "intel_x02_adversarial_multi_step.yaml")
        audit_state = {
            "native_environment": {
                "version": 1,
                "surfaces": ["skills"],
                "skills": {
                    "status": "ready",
                    "ready_count": 3,
                    "missing_count": 3,
                    "workspace_dir": "/Users/test/clawd",
                    "managed_skills_dir": "/Users/test/.openclaw/skills",
                    "ready_examples": ["feishu-calendar", "tmux", "weather"],
                    "missing_examples": ["1password", "slack", "zeta"],
                    "ready_list": ["feishu-calendar", "tmux", "weather"],
                    "missing_list": ["1password", "slack", "zeta"],
                    "first_missing_family_by_skill": {"1password": "bins", "slack": "env", "zeta": "bins"},
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_skills_inventory",
            side_effect=AssertionError("should use trace snapshot"),
        ):
            Path(tmpdir, "output.json").write_text(
                json.dumps(
                    {
                        "workflow_completed": True,
                        "steps_executed": 5,
                        "skills_status": {"ready": 3, "missing": 3},
                        "filtered_count": 6,
                        "aggregation": {"sum": 7481.60, "avg": 1496.32, "max": 3456.79, "min": 789.01},
                        "constraint_notes": ["Detected the contradictory score rules and kept the stricter score >= 60 constraint."],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _tool_trace(
                    ("skills_list", {}),
                    ("read", {"path": "workflow.json"}),
                    ("read", {"path": "data.json"}),
                    audit_state=audit_state,
                ),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["skills_queried"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["completed_all_steps"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["filter_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["aggregation_precise"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["contradiction_handled"]["score"], 0.15)
        self.assertEqual(result["process_score"], 1.0)

    def test_message_dry_run_custom_check_scores_full(self) -> None:
        scenario = load_scenario(scenarios_root() / "tool_use" / "16_openclaw_message_dry_run_live.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.message_dry_run_payload",
            return_value=MESSAGE_DRY_RUN_FIXTURE,
        ):
            Path(tmpdir, "message_dry_run_report.json").write_text(
                """
{"channel": "telegram", "handled_by": "core", "delivery_route": "telegram:@benchmark_target", "via": "direct", "dry_run": true, "has_media": false}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace("openclaw message send --dry-run --json --channel telegram --target @benchmark_target --message 'hello from benchmark'"),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_openclaw_message_cli"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["core_fields_are_correct"]["score"], 0.25)
        self.assertEqual(result["checkpoints"]["delivery_route_is_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["dry_run_flag_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["transport_fields_are_correct"]["score"], 0.1)
        self.assertEqual(result["process_score"], 1.0)

    def test_session_pressure_custom_check_scores_full(self) -> None:
        scenario = load_scenario(scenarios_root() / "planning" / "14_openclaw_session_pressure_live.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_sessions_inventory",
            return_value=SESSIONS_FIXTURE,
        ):
            Path(tmpdir, "sessions_pressure_report.json").write_text(
                """
{"session_count": 2, "any_session_over_context_limit": true, "over_limit_session_keys": ["agent:main:main"], "largest_input_tokens_session": "agent:main:main", "largest_input_tokens": 255678, "largest_context_limit": 200000, "recommended_action": "start_fresh_session"}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace("openclaw sessions --json"),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_openclaw_sessions_cli"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["session_count_is_correct"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["over_limit_summary_is_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["largest_session_summary_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["recommended_action_is_correct"]["score"], 0.1)
        self.assertEqual(result["process_score"], 1.0)

    def test_release_reminder_readiness_custom_check_scores_full(self) -> None:
        scenario = load_scenario(scenarios_root() / "planning" / "15_openclaw_release_reminder_readiness_live.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.load_agents_inventory",
            return_value=AGENTS_FIXTURE,
        ), patch(
            "harness.openclaw_native.load_skills_inventory",
            return_value=SKILLS_FIXTURE,
        ), patch(
            "harness.openclaw_native.message_dry_run_payload",
            return_value=MESSAGE_DRY_RUN_FIXTURE,
        ):
            Path(tmpdir, "release_reminder_readiness.json").write_text(
                """
{"default_agent_id": "main", "default_agent_model": "glm/GLM-5", "default_agent_workspace": "/Users/test/clawd", "calendar_skill_status": "ready_external", "telegram_delivery_route": "telegram:@benchmark_target", "telegram_handled_by": "core", "telegram_via": "direct", "safe_to_stage_release_reminder": true, "blocking_reasons": []}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace(
                    "openclaw agents list --json",
                    "openclaw skills list --json",
                    "openclaw message send --dry-run --json --channel telegram --target @benchmark_target --message 'hello from benchmark'",
                ),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_openclaw_agents_cli"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["used_openclaw_skills_cli"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["used_openclaw_message_cli"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["agent_summary_is_correct"]["score"], 0.2)
        self.assertEqual(result["checkpoints"]["calendar_skill_status_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["telegram_delivery_summary_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["readiness_decision_is_correct"]["score"], 0.1)
        self.assertEqual(result["process_score"], 1.0)

    def test_gateway_surface_matrix_custom_check_scores_full(self) -> None:
        scenario = load_scenario(scenarios_root() / "synthesis" / "17_openclaw_gateway_surface_matrix_live.yaml")
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "harness.openclaw_native.browser_status_output",
            return_value=GATEWAY_OUTPUT,
        ), patch(
            "harness.openclaw_native.cron_list_output",
            return_value=GATEWAY_OUTPUT,
        ), patch(
            "harness.openclaw_native.message_dry_run_payload",
            return_value=MESSAGE_DRY_RUN_FIXTURE,
        ):
            Path(tmpdir, "gateway_surface_matrix.json").write_text(
                """
{"browser": {"status": "gateway_closed", "gateway_target": "ws://127.0.0.1:18789"}, "cron": {"status": "gateway_closed", "gateway_target": "ws://127.0.0.1:18789"}, "message_dry_run": {"status": "ready", "delivery_route": "telegram:@benchmark_target", "dry_run": true}, "safe_for_native_benchmarking_now": ["message_dry_run"], "blocked_by_gateway": ["browser", "cron"], "recommended_starting_surface": "message_dry_run"}
""".strip(),
                encoding="utf-8",
            )
            result = run_custom_checks(
                scenario,
                Path(tmpdir),
                _trace(
                    "openclaw browser status --json",
                    "openclaw cron list --json",
                    "openclaw message send --dry-run --json --channel telegram --target @benchmark_target --message 'hello from benchmark'",
                ),
                [],
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["checkpoints"]["used_browser_status_probe"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["used_cron_list_probe"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["used_message_dry_run_probe"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["browser_summary_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["cron_summary_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["message_summary_is_correct"]["score"], 0.15)
        self.assertEqual(result["checkpoints"]["surface_partitions_are_correct"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["recommended_surface_is_correct"]["score"], 0.05)
        self.assertEqual(result["process_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
