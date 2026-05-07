from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import custom_checks
from harness.custom_checks import _load_module


class CustomCheckLoaderRetryTests(unittest.TestCase):
    def test_load_module_retries_transient_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            module_path = Path(tmpdir) / "temp_custom_check.py"
            module_path.write_text("VALUE = 7\n", encoding="utf-8")
            real_spec_from_file_location = __import__("importlib.util").util.spec_from_file_location
            attempts = {"count": 0}

            def flaky_spec_from_file_location(name, location):
                spec = real_spec_from_file_location(name, location)
                loader = spec.loader
                real_exec_module = loader.exec_module

                def flaky_exec_module(module):
                    attempts["count"] += 1
                    if attempts["count"] == 1:
                        raise PermissionError("[Errno 1] Operation not permitted")
                    return real_exec_module(module)

                loader.exec_module = flaky_exec_module
                return spec

            with (
                mock.patch("harness.custom_checks.importlib.util.spec_from_file_location", side_effect=flaky_spec_from_file_location),
                mock.patch("harness.custom_checks._load_module_from_source", side_effect=PermissionError("fallback blocked")),
                mock.patch("harness.custom_checks.time.sleep"),
            ):
                module = _load_module(module_path)

        self.assertEqual(module.VALUE, 7)
        self.assertEqual(attempts["count"], 2)

    def test_load_module_falls_back_to_source_read_after_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            module_path = Path(tmpdir) / "temp_custom_check.py"
            module_path.write_text("VALUE = 11\n", encoding="utf-8")
            real_spec_from_file_location = __import__("importlib.util").util.spec_from_file_location

            def flaky_spec_from_file_location(name, location):
                spec = real_spec_from_file_location(name, location)

                def blocked_exec_module(_module):
                    raise PermissionError("[Errno 1] Operation not permitted")

                spec.loader.exec_module = blocked_exec_module
                return spec

            with mock.patch("harness.custom_checks.importlib.util.spec_from_file_location", side_effect=flaky_spec_from_file_location):
                module = _load_module(module_path)

        self.assertEqual(module.VALUE, 11)

    def test_load_module_reuses_cached_module_for_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            module_path = Path(tmpdir) / "temp_custom_check.py"
            module_path.write_text("VALUE = 13\n", encoding="utf-8")
            custom_checks._MODULE_CACHE.clear()

            first = _load_module(module_path)
            with mock.patch("harness.custom_checks.importlib.util.spec_from_file_location") as spec_from_file_location:
                second = _load_module(module_path)

        self.assertIs(first, second)
        spec_from_file_location.assert_not_called()


if __name__ == "__main__":
    unittest.main()
