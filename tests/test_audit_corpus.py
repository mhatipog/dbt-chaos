"""Offline corpus auditors must detect both corrupt bytes and forged traces."""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbt_chaos.audit_corpus import audit_corpus
from dbt_chaos.full_datasets import ScriptedDatasetPlanner, build_corpus, export_corpus


class CorpusAuditTests(unittest.TestCase):
    def make_fixture(self, root):
        corpus = build_corpus(
            planner=ScriptedDatasetPlanner(),
            seed=20261119, steps=3, execute_dbt=False,
        )
        return export_corpus(corpus, root)

    def test_all_snapshots_replay_from_hidden_ledger_and_recorded_agent_actions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "corpus"
            manifest = self.make_fixture(root)
            result = audit_corpus(root)
            self.assertTrue(result["verified"])
            self.assertEqual(len(manifest["files"]), result["files_verified"])
            self.assertEqual(3, result["snapshots"])
            self.assertEqual(manifest["initial_rows"], result["baseline_rows"])
            self.assertEqual(1081, result["events"])
            self.assertEqual(["transformation_changed", "deleted_source_row", "no_change"],
                             [step["effect"] for step in result["steps"]])
            self.assertEqual([], result["steps"][0]["enhanced_source_alerts"])

    def test_tampered_source_csv_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "corpus"
            self.make_fixture(root)
            csv = root / "steps/02/source_delivery/payments.csv"
            csv.write_bytes(csv.read_bytes().replace(b"capture", b"refund", 1))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                audit_corpus(root)

    def test_forged_model_edit_is_rejected_even_if_manifest_hash_updated(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "corpus"
            self.make_fixture(root)
            trace_file = root / "trace.json"
            trace = json.loads(trace_file.read_text())
            trace["steps"][1]["proposal"]["operation"] = "keep"
            new_bytes = (json.dumps(trace, indent=2, sort_keys=True) + "\n").encode()
            trace_file.write_bytes(new_bytes)
            manifest_file = root / "manifest.json"
            manifest = json.loads(manifest_file.read_text())
            manifest["files"]["trace.json"]["sha256"] = sha256(new_bytes).hexdigest()
            manifest["files"]["trace.json"]["size_bytes"] = len(new_bytes)
            manifest_file.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "model proposal is not reproducible"):
                audit_corpus(root)

    def test_replay_cannot_be_faked_by_matching_manifest_hashes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "corpus"
            self.make_fixture(root)
            csv_file = root / "steps/02/source_delivery/payments.csv"
            rows = csv_file.read_bytes().replace(b"capture", b"refund", 1)
            csv_file.write_bytes(rows)
            manifest_file = root / "manifest.json"
            manifest = json.loads(manifest_file.read_text())
            rel = "steps/02/source_delivery/payments.csv"
            manifest["files"][rel]["sha256"] = sha256(rows).hexdigest()
            manifest["files"][rel]["size_bytes"] = len(rows)
            manifest_file.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "snapshot does not replay"):
                audit_corpus(root)


if __name__ == "__main__":
    unittest.main()
