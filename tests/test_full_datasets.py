"""Tests for process-grounded FULL source fixtures and bounded weak-LLM data edits."""
from __future__ import annotations

import csv
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbt_chaos.commerce import oracle, source_contract_alerts
from dbt_chaos.full_datasets import (
    Profile, ScriptedDatasetPlanner, absolute_group_error, apply_proposal, build_corpus, clean_dataset,
    export_corpus, generate_events, parse_profile, parse_proposal,
    replay_events, ticket_for, validate_new_value,
)


class StubLLM:
    name = "stub_responses_not_actual_llm"
    model_sha256 = "TEST-ONLY"
    def __init__(self):
        self.views = []
        self.seen = 0

    def design(self, seed):
        return json.dumps({
            "customers": 24, "orders": 120, "cancel_percent": 7,
            "capture_percent": 90, "refund_percent": 40,
            "history_percent": 25,
        })

    def edit(self, ticket, view):
        self.seen += 1
        self.views.append(view)
        if self.seen == 1:
            return json.dumps({"operation": "simplify_customer_join",
                               "note": "A direct join is easier to maintain."})
        if self.seen == 2:
            return json.dumps({"operation": "drop_row", "table": "payments",
                               "row_id": ticket["exposed_rows"]["payments"][0]["row_id"],
                               "note": "I think that refund was duplicated."})
        return json.dumps({"operation": "keep", "note": "Looks fine."})


