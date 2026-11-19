"""Standalone multi-source platform challenge without a paid API or dbt."""
from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbt_chaos.reconciliation_lab import (
    FORMAT, export_scenario, score_scenario, run_native_demo,
)


class ReconciliationChallengeTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(prefix="dbt-chaos-reconciliation-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.public = self.root / "public"
        self.private = self.root / "private"
        self.output = self.root / "published.csv"
        self.held = self.root / "held.csv"

    def create(self, scenario="qwen_refund_source_only"):
        return export_scenario(
            scenario, public_dir=self.public, private_dir=self.private)

    def write_published(self, records):
        with self.output.open("w", newline="") as f:
            out = csv.writer(f)
            out.writerow(["order_day", "segment", "revenue_cents"])
            for group, cents in sorted(records.items()):
                out.writerow([*group.split("|", 1), cents])

    def write_held(self, keys):
        with self.held.open("w", newline="") as f:
            out = csv.writer(f)
            out.writerow(["order_day", "segment"])
            for group in sorted(keys):
                out.writerow(group.split("|", 1))

    def test_six_source_tables_but_no_business_truth_leaks(self):
        result = self.create()
        self.assertEqual(6, result["file_count"])
        self.assertEqual(2000, result["source_business_discrepancy_cents"])
        self.assertTrue(result["sealed_answer_key"])
        meta = json.loads((self.public / "manifest.json").read_text())
        self.assertEqual(FORMAT, meta["format"])
        self.assertEqual(6, len(meta["raw_source_files"]))
        self.assertFalse(meta["business_oracle_included"])
        self.assertTrue((self.public / "inputs/provider_transactions.csv").exists())
        self.assertTrue((self.public / "inputs/accounting_journal.csv").exists())
        self.assertTrue((self.public / "inputs/bank_batches.csv").exists())
        self.assertFalse((self.public / "answer_key.json").exists())
        self.assertFalse((self.public / "original_business_event_log.json").exists())
        key = json.loads((self.private / "answer_key.json").read_text())
        self.assertEqual(1081, len(key["original_business_event_log"]))
        self.assertEqual("disputed",
                         key["reference_detectability"]["status"])
        self.assertEqual("merchant_application",
                         meta["correlated_provenance"]["accounting_journal"])

    def test_public_and_private_must_be_disjoint_empty(self):
        with self.assertRaisesRegex(ValueError, "disjoint"):
            export_scenario("clean_mature", public_dir=self.public,
                            private_dir=self.public / "secret")
        self.assertFalse(self.public.exists())
        self.create()
        with self.assertRaisesRegex(ValueError, "empty"):
            export_scenario("clean_mature", public_dir=self.public,
                            private_dir=self.root / "newprivate")

    def test_naive_platform_publishes_wrong_refund_without_warning(self):
        self.create()
        key = json.loads((self.private / "answer_key.json").read_text())
        self.write_published(key["expected_from_admitted_source"])
        report = score_scenario(
            public_dir=self.public,
            answer_key=self.private / "answer_key.json",
            published=self.output)
        score = report["business_score"]
        self.assertEqual("silently_wrong", score["status"])
        self.assertEqual(2000, score["false_published_l1_cents"])
        self.assertEqual(1, len(score["false_published_groups"]))
        self.assertEqual(0, report["relative_to_admitted_source_l1_cents"])
        self.assertGreater(report["observable_reference_disputes"], 0)
        self.assertTrue(report["oracle_hidden_from_platform"])

    def test_platform_can_hold_disputed_day_without_publishing_false_numbers(self):
        self.create()
        key = json.loads((self.private / "answer_key.json").read_text())
        expected = key["expected_business_gold"]
        held = set(key["reference_detectability"]["held_groups"])
        self.write_published({
            k:v for k,v in expected.items() if k not in held
        })
        self.write_held(held)
        report = score_scenario(
            public_dir=self.public,
            answer_key=self.private / "answer_key.json",
            published=self.output, held=self.held)
        score = report["business_score"]
        self.assertEqual("partially_held", score["status"])
        self.assertEqual(0, score["false_published_l1_cents"])
        self.assertGreater(len(score["held_groups"]), 0)
        self.assertGreater(score["fraction_of_correct_business_value_published"], 0)
        self.assertLess(score["fraction_of_correct_business_value_published"], 1)

    def test_joint_wrong_sources_are_an_information_limit_not_a_failing_detector(self):
        self.create("all_claimed_feeds_agree_on_wrong_value")
        key=json.loads((self.private/"answer_key.json").read_text())
        self.write_published(key["expected_from_admitted_source"])
        outcome=score_scenario(
            public_dir=self.public,answer_key=self.private/"answer_key.json",
            published=self.output)
        self.assertEqual("silently_wrong",outcome["business_score"]["status"])
        self.assertEqual("unobservable_with_provided_evidence",
                         outcome["detectability_given_available_evidence"])
        self.assertFalse(outcome["platform_published_error_despite_observable_dispute"])
        self.assertFalse(outcome["evidence_has_authenticated_independent_roots"])
        self.assertEqual(2000,outcome["source_vs_business_error_cents"])

    def test_clean_pending_settlement_is_not_error_and_safe_hold_has_cost(self):
        self.create("clean_before_settlement")
        key = json.loads((self.private / "answer_key.json").read_text())
        self.assertEqual("pending_evidence",key["reference_detectability"]["status"])
        self.assertEqual([],key["reference_detectability"]["findings"])
        self.write_published({})
        self.write_held(key["expected_business_gold"].keys())
        report=score_scenario(
            public_dir=self.public,answer_key=self.private/"answer_key.json",
            published=self.output,held=self.held)
        self.assertEqual("held",report["business_score"]["status"])
        self.assertEqual(0.0,
                         report["business_score"]["fraction_of_correct_business_value_published"])
        self.assertEqual(0, report["observable_reference_disputes"])

    def test_fully_reconciled_mature_clean_source_scores_correct(self):
        self.create("clean_mature")
        key = json.loads((self.private / "answer_key.json").read_text())
        self.write_published(key["expected_business_gold"])
        score=score_scenario(
            public_dir=self.public,answer_key=self.private/"answer_key.json",
            published=self.output)
        self.assertEqual("correctly_published",score["business_score"]["status"])
        self.assertEqual("verified",score["observable_reference_status"])
        self.assertEqual(0,score["observable_reference_disputes"])

    def test_corrupted_public_csv_cannot_be_scored_using_original_private_key(self):
        self.create()
        key = json.loads((self.private / "answer_key.json").read_text())
        self.write_published(key["expected_from_admitted_source"])
        p = self.public / "inputs/provider_transactions.csv"
        p.write_bytes(p.read_bytes().replace(b"4900",b"2900",1))
        with self.assertRaisesRegex(ValueError, "source evidence changed"):
            score_scenario(public_dir=self.public,
                           answer_key=self.private/"answer_key.json",
                           published=self.output)

    def test_invalid_published_grain_and_undeclared_missing_are_rejected_or_wrong(self):
        self.create()
        key = json.loads((self.private / "answer_key.json").read_text())
        self.write_published({})
        result=score_scenario(
            public_dir=self.public,answer_key=self.private/"answer_key.json",
            published=self.output)
        self.assertEqual("silently_wrong",result["business_score"]["status"])
        self.assertGreater(len(result["business_score"]["silent_missing_groups"]),0)
        text = self.output.read_text().splitlines()
        self.output.write_text("\n".join(text+["2026-02-01,retail,100","2026-02-01,retail,200"])+"\n")
        with self.assertRaisesRegex(ValueError, "duplicate published grain"):
            score_scenario(public_dir=self.public,
                           answer_key=self.private/"answer_key.json",
                           published=self.output)

    def test_correct_end_value_does_not_prove_attested_repair(self):
        self.create()
        key=json.loads((self.private/"answer_key.json").read_text())
        self.write_published(key["expected_business_gold"])
        score=score_scenario(public_dir=self.public,
                             answer_key=self.private/"answer_key.json",
                             published=self.output)
        self.assertEqual("correctly_published",score["business_score"]["status"])
        self.assertTrue(any("does not establish an evidence-backed repair" in w
                            for w in score["warnings"]))


if __name__=="__main__":
    unittest.main()
