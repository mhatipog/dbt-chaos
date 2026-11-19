"""Verify matched-model audit never mistakes sampler changes for business truth."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbt_chaos.relay_benchmark import (
    NoOpPlanner, CharterSensitiveCalibration, run_comparison,
)
from dbt_chaos.relay_diagnostics import analyse


class RelayDiagnosticsTests(unittest.TestCase):
    def test_identical_noop_arms_have_no_fake_divergence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_comparison(
                planner_factory=lambda seed: NoOpPlanner(),
                seed=20261119, steps=3, checkpoints=set(),
                modes=("relay", "anchored", "fresh"), output_dir=root,
            )
            out = analyse(root)
            self.assertTrue(out["fixed_task_tape_identical"])
            self.assertTrue(out["initial_process_identical"])
            self.assertTrue(out["model_weights_identical"])
            for p in out["pairwise_first_divergences"]:
                self.assertIsNone(p["first_behavioral_decision_divergence"])
                self.assertIsNone(p["first_full_source_snapshot_divergence"])
            for arm in out["arms"].values():
                self.assertEqual(0, arm["applied_operations"])
                self.assertEqual(0.0, arm["source_l1_end_eur"])
                self.assertEqual(3, arm["verified_snapshots"])

    def test_scripted_context_sensitive_change_has_same_pre_edit_state(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_comparison(
                planner_factory=lambda seed: CharterSensitiveCalibration(),
                seed=20261119, steps=6, checkpoints=set(),
                modes=("relay", "anchored"), output_dir=root,
            )
            out = analyse(root)
            self.assertEqual(2, out["pairwise_first_divergences"][0]
                             ["first_behavioral_decision_divergence"])
            self.assertTrue(out["pairwise_first_divergences"][0]
                            ["identical_delivered_source_before_decision"])
            self.assertEqual(2, out["pairwise_first_divergences"][0]
                             ["first_full_source_snapshot_divergence"])
            self.assertGreater(out["arms"]["relay"]["source_l1_end_eur"], 0)
            self.assertEqual(0.0, out["arms"]["anchored"]["source_l1_end_eur"])
            self.assertEqual("matched_good_faith_relay_posthoc_v1",
                             out["experiment"])


if __name__ == "__main__":
    unittest.main()