class FullDatasetTests(unittest.TestCase):
    def test_event_log_deterministic_nontrivial_and_clean(self):
        profile = Profile()
        events, tables = clean_dataset(profile)
        self.assertEqual(events, generate_events(profile))
        self.assertEqual(tables, replay_events(events))
        self.assertEqual([], source_contract_alerts(tables))
        self.assertEqual(profile.orders,
                         len({row["order_id"] for row in tables["orders"]}))
        self.assertEqual(profile.customers,
                         len({row["customer_id"] for row in tables["customers"]}))
        self.assertGreater(len(events), 1000)
        self.assertGreater(len(tables["payments"]), 200)
        self.assertGreater(len(oracle(tables)), 15)
        self.assertTrue(any(r["status"] == "cancelled" for r in tables["orders"]))
        self.assertTrue(any(r["version"] == 2 for r in tables["customers"]))
        self.assertTrue(any(p["kind"] == "refund" for p in tables["payments"]))

    def test_event_payments_follow_process_constraints(self):
        events, tables = clean_dataset(Profile(seed=23067))
        last_order = {r["order_id"]: r for r in tables["orders"]
                      if r["version"] == max(x["version"] for x in tables["orders"]
                                               if x["order_id"] == r["order_id"])}
        captures = {}
        refunds = {}
        for payment in tables["payments"]:
            target = captures if payment["kind"] == "capture" else refunds
            target[payment["order_id"]] = (
                target.get(payment["order_id"], 0) + payment["amount_cents"])
        for oid, cents in captures.items():
            self.assertEqual("completed", last_order[oid]["status"])
            self.assertGreater(cents, 0)
            self.assertLessEqual(cents, last_order[oid]["gross_cents"])
        for oid, cents in refunds.items():
            self.assertLessEqual(cents, captures[oid])
        self.assertEqual([], source_contract_alerts(tables))

    def test_group_error_not_masked_by_segment_reclassification(self):
        _, truth = clean_dataset(Profile())
        before = oracle(truth)
        modified = deepcopy(truth)
        target = next(c for c in modified["customers"]
                      if c["customer_id"] == 33 and c["version"] == 2)
        self.assertEqual("business", target["segment"])
        target["segment"] = "retail"
        after = oracle(modified)
        # A financially large segment misclassification has ZERO net drift.
        self.assertEqual(sum(before.values()), sum(after.values()))
        self.assertGreater(absolute_group_error(before, after), 0)
        self.assertEqual(0, absolute_group_error(before, before))
        self.assertEqual([], source_contract_alerts(modified))

    def test_model_profile_without_history_is_rejected_with_reason(self):
        class MissingHistory(StubLLM):
            def design(self, seed):
                return json.dumps({
                    "customers": 12, "orders": 480, "cancel_percent": 0,
                    "capture_percent": 90, "refund_percent": 21,
                    "history_percent": 0,
                })
        agent = MissingHistory()
        corpus = build_corpus(planner=agent, steps=1)
        self.assertFalse(corpus["profile_accepted"])
        self.assertIn("history", corpus["profile_fallback_reason"])
        self.assertEqual(64, corpus["profile"].customers)
        self.assertTrue(corpus["raw_profile_proposal"])
        self.assertEqual([], source_contract_alerts(corpus["truth"]))

    def test_profile_validation_and_fallback(self):
        raw = json.dumps({"customers": 24, "orders": 120,
                          "cancel_percent": 10, "capture_percent": 80,
                          "refund_percent": 25, "history_percent": 20})
        profile, valid = parse_profile(raw, seed=12)
        self.assertTrue(valid)
        self.assertEqual(12, profile.seed)
        self.assertEqual(120, profile.orders)
        for bad in (raw.replace("120", "\"120\""),
                    '{"customers": 9999}',
                    '{"customers": 20, "orders": 120, "cancel_percent": 100}',
                    "DROP TABLE orders"):
            with self.subTest(bad=bad):
                value, accepted = parse_profile(bad, seed=12)
                self.assertFalse(accepted)
                self.assertEqual(Profile(seed=12), value)

    def test_proposal_and_cell_are_allowlisted(self):
        clean = '{"operation":"edit_cell","table":"payments",' \
                '"row_id":35000,"field":"amount_cents","value":300}'
        proposal, valid = parse_proposal(clean)
        self.assertTrue(valid)
        self.assertEqual("edit_cell", proposal["operation"])
        for bad in ('{"operation":"write_sql","sql":"drop table raw.orders"}',
                    '{"operation":"drop_row","row_id":true}',
                    '{"operation":"replay_delivery","row_id":-1}', "not json"):
            with self.subTest(bad=bad):
                _, accepted = parse_proposal(bad)
                self.assertFalse(accepted)
        self.assertFalse(validate_new_value("orders", "row_id", 42))
        self.assertFalse(validate_new_value("orders", "gross_cents", "100"))
        self.assertFalse(validate_new_value("customers", "segment", "wrong"))
        self.assertFalse(validate_new_value("payments", "amount_cents", -1))
        self.assertTrue(validate_new_value("payments", "amount_cents", 450))

    def test_unseen_record_cannot_be_modified(self):
        _, truth = clean_dataset(Profile())
        delivery = json.loads(json.dumps(truth))
        before = json.dumps(delivery, sort_keys=True)
        logic, effect = apply_proposal(
            delivery, "none",
            {"operation": "drop_row", "table": "orders", "row_id": 20100},
            {"orders": set()})
        self.assertEqual(("none", "rejected_unobserved_row"), (logic, effect))
        self.assertEqual(before, json.dumps(delivery, sort_keys=True))

    def test_stub_agent_writes_entire_dataset_with_immutable_ledger(self):
        agent = StubLLM()
        corpus = build_corpus(planner=agent, steps=3, seed=721)
        self.assertEqual(True, corpus["profile_accepted"])
        self.assertTrue(corpus["profile_generated_by_model"])
        self.assertEqual(120, corpus["profile"].orders)
        self.assertEqual(3, agent.seen)
        self.assertEqual("stub_responses_not_actual_llm", corpus["model"])
        self.assertEqual("transformation_changed", corpus["steps"][0]["edit_effect"])
        self.assertEqual("deleted_source_row", corpus["steps"][1]["edit_effect"])
        self.assertEqual([], source_contract_alerts(corpus["truth"]))
        self.assertEqual("none", corpus["steps"][0]["source_contract_alerts"][0]
                         if corpus["steps"][0]["source_contract_alerts"] else "none")
        self.assertEqual(corpus["truth"], replay_events(corpus["events"]))
        self.assertEqual(len(corpus["datasets"]), 3)
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "bundle"
            manifest = export_corpus(corpus, dest)
            self.assertEqual(3, manifest["full_dataset_snapshots"])
            self.assertGreater(len(manifest["files"]), 14)
            for rel, entry in manifest["files"].items():
                self.assertEqual(entry["sha256"],
                                 sha256((dest / rel).read_bytes()).hexdigest())
            self.assertTrue((dest / "ledger/process_events.jsonl").exists())
            self.assertTrue((dest / "steps/03/source_delivery/payments.csv").exists())
            trace = json.loads((dest / "trace.json").read_text())
            self.assertEqual(3, len(trace["steps"]))
            with (dest / "ledger/source_of_truth/orders.csv").open() as source:
                record_count = sum(1 for _ in csv.DictReader(source))
            self.assertEqual(corpus["profile"].orders,
                             record_count -
                             sum(1 for r in corpus["truth"]["orders"] if r["version"] == 2))
            with self.assertRaises(ValueError):
                export_corpus(corpus, dest)  # reject stale/mixed bundles

    def test_full_context_has_prior_tasks_without_ledger(self):
        for mode in ("handoff", "full_history", "no_notes"):
            with self.subTest(mode=mode):
                agent = StubLLM()
                corpus = build_corpus(planner=agent, steps=3, seed=721,
                                      context_mode=mode, model_design=False)
                self.assertEqual(3, len(corpus["steps"]))
                self.assertNotIn("ledger", agent.views[1])
                if mode == "full_history":
                    self.assertEqual(1, len(agent.views[1]["history"]))
                elif mode == "handoff":
                    self.assertIn("prior_note", agent.views[1])
                    self.assertNotIn("history", agent.views[1])
                else:
                    self.assertNotIn("prior_note", agent.views[1])
                    self.assertNotIn("history", agent.views[1])

    def test_scripted_calibration_not_misrepresented_as_model(self):
        corpus = build_corpus(planner=ScriptedDatasetPlanner(), steps=3,
                              seed=20261119)
        self.assertEqual("scripted_fixture_not_llm", corpus["model"])
        self.assertEqual("transformation_changed", corpus["steps"][0]["edit_effect"])
        self.assertEqual("deleted_source_row", corpus["steps"][1]["edit_effect"])
        self.assertTrue(corpus["steps"][1]["input_vs_process"])
        self.assertEqual("no_change", corpus["steps"][2]["edit_effect"])


if __name__ == "__main__":
    unittest.main()
