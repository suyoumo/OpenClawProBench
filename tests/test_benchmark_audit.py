from __future__ import annotations

from collections import Counter
import unittest

from scripts.audit_benchmark_profile import audit_profile
from harness.loader import load_scenarios


class BenchmarkAuditTests(unittest.TestCase):
    def test_core_audit_includes_live_subset_guardrails(self) -> None:
        summary = audit_profile("core")
        expected = load_scenarios(benchmark_group="intelligence", benchmark_core=True)
        expected_live = [scenario for scenario in expected if scenario.execution_mode == "live"]

        self.assertEqual(summary["scenario_count"], len(expected))
        self.assertEqual(summary["signal_sources"], dict(Counter(scenario.signal_source.value for scenario in expected)))
        self.assertEqual(summary["live_subset"]["scenario_count"], len(expected_live))
        self.assertEqual(summary["live_subset"]["dimensions"], dict(Counter(scenario.dimension.value for scenario in expected_live)))
        self.assertLessEqual(summary["live_subset"]["easy_weight_share"], 0.05)
        self.assertLessEqual(summary["live_subset"]["medium_weight_share"], 0.20)
        self.assertGreaterEqual(summary["live_subset"]["hard_expert_weight_share"], 0.75)
        self.assertGreaterEqual(summary["live_subset"]["expert_weight_share"], 0.20)
        self.assertEqual(summary["violations"], [])


if __name__ == "__main__":
    unittest.main()
