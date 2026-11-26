"""The luck check: how many labels stand out once every judged name counts.

Benjamini-Yekutieli step-up on each label's drift t, as a two-sided normal
p-value, against every name the sweep judged.
"""

import math
import unittest

import recent
import recent_note


def _threshold(rank, tests, q=0.10):
    return rank * q / (tests * sum(1.0 / i for i in range(1, tests + 1)))


class LuckTests(unittest.TestCase):
    def test_hand_worked_case(self):
        # 3 labels among 10 names. c(10) = 2.928968...; thresholds for ranks
        # 1..3 are 0.003414, 0.006828, 0.010242.
        out = recent.luck_check([5.0, 2.5, 2.0], 10)
        # p(5.0) = 5.7e-7 passes; p(2.5) = 0.0124 > 0.006828 fails; p(2.0) =
        # 0.0455 > 0.010242 fails.
        self.assertEqual(out, {"labelled": 3, "tests": 10, "pass": 1, "q": 0.10})
        self.assertLess(math.erfc(5 / math.sqrt(2)), _threshold(1, 10))
        self.assertGreater(math.erfc(2.5 / math.sqrt(2)), _threshold(2, 10))

    def test_step_up_keeps_earlier_ranks(self):
        # Rank 2 passes even though, alone, rank 1 would too: k is the largest
        # rank that passes, and every smaller p-value counts with it.
        out = recent.luck_check([6.0, 6.0, 0.1], 5)
        self.assertEqual(out["pass"], 2)

    def test_one_way_series_and_sign(self):
        out = recent.luck_check([99.0, -99.0, -3.0], 900)
        self.assertEqual(out["pass"], 2)    # t = 3 is not enough among 900

    def test_more_tests_is_stricter(self):
        few = recent.luck_check([4.0] * 5, 20)["pass"]
        many = recent.luck_check([4.0] * 5, 2000)["pass"]
        self.assertGreaterEqual(few, many)
        self.assertEqual(few, 5)
        self.assertEqual(many, 0)

    def test_nothing_to_check(self):
        self.assertIsNone(recent.luck_check([], 100))
        self.assertIsNone(recent.luck_check([None, float("nan")], 100))
        self.assertIsNone(recent.luck_check([3.0, 3.0], 1))   # fewer tests than labels

    def test_note_wording(self):
        line = recent_note.summarize({"rows": [], "bearish": [], "stats": {},
                                      "luck": {"labelled": 76, "tests": 914,
                                               "pass": 9, "q": 0.1}})
        self.assertIn("luck check: with 914 names tested at once, at least 9 of "
                      "76 labels still stand out (at most 10% of those could be "
                      "chance)", line)


if __name__ == "__main__":
    unittest.main()
