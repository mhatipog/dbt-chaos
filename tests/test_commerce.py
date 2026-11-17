import unittest
from dbt_chaos.commerce import (
 CommerceCase,SOURCE_FAULTS,LOGIC_FAULTS,PAIR_PROBES,baseline,
 inject_source,oracle,source_contract_alerts,classify,cases,assess,summarize,interaction_effects,
)

class CommerceTests(unittest.TestCase):
    def test_baseline_business_truth(self):
        self.assertEqual(oracle(baseline()), {
            ("2026-02-01","retail"):10000,
            ("2026-02-01","business"):5000,
            ("2026-02-02","retail"):3000})
        self.assertEqual([],source_contract_alerts(baseline()))

    def test_all_source_faults_deterministic(self):
        for fault in SOURCE_FAULTS:
            with self.subTest(fault=fault):
                a=inject_source(fault)
                self.assertEqual(a,inject_source(fault))
                self.assertEqual(set(a),{"orders","customers","payments"})
                self.assertTrue(all(type(x) is int for x in oracle(a).values()))

    def test_expected_source_quality_alerts(self):
        expectations={
            "duplicate_customer":"duplicate_customers",
            "duplicate_payment":"duplicate_payments",
            "duplicate_order":"duplicate_orders",
            "orphan_customer":"invalid_orders",
            "null_payment":"invalid_payments",
            "negative_payment":"invalid_payments",
            "usd_order":"invalid_orders",
            "invalid_order_status":"invalid_orders",
            "null_order_gross":"invalid_orders",
        }
        for fault,alert in expectations.items():
            with self.subTest(fault=fault):
                self.assertIn(alert,source_contract_alerts(inject_source(fault)))

    def test_unobservable_missing_refund_and_valid_version_change(self):
        self.assertEqual([],source_contract_alerts(inject_source("missing_refund")))
        self.assertNotEqual(oracle(inject_source("missing_refund")),oracle(baseline()))
        updated=oracle(inject_source("customer_version_change"))
        self.assertEqual(15000,updated[("2026-02-01","business")])
        self.assertNotIn(("2026-02-01","retail"),updated)

    def test_complete_two_axis_case_selection(self):
        scenarios=cases()
        self.assertEqual(1+len(SOURCE_FAULTS)-1+len(LOGIC_FAULTS)-1+len(PAIR_PROBES),len(scenarios))
        self.assertIn(CommerceCase("duplicate_customer","skip_customer_dedup"),scenarios)
        self.assertEqual(len(cases(True)),
                         len(scenarios)+len(SOURCE_FAULTS[1:])*len(LOGIC_FAULTS[1:])-len(PAIR_PROBES))
        with self.assertRaises(ValueError):CommerceCase("sql injection","none")
        with self.assertRaises(ValueError):CommerceCase("none","DROP TABLE")

    def test_classification_is_separate_from_alerting(self):
        expected={("2026-02-01","retail"):10000}
        wrong={("2026-02-01","retail"):12000}
        self.assertEqual("correct",classify(expected,expected,[],[]))
        self.assertEqual("contained",classify(expected,expected,["source_duplicate_customers"],[]))
        self.assertEqual("silent_corruption",classify(expected,wrong,["source_duplicate_customers"],[]))
        self.assertEqual("detected_failure",classify(expected,wrong,[],["gold_invalid"]))
        self.assertEqual("execution_failure",classify(expected,{},[],[],"failed"))
    def test_provenance_and_summary(self):
        case=CommerceCase("missing_refund","ignore_refunds")
        result=assess(case,oracle(inject_source("missing_refund")),[],[])
        self.assertTrue(result["source_loss_not_self_verifiable"])
        self.assertTrue(result["source_baseline_difference"])
        self.assertEqual("combined",result["origin"])
        self.assertEqual({"correct":1},summarize([result])["outcomes"])

    def test_interaction_attribution_keeps_controls(self):
        src=CommerceCase("duplicate_customer")
        sql=CommerceCase(logic_fault="skip_customer_dedup")
        combo=CommerceCase("duplicate_customer","skip_customer_dedup")
        ref=oracle(inject_source("duplicate_customer"))
        wrong=dict(ref)
        wrong[("2026-02-01","retail")]+=10000
        results=[
            assess(src,ref,["source_duplicate_customers"],[]),
            assess(sql,oracle(baseline()),[],[]),
            assess(combo,wrong,["source_duplicate_customers"],[]),
        ]
        self.assertEqual("emergent_corruption",interaction_effects(results)[0]["interaction"])
        base=oracle(baseline())
        admitted=oracle(inject_source("missing_refund"))
        src=assess(CommerceCase("missing_refund"),admitted,[],[])
        bad=dict(base);bad[("2026-02-01","retail")]+=2000
        sql=assess(CommerceCase(logic_fault="ignore_refunds"),bad,[],[])
        combo=assess(CommerceCase("missing_refund","ignore_refunds"),admitted,[],[])
        relations=interaction_effects([src,sql,combo])
        self.assertEqual("masked_corruption",relations[0]["interaction"])
    def test_scorecard_tracks_mismatch_detection_and_amount(self):
        case=CommerceCase(logic_fault="ignore_refunds")
        observed=dict(oracle(baseline()))
        observed[("2026-02-01","retail")]+=2000
        result=assess(case,observed,[],[])
        self.assertEqual(2000,result["absolute_synthetic_cents_difference"])
        self.assertEqual(2000,result["net_synthetic_cents_difference"])
        score=summarize([result])["scorecard"]
        self.assertEqual(1,score["sql_only_mutants_changed_output"])
        self.assertEqual(100,score["undetected_of_incorrect_output_pct"])
    def test_fixture_isolation(self):
        inject_source("duplicate_customer")
        self.assertEqual(3,len(baseline()["customers"]))

if __name__=="__main__":
    unittest.main()
