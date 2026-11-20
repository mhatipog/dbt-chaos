"""End-to-end native dbt multi-evidence reconciler, not merely Python scoring."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import unittest
import importlib.util

from dbt_chaos.commerce import CommerceCase, oracle
from dbt_chaos.commerce_runner import run_case
from dbt_chaos.reconciliation import (
    make_scenarios, reconcile, score_against_process,
)
from dbt_chaos.relay_platform_replay import score_publication


@unittest.skipUnless(importlib.util.find_spec("duckdb") is not None,
                     "requires optional dbt/DuckDB extra")
class NativeReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = make_scenarios()
        cls.truth = cls.corpus["truth"]
        cls.true_gold = oracle(cls.truth)

    def execute(self, name, quality_enabled=False):
        case = self.corpus["cases"][name]
        report = run_case(
            CommerceCase(), admitted_data=case["source"],
            process_data=self.truth, quality_enabled=quality_enabled,
            reconciliation_enabled=True,
            reconciliation_evidence=case["evidence"],
            reconciliation_as_of_lag_days=case["as_of_lag_days"],
        )
        self.assertTrue(report["native_reconciliation"]["models_executed_by_dbt"])
        return report["native_reconciliation"], report

    def score(self, result):
        native = {tuple(k.split("|", 1)): int(v)
                  for k, v in result["released_gold"].items()}
        held = {tuple(k.split("|", 1)) for k in result["held_groups"]}
        if result["release_status"] == "withheld_all":
            held |= set(self.true_gold)
        return score_publication(self.true_gold, native, held)

    def test_clean_all_evidence_matured_is_fully_released(self):
        rec, report = self.execute("clean_mature")
        self.assertEqual("published", rec["release_status"])
        self.assertEqual(0, rec["dispute_count"])
        self.assertEqual(0, rec["pending_count"])
        self.assertEqual(0, rec["held_group_count"])
        self.assertEqual(len(self.truth["payments"]), len(rec["payment_evidence"]))
        self.assertEqual(set(rec["released_gold"]), set(
            f"{d}|{s}" for d, s in self.true_gold))
        self.assertEqual("correctly_published", self.score(rec)["status"])
        self.assertEqual("correct", report["classification"])
        self.assertEqual([], report["source_alerts"])

    def test_qwen_refund_disagreement_prevents_silent_publication(self):
        rec, report = self.execute("qwen_refund_source_only")
        statuses = {p["payment_id"]:p for p in rec["payment_evidence"]}
        self.assertEqual("provider_transaction_mismatch", statuses[288]["status"])
        self.assertEqual(2900, statuses[288]["operational_cents"])
        self.assertEqual(4900, statuses[288]["provider_cents"])
        self.assertGreater(rec["dispute_count"], 0)
        self.assertTrue(any(b["status"]=="independent_bank_balance_mismatch"
                            for b in rec["bank_evidence"]))
        self.assertGreater(len(rec["held_groups"]), 0)
        self.assertLess(len(rec["released_gold"]), rec["original_group_count"])
        self.assertEqual([], report["source_alerts"])
        self.assertEqual("correct", report["classification"])
        score = self.score(rec)
        self.assertEqual(0, score["false_published_l1_cents"])
        self.assertEqual("partially_held", score["status"])
        self.assertGreater(score["fraction_of_correct_business_value_published"], 0)
        self.assertLess(score["fraction_of_correct_business_value_published"], 1)
        # The original source is STILL corrupt. This is containment, not repair.
        self.assertNotEqual(oracle(self.corpus["cases"]["qwen_refund_source_only"]
                                   ["source"]), self.true_gold)

    def test_correlated_internal_accounting_copy_is_not_double_confirmation(self):
        rec, _ = self.execute("qwen_refund_and_correlated_gl")
        item = next(p for p in rec["payment_evidence"]
                    if p["payment_id"] == 288)
        self.assertEqual("provider_transaction_mismatch", item["status"])
        self.assertEqual(-2900, item["journal_signed_cents"])
        self.assertTrue(any(b["status"]=="independent_bank_balance_mismatch"
                            for b in rec["bank_evidence"]))
        self.assertEqual(0, self.score(rec)["false_published_l1_cents"])

    def test_bank_detects_when_provider_and_internal_copy_both_wrong(self):
        rec, _ = self.execute("psp_and_gl_corrupted_bank_catches")
        item = next(p for p in rec["payment_evidence"]
                    if p["payment_id"] == 288)
        self.assertEqual("provider_matched", item["status"])
        self.assertEqual(2900, item["provider_cents"])
        self.assertTrue(any(b["status"]=="independent_bank_balance_mismatch"
                            for b in rec["bank_evidence"]))
        self.assertEqual(0, self.score(rec)["false_published_l1_cents"])
        self.assertGreater(len(rec["held_groups"]), 0)

    def test_all_claimed_feeds_agree_on_wrong_value_is_information_limit(self):
        rec, original = self.execute("all_claimed_feeds_agree_on_wrong_value")
        self.assertEqual("published", rec["release_status"])
        self.assertEqual(0, rec["dispute_count"])
        self.assertEqual(0, rec["pending_count"])
        self.assertEqual([], rec["held_groups"])
        status = self.score(rec)
        self.assertEqual("silently_wrong", status["status"])
        self.assertEqual(2000, status["false_published_l1_cents"])
        # This is not a fixable data-platform detection failure: all
        # observations fed to SQL agree. The independently held oracle
        # establishes the unobservable difference after execution only.
        self.assertEqual([], original["source_alerts"])

    def test_legitimate_evidence_lateness_causes_pending_not_dispute(self):
        for name in ("clean_before_settlement", "clean_after_provider_before_bank"):
            with self.subTest(name=name):
                rec, _ = self.execute(name)
                self.assertEqual("withheld_all", rec["release_status"])
                self.assertEqual(0, rec["dispute_count"])
                self.assertGreater(rec["pending_count"], 0)
                self.assertEqual({}, rec["released_gold"])
                self.assertEqual("held", self.score(rec)["status"])
                self.assertEqual(0.0,
                                 self.score(rec)["fraction_of_correct_business_value_published"])

    def test_permanently_missing_provider_receipt_becomes_dispute(self):
        rec, _ = self.execute("missing_provider_after_sla")
        item = next(p for p in rec["payment_evidence"] if p["payment_id"]==288)
        self.assertEqual("provider_missing_after_sla", item["status"])
        self.assertGreater(rec["dispute_count"], 0)
        self.assertEqual(0, rec["pending_count"])
        self.assertEqual(0, self.score(rec)["false_published_l1_cents"])

    def test_intact_internal_gl_can_detect_mismatch_early_without_psp(self):
        rec, _ = self.execute("qwen_internal_gl_detects_early")
        item = next(p for p in rec["payment_evidence"] if p["payment_id"]==288)
        self.assertEqual("correlated_internal_gl_mismatch", item["status"])
        self.assertEqual(0, item["provider_cents"] or 0)
        self.assertEqual("withheld_all", rec["release_status"])
        self.assertGreater(rec["dispute_count"], 0)

    def test_qwen_before_provider_with_two_correlated_wrong_copies_is_pending(self):
        rec, _ = self.execute("qwen_before_provider")
        item = next(p for p in rec["payment_evidence"] if p["payment_id"]==288)
        self.assertEqual("pending_provider", item["status"])
        self.assertEqual("withheld_all", rec["release_status"])
        self.assertEqual(0, rec["dispute_count"])
        self.assertGreater(rec["pending_count"], 0)

    def test_existing_quality_gate_can_be_combined_without_bypassing_reconciliation(self):
        rec, report = self.execute("qwen_refund_source_only",
                                   quality_enabled=True)
        self.assertEqual(0, report["native_quality"]["quarantined_row_count"])
        self.assertEqual("published", report["native_quality"]["release_status"])
        self.assertGreater(len(rec["held_groups"]), 0)
        self.assertLess(len(rec["released_gold"]),
                        len(report["native_quality"]["released_gold"]))
        self.assertEqual(0, self.score(rec)["false_published_l1_cents"])

    def test_bad_evidence_provenance_rejected_before_dbt_execution(self):
        s = deepcopy(self.corpus["cases"]["clean_mature"])
        s["evidence"]["bank_batches"][0]["origin_root"] = "independent_psp"
        with self.assertRaisesRegex(ValueError, "provenance"):
            run_case(
                CommerceCase(), admitted_data=s["source"],
                process_data=self.truth, reconciliation_enabled=True,
                reconciliation_evidence=s["evidence"],
            )
        with self.assertRaisesRegex(ValueError, "requires"):
            run_case(CommerceCase(), admitted_data=self.truth,
                     reconciliation_enabled=True)
        with self.assertRaisesRegex(ValueError, "invalid reconciliation as-of"):
            run_case(CommerceCase(), admitted_data=self.truth,
                     reconciliation_enabled=True,
                     reconciliation_evidence=self.corpus["original_provider"],
                     reconciliation_as_of_lag_days=-1)


if __name__ == "__main__":
    unittest.main()
