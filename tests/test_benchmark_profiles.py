from __future__ import annotations

import unittest

from harness.benchmark_profiles import benchmark_profile_choices, infer_benchmark_profile, resolve_benchmark_selection


class BenchmarkProfileTests(unittest.TestCase):
    def test_core_profile_resolves_to_intelligence_core(self) -> None:
        selection = resolve_benchmark_selection("core")

        self.assertEqual(selection["benchmark_profile"], "core")
        self.assertEqual(selection["benchmark_group"], "intelligence")
        self.assertTrue(selection["benchmark_core"])
        self.assertIsNone(selection["signal_source"])

    def test_full_profile_resolves_to_unfiltered_selection(self) -> None:
        selection = resolve_benchmark_selection("full")

        self.assertEqual(selection["benchmark_profile"], "full")
        self.assertIsNone(selection["benchmark_group"])
        self.assertIsNone(selection["benchmark_core"])
        self.assertIsNone(selection["signal_source"])

    def test_native_profile_resolves_to_active_openclaw_native_slice(self) -> None:
        selection = resolve_benchmark_selection("native")

        self.assertEqual(selection["benchmark_profile"], "native")
        self.assertEqual(selection["benchmark_status"], "active")
        self.assertEqual(selection["signal_source"], "openclaw_native")

    def test_profile_choices_exclude_removed_smoke_profile(self) -> None:
        self.assertNotIn("smoke", benchmark_profile_choices())

    def test_non_canonical_override_becomes_custom(self) -> None:
        selection = resolve_benchmark_selection("core", benchmark_core=False)

        self.assertEqual(selection["benchmark_profile"], "custom")
        self.assertEqual(selection["benchmark_group"], "intelligence")
        self.assertFalse(selection["benchmark_core"])
        self.assertEqual(infer_benchmark_profile("intelligence", False, "active", None), "custom")


if __name__ == "__main__":
    unittest.main()
