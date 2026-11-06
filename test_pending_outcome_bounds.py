import unittest

import pending_outcome_bounds as bounds


class PendingBoundsTests(unittest.TestCase):
    def test_correct_exact_integer_threshold_and_unknowns(self):
        result = bounds.summarize({"observed": {"rule_calls": 252, "observed_correct": 123},
                                   "not_due": {"rule_calls": 24}})
        self.assertEqual(result["all_calls"], 276)
        self.assertEqual(result["additional_correct_needed_for_51_pct"], 18)
        self.assertEqual(result["all_unresolved_miss_pct"], 44.57)
        self.assertEqual(result["all_unresolved_correct_pct"], 53.26)
        self.assertTrue(result["target_possible"])

    def test_missing_counts_are_not_misclassified_and_bad_counts_fail(self):
        self.assertIsNone(bounds.summarize({})["observed_hit_pct"])
        with self.assertRaises(ValueError):
            bounds.summarize({"observed": {"rule_calls": 1, "observed_correct": 2}})


if __name__ == "__main__":
    unittest.main()
