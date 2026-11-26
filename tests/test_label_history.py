"""The label history walk agrees with the badge and with `onset` (invariant 2)."""

import math
import random
import unittest
from unittest import mock

import onset
import trend

DAY = 86400


def series(seed, n=400, drift=0.0):
    rng = random.Random(seed)
    p, closes = 100.0, []
    for _ in range(n):
        p *= math.exp(rng.gauss(drift, 0.015))
        closes.append(p)
    # Weekday stamps ending "now", so window_now and window_at line up the way a chart's do.
    stamps, t = [], 1_790_000_000 - (1_790_000_000 % DAY) + 14 * 3600
    while len(stamps) < n:
        if (t // DAY + 4) % 7 < 5:
            stamps.append(t)
        t += DAY
    return stamps, closes


class LabelHistoryTests(unittest.TestCase):
    def check(self, seed, drift):
        stamps, closes = series(seed, drift=drift)
        vols = [0.0] * len(closes)
        with mock.patch.object(onset.time, "time", return_value=stamps[-1]):
            labels = onset.history(stamps, closes, vols, first=150)
            badge = onset.current(stamps, closes, vols)["label"]
            self.assertEqual(labels[-1], badge)
            if badge in ("bullish", "bearish"):
                run = onset.onset(stamps, closes, vols, want=badge)
                i = len(labels) - 1
                while i > 0 and labels[i - 1] == badge:
                    i -= 1
                self.assertEqual(stamps[150 + i], run["since"])
                self.assertEqual(len(labels) - i, run["run"])
        return labels

    def test_matches_badge_and_onset(self):
        seen = set()
        for seed in range(30):
            for drift in (0.004, -0.004, 0.0015, 0.0):
                seen.add(self.check(seed, drift)[-1])
        self.assertTrue({"bullish", "bearish"} <= seen)

    def test_short_history_is_none(self):
        stamps, closes = series(1, n=120)
        labels = onset.history(stamps, closes, [0.0] * 120, first=0)
        self.assertIsNone(labels[0])
        self.assertIsNone(labels[30])           # 30 bars cannot hold three months
        self.assertIsNotNone(labels[-1])

    def test_summary(self):
        out = onset.history_summary([None, "neutral", "bullish", "bullish", "neutral", "bearish"])
        self.assertEqual(out["bars"], 5)
        self.assertEqual(out["counts"], {"bullish": 2, "neutral": 2, "bearish": 1})
        self.assertEqual(out["changes"], 3)
        self.assertEqual(out["longest"], {"bullish": 2, "bearish": 1})


if __name__ == "__main__":
    unittest.main()
