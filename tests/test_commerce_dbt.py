"""Actual dbt SQL and test results; only enabled with dbt extras."""
import importlib.util
import unittest
from dbt_chaos.commerce import CommerceCase
from dbt_chaos.commerce_runner import run_case

@unittest.skipUnless(importlib.util.find_spec("duckdb") is not None,
                     "Optional dbt/DuckDB dependencies are absent")
class CommerceActualDbtTests(unittest.TestCase):
    def test_baseline(self):
        r=run_case(CommerceCase())
        self.assertEqual("correct",r["classification"])
        self.assertEqual({},r["contract_difference"])

    def test_duplicate_customer_is_contained(self):
        r=run_case(CommerceCase("duplicate_customer"))
        self.assertEqual("contained",r["classification"])
        self.assertIn("source_duplicate_customers",r["source_alerts"])

    def test_wrong_refund_logic_silently_corrupts(self):
        r=run_case(CommerceCase(logic_fault="ignore_refunds"))
        self.assertEqual("silent_corruption",r["classification"])
        self.assertEqual([],r["source_alerts"])

    def test_combined_duplicate_and_missing_dedup(self):
        r=run_case(CommerceCase("duplicate_customer","skip_customer_dedup"))
        self.assertEqual("silent_corruption",r["classification"])
        self.assertIn("source_duplicate_customers",r["source_alerts"])

    def test_invalid_payment_quarantined(self):
        r=run_case(CommerceCase("null_payment"))
        self.assertEqual("contained",r["classification"])
        self.assertIn("source_invalid_payments",r["source_alerts"])

    def test_currency_fault_amplified_by_sql_defect(self):
        r=run_case(CommerceCase("usd_order","ignore_currency"))
        self.assertEqual("silent_corruption",r["classification"])
        self.assertIn("source_invalid_orders",r["source_alerts"])

    def test_missing_source_refund_cannot_be_inferred(self):
        r=run_case(CommerceCase("missing_refund"))
        self.assertTrue(r["source_loss_not_self_verifiable"])
        self.assertEqual("correct",r["classification"])
        self.assertTrue(r["source_baseline_difference"])

    def test_compound_mutations_can_mask(self):
        r=run_case(CommerceCase("missing_refund","ignore_refunds"))
        self.assertEqual("correct",r["classification"])
        self.assertTrue(r["source_baseline_difference"])

if __name__=="__main__":
    unittest.main()
