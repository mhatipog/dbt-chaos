"""Controls for the matched handoff experiment; scripted faults != LLM evidence."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbt_chaos.audit_corpus import audit_corpus
from dbt_chaos.full_datasets import (
    Profile, ScriptedDatasetPlanner, build_corpus, clean_dataset,
)
from dbt_chaos.relay_benchmark import (
    CharterSensitiveCalibration, NoOpPlanner, describe,
    make_matched_tasks, run_comparison,
)


class RelayBenchmarkTests(unittest.TestCase):
    def test_same_tickets_and_original_process_are_reproducible(self):
        a = make_matched_tasks(20261119, 20)
        b = make_matched_tasks(20261119, 20)
        self.assertEqual(a, b)
        self.assertEqual(20, len(a))
        self.assertEqual("join_review", a[0]["ticket_id"])
        self.assertEqual("reconciliation", a[1]["ticket_id"])
        self.assertEqual("profile_sync", a[2]["ticket_id"])
        self.assertEqual("routine_audit", a[5]["ticket_id"])
        self.assertNotEqual(make_matched_tasks(20261120, 20), a)

    def test_context_is_explicit_and_does_not_hide_oracle_leakage(self):
        class Observer(NoOpPlanner):
            def __init__(self):
                self.views = []
            def edit(self, ticket, view):
                self.views.append(json.loads(json.dumps(view)))
                return super().edit(ticket, view)

        _, clean = clean_dataset(Profile())
        tape = make_matched_tasks(20261119, 3)
        for mode, expected_policy, expected_note in (
            ("relay", 1, 2), ("anchored", 3, 2), ("fresh", 3, 0)):
            with self.subTest(mode=mode):
                worker = Observer()
                run = build_corpus(
                    planner=worker, seed=20261119, steps=3,
                    model_design=False, context_mode=mode,
                    fixed_tickets=tape, dbt_checkpoints=set(),
                )
                self.assertEqual(3, len(run["steps"]))
                self.assertEqual(expected_policy, sum(
                    "official_business_charter" in x for x in worker.views))
                self.assertEqual(expected_note, sum(
                    "prior_note" in x for x in worker.views))
                for view in worker.views:
                    self.assertNotIn("oracle", view)
                    self.assertNotIn("business_truth", view)
                    self.assertNotIn("process_event_log", view)
                    self.assertEqual(
                        {"customers", "orders", "payments"},
                        set(view["tables"]),
                    )

    def test_noop_full_twenty_step_export_and_audit(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp)
            report = run_comparison(
                planner_factory=lambda seed: NoOpPlanner(),
                modes=("relay", "anchored", "fresh"),
                steps=20, seed=20261119, checkpoints=set(), output_dir=output,
            )
            self.assertEqual(3, len(report["results"]))
            self.assertEqual(20, len(make_matched_tasks(20261119, 20)))
            for arm in report["results"]:
                self.assertEqual(20, arm["steps"])
                self.assertEqual(0, arm["applied_edits"])
                self.assertEqual(0, arm["invalid_model_outputs"])
                self.assertEqual(0, arm["final_source_absolute_error_cents"])
                self.assertIsNone(arm["first_source_error_step"])
                self.assertIsNone(arm["first_measured_output_error_step"])
                self.assertEqual([], arm["checkpoint_dbt_results"])
                audit = audit_corpus(output / arm["mode"])
                self.assertTrue(audit["verified"])
                self.assertEqual(20, audit["snapshots"])
                self.assertEqual(1081, audit["events"])

    def test_causal_plumbing_calibration_separates_relay_from_anchored(self):
        run = run_comparison(
            planner_factory=lambda seed: CharterSensitiveCalibration(),
            modes=("relay", "anchored", "fresh"),
            steps=8, checkpoints=set(), seed=20261119,
        )
        by_mode = {r["mode"]: r for r in run["results"]}
        self.assertEqual(1, by_mode["relay"]["charter_received_steps"])
        self.assertEqual(8, by_mode["anchored"]["charter_received_steps"])
        self.assertEqual(8, by_mode["fresh"]["charter_received_steps"])
        self.assertEqual(7, by_mode["relay"]["notes_received_steps"])
        self.assertEqual(7, by_mode["anchored"]["notes_received_steps"])
        self.assertEqual(0, by_mode["fresh"]["notes_received_steps"])
        self.assertGreater(by_mode["relay"]["final_source_absolute_error_cents"], 0)
        self.assertEqual(0, by_mode["anchored"]["final_source_absolute_error_cents"])
        self.assertEqual(0, by_mode["fresh"]["final_source_absolute_error_cents"])
        self.assertEqual("scripted_context_sensitivity_not_llm",
                         by_mode["relay"]["model"])

    def test_existing_context_modes_and_validations_remain_compatible(self):
        _, _ = clean_dataset(Profile())
        for mode in ("handoff", "full_history", "no_notes"):
            corpus = build_corpus(
                planner=NoOpPlanner(), seed=20261119, steps=2,
                context_mode=mode, model_design=False,
            )
            self.assertEqual(2, len(corpus["steps"]))
        for invalid in ("missing", "relay_lossy_hacker"):
            with self.assertRaises(ValueError):
                run_comparison(planner_factory=lambda seed: NoOpPlanner(),
                               modes=(invalid,), checkpoints=set())
        with self.assertRaises(ValueError):
            run_comparison(planner_factory=lambda seed: NoOpPlanner(),
                           modes=("relay", "relay"), checkpoints=set())
        with self.assertRaises(ValueError):
            run_comparison(planner_factory=lambda seed: NoOpPlanner(),
                           steps=21, checkpoints=set())
        with self.assertRaises(ValueError):
            run_comparison(planner_factory=lambda seed: NoOpPlanner(),
                           steps=4, checkpoints={5})
        with self.assertRaises(ValueError):
            build_corpus(planner=NoOpPlanner(), seed=20261119, steps=3,
                         model_design=False, context_mode="relay",
                         fixed_tickets=make_matched_tasks(20261119, 2))


if __name__ == "__main__":
    unittest.main()
