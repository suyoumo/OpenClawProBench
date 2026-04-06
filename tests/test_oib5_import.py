from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

from harness.custom_checks import run_custom_checks
from harness.loader import load_scenario, scenarios_root
from harness.runner import _copy_workspace_files


class OIB5ImportTests(unittest.TestCase):
    def _load_t17_module(self):
        path = scenarios_root().parents[0] / "custom_checks" / "oib5" / "t17_fault_recovery.py"
        spec = importlib.util.spec_from_file_location("t17_fault_recovery_test", path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _load_oib5_module(self, module_name: str):
        path = scenarios_root().parents[0] / "custom_checks" / "oib5" / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(f"{module_name}_test", path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_workspace_seed_dir_copies_nested_fixtures(self) -> None:
        scenario = load_scenario(scenarios_root() / "oib5" / "oib5_t04_file_search.yaml")
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            _copy_workspace_files(scenario, workspace)
            self.assertTrue((workspace / "logs" / "app.log").exists())
            self.assertTrue((workspace / "logs" / "auth.log").exists())
            self.assertTrue((workspace / "logs" / "worker.log").exists())

    def test_imported_custom_check_uses_grade_process(self) -> None:
        scenario = load_scenario(scenarios_root() / "oib5" / "oib5_t01_file_extraction.yaml")
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            _copy_workspace_files(scenario, workspace)
            result = run_custom_checks(
                scenario,
                workspace,
                {"events": [], "metrics": {"tool_calls": 0}},
                [],
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("checkpoints", result)
        self.assertIn("file_exists", result["checkpoints"])
        self.assertIn("process_score", result)
        self.assertEqual(result["process_score"], 1.0)

    def test_t17_fault_recovery_check_tolerates_permission_denied_paths(self) -> None:
        module = self._load_t17_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            blocked = workspace / "output"
            blocked.mkdir()
            os.chmod(blocked, 0)
            try:
                result = module.grade(str(workspace), {"events": []})
            finally:
                os.chmod(blocked, 0o755)

        self.assertIn("checkpoints", result)
        self.assertEqual(result["checkpoints"]["alternative_found"]["score"], 0.0)
        self.assertEqual(result["checkpoints"]["result_correct"]["score"], 0.0)

    @unittest.skipUnless(find_spec("pytest") is not None, "pytest is required for pytest-style test execution")
    def test_t23_fullstack_check_counts_pytest_style_results(self) -> None:
        module = self._load_oib5_module("t23_fullstack_project")
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "main.py").write_text(
                """
from fastapi import FastAPI, HTTPException
app = FastAPI()
DATABASE = "todos.db"

def row_to_dict(row):
    return row

@app.get("/todos")
def list_todos():
    return []

@app.post("/todos")
def create_todo():
    raise HTTPException(status_code=400, detail="bad")

@app.get("/todos/{todo_id}")
def get_todo(todo_id: int):
    raise HTTPException(status_code=404, detail="missing")

@app.put("/todos/{todo_id}")
def update_todo(todo_id: int):
    return {"created_at": "2026-01-01T00:00:00Z", "priority": "high"}

@app.delete("/todos/{todo_id}")
def delete_todo(todo_id: int):
    return {"message": "deleted"}
                """.strip(),
                encoding="utf-8",
            )
            (workspace / "README.md").write_text("run instructions " * 5, encoding="utf-8")
            (workspace / "test_api.py").write_text(
                """
def test_one():
    assert True

def test_two():
    assert True

def test_three():
    assert True

def test_four():
    assert True

def test_five():
    assert True

def test_six():
    assert True

def test_seven():
    assert True

def test_eight():
    assert True
                """.strip(),
                encoding="utf-8",
            )

            result = module.grade(str(workspace), {"events": []})

        self.assertEqual(result["checkpoints"]["test_count"]["detail"], "8 tests (need >= 8)")
        self.assertEqual(result["checkpoints"]["test_count"]["score"], 0.1)
        self.assertEqual(result["checkpoints"]["tests_pass"]["detail"], "8/8 passed")
        self.assertEqual(result["checkpoints"]["tests_pass"]["score"], 0.3)


if __name__ == "__main__":
    unittest.main()
