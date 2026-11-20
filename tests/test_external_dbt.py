"""External dbt adapter: trusted truth, source mutation, and live isolated runs."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import importlib.util
import json
import shutil
import unittest

from dbt_chaos.external_dbt import (
    ExternalProjectError, _compare, _inventory, _read_csv, _trusted_expected,
    build_mutation, run_external_campaign, write_external_report,
)

PROJECT = Path("tests/fixtures/foreign_dbt_project")
TRUTH = Path("tests/fixtures/foreign_expected_gold.csv")
SOURCE = PROJECT / "seeds/payments.csv"


class ExternalProjectUnitTests(unittest.TestCase):
    def test_seed_mutations_are_deterministic_and_leave_input_untouched(self):
        original = SOURCE.read_bytes()
        files = {}
        for fault in ("amount_shift", "duplicate_row", "drop_row"):
            data, event = build_mutation(
                SOURCE, fault, column="amount_cents",
                match_column="payment_id", match_value="2", delta=2000)
            self.assertEqual(4, event["input_rows_before"])
            files[fault] = data
            again, again_event = build_mutation(
                SOURCE, fault, column="amount_cents",
                match_column="payment_id", match_value="2", delta=2000)
            self.assertEqual((data, event), (again, again_event))
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / "source.csv"
                path.write_bytes(data)
                cols, rows = _read_csv(path)
                self.assertEqual(4, len(cols))
                if fault == "amount_shift":
                    self.assertEqual(4, len(rows))
                    self.assertEqual("2900", rows[1]["amount_cents"])
                elif fault == "duplicate_row":
                    self.assertEqual(5, len(rows))
                    self.assertEqual(rows[1], rows[2])
                else:
                    self.assertEqual(3, len(rows))
                    self.assertNotIn("2", [r["payment_id"] for r in rows])
        self.assertEqual(original, SOURCE.read_bytes())
        self.assertEqual(3, len(files))

    def test_provenance_is_never_baseline_generated(self):
        expect = _trusted_expected(
            TRUTH, ["order_id", "revenue_cents"])
        self.assertEqual(2, expect["row_count"])
        self.assertEqual(
            "caller_provided_reference_not_generated_by_target",
            expect["provenance"])
        report = _compare(
            expect, {"columns": ["order_id", "revenue_cents"],
                     "rows": [("100", "7100"), ("101", "17500")]})
        self.assertFalse(report["equal"])
        self.assertEqual(1, report["removed_rows"])
        self.assertEqual(1, report["added_rows"])

    def test_input_validation_requires_no_ambient_code_execution(self):
        info = _inventory(PROJECT)
        self.assertEqual("foreign_retail", info["name"])
        self.assertEqual(1, len(
            [p for p in info["files"] if p.stem == "payments"]))
        with self.assertRaisesRegex(ExternalProjectError, "explicit"):
            run_external_campaign(
                project_dir=PROJECT, model="gold_revenue", seed_table="payments",
                column="amount_cents", match_column="payment_id",
                match_value="2", delta=2000, faults=("amount_shift",),
                independent_expected=TRUTH,
                acknowledge_code_execution=False)

    def test_injection_and_ambiguous_rows_fail_closed(self):
        for match_value in ("nonexistent", ""):
            with self.subTest(match_value=match_value), self.assertRaisesRegex(
                    ExternalProjectError, "exactly one"):
                build_mutation(
                    SOURCE, "amount_shift", column="amount_cents",
                    match_column="payment_id", match_value=match_value,
                    delta=2000)
        with self.assertRaisesRegex(ExternalProjectError, "nonpositive"):
            build_mutation(
                SOURCE, "amount_shift", column="amount_cents",
                match_column="payment_id", match_value="2", delta=5000)
        with self.assertRaisesRegex(ExternalProjectError, "unsupported"):
            build_mutation(
                SOURCE, "freeform_sql", column="amount_cents",
                match_column="payment_id", match_value="2", delta=2000)

    def test_symlinks_and_package_manifests_are_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dbt_project.yml").write_text(
                (PROJECT / "dbt_project.yml").read_text())
            (root / "packages.yml").write_text("packages: []")
            with self.assertRaisesRegex(ExternalProjectError, "package installs"):
                _inventory(root)
            (root / "packages.yml").unlink()
            (root / "seeds").mkdir()
            (root / "seeds/payments.csv").symlink_to(SOURCE.resolve())
            with self.assertRaisesRegex(ExternalProjectError, "symlink"):
                _inventory(root)

    def test_results_refuse_overwrite(self):
        report = {"format": "test", "cases": []}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            write_external_report(report, path)
            self.assertEqual(report, json.loads(path.read_text()))
            with self.assertRaisesRegex(ExternalProjectError, "new"):
                write_external_report(report, path)


@unittest.skipUnless(
    shutil.which("dbt") is not None and
    importlib.util.find_spec("duckdb") is not None,
    "integration test needs optional dbt and DuckDB dependencies",
)
class ExternalProjectRealDbtTests(unittest.TestCase):
    def test_real_external_project_fails_existing_tests_to_protect_duplicates_but_not_refund(self):
        report = run_external_campaign(
            project_dir=PROJECT, model="gold_revenue", seed_table="payments",
            column="amount_cents", match_column="payment_id",
            match_value="2", delta=2000,
            faults=("amount_shift", "duplicate_row", "drop_row"),
            independent_expected=TRUTH, acknowledge_code_execution=True,
            timeout=120,
        )
        self.assertEqual("real_dbt_core_and_duckdb", report["engine"])
        self.assertEqual("foreign_retail", report["project"])
        self.assertTrue(report["clean_baseline_matches_independent_gold"])
        self.assertEqual("tests_passed", report["clean_baseline_test_verdict"])
        by_fault = {c["fault"]: c for c in report["cases"]}
        self.assertEqual(
            "silent_business_mismatch", by_fault["amount_shift"]["outcome"])
        self.assertGreater(by_fault["amount_shift"]["tests_executed"], 0)
        self.assertEqual(
            "detected_business_mismatch", by_fault["duplicate_row"]["outcome"])
        self.assertEqual(
            "test_detected", by_fault["duplicate_row"]["test_verdict"])
        self.assertEqual("silent_business_mismatch", by_fault["drop_row"]["outcome"])
        # A missing row with no completeness rule can also escape schema tests.
        self.assertEqual(2, report["silent_business_mismatches"])
        self.assertTrue(all(
            c.get("outcome") != "execution_failed_not_a_dbt_test_detection"
            for c in report["cases"]))


if __name__ == "__main__":
    unittest.main()
