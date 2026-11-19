"""Realistic evidence availability, correlated copies and reconciliability."""
from __future__ import annotations

from copy import deepcopy
import unittest

from dbt_chaos.commerce import oracle
from dbt_chaos.full_datasets import absolute_group_error
from dbt_chaos.reconciliation import (
    EVIDENCE_ROOTS, evidence_from_process, make_scenarios, reconcile,
    score_against_process, validate_evidence, evaluate_scenarios,
)


class ReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = make_scenarios()
        cls.truth = cls.b["truth"]
        cls.clean = cls.b["cases"]["clean_mature"]

    def test_clean_multisource_evidence_matures_to_verified(self):
        evidence = evidence_from_process(self.b["events"], self.truth)
        self.assertEqual(self.clean["evidence"], evidence)
        self.assertEqual(len(self.truth["payments"]),
                         len(evidence["provider_transactions"]))
        self.assertEqual(len(self.truth["payments"]),
                         len(evidence["accounting_journal"]))
        self.assertEqual(28, len(evidence["bank_batches"]))
        rec = reconcile(self.truth, evidence, as_of_lag_days=5)
        self.assertEqual("verified", rec["status"])
        self.assertEqual([], rec["findings"])
        self.assertEqual([], rec["held_groups"])
        self.assertEqual(2, rec["independent_external_root_count"])
        self.assertEqual(len(self.truth["payments"]),
                         rec["matched_provider_count"])
        score = score_against_process(self.truth, rec, self.truth)
        self.assertEqual("correctly_published", score["status"])
        self.assertEqual(1.0, score["fraction_of_correct_business_value_published"])

    def test_original_qwen_refund_is_detectable_only_with_extra_evidence(self):
        s = self.b["cases"]["qwen_refund_source_only"]
        self.assertEqual(2900, next(r["amount_cents"] for r in s["source"]["payments"]
                                   if r["payment_id"] == 288))
        r = reconcile(s["source"], s["evidence"], as_of_lag_days=5)
        self.assertEqual("disputed", r["status"])
        self.assertIn("provider_transaction_mismatch",
                      [x["code"] for x in r["findings"]])
        self.assertIn("correlated_internal_gl_mismatch",
                      [x["code"] for x in r["findings"]])
        self.assertIn("independent_bank_balance_mismatch",
                      [x["code"] for x in r["findings"]])
        self.assertTrue(any(x["payment_id"] == 288 for x in r["findings"]))
        score = score_against_process(s["source"], r, self.truth)
        self.assertEqual(2000, score["source_error_l1_cents"])
        self.assertEqual(0, score["false_published_l1_cents"])
        self.assertGreater(len(r["held_groups"]), 0)
        self.assertEqual("partially_held", score["status"])
        self.assertLess(score["fraction_of_correct_business_value_published"], 1.0)
        self.assertGreater(score["fraction_of_correct_business_value_published"], 0.0)

    def test_two_correlated_wrong_copies_are_not_independent(self):
        s = self.b["cases"]["qwen_refund_and_correlated_gl"]
        gl = next(x for x in s["evidence"]["accounting_journal"]
                  if x["payment_id"] == 288)
        self.assertEqual(-2900, gl["signed_cents"])
        r = reconcile(s["source"], s["evidence"], as_of_lag_days=5)
        codes = [x["code"] for x in r["findings"]]
        self.assertNotIn("correlated_internal_gl_mismatch", codes)
        self.assertIn("provider_transaction_mismatch", codes)
        self.assertIn("independent_bank_balance_mismatch", codes)
        self.assertEqual("merchant_application", r["correlated_journal_root"])

    def test_bank_detects_when_provider_and_gl_both_wrong(self):
        s = self.b["cases"]["psp_and_gl_corrupted_bank_catches"]
        r = reconcile(s["source"], s["evidence"], as_of_lag_days=5)
        codes = [x["code"] for x in r["findings"]]
        self.assertNotIn("provider_transaction_mismatch", codes)
        self.assertNotIn("correlated_internal_gl_mismatch", codes)
        self.assertIn("independent_bank_balance_mismatch", codes)
        self.assertGreater(len(r["held_groups"]), 0)
        scored = score_against_process(s["source"], r, self.truth)
        self.assertEqual(0, scored["false_published_l1_cents"])

    def test_all_claimed_sources_agree_yet_original_business_truth_is_wrong(self):
        item=self.b["cases"]["all_claimed_feeds_agree_on_wrong_value"]
        rec=reconcile(item["source"], item["evidence"], as_of_lag_days=5)
        self.assertEqual("verified", rec["status"])
        self.assertEqual([], rec["findings"])
        self.assertEqual([], rec["held_groups"])
        self.assertEqual(2, rec["independent_external_root_count"])
        outcome=score_against_process(item["source"], rec, self.truth)
        self.assertEqual(2000, outcome["source_error_l1_cents"])
        self.assertEqual(2000, outcome["false_published_l1_cents"])
        self.assertEqual("unobservable_with_provided_evidence",
                         outcome["detectability"])
        self.assertFalse(outcome["platform_should_be_penalized_for_missing_detection"])
        # Root labels are asserted strings, NOT cryptographic guarantees.
        self.assertEqual("independent_bank",
                         item["evidence"]["bank_batches"][0]["origin_root"])

    def test_no_false_alarm_before_provider_or_bank_arrive(self):
        for name in ("clean_before_settlement",
                     "clean_after_provider_before_bank"):
            s = self.b["cases"][name]
            r = reconcile(s["source"], s["evidence"],
                          as_of_lag_days=s["as_of_lag_days"])
            self.assertEqual("pending_evidence", r["status"])
            self.assertEqual([], r["findings"])
            score = score_against_process(s["source"], r, self.truth)
            self.assertEqual(0, score["false_published_l1_cents"])
            self.assertEqual("held", score["status"])
            self.assertEqual(0.0, score["fraction_of_correct_business_value_published"])

    def test_intact_internal_journal_can_detect_early_without_proving_truth(self):
        s = self.b["cases"]["qwen_internal_gl_detects_early"]
        rec = reconcile(s["source"], s["evidence"], as_of_lag_days=0)
        self.assertEqual("disputed", rec["status"])
        self.assertIn("correlated_internal_gl_mismatch",
                      [x["code"] for x in rec["findings"]])
        self.assertNotIn("provider_transaction_mismatch",
                         [x["code"] for x in rec["findings"]])
        self.assertEqual(0, rec["independent_external_root_count"])
        # An internal discrepancy deserves a hold, but not an automatic
        # conclusion about whether the GL or payment row is authoritative.
        self.assertTrue(rec["held_groups"])

    def test_provider_missing_after_sla_is_dispute_not_uncertain_forever(self):
        s = self.b["cases"]["missing_provider_after_sla"]
        r = reconcile(s["source"], s["evidence"], as_of_lag_days=5)
        self.assertIn("provider_record_missing_after_sla",
                      [x["code"] for x in r["findings"]])
        self.assertEqual("disputed", r["status"])
        self.assertIn(288, [x["payment_id"] for x in r["findings"]])
        self.assertGreater(len(r["held_groups"]), 0)

    def test_corrupt_source_can_be_pending_until_evidence_matures(self):
        s = self.b["cases"]["qwen_before_provider"]
        r = reconcile(s["source"], s["evidence"], as_of_lag_days=0)
        self.assertEqual("pending_evidence", r["status"])
        self.assertEqual([], r["findings"])
        self.assertEqual(0, r["independent_external_root_count"])
        self.assertTrue(r["pending_provider_payment_ids"])
        self.assertTrue(r["held_groups"])

    def test_reconciler_cannot_treat_correlated_journal_as_distinct_root(self):
        e = deepcopy(self.clean["evidence"])
        journal = e["accounting_journal"][0]
        journal["origin_root"] = "independent_bank"
        with self.assertRaisesRegex(ValueError, "provenance"):
            reconcile(self.truth, e, as_of_lag_days=5)
        e = deepcopy(self.clean["evidence"])
        bank = e["bank_batches"][0]
        bank["origin_root"] = "independent_psp"
        with self.assertRaisesRegex(ValueError, "provenance"):
            validate_evidence(e)

    def test_can_simulate_financially_plausible_counterfactual_without_truth_leak(self):
        s = deepcopy(self.clean)
        target = next(p for p in s["source"]["payments"]
                      if p["payment_id"] == 288)
        target["amount_cents"] = 2900
        e = s["evidence"]
        # Another plausible history is possible, but original external
        # provider + bank observations expose the disagreement.
        before = deepcopy(s["source"])
        rec = reconcile(s["source"], e, as_of_lag_days=5)
        self.assertEqual(before, s["source"])
        self.assertNotEqual(oracle(s["source"]), oracle(self.truth))
        self.assertEqual(2000, absolute_group_error(
            oracle(s["source"]), oracle(self.truth)))
        self.assertTrue(rec["findings"])

    def test_reference_matrix_uses_single_real_llm_action_not_new_inference(self):
        report = evaluate_scenarios()
        self.assertEqual("multisource_reconciliation_reference_v1",
                         report["experiment"])
        self.assertEqual(10, len(report["cases"]))
        by_name = {r["scenario"]: r for r in report["cases"]}
        self.assertEqual("verified", by_name["clean_mature"]
                         ["reconciliation"]["status"])
        self.assertEqual("disputed", by_name["qwen_refund_source_only"]
                         ["reconciliation"]["status"])
        self.assertEqual("pending_evidence", by_name["clean_before_settlement"]
                         ["reconciliation"]["status"])
        self.assertEqual("disputed", by_name["psp_and_gl_corrupted_bank_catches"]
                         ["reconciliation"]["status"])


if __name__ == "__main__":
    unittest.main()
