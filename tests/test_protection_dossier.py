"""Dossier export preserves actual publication versus withheld evidence."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbt_chaos.commerce import oracle
from dbt_chaos.protection import recorded_qwen_source_cases
from dbt_chaos.protection_dossier import export_policy_dossier, audit_policy_dossier


def synthetic_matrix():
    truth, _ = recorded_qwen_source_cases()
    gold = {f"{d}|{s}": cents for (d, s), cents in oracle(truth).items()}
    base = {
        "scenario": "clean_control", "policy": "raw", "verdict": "business_correct",
        "observed": gold, "publication_status": "published",
        "candidate_detector_findings": [], "quarantine_manifest": [],
        "evidence_manifest": [], "held_groups": [],
        "dbt_executed": True, "dbt_result_reused": False,
        "truth_group_count": len(gold),
    }
    blocked = deepcopy(base)
    blocked.update({
        "policy": "strict_gate", "observed": {}, "held_groups": sorted(gold),
        "publication_status": "withheld", "verdict": "withheld_all",
        "dbt_executed": False, "dbt_result_reused": False,
    })
    return {
        "experiment": "protection_replay_20261119_v1",
        "provenance": "test-only synthetic metrics, no real dbt run",
        "unique_real_dbt_executions": 1,
        "evaluations": [base, blocked],
    }


class ProtectionDossierTests(unittest.TestCase):
    def test_export_real_tables_with_explicit_unexecuted_label(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "dossier"
            manifest = export_policy_dossier(synthetic_matrix(), output)
            self.assertEqual(2, manifest["evaluations"])
            summary = audit_policy_dossier(output)
            self.assertTrue(summary["verified"])
            self.assertGreater(summary["files"], 12)
            self.assertTrue((output /
                 "cases/clean_control/raw/dbt_input/payments.csv").exists())
            self.assertTrue((output /
                 "cases/clean_control/strict_gate/unexecuted_candidate_input/payments.csv").exists())
            self.assertFalse((output /
                 "cases/clean_control/strict_gate/dbt_input/payments.csv").exists())
            self.assertTrue((output /
                 "cases/clean_control/strict_gate/held_reporting_groups.csv").exists())
            held = (output /
                 "cases/clean_control/strict_gate/held_reporting_groups.csv").read_text()
            self.assertGreater(held.count("\n"), 15)
            with self.assertRaisesRegex(ValueError, "empty"):
                export_policy_dossier(synthetic_matrix(), output)

    def test_corrupted_file_rejected(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "dossier"
            export_policy_dossier(synthetic_matrix(), output)
            p = output / "cases/clean_control/raw/dbt_input/payments.csv"
            p.write_bytes(p.read_bytes() + b"bad row\n")
            with self.assertRaisesRegex(ValueError, "changed dossier evidence"):
                audit_policy_dossier(output)


if __name__ == "__main__":
    unittest.main()
