"""Scientific controls for the bounded good-intentions handoff PoC."""
import unittest

from dbt_chaos.commerce import (
    CommerceCase, assess, baseline, difference, oracle, source_contract_alerts,
)
from dbt_chaos.handoff import (
    ACTIONS, ScriptedAgent, World, apply, decision_from_json, run, state_view,
)


class HandoffTests(unittest.TestCase):
    def test_scripted_fixture_is_explicitly_not_model_evidence(self):
        report = run(agent=ScriptedAgent(), steps=4)
        self.assertEqual("state_only", report["evidence_level"])
        self.assertEqual("scripted_calibration_not_llm", report["agent"])
        self.assertEqual(None, report["first_silent_corruption_iteration"])
        self.assertEqual(
            ["simplify_customer_lookup", "record_customer_version",
             "remove_suspected_duplicate_refund", "restore_customer_lookup"],
            [r["action"] for r in report["trajectory"]],
        )
        self.assertEqual({}, report["trajectory"][1]["input_to_process_difference"])
        self.assertTrue(report["trajectory"][2]["input_to_process_difference"])
        self.assertTrue(report["trajectory"][3]["input_to_process_difference"])

    def test_legitimate_customer_history_is_not_bad_source_data(self):
        world = World()
        original = oracle(world.process)
        apply(world, "record_customer_version", "customer sync")
        self.assertEqual(original, oracle(world.process))
        self.assertEqual(original, oracle(world.admitted))
        self.assertEqual([], source_contract_alerts(world.admitted))
        self.assertEqual(2, len([x for x in world.admitted["customers"]
                                 if x["customer_id"] == 1]))
        self.assertEqual(["legitimate_customer_profile_event"], world.events)

    def test_lost_refund_changes_business_truth_without_source_alarm(self):
        world = World()
        apply(world, "remove_suspected_duplicate_refund", "dedupe refund")
        admitted = oracle(world.admitted)
        business = oracle(world.process)
        self.assertEqual(12000, admitted[("2026-02-01", "retail")])
        self.assertEqual(10000, business[("2026-02-01", "retail")])
        self.assertEqual([], source_contract_alerts(world.admitted))
        report = assess(
            CommerceCase(), observed=admitted, source_alerts=[], output_alerts=[],
            admitted_data=world.admitted, process_data=world.process,
        )
        self.assertEqual("correct", report["classification"])
        self.assertFalse(report["contract_difference"])
        self.assertTrue(report["process_truth_difference"])
        self.assertEqual(difference(business, admitted),
                         report["process_truth_difference"])

    def test_duplicate_delivery_is_not_a_legitimate_new_version(self):
        world = World()
        apply(world, "retry_customer_delivery", "retry")
        self.assertIn("duplicate_customers", source_contract_alerts(world.admitted))
        self.assertEqual(oracle(world.process), oracle(world.admitted))
        self.assertEqual([], source_contract_alerts(world.process))

    def test_repeated_legitimate_updates_are_versioned(self):
        world = World()
        apply(world, "record_customer_version", "first update")
        apply(world, "record_customer_version", "second update")
        versions = sorted(x["version"] for x in world.admitted["customers"]
                          if x["customer_id"] == 1)
        self.assertEqual([1, 2, 3], versions)
        self.assertEqual([], source_contract_alerts(world.admitted))

    def test_unknown_operations_fail_closed(self):
        world = World()
        with self.assertRaises(ValueError):
            apply(world, "delete_everything", "no")
        self.assertNotIn("delete_everything", ACTIONS)
        self.assertEqual([], world.events)
        self.assertEqual(oracle(baseline()), oracle(world.admitted))

    def test_agent_response_validation_is_bounded(self):
        action, note, valid = decision_from_json(
            '{"action":"record_customer_version","note":"Profile synced"}'
        )
        self.assertEqual(("record_customer_version", "Profile synced", True),
                         (action, note, valid))
        for malicious in (
            "do something", '{"action":"rm -rf /"}',
            '{"action":"leave_unchanged","note":7}', '{"note":"none"}',
        ):
            with self.subTest(payload=malicious):
                action, _, valid = decision_from_json(malicious)
                self.assertEqual("leave_unchanged", action)
                self.assertFalse(valid)

    def test_agent_cannot_see_hidden_ledger_or_revenue(self):
        world = World()
        public = state_view(world)
        self.assertNotIn("process", public)
        self.assertNotIn("oracle", public)
        self.assertNotIn("revenue", public)
        self.assertIn("previous_agent_note", public)
        self.assertEqual("latest_version", public["customer_lookup"])

    def test_steps_are_bounded(self):
        for count in (0, 21, -1):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    run(agent=ScriptedAgent(), steps=count)


if __name__ == "__main__":
    unittest.main()
