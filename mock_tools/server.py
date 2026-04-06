"""Mock tool server with fault injection and optional FastAPI wrapper."""

from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from typing import Any

try:
    from fastapi import FastAPI
except ImportError:  # pragma: no cover - optional dependency
    FastAPI = None


class MockToolServer:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._scenario: dict[str, Any] = {}
        self._tool_calls: list[dict[str, Any]] = []
        self._audit: dict[str, Any] = {
            "email": {"drafts": [], "sent": []},
            "calendar": {"created_events": []},
            "files": {"created": [], "modified": [], "deleted": []},
        }
        self._fault_hits: dict[str, int] = {}

    def set_scenario(self, scenario: dict[str, Any]) -> None:
        self.reset()
        self._scenario = deepcopy(scenario)

    def get_tool_calls(self) -> list[dict[str, Any]]:
        return deepcopy(self._tool_calls)

    def get_audit(self) -> dict[str, Any]:
        return deepcopy(self._audit)

    def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        self._tool_calls.append(
            {
                "tool": tool_name,
                "args": deepcopy(payload),
                "timestamp": now,
            }
        )

        fault = self._resolve_fault(tool_name, payload)
        if fault is not None:
            return fault

        rules = (self._scenario.get("mock_responses") or {}).get(tool_name, [])
        payload_text = json.dumps(payload, ensure_ascii=False)
        for rule in rules:
            trigger = str(rule.get("trigger", ".*"))
            if re.search(trigger, payload_text, re.IGNORECASE):
                self._apply_audit_updates(rule.get("audit_updates") or {})
                status = str(rule.get("status", "completed"))
                return {
                    "status": status,
                    "status_code": int(rule.get("exit_code", 200)),
                    "response": deepcopy(rule.get("response")),
                }

        return {"status": "completed", "status_code": 200, "response": {}}

    def _resolve_fault(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        payload_text = json.dumps(payload, ensure_ascii=False)
        for index, fault in enumerate(self._scenario.get("fault_injection") or []):
            if fault.get("tool") != tool_name:
                continue
            trigger = str(fault.get("trigger", ".*"))
            if not re.search(trigger, payload_text, re.IGNORECASE):
                continue
            key = f"{tool_name}:{index}"
            hits = self._fault_hits.get(key, 0)
            fault_type = fault.get("fault_type")

            if fault_type == "error_then_success":
                success_after = int(fault.get("success_after", 1))
                if hits < success_after:
                    self._fault_hits[key] = hits + 1
                    return {
                        "status": "error",
                        "status_code": int(fault.get("error_code", 500)),
                        "response": fault.get("error_response", "fault injected error"),
                    }
                continue

            if fault_type == "persistent_error":
                return {
                    "status": "error",
                    "status_code": int(fault.get("error_code", 500)),
                    "response": fault.get("error_response", "persistent fault"),
                }

            if fault_type == "timeout":
                return {
                    "status": "timeout",
                    "status_code": 504,
                    "response": fault.get("error_response", "simulated timeout"),
                }

            if fault_type == "partial_response":
                return {
                    "status": "completed",
                    "status_code": 206,
                    "response": deepcopy(fault.get("partial_response", {})),
                }
        return None

    def _apply_audit_updates(self, updates: dict[str, Any]) -> None:
        for path, value in updates.items():
            current = self._audit
            parts = path.split(".")
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            leaf = parts[-1]
            if isinstance(current.get(leaf), list):
                current[leaf].append(deepcopy(value))
            else:
                current[leaf] = deepcopy(value)


def create_app(server: MockToolServer | None = None):  # pragma: no cover - optional dependency
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Install requirements.txt to run the HTTP server.")
    runtime = server or MockToolServer()
    app = FastAPI(title="OpenClawBench v6 Mock Tools")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/set_scenario")
    def set_scenario(payload: dict[str, Any]):
        runtime.set_scenario(payload)
        return {"ok": True}

    @app.post("/tools/{tool_name}")
    def call_tool(tool_name: str, payload: dict[str, Any]):
        return runtime.call_tool(tool_name, payload)

    @app.get("/tool_calls")
    def tool_calls():
        return runtime.get_tool_calls()

    @app.get("/audit")
    def audit():
        return runtime.get_audit()

    @app.post("/reset")
    def reset():
        runtime.reset()
        return {"ok": True}

    return app

