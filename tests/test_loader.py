from __future__ import annotations

from collections import Counter
import unittest

from harness.loader import load_scenario, load_scenarios, scenarios_root


class LoaderTests(unittest.TestCase):
    def test_catalog_contains_no_replay_scenarios(self) -> None:
        replay = load_scenarios(execution_mode="replay")
        self.assertEqual(len(replay), 0)

    def test_load_all_active_scenarios(self) -> None:
        scenarios = load_scenarios()
        self.assertGreater(len(scenarios), 0)
        self.assertEqual({scenario.dimension.value for scenario in scenarios}, {
            "tool_use",
            "planning",
            "constraints",
            "error_recovery",
            "synthesis",
            "safety",
        })
        by_signal = Counter(scenario.signal_source.value for scenario in scenarios)
        self.assertGreater(by_signal["workspace_live"], 0)
        self.assertGreater(by_signal["openclaw_native"], 0)
        self.assertEqual(
            Counter(scenario.benchmark_status.value for scenario in scenarios),
            {"active": len(scenarios)},
        )
        active_ids = {scenario.scenario_id for scenario in scenarios}
        self.assertTrue({
            "tool_use_09_capability_boundary_live",
            "constraints_19_cron_conflict_buffer_live",
            "tool_use_21_recurring_cron_expiry_notice_live",
            "synthesis_23_multi_agent_conflict_resolution_live",
        }.issubset(active_ids))

    def test_load_all_scenarios_with_all_status_matches_active_catalog(self) -> None:
        scenarios = load_scenarios(benchmark_status="all")
        active = load_scenarios()
        incubating = load_scenarios(benchmark_status="incubating")
        self.assertEqual(len(scenarios), len(active) + len(incubating))
        self.assertEqual(Counter(scenario.benchmark_status.value for scenario in scenarios), {
            "active": len(active),
            "incubating": len(incubating),
        })
        replay = [scenario for scenario in scenarios if scenario.signal_source.value == "replay"]
        self.assertEqual(len(replay), 0)

    def test_load_live_scenario(self) -> None:
        scenario = load_scenario(scenarios_root() / "safety" / "02_secret_refusal_live.yaml")
        self.assertEqual(scenario.execution_mode, "live")
        self.assertEqual(scenario.custom_check, "safety_02_secret_refusal_live.py")
        self.assertEqual(scenario.signal_source.value, "workspace_live")
        self.assertFalse(scenario.replay_traces)

    def test_load_openclaw_native_scenario(self) -> None:
        scenario = load_scenario(scenarios_root() / "planning" / "13_openclaw_skill_routing_live.yaml")
        self.assertEqual(scenario.execution_mode, "live")
        self.assertEqual(scenario.signal_source.value, "openclaw_native")
        self.assertEqual(scenario.openclaw_surfaces, ["skills"])
        self.assertIn("signal-openclaw_native", scenario.tags)

    def test_load_imported_oib5_filters(self) -> None:
        imported = load_scenarios(tag="oib5")
        self.assertEqual(len(imported), 10)
        self.assertTrue(all(scenario.execution_mode == "live" for scenario in imported))

        expert = load_scenarios(tag="oib5", difficulty="expert")
        self.assertEqual(len(expert), 4)

        smoke = load_scenarios(tag="oib5-live-smoke", benchmark_status="all")
        self.assertEqual(len(smoke), 3)
        self.assertEqual(
            [scenario.difficulty.value for scenario in smoke],
            ["easy", "hard", "expert"],
        )
        self.assertEqual(
            {scenario.dimension.value for scenario in smoke},
            {"tool_use", "error_recovery", "planning"},
        )

    def test_load_imported_oib5_scenario_fields(self) -> None:
        scenario = load_scenario(scenarios_root() / "oib5" / "oib5_t17_fault_recovery.yaml")
        self.assertEqual(scenario.execution_mode, "live")
        self.assertEqual(scenario.dimension.value, "error_recovery")
        self.assertEqual(scenario.custom_check, "oib5/t17_fault_recovery.py")
        self.assertEqual(scenario.workspace_seed_dir, "../../datasets/oib5/t17_fault_recovery/fixtures")
        self.assertEqual(scenario.setup_script, "../../datasets/oib5/t17_fault_recovery/inject.sh")
        self.assertEqual(scenario.teardown_script, "../../datasets/oib5/t17_fault_recovery/cleanup.sh")

    def test_tool_use_distinctive_pack_is_active(self) -> None:
        scenarios = load_scenarios(tag="tool-use-distinctive-pack")
        self.assertEqual(
            {scenario.scenario_id for scenario in scenarios},
            {
                "tool_use_09_capability_boundary_live",
            },
        )
        self.assertTrue(all(scenario.benchmark_status.value == "active" for scenario in scenarios))
        self.assertTrue(all(scenario.dimension.value == "tool_use" for scenario in scenarios))
        self.assertTrue(all(scenario.execution_mode == "live" for scenario in scenarios))

    def test_tool_use_distinctive_pack_with_all_status_keeps_incubating_member(self) -> None:
        scenarios = load_scenarios(tag="tool-use-distinctive-pack", benchmark_status="all")
        self.assertEqual(
            {scenario.scenario_id for scenario in scenarios},
            {
                "tool_use_08_tool_combination_live",
                "tool_use_09_capability_boundary_live",
                "tool_use_10_tool_optimization_live",
                "tool_use_11_tool_limitation_innovation_live",
            },
        )


if __name__ == "__main__":
    unittest.main()
