"""Real DuckDB+dbt warehouse-side quarantine/release tests (opt-in only)."""
from copy import deepcopy
import unittest
import importlib.util

from dbt_chaos.commerce import CommerceCase, oracle, source_contract_alerts
from dbt_chaos.commerce_runner import run_case
from dbt_chaos.protection import recorded_qwen_source_cases


@unittest.skipUnless(importlib.util.find_spec("duckdb") is not None,
                     "requires optional dbt/DuckDB extra")
class NativeDbtQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.truth, cases = recorded_qwen_source_cases()
        cls.samples = {c["name"]: c["delivered"] for c in cases}
        cls.executed = {
            name: run_case(
                CommerceCase(), admitted_data=cls.samples[name],
                process_data=cls.truth, quality_enabled=True,
            )
            for name in ("clean_control", "qwen_refund", "qwen_segment",
                         "qwen_order_deleted", "benign_exact_retry_control")
        }

    def test_clean_is_published_without_quarantine(self):
        report = self.executed["clean_control"]
        quality = report["native_quality"]
        self.assertTrue(quality["models_executed_by_dbt"])
        self.assertEqual("published", quality["release_status"])
        self.assertEqual(0, quality["quarantined_row_count"])
        expected = {f"{d}|{s}": cents for (d, s), cents in oracle(self.truth).items()}
        self.assertEqual(expected, quality["released_gold"])
        self.assertEqual([], quality["held_groups"])
        self.assertEqual("correct", report["classification"])

    def test_plausible_refund_and_segment_changes_remain_unobservable(self):
        expected = {f"{d}|{s}": cents for (d, s), cents in oracle(self.truth).items()}
        for name in ("qwen_refund", "qwen_segment"):
            with self.subTest(name=name):
                quality = self.executed[name]["native_quality"]
                self.assertEqual("published", quality["release_status"])
                self.assertEqual(0, quality["quarantined_row_count"])
                self.assertNotEqual(expected, quality["released_gold"])
                self.assertEqual([], quality["quarantine"])
                self.assertEqual([], source_contract_alerts(self.samples[name]))

    def test_orphan_payment_really_enters_warehouse_quarantine_and_blocks_publication(self):
        quality = self.executed["qwen_order_deleted"]["native_quality"]
        self.assertEqual("withheld_all", quality["release_status"])
        self.assertEqual({}, quality["released_gold"])
        self.assertGreater(quality["global_risk_count"], 0)
        self.assertTrue(all(q["reason"]=="missing_order" for q in quality["quarantine"]))
        self.assertIn(467, [q["order_id"] for q in quality["quarantine"]])
        self.assertGreater(quality["quarantined_row_count"], 0)

    def test_benign_duplicate_replayed_payment_is_deduplicated_not_blocked(self):
        quality = self.executed["benign_exact_retry_control"]["native_quality"]
        expected = {f"{d}|{s}": cents for (d, s), cents in oracle(self.truth).items()}
        self.assertEqual("published", quality["release_status"])
        self.assertEqual(expected, quality["released_gold"])
        self.assertEqual(1, quality["quarantined_row_count"])
        self.assertEqual("exact_delivery_replay", quality["quarantine"][0]["reason"])
        self.assertEqual([], quality["held_groups"])
        self.assertIn("source_duplicate_payments",
                      self.executed["benign_exact_retry_control"]["source_alerts"])

    def test_negative_payment_is_quarantined_but_other_groups_publish(self):
        sample = deepcopy(self.truth)
        row = next(x for x in sample["payments"] if x["kind"] == "capture")
        row["amount_cents"] = -123
        result = run_case(CommerceCase(), admitted_data=sample,
                          process_data=self.truth, quality_enabled=True)
        quality = result["native_quality"]
        self.assertEqual("partial", quality["release_status"])
        self.assertTrue(any(q["row_id"] == row["row_id"]
                            and q["reason"] == "invalid_payment_fields"
                            for q in quality["quarantine"]))
        self.assertGreater(len(quality["held_groups"]), 0)
        self.assertGreater(len(quality["released_gold"]), 0)
        truth = {f"{d}|{s}": cents for (d, s), cents in oracle(self.truth).items()}
        for key, amount in quality["released_gold"].items():
            self.assertEqual(truth[key], amount)
        self.assertFalse(any(k in quality["released_gold"]
                             for k in quality["held_groups"]))

    def test_conflicting_same_version_blocks_not_guesses(self):
        sample = deepcopy(self.truth)
        first = sample["payments"][0]
        extra = dict(first, row_id=max(r["row_id"] for r in sample["payments"]) + 1,
                     amount_cents=first["amount_cents"] + 200)
        sample["payments"].append(extra)
        quality = run_case(
            CommerceCase(), admitted_data=sample, process_data=self.truth,
            quality_enabled=True)["native_quality"]
        self.assertEqual("withheld_all", quality["release_status"])
        self.assertEqual({}, quality["released_gold"])
        self.assertTrue(any(q["reason"] == "conflicting_same_version"
                            for q in quality["quarantine"]))


if __name__ == "__main__":
    unittest.main()
