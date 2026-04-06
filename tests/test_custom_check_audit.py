from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.audit_custom_checks import audit_custom_checks


class CustomCheckAuditTests(unittest.TestCase):
    def test_audit_custom_checks_classifies_referenced_helper_and_orphan_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "used.py").write_text("def grade(workspace, trace):\n    return {}\n", encoding="utf-8")
            (root / "orphan.py").write_text("def grade(workspace, trace):\n    return {}\n", encoding="utf-8")
            (root / "helpers.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
            (root / "broken.py").write_text("def grade(\n", encoding="utf-8")

            result = audit_custom_checks(
                custom_checks_root=root,
                references_by_path={"used.py": ["scenario_used"]},
            )

        self.assertEqual(result["summary"]["referenced_count"], 1)
        self.assertEqual(result["summary"]["helper_count"], 1)
        self.assertEqual(result["summary"]["orphan_count"], 1)
        self.assertEqual(result["summary"]["syntax_error_count"], 1)
        self.assertEqual(result["orphan_custom_checks"], ["orphan.py"])
        self.assertEqual(result["helper_modules"], ["helpers.py"])
        self.assertEqual(result["modules"][0]["path"], "broken.py")
        referenced_row = next(row for row in result["modules"] if row["path"] == "used.py")
        self.assertEqual(referenced_row["status"], "referenced")
        self.assertEqual(referenced_row["referenced_by"], ["scenario_used"])
        orphan_row = next(row for row in result["modules"] if row["path"] == "orphan.py")
        self.assertEqual(orphan_row["git_tracking_status"], "unknown")
        self.assertEqual(orphan_row["orphan_reason"], "unreferenced_standalone")
        self.assertEqual(orphan_row["recommended_action"], "review_tracked_orphan")
        self.assertEqual(result["summary"]["orphan_reasons"]["unreferenced_standalone"], 1)
        self.assertEqual(result["summary"]["recommendation_counts"]["review_tracked_orphan"], 1)

    def test_audit_custom_checks_reports_missing_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "used.py").write_text("def grade(workspace, trace):\n    return {}\n", encoding="utf-8")

            result = audit_custom_checks(
                custom_checks_root=root,
                references_by_path={
                    "used.py": ["scenario_used"],
                    "missing.py": ["scenario_missing"],
                },
            )

        self.assertEqual(result["missing_references"], ["missing.py"])

    def test_audit_custom_checks_marks_shadowed_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "demo.py").write_text("def grade(workspace, trace):\n    return {}\n", encoding="utf-8")
            (root / "demo_live_v2.py").write_text("def grade(workspace, trace):\n    return {'live': True}\n", encoding="utf-8")

            result = audit_custom_checks(
                custom_checks_root=root,
                references_by_path={"demo_live_v2.py": ["scenario_live"]},
            )

        row = result["modules"][0]
        self.assertEqual(row["status"], "orphan")
        self.assertEqual(row["related_referenced_paths"], ["demo_live_v2.py"])
        self.assertEqual(row["orphan_reason"], "shadowed_by_referenced_variant")
        self.assertGreater(row["shadow_similarity"], 0.0)
        self.assertEqual(row["recommended_action"], "confirm_before_delete_divergent_shadow")
        self.assertEqual(result["summary"]["orphan_reasons"]["shadowed_by_referenced_variant"], 1)
        self.assertEqual(
            result["summary"]["recommendation_counts"]["confirm_before_delete_divergent_shadow"],
            1,
        )

    def test_audit_custom_checks_builds_sorted_orphan_review_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            identical_body = "def grade(workspace, trace):\n    return {'same': True}\n"
            (root / "identical.py").write_text(identical_body, encoding="utf-8")
            (root / "identical_live.py").write_text(identical_body, encoding="utf-8")
            (root / "divergent.py").write_text(
                "def grade(workspace, trace):\n    return {'version': 1}\n",
                encoding="utf-8",
            )
            (root / "divergent_live.py").write_text(
                "def grade(workspace, trace):\n    return {'version': 2, 'live': True}\n",
                encoding="utf-8",
            )
            (root / "standalone.py").write_text(
                "def grade(workspace, trace):\n    return {'orphan': True}\n",
                encoding="utf-8",
            )

            result = audit_custom_checks(
                custom_checks_root=root,
                references_by_path={
                    "identical_live.py": ["scenario_identical"],
                    "divergent_live.py": ["scenario_divergent"],
                },
            )

        queue = result["orphan_review_queue"]
        self.assertEqual([item["path"] for item in queue], ["identical.py", "divergent.py", "standalone.py"])
        self.assertEqual(queue[0]["recommended_action"], "delete_candidate_identical_shadow")
        self.assertEqual(queue[0]["shadow_similarity"], 1.0)
        self.assertEqual(queue[1]["recommended_action"], "confirm_before_delete_divergent_shadow")
        self.assertGreater(queue[1]["shadow_similarity"], 0.0)
        self.assertEqual(queue[2]["recommended_action"], "review_tracked_orphan")
        self.assertEqual(queue[2]["related_referenced_paths"], [])


if __name__ == "__main__":
    unittest.main()
