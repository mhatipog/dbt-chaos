"""Evidence-gated maintenance protects real business facts, not just source syntax."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbt_chaos.commerce import oracle
from dbt_chaos.evidence_gate import (
    decide_and_apply, replay_frozen_chain,
    replay_recorded_refund_demo, to_markdown,
)
from dbt_chaos.full_datasets import Profile, ScriptedDatasetPlanner, build_corpus
from dbt_chaos.full_datasets import clean_dataset, export_corpus


class EvidenceGateUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events, cls.truth = clean_dataset(Profile(seed=20261119))
        cls.refund = next(r for r in cls.truth["payments"]
                          if r["row_id"] == 30669)
        if cls.refund["amount_cents"] != 4900:
            raise AssertionError("recorded Qwen refund precondition changed")

    def make_decision(self, proposal, *, state=None, tier="source_only",
                      truth=None, logic="none"):
        data = deepcopy(self.truth) if state is None else state
        table = proposal.get("table", "payments")
        ids = {table: {proposal.get("row_id", -1)}}
        decision = decide_and_apply(data, logic, proposal, ids,
                                    evidence_tier=tier,
                                    attested_source=truth)
        return decision, data

    def test_wrong_refund_is_held_before_change(self):
        proposal = {
            "operation": "edit_cell", "table": "payments", "row_id": 30669,
            "field": "amount_cents", "value": 2900,
            "note": "I have checked this; proof confirmed.",
            "evidence_id": "trusted_process_log",
        }
        for tier in ("source_only", "attested"):
            with self.subTest(tier=tier):
                state = deepcopy(self.truth)
                before = deepcopy(state)
                decision, state = self.make_decision(
                    proposal, state=state, tier=tier,
                    truth=self.truth if tier == "attested" else None)
                self.assertEqual("review_required", decision["decision"])
                self.assertFalse(decision["actually_applied"])
                self.assertEqual(before, state)
                self.assertEqual(oracle(self.truth), oracle(state))
                self.assertIsNone(decision["evidence_id"])

    def test_genuine_correction_only_admitted_with_external_attestation(self):
        state = deepcopy(self.truth)
        payment = next(r for r in state["payments"] if r["row_id"] == 30669)
        payment["amount_cents"] = 2900  # initial bad delivered extract
        correction = {
            "operation": "edit_cell", "table": "payments", "row_id": 30669,
            "field": "amount_cents", "value": 4900,
            "note": "Correct amount from settlement records (UNVERIFIED note).",
        }
        original = deepcopy(state)
        restricted, state = self.make_decision(correction, state=state)
        self.assertEqual("review_required", restricted["decision"])
        self.assertEqual(original, state)
        self.assertNotEqual(oracle(self.truth), oracle(state))

        proven, state = self.make_decision(
            correction, state=state, tier="attested", truth=self.truth)
        self.assertEqual("accepted", proven["decision"])
        self.assertEqual("exact_event_attestation", proven["reason"])
        self.assertEqual("trusted_process_log", proven["evidence_id"])
        self.assertEqual(self.truth, state)

    def test_unchanged_field_allowed_without_evidence(self):
        proposal = {"operation": "edit_cell", "table": "payments",
                    "row_id": 30669, "field": "amount_cents", "value": 4900}
        decision, state = self.make_decision(proposal)
        self.assertEqual("accepted", decision["decision"])
        self.assertEqual("already_equal_no_change", decision["reason"])
        self.assertFalse(decision["actually_applied"])
        self.assertEqual(self.truth, state)

    def test_external_evidence_is_not_supplied_to_source_only(self):
        with self.assertRaisesRegex(ValueError, "must not"):
            self.make_decision({"operation": "keep"}, tier="source_only",
                               truth=self.truth)
        with self.assertRaisesRegex(ValueError, "requires"):
            self.make_decision({"operation": "keep"}, tier="attested")

    def test_unproven_sql_simplification_is_held_even_with_attestation(self):
        proposal = {"operation": "simplify_customer_join",
                    "note": "This SQL is simpler; skip latest customer version"}
        for tier in ("source_only", "attested"):
            decision, state = self.make_decision(
                proposal, tier=tier,
                truth=self.truth if tier == "attested" else None)
            self.assertEqual("review_required", decision["decision"])
            self.assertEqual("sql_equivalence_not_proven", decision["reason"])
            self.assertEqual("none", decision["next_logic"])
            self.assertEqual(self.truth, state)
        restore, _ = self.make_decision(
            {"operation": "restore_customer_join"}, logic="skip_customer_dedup")
        self.assertEqual("accepted", restore["decision"])
        self.assertEqual("none", restore["next_logic"])

    def test_safe_retry_allowed_but_not_under_unknown_sql(self):
        proposal = {"operation": "replay_delivery", "table": "payments",
                    "row_id": 30669}
        good, data = self.make_decision(proposal)
        self.assertEqual("accepted", good["decision"])
        self.assertEqual("idempotent_delivery_retry", good["reason"])
        self.assertEqual(1 + len(self.truth["payments"]), len(data["payments"]))
        self.assertEqual(oracle(self.truth), oracle(data))

        uncertain, data = self.make_decision(
            proposal, logic="skip_customer_dedup")
        self.assertEqual("review_required", uncertain["decision"])
        self.assertEqual(len(self.truth["payments"]), len(data["payments"]))

    def test_provable_duplicate_cleanup_is_not_overblocked(self):
        state = deepcopy(self.truth)
        original = next(p for p in state["payments"] if p["row_id"] == 30669)
        duplicate_id = max(r["row_id"] for r in state["payments"]) + 1
        state["payments"].append(dict(original, row_id=duplicate_id))
        before = oracle(state)
        proposal = {"operation": "drop_row", "table": "payments",
                    "row_id": duplicate_id}
        result, state = self.make_decision(proposal, state=state)
        self.assertEqual("accepted", result["decision"])
        self.assertEqual("exact_duplicate_cleanup", result["reason"])
        self.assertEqual(before, oracle(state))
        self.assertEqual(self.truth, state)

    def test_missing_and_unexposed_rows_do_not_modify_delivery(self):
        example = {"operation": "drop_row", "table": "orders", "row_id": 20100}
        state = deepcopy(self.truth)
        before = deepcopy(state)
        output = decide_and_apply(
            state, "none", example, {"orders": set()})
        self.assertEqual("rejected", output["decision"])
        self.assertEqual("row_not_visible_to_worker", output["reason"])
        self.assertEqual(before, state)

    def test_false_attestation_for_deleted_real_refund_is_rejected(self):
        state = deepcopy(self.truth)
        bad = {"operation": "drop_row", "table": "payments", "row_id": 30669}
        result, state = self.make_decision(
            bad, state=state, tier="attested", truth=self.truth)
        self.assertEqual("review_required", result["decision"])
        self.assertEqual(self.truth, state)
        # A genuine EXTRA record absent from the independent ledger can be
        # removed with exact attestation; not all drops are prohibited.
        state = deepcopy(self.truth)
        extra_id = max(r["row_id"] for r in state["payments"]) + 1
        state["payments"].append(dict(self.refund, row_id=extra_id))
        proven, state = self.make_decision(
            {"operation": "drop_row", "table": "payments", "row_id": extra_id},
            state=state, tier="attested", truth=self.truth)
        self.assertEqual("accepted", proven["decision"])
        self.assertEqual("exact_event_attestation", proven["reason"])
        self.assertEqual(self.truth, state)


class EvidenceGateRealDbtTests(unittest.TestCase):
    def test_one_command_recorded_model_mutation_is_detected_and_prevented(self):
        result = replay_recorded_refund_demo()
        self.assertIn("recorded_qwen_refund", result["experiment"])
        self.assertEqual("silently_wrong",
                         result["results"]["ungated"]["real_dbt"]["status"])
        self.assertEqual(2000,
                         result["results"]["ungated"]["real_dbt"]
                         ["false_published_l1_cents"])
        for tier in ("source_only", "attested"):
            result_score = result["results"][tier]
            self.assertEqual("review_required", result_score["gate"]["decision"])
            self.assertEqual("correctly_published",
                             result_score["real_dbt"]["status"])
            self.assertEqual("correctly_published",
                             result_score["native_dbt"]["status"])
            self.assertEqual(0, result_score["native_quarantined_count"])
        self.assertEqual("silently_wrong",
                         result["results"]["ungated"]["native_dbt"]["status"])
        report = to_markdown(result)
        self.assertIn("€20.00", report)
        self.assertIn("review_required", report)

    def test_a_scripted_chain_replays_only_frozen_actions_not_the_model(self):
        with TemporaryDirectory() as td:
            folder = Path(td) / "fixture"
            script = ScriptedDatasetPlanner()
            corpus = build_corpus(
                planner=script, seed=20261119, steps=3,
                model_design=False, execute_dbt=True)
            export_corpus(corpus, folder)
            first = replay_frozen_chain(
                folder, tier="source_only", quality_enabled=True)
            self.assertTrue(first["archived_model_trace_verified"])
            self.assertEqual("scripted_fixture_not_llm",
                             first["source_model"])
            self.assertEqual(3, first["source_step_count"])
            self.assertGreater(
                first["original_ungated_publication"]
                ["false_published_l1_cents"], 0)
            self.assertEqual(0,
                             first["guarded_dbt_publication"]
                             ["false_published_l1_cents"])
            self.assertGreaterEqual(first["actions_held_for_review"], 2)
            self.assertEqual(0, first["native_dbt_quarantined_rows"])
            self.assertIn("Actions held for review:", to_markdown(first))


if __name__ == "__main__":
    unittest.main()
