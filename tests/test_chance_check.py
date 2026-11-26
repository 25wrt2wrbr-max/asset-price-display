"""The chance yardstick: labels pure-noise series would get, beside the labels found."""

import math
import random
import unittest

import recent
import recent_note
import trend


class ChanceTests(unittest.TestCase):
    def test_counts(self):
        health = [{"market": "US", "bullish": 40, "bearish": 10, "neutral": 450, "judged": 500},
                  {"market": "Crypto", "bullish": 2, "bearish": 5, "neutral": 18, "judged": 25}]
        out = recent.chance_check(health)
        self.assertEqual(out["judged"], 525)
        self.assertEqual(out["expected"], round(525 * recent.CHANCE_RATE))
        self.assertEqual((out["bullish"], out["bearish"]), (42, 15))

    def test_nothing_judged(self):
        self.assertIsNone(recent.chance_check([]))
        self.assertIsNone(recent.chance_check(None))

    def test_note_wording_and_old_copy(self):
        line = recent_note.summarize({"rows": [], "bearish": [], "stats": {},
                                      "chance": {"judged": 914, "rate": 0.037, "expected": 34,
                                                 "bullish": 60, "bearish": 31}})
        self.assertIn("by chance alone about 34 of 914 names judged would read bullish "
                      "and about 34 bearish; this scan found 60 bullish and 31 bearish", line)
        old = recent_note.summarize({"rows": [], "bearish": [], "stats": {}})
        self.assertNotIn("by chance", old)

    def test_rate_still_matches_the_classifier(self):
        # A smaller rerun of the measurement behind CHANCE_RATE.
        rng = random.Random(7)
        n, labelled = 3000, 0
        for _ in range(n):
            p, closes = 100.0, [100.0]
            for _ in range(62):
                p *= math.exp(rng.gauss(0, 0.02))
                closes.append(p)
            labelled += trend.classify(closes)["label"] != "neutral"
        per_side = labelled / n / 2
        self.assertLess(abs(per_side - recent.CHANCE_RATE), 0.012, per_side)


if __name__ == "__main__":
    unittest.main()
