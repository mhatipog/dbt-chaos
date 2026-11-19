"""Score actual released information, not theoretical warehouse tables."""
import unittest

from dbt_chaos.relay_platform_replay import score_publication


class NativeRelayScoringTests(unittest.TestCase):
    def setUp(self):
        self.truth = {("2026-02-01", "retail"): 10000,
                      ("2026-02-01", "business"): 20000}

    def test_fully_correct_publication(self):
        result = score_publication(self.truth, self.truth, set())
        self.assertEqual("correctly_published", result["status"])
        self.assertEqual(1.0, result["fraction_of_correct_business_value_published"])
        self.assertEqual(0, result["false_published_l1_cents"])
        self.assertEqual([], result["silent_missing_groups"])

    def test_wrong_refund_with_no_source_warning_is_published_error(self):
        delivered = dict(self.truth)
        delivered[("2026-02-01", "retail")] += 2000
        result = score_publication(self.truth, delivered, set())
        self.assertEqual("silently_wrong", result["status"])
        self.assertEqual(2000, result["false_published_l1_cents"])
        self.assertEqual(["2026-02-01|retail"], result["false_published_groups"])
        self.assertAlmostEqual(2 / 3,
                               result["fraction_of_correct_business_value_published"],
                               places=5)

    def test_all_held_is_not_miscounted_as_correct(self):
        result = score_publication(self.truth, {}, set(self.truth))
        self.assertEqual("held", result["status"])
        self.assertEqual(0, result["false_published_l1_cents"])
        self.assertEqual(0.0, result["fraction_of_correct_business_value_published"])
        self.assertEqual([], result["silent_missing_groups"])

    def test_partial_hold_publishes_only_valid_group(self):
        kept = {("2026-02-01", "retail"): 10000}
        held = {("2026-02-01", "business")}
        result = score_publication(self.truth, kept, held)
        self.assertEqual("partially_held", result["status"])
        self.assertAlmostEqual(1 / 3, result["fraction_of_correct_business_value_published"], places=5)
        self.assertEqual([], result["false_published_groups"])

    def test_unannounced_missing_group_is_not_silent_withholding(self):
        kept = {("2026-02-01", "retail"): 10000}
        result = score_publication(self.truth, kept, set())
        self.assertEqual("silently_wrong", result["status"])
        self.assertEqual(["2026-02-01|business"], result["silent_missing_groups"])
        self.assertEqual(20000, result["unannounced_missing_l1_cents"])

    def test_a_held_group_may_not_appear_in_public_gold(self):
        with self.assertRaisesRegex(ValueError, "withheld"):
            score_publication(
                self.truth, self.truth, {("2026-02-01", "retail")})


if __name__ == "__main__":
    unittest.main()
