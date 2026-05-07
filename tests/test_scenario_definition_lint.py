from __future__ import annotations

import unittest

from scripts.lint_scenario_definitions import lint_scenario_definitions


class ScenarioDefinitionLintTests(unittest.TestCase):
    def test_lint_requires_explicit_status_and_signal_metadata(self) -> None:
        summary = lint_scenario_definitions(benchmark_profile="full")

        self.assertEqual(summary["candidate_views"]["explicit_metadata_missing"], [])
        for row in summary["scenarios"]:
            self.assertTrue(row["has_explicit_benchmark_status"], row["scenario_id"])
            self.assertTrue(row["has_explicit_signal_source"], row["scenario_id"])
            self.assertNotIn("missing_explicit_benchmark_status", row["flags"])
            self.assertNotIn("missing_explicit_signal_source", row["flags"])

    def test_lint_keeps_scenario_category_optional_but_visible(self) -> None:
        summary = lint_scenario_definitions(benchmark_profile="full")
        rows = {row["scenario_id"]: row for row in summary["scenarios"]}

        self.assertIsNone(rows["constraints_10_dynamic_adaptation_live"]["scenario_category"])
        self.assertEqual(rows["oib5_t24_legacy_modernize"]["scenario_category"], "imported_oib5")

    def test_lint_does_not_flag_recently_hardened_cases(self) -> None:
        summary = lint_scenario_definitions(benchmark_profile="full")
        rows = {row["scenario_id"]: row for row in summary["scenarios"]}

        self.assertEqual(rows["error_recovery_07_partial_success_live"]["flags"], [])
        self.assertNotIn("prompt_input_not_declared", rows["tool_use_06_workspace_forensics_live"]["flags"])
        self.assertNotIn("custom_check_output_mismatch", rows["oib5_t25_etl_pipeline"]["flags"])

    def test_lint_finds_no_prompt_input_mismatches_in_full_profile(self) -> None:
        summary = lint_scenario_definitions(benchmark_profile="full")

        self.assertEqual(summary["candidate_views"]["prompt_input_mismatch"], [])
        for row in summary["scenarios"]:
            self.assertNotIn("prompt_input_not_declared", row["flags"], row["scenario_id"])

    def test_lint_clears_constraints_03_prompt_input_mismatch(self) -> None:
        summary = lint_scenario_definitions(benchmark_status="all")
        rows = {row["scenario_id"]: row for row in summary["scenarios"]}

        self.assertEqual(rows["constraints_03_exact_format_live"]["flags"], [])
        self.assertEqual(rows["constraints_03_exact_format_live"]["missing_input_refs"], [])

    def test_lint_does_not_flag_hardened_constraints_08_case(self) -> None:
        summary = lint_scenario_definitions(benchmark_profile="full")
        rows = {row["scenario_id"]: row for row in summary["scenarios"]}

        self.assertEqual(rows["constraints_08_temporal_constraints_live"]["flags"], [])
        self.assertEqual(
            rows["constraints_08_temporal_constraints_live"]["workspace_seed_dir"],
            "../../datasets/constraints_08_temporal_constraints/fixtures",
        )

    def test_lint_does_not_flag_hardened_synthesis_10_case(self) -> None:
        summary = lint_scenario_definitions(benchmark_profile="full")
        rows = {row["scenario_id"]: row for row in summary["scenarios"]}

        self.assertEqual(rows["synthesis_10_cross_modal_reasoning_live"]["flags"], [])
        self.assertEqual(
            rows["synthesis_10_cross_modal_reasoning_live"]["workspace_seed_dir"],
            "../../datasets/frontier/synthesis_10_cross_modal_reasoning_live/fixtures",
        )

    def test_lint_does_not_flag_hardened_synthesis_13_case(self) -> None:
        summary = lint_scenario_definitions(benchmark_profile="full")
        rows = {row["scenario_id"]: row for row in summary["scenarios"]}

        self.assertEqual(rows["synthesis_13_incident_timeline_fusion_live"]["flags"], [])
        self.assertEqual(
            rows["synthesis_13_incident_timeline_fusion_live"]["workspace_seed_dir"],
            "../../datasets/frontier/synthesis_13_incident_timeline_fusion_live/fixtures",
        )

    def test_lint_does_not_flag_hardened_error_recovery_06_case(self) -> None:
        summary = lint_scenario_definitions(benchmark_profile="full")
        rows = {row["scenario_id"]: row for row in summary["scenarios"]}

        self.assertEqual(rows["error_recovery_06_cascading_failure_live"]["flags"], [])
        self.assertEqual(
            rows["error_recovery_06_cascading_failure_live"]["workspace_seed_dir"],
            "../../datasets/error_recovery_06_cascading_failure/fixtures",
        )

    def test_lint_does_not_flag_hardened_error_recovery_08_case(self) -> None:
        summary = lint_scenario_definitions(benchmark_profile="full")
        rows = {row["scenario_id"]: row for row in summary["scenarios"]}

        self.assertEqual(rows["error_recovery_08_graceful_degradation_live"]["flags"], [])
        self.assertEqual(
            rows["error_recovery_08_graceful_degradation_live"]["workspace_seed_dir"],
            "../../datasets/error_recovery_08_graceful_degradation/fixtures",
        )

    def test_lint_does_not_flag_hardened_planning_08_case(self) -> None:
        summary = lint_scenario_definitions(benchmark_status="all")
        rows = {row["scenario_id"]: row for row in summary["scenarios"]}

        self.assertEqual(rows["planning_08_uncertainty_reasoning_live"]["flags"], [])
        self.assertEqual(
            rows["planning_08_uncertainty_reasoning_live"]["workspace_seed_dir"],
            "../../datasets/planning_08_uncertainty_reasoning/fixtures",
        )

    def test_lint_does_not_flag_hardened_planning_09_case(self) -> None:
        summary = lint_scenario_definitions(benchmark_profile="full")
        rows = {row["scenario_id"]: row for row in summary["scenarios"]}

        self.assertEqual(rows["planning_09_resource_contention_live"]["flags"], [])
        self.assertEqual(
            rows["planning_09_resource_contention_live"]["workspace_seed_dir"],
            "../../datasets/planning_09_resource_contention/fixtures",
        )

    def test_lint_does_not_flag_hardened_planning_07_case(self) -> None:
        summary = lint_scenario_definitions(benchmark_profile="full")
        rows = {row["scenario_id"]: row for row in summary["scenarios"]}

        self.assertEqual(rows["planning_07_dynamic_resource_allocation_live"]["flags"], [])
        self.assertEqual(
            rows["planning_07_dynamic_resource_allocation_live"]["workspace_seed_dir"],
            "../../datasets/planning_07_dynamic_resource_allocation/fixtures",
        )


if __name__ == "__main__":
    unittest.main()
