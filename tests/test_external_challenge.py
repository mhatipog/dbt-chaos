"""Any-platform challenge: separate public input from private business truth."""
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import unittest

from dbt_chaos.external_challenge import (
    FORMAT, export_external_challenge,
    export_recorded_qwen_starter_challenge, score_external_challenge,
)
from dbt_chaos.full_datasets import (
    ScriptedDatasetPlanner, build_corpus, export_corpus,
)


class ExternalChallengeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.corpus = root / "corpus"
        self.public = root / "shared_with_platform"
        self.private = root / "secret_answer_key"
        self.published = root / "platform_output"
        self.held = root / "held_output"
        initial = build_corpus(
            planner=ScriptedDatasetPlanner(), seed=20261119,
            steps=3, model_design=False, execute_dbt=False)
        export_corpus(initial, self.corpus)

    def create(self):
        return export_external_challenge(
            corpus=self.corpus, public_dir=self.public,
            private_dir=self.private, step=2)

    def export_gold(self, stage, mapping):
        self.published.mkdir(parents=True, exist_ok=True)
        with (self.published / f"{stage}.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(("order_day", "segment", "revenue_cents"))
            for key, cents in sorted(mapping.items()):
                day, segment = key.split("|", 1)
                w.writerow([day, segment, cents])

    def export_held(self, stage, groups):
        self.held.mkdir(parents=True, exist_ok=True)
        with (self.held / f"{stage}.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(("order_day", "segment"))
            for key in sorted(groups):
                w.writerow(key.split("|", 1))

    def test_one_command_recorded_qwen_starter_needs_no_model_or_dbt(self):
        summary = export_recorded_qwen_starter_challenge(
            public_dir=self.public, private_dir=self.private)
        self.assertTrue(summary["verified_source_corpus"])
        self.assertTrue(summary["separation_verified"])
        self.assertEqual(2000, summary["source_business_l1_cents"])
        self.assertIn("recorded", summary["model"])
        self.assertIn("without running a new model",
                      summary["starter_provenance"])
        from dbt_chaos.audit_corpus import read_tables
        clean = read_tables(self.public, "inputs/clean")
        chaos = read_tables(self.public, "inputs/chaos")
        before = next(r for r in clean["payments"] if r["row_id"] == 30669)
        after = next(r for r in chaos["payments"] if r["row_id"] == 30669)
        self.assertEqual(4900, before["amount_cents"])
        self.assertEqual(2900, after["amount_cents"])
        self.assertEqual(
            {k: v for k, v in before.items() if k != "amount_cents"},
            {k: v for k, v in after.items() if k != "amount_cents"},
        )
        self.assertFalse((self.public / "answer_key.json").exists())
        self.assertTrue((self.private / "answer_key.json").exists())
        key = json.loads((self.private / "answer_key.json").read_text())
        self.export_gold("clean", key["expected_business"])
        self.export_gold("chaos", key["expected_given_source"]["chaos"])
        result = score_external_challenge(
            public_dir=self.public, answer_key=self.private / "answer_key.json",
            published_dir=self.published)
        self.assertEqual("garbage_passed_through",
                         result["results"]["chaos"]["verdict"])
        self.assertEqual(2000,
                         result["results"]["chaos"]["source_to_process_l1_cents"])

    def test_independent_truth_never_appears_in_public_exports(self):
        summary = self.create()
        self.assertTrue(summary["verified_source_corpus"])
        self.assertTrue(summary["separation_verified"])
        self.assertGreater(summary["source_business_l1_cents"], 0)
        self.assertEqual("scripted_fixture_not_llm", summary["model"])
        self.assertTrue((self.public / "inputs/clean/customers.csv").exists())
        self.assertTrue((self.public / "inputs/chaos/payments.csv").exists())
        self.assertTrue((self.private / "answer_key.json").exists())
        self.assertFalse((self.public / "answer_key.json").exists())
        self.assertFalse((self.public / "ledger/process_events.jsonl").exists())
        self.assertEqual(6, len(json.loads(
            (self.public / "manifest.json").read_text())["input_files"]))
        manifest=json.loads((self.public / "manifest.json").read_text())
        self.assertFalse(manifest["publishable_truth_included"])
        self.assertEqual(FORMAT, manifest["format"])
        self.assertEqual(2, manifest["source_step"])
        self.assertIn("order_day,segment,revenue_cents",
                      (self.public / "README.md").read_text())

    def test_cannot_accidentally_embed_private_truth_under_public_directory(self):
        with self.assertRaisesRegex(ValueError, "disjoint"):
            export_external_challenge(
                corpus=self.corpus, public_dir=self.public,
                private_dir=self.public / "secret")
        self.assertFalse(self.public.exists())
        with self.assertRaisesRegex(ValueError, "disjoint"):
            export_external_challenge(
                corpus=self.corpus, public_dir=self.public / "challenge",
                private_dir=self.public)
        self.assertFalse(self.public.exists())

    def test_platform_can_correctly_transform_delivered_garbage_and_fail_business(self):
        self.create()
        key = json.loads((self.private / "answer_key.json").read_text())
        self.export_gold("clean", key["expected_business"])
        self.export_gold("chaos", key["expected_given_source"]["chaos"])
        score = score_external_challenge(
            public_dir=self.public, answer_key=self.private / "answer_key.json",
            published_dir=self.published)
        self.assertEqual(FORMAT, score["format"])
        self.assertFalse(score["clean_baseline_wrong"])
        self.assertEqual("business_correct", score["results"]["clean"]["verdict"])
        self.assertEqual("garbage_passed_through", score["results"]["chaos"]["verdict"])
        self.assertGreater(score["results"]["chaos"]["source_to_process_l1_cents"], 0)
        self.assertEqual(0, score["results"]["chaos"]["published_vs_admitted_l1_cents"])
        self.assertGreater(score["wrong_chaos_published_groups"], 0)

    def test_alert_not_automatically_credited_as_containment(self):
        self.create()
        key=json.loads((self.private/"answer_key.json").read_text())
        self.export_gold("clean", key["expected_business"])
        self.export_gold("chaos", key["expected_given_source"]["chaos"])
        warnings=self.root/"alerts.json"
        warnings.write_text(json.dumps({"clean": [],
                                        "chaos": ["Payment needs checking"]}))
        score=score_external_challenge(
            public_dir=self.public, answer_key=self.private/"answer_key.json",
            published_dir=self.published, alerts_json=warnings)
        self.assertEqual("detected_but_exposed", score["results"]["chaos"]["verdict"])
        self.assertGreater(score["wrong_chaos_published_groups"], 0)

    def test_all_held_scores_zero_availability_without_falsely_passing(self):
        self.create()
        key=json.loads((self.private/"answer_key.json").read_text())
        self.export_gold("clean", key["expected_business"])
        self.export_gold("chaos", {})
        self.export_held("chaos", key["expected_business"].keys())
        score=score_external_challenge(
            public_dir=self.public, answer_key=self.private/"answer_key.json",
            published_dir=self.published, held_dir=self.held)
        self.assertEqual("all_withheld", score["results"]["chaos"]["verdict"])
        published=score["results"]["chaos"]["published"]
        self.assertEqual("held", published["status"])
        self.assertEqual(0.0, published["fraction_of_correct_business_value_published"])
        self.assertEqual([], published["silent_missing_groups"])
        self.assertEqual(0, score["wrong_chaos_published_groups"])

    def test_unexplained_missing_output_is_not_quarantine(self):
        self.create()
        key=json.loads((self.private/"answer_key.json").read_text())
        self.export_gold("clean", key["expected_business"])
        self.export_gold("chaos", {})
        score=score_external_challenge(
            public_dir=self.public, answer_key=self.private/"answer_key.json",
            published_dir=self.published)
        self.assertEqual("silently_wrong",
                         score["results"]["chaos"]["published"]["status"])
        self.assertGreater(
            len(score["results"]["chaos"]["published"]["silent_missing_groups"]), 0)

    def test_matching_true_business_gold_does_not_claim_verified_repair(self):
        self.create()
        key=json.loads((self.private/"answer_key.json").read_text())
        self.export_gold("clean", key["expected_business"])
        self.export_gold("chaos", key["expected_business"])
        score=score_external_challenge(
            public_dir=self.public, answer_key=self.private/"answer_key.json",
            published_dir=self.published)
        self.assertEqual("correct_output_external_evidence_not_verified",
                         score["results"]["chaos"]["verdict"])
        self.assertEqual(0, score["wrong_chaos_published_groups"])

    def test_tampered_input_cannot_be_scored_as_original_challenge(self):
        self.create()
        key=json.loads((self.private/"answer_key.json").read_text())
        self.export_gold("clean", key["expected_business"])
        self.export_gold("chaos", key["expected_business"])
        file=self.public/"inputs/chaos/payments.csv"
        file.write_bytes(file.read_bytes().replace(b"refund", b"capture", 1))
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            score_external_challenge(
                public_dir=self.public, answer_key=self.private/"answer_key.json",
                published_dir=self.published)

    def test_duplicate_published_gold_key_is_error_not_aggregation(self):
        self.create()
        key=json.loads((self.private/"answer_key.json").read_text())
        self.export_gold("clean", key["expected_business"])
        self.export_gold("chaos", key["expected_given_source"]["chaos"])
        file=self.published/"chaos.csv"
        lines=file.read_text().splitlines()
        file.write_text("\n".join(lines+[lines[1]])+"\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            score_external_challenge(
                public_dir=self.public, answer_key=self.private/"answer_key.json",
                published_dir=self.published)


if __name__=="__main__":
    unittest.main()
