"""Protection benchmark: do not confuse warning, quarantine, and trusted recovery."""
from copy import deepcopy
import unittest

from dbt_chaos.commerce import oracle, source_contract_alerts
from dbt_chaos.full_datasets import enhanced_source_alerts
from dbt_chaos.protection import (
    detect_and_quarantine, evaluate_policy, recorded_qwen_source_cases,
)


class ObservableProtectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.truth, cls.cases = recorded_qwen_source_cases()
        cls.by_case = {item["name"]: item["delivered"] for item in cls.cases}

    def test_clean_source_does_not_quarantine_legitimate_history(self):
        plan = detect_and_quarantine(self.truth)
        self.assertEqual([], plan.warnings)
        self.assertEqual([], plan.quarantined)
        self.assertEqual(set(), plan.hold_groups)
        self.assertFalse(plan.global_hold)
        self.assertEqual(self.truth, plan.accepted)

    def test_exact_duplicate_replay_is_idempotent_not_business_loss(self):
        sample = deepcopy(self.truth)
        existing = sample["customers"][0]
        copy = dict(existing, row_id=999999)
        sample["customers"].append(copy)
        plan = detect_and_quarantine(sample)
        self.assertFalse(plan.global_hold)
        self.assertEqual([], sorted(plan.hold_groups))
        self.assertEqual(1, len(plan.quarantined))
        self.assertEqual("exact_delivery_replay", plan.quarantined[0]["reason"])
        self.assertEqual("quarantine", plan.quarantined[0]["disposition"])
        self.assertEqual(self.truth, plan.accepted)
        self.assertEqual(oracle(self.truth), oracle(sample))

    def test_model_source_edits_are_reproducible(self):
        for case in self.cases:
            with self.subTest(case=case["name"]):
                plan = detect_and_quarantine(case["delivered"])
                if case["name"] in ("clean_control", "qwen_refund", "qwen_segment"):
                    self.assertEqual([], plan.quarantined)
                    self.assertEqual([], plan.warnings)
                if case["name"] == "qwen_refund":
                    self.assertEqual(-36100, sum(oracle(case["delivered"]).values())
                                     - sum(oracle(self.truth).values()))
                if case["name"] == "qwen_segment":
                    self.assertEqual(-36100, sum(oracle(case["delivered"]).values())
                                     - sum(oracle(self.truth).values()))
                    self.assertNotEqual(oracle(case["delivered"]), oracle(self.truth))
                if case["name"] == "qwen_order_deleted":
                    self.assertTrue(plan.global_hold)
                    self.assertIn("payments_missing_order", plan.warnings)
                    self.assertTrue(any(x["reason"] == "missing_order" for x in plan.quarantined))

    def test_benign_retry_is_safe_to_deduplicate_without_holding_revenue(self):
        sample = self.by_case["benign_exact_retry_control"]
        self.assertEqual(oracle(self.truth), oracle(sample))
        plan = detect_and_quarantine(sample)
        self.assertFalse(plan.global_hold)
        self.assertEqual(set(), plan.hold_groups)
        self.assertEqual(1, len(plan.quarantined))
        self.assertEqual("exact_delivery_replay", plan.quarantined[0]["reason"])
        self.assertEqual(self.truth, plan.accepted)

    def test_missing_order_is_detectable_but_not_inferable(self):
        sample = self.by_case["qwen_order_deleted"]
        self.assertEqual([], source_contract_alerts(sample))
        self.assertIn("payments_missing_order", enhanced_source_alerts(sample))
        plan = detect_and_quarantine(sample)
        self.assertTrue(plan.global_hold)
        self.assertNotEqual(sample, plan.accepted)
        self.assertNotEqual(oracle(sample), oracle(self.truth))

    def test_cancelled_and_usd_are_not_corrupt_records(self):
        sample = deepcopy(self.truth)
        sample["orders"][0]["currency"] = "USD"
        plan = detect_and_quarantine(sample)
        self.assertFalse(plan.global_hold)
        self.assertEqual([], plan.quarantined)
        # Legacy contract may label USD as "invalid_orders", but a valid USD
        # order is not itself corrupt; reporting contract excludes it.
        self.assertTrue(any(row["status"] == "cancelled"
                            for row in plan.accepted["orders"]))

    def test_refund_corruption_is_indistinguishable_without_external_truth(self):
        sample = self.by_case["qwen_refund"]
        self.assertEqual([], detect_and_quarantine(sample).quarantined)
        self.assertEqual([], source_contract_alerts(sample))
        self.assertEqual([], enhanced_source_alerts(sample))
        self.assertNotEqual(oracle(sample), oracle(self.truth))

    def test_invalid_payment_is_quarantined_and_business_group_held(self):
        sample = deepcopy(self.truth)
        row = next(p for p in sample["payments"] if p["kind"] == "capture")
        row["amount_cents"] = -123
        plan = detect_and_quarantine(sample)
        self.assertTrue(any(q["reason"] == "invalid_payment_fields"
                            for q in plan.quarantined))
        self.assertFalse(plan.global_hold)
        self.assertGreater(len(plan.hold_groups), 0)
        self.assertEqual(len(sample["payments"]) - 1, len(plan.accepted["payments"]))
        self.assertEqual([], source_contract_alerts(self.truth))

    def test_impossible_refund_balance_is_held_not_guessed(self):
        sample = deepcopy(self.truth)
        refund = next(row for row in sample["payments"] if row["kind"] == "refund")
        refund["amount_cents"] = 50_000_000
        plan = detect_and_quarantine(sample)
        self.assertTrue(any(q["reason"] == "impossible_payment_balance"
                            for q in plan.quarantined))
        self.assertTrue(plan.hold_groups)
        self.assertFalse(plan.global_hold)

    def test_unknown_policy_and_external_evidence_required(self):
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            evaluate_policy(delivered=self.truth, independent_truth=self.truth,
                            policy="magic_repair")
        with self.assertRaisesRegex(ValueError, "requires"):
            evaluate_policy(delivered=self.truth, independent_truth=self.truth,
                            policy="attested_replay")
        self.assertEqual(self.truth, self.by_case["clean_control"])


class ExecutablePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.truth, cases = recorded_qwen_source_cases()
        cls.cases = {item["name"]: item["delivered"] for item in cases}
        cls.cache = {}

    def eval(self, case, policy, logic_fault="none"):
        return evaluate_policy(
            delivered=self.cases[case], independent_truth=self.truth,
            policy=policy, logic_fault=logic_fault,
            attested_source=self.truth if policy == "attested_replay" else None,
            cache=self.cache)

    def test_clean_control_is_fully_usable(self):
        baseline = self.eval("clean_control", "raw")
        self.assertEqual("business_correct", baseline["verdict"])
        self.assertEqual(0, baseline["observed_absolute_error_cents"])
        self.assertEqual(1.0, baseline["safe_truth_value_fraction"])
        self.assertEqual("published", baseline["publication_status"])
        self.assertEqual([], baseline["quarantine_manifest"])

    def test_source_errors_are_silent_when_internal_rules_cannot_see_them(self):
        for name in ("qwen_refund", "qwen_segment"):
            with self.subTest(name=name):
                raw = self.eval(name, "raw")
                self.assertEqual("silent_corruption", raw["verdict"])
                self.assertEqual([], raw["observable_warnings"])
                self.assertEqual(0, raw["quarantined_records"])
                self.assertGreater(raw["observed_absolute_error_cents"], 0)
                monitor = self.eval(name, "monitor")
                strict = self.eval(name, "strict_gate")
                self.assertEqual("silent_corruption", monitor["verdict"])
                self.assertEqual("silent_corruption", strict["verdict"])
                self.assertEqual(0, strict["recovered_from_attestation"])
                self.assertEqual("published", strict["publication_status"])
                self.assertFalse(monitor["dbt_executed"])  # shared real run cached
                self.assertTrue(monitor["dbt_result_reused"])

    def test_quarantine_cannot_safely_recreate_missing_order(self):
        raw = self.eval("qwen_order_deleted", "raw")
        monitor = self.eval("qwen_order_deleted", "monitor")
        quarantine = self.eval("qwen_order_deleted", "quarantine")
        strict = self.eval("qwen_order_deleted", "strict_gate")
        self.assertEqual("silent_corruption", raw["verdict"])
        self.assertEqual("detected_but_exposed", monitor["verdict"])
        self.assertEqual("withheld_all", quarantine["verdict"])
        self.assertEqual("withheld_all", strict["verdict"])
        self.assertGreater(quarantine["quarantined_records"], 0)
        self.assertEqual(0, strict["quarantined_records"])  # blocked != quarantined
        self.assertEqual("withheld", strict["publication_status"])
        self.assertEqual(0.0, strict["safe_truth_value_fraction"])
        self.assertFalse(quarantine["dbt_executed"])
        self.assertFalse(strict["dbt_executed"])

    def test_benign_retry_exposes_availability_cost_of_over_strict_policy(self):
        name = "benign_exact_retry_control"
        raw = self.eval(name, "raw")
        monitor = self.eval(name, "monitor")
        quarantine = self.eval(name, "quarantine")
        strict = self.eval(name, "strict_gate")
        attested = self.eval(name, "attested_replay")
        self.assertEqual("business_correct", raw["verdict"])
        self.assertEqual("business_correct", monitor["verdict"])
        self.assertEqual("business_correct", quarantine["verdict"])
        self.assertEqual(1, quarantine["quarantined_records"])
        self.assertEqual(0, quarantine["quarantined_genuine_records"])
        self.assertEqual(1.0, quarantine["safe_truth_value_fraction"])
        self.assertEqual("withheld_all", strict["verdict"])
        self.assertEqual(0.0, strict["safe_truth_value_fraction"])
        self.assertEqual("evidence_recovered", attested["verdict"])
        self.assertEqual(0, attested["observed_absolute_error_cents"])
        self.assertGreater(len(raw["dbt_source_alerts"]), 0)
        self.assertEqual([], raw["candidate_detector_findings"])

    def test_attested_replay_restores_source_but_never_claims_magic(self):
        for name in ("qwen_refund", "qwen_segment", "qwen_order_deleted"):
            with self.subTest(name=name):
                repaired = self.eval(name, "attested_replay")
                self.assertEqual("evidence_recovered", repaired["verdict"])
                self.assertEqual(0, repaired["observed_absolute_error_cents"])
                self.assertGreater(repaired["recovered_from_attestation"], 0)
                self.assertEqual("external_trusted_process_log",
                                 repaired["protection_evidence_tier"])
                self.assertEqual("published", repaired["publication_status"])
                self.assertTrue(all(c["evidence"] == "process_event_log"
                                    for c in repaired["evidence_manifest"]))
        # Independent source attestation does not repair faulty SQL logic.
        with_bug = self.eval("qwen_refund", "attested_replay",
                             logic_fault="skip_customer_dedup")
        self.assertNotEqual("evidence_recovered", with_bug["verdict"])
        self.assertGreater(with_bug["observed_absolute_error_cents"], 0)

    def test_valid_but_flagged_payment_holds_group_not_zero_fills(self):
        sample = deepcopy(self.truth)
        target = next(row for row in sample["payments"] if row["kind"] == "capture")
        target["amount_cents"] = -100
        report = evaluate_policy(
            delivered=sample, independent_truth=self.truth,
            policy="quarantine", cache=self.cache)
        self.assertEqual("partial_safe_publication", report["verdict"])
        self.assertEqual("partial", report["publication_status"])
        self.assertGreater(len(report["held_groups"]), 0)
        self.assertLess(report["safe_truth_value_fraction"], 1)
        self.assertEqual(0, report["incorrect_published_group_count"])
        # A rewritten negative amount is not the original genuine event;
        # its quarantine is appropriate, but withholding its reporting group
        # still reduces coverage.
        self.assertEqual(0, report["quarantined_genuine_records"])


if __name__ == "__main__":
    unittest.main()
