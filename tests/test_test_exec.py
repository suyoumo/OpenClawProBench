from __future__ import annotations

import tempfile
import textwrap
import unittest
from importlib.util import find_spec
from pathlib import Path

from harness.test_exec import (
    count_test_functions,
    first_existing_path,
    has_valid_python_syntax,
    run_test_file,
    summarize_test_file,
)


class TestExecTests(unittest.TestCase):
    def test_first_existing_path_prefers_named_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            named = workspace / "main.py"
            nested = workspace / "nested" / "app.py"
            nested.parent.mkdir()
            named.write_text("print('main')\n", encoding="utf-8")
            nested.write_text("print('nested')\n", encoding="utf-8")

            result = first_existing_path(workspace, ["main.py", "server.py"], "app.py")

        self.assertEqual(result, named)

    def test_has_valid_python_syntax_handles_valid_and_invalid_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            valid = workspace / "valid.py"
            invalid = workspace / "invalid.py"
            valid.write_text("value = 1\n", encoding="utf-8")
            invalid.write_text("def broken(:\n", encoding="utf-8")

            self.assertTrue(has_valid_python_syntax(valid))
            self.assertFalse(has_valid_python_syntax(invalid))

    @unittest.skipUnless(find_spec("pytest") is not None, "pytest is required for pytest-style test execution")
    def test_run_test_file_supports_pytest_style_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / "test_example.py"
            test_file.write_text(
                textwrap.dedent(
                    """
                    def test_one():
                        assert True

                    def test_two():
                        assert 1 + 1 == 2
                    """
                ),
                encoding="utf-8",
            )

            summary = summarize_test_file(workspace, test_file, timeout_seconds=30)

        self.assertEqual((summary.passed, summary.total, summary.discovered), (2, 2, 2))

    def test_run_test_file_supports_unittest_style_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / "test_example.py"
            test_file.write_text(
                textwrap.dedent(
                    """
                    import unittest

                    class SampleTests(unittest.TestCase):
                        def test_one(self):
                            self.assertTrue(True)

                        def test_two(self):
                            self.assertEqual(2 * 2, 4)

                    if __name__ == "__main__":
                        unittest.main()
                    """
                ),
                encoding="utf-8",
            )

            passed, total = run_test_file(workspace, test_file, timeout_seconds=30)
            test_count = count_test_functions(test_file)

        self.assertEqual((passed, total), (2, 2))
        self.assertEqual(test_count, 2)
