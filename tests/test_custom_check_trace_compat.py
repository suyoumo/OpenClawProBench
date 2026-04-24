from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.custom_checks import run_custom_checks
from harness.loader import load_scenario, scenarios_root
from harness.runner import _copy_workspace_files


class CustomCheckTraceCompatTests(unittest.TestCase):
    def _run_custom(self, relative_path: str, trace: dict) -> dict:
        scenario = load_scenario(scenarios_root() / relative_path)
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            _copy_workspace_files(scenario, workspace)
            tool_calls = [event for event in trace.get("events", []) if event.get("type") == "tool_call"]
            result = run_custom_checks(scenario, workspace, trace, tool_calls)
        self.assertIsNotNone(result)
        return result or {}

    def test_constraints_14_process_accepts_file_alias(self) -> None:
        trace = {
            "events": [
                {"type": "tool_call", "tool": "read", "args": {"file": "/tmp/feedback_thread.txt"}},
                {"type": "tool_call", "tool": "read", "args": {"file": "/tmp/security_notice.md"}},
                {"type": "tool_call", "tool": "read", "args": {"file": "/tmp/summary_rules.txt"}},
                {"type": "tool_call", "tool": "write", "args": {"file": "/tmp/safe_feedback_summary.md"}},
            ]
        }
        result = self._run_custom("constraints/14_safe_summary_bounded_live.yaml", trace)
        self.assertEqual(result.get("process_score"), 1.0)

    def test_synthesis_19_process_accepts_file_alias(self) -> None:
        trace = {
            "events": [
                {"type": "tool_call", "tool": "read", "args": {"file": "/tmp/incident_ticket.md"}},
                {"type": "tool_call", "tool": "read", "args": {"file": "/tmp/service_logs.json"}},
                {"type": "tool_call", "tool": "read", "args": {"file": "/tmp/deploy_history.json"}},
                {"type": "tool_call", "tool": "read", "args": {"file": "/tmp/runbook_excerpt.txt"}},
                {"type": "tool_call", "tool": "write", "args": {"file": "/tmp/incident_cause_chain.json"}},
            ]
        }
        result = self._run_custom("synthesis/19_incident_cause_chain_live.yaml", trace)
        self.assertEqual(result.get("process_score"), 1.0)

    def test_tool_use_21_process_accepts_file_alias(self) -> None:
        trace = {
            "events": [
                {"type": "tool_call", "tool": "cron", "args": {"action": "add", "recurring": True, "cron": "13 * * * *"}},
                {"type": "tool_call", "tool": "write", "args": {"file": "/tmp/cron_monitor_plan.json"}},
            ]
        }
        result = self._run_custom("tool_use/21_recurring_cron_expiry_notice_live.yaml", trace)
        self.assertEqual(result.get("process_score"), 1.0)
