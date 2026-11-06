import time
import unittest
from unittest import mock

import onset
import recent
import trend
import tv


def _gentle(n=91, step=1.002, wobble=0.012):
    """A rise too noisy to enter a label but steady enough to lean."""
    import random
    rng = random.Random(7)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] * step * (1 + rng.gauss(0, wobble)))
    return closes


class LeanFieldTests(unittest.TestCase):
    """`lean` is a reading of the zone, never a label."""

    def test_a_label_carries_no_lean(self):
        up = trend.classify([100 * 1.01 ** i for i in range(60)])
        self.assertEqual(up["label"], "bullish")
        self.assertIsNone(up["lean"])
        self.assertGreaterEqual(up["progress"], 1.0)

    def test_a_flat_series_leans_nowhere(self):
        flat = trend.classify([100.0] * 60)
        self.assertIsNone(flat["lean"])
        self.assertEqual(flat["progress"], 0.0)

    def test_lean_matches_the_hold_band(self):
        seen = 0
        import random
        rng = random.Random(1)
        for _ in range(300):
            c = [100.0]
            for _ in range(70):
                c.append(c[-1] * (1 + rng.gauss(0.001, 0.012)))
            call = trend.classify(c)
            score, t = call["score"], call["significance"]
            if call["lean"] == "bullish":
                seen += 1
                self.assertEqual(call["label"], "neutral")
                self.assertGreaterEqual(score, trend.HOLD_SCORE)
                self.assertGreaterEqual(t, trend.HOLD_T)
                self.assertLess(call["progress"], 1.0)
        self.assertGreater(seen, 0)

    def test_a_bond_reading_flips_the_lean(self):
        out = tv.bond_price_call({"label": "neutral", "score": -0.2,
                                  "significance": -1.4, "lean": "bearish"})
        self.assertEqual(out["lean"], "bullish")


class LeaningWalkTests(unittest.TestCase):
    def test_leaning_is_none_unless_neutral_and_leaning(self):
        now = int(time.time())
        up = [100 * 1.01 ** i for i in range(91)]
        stamps = [now - 86400 * (90 - i) for i in range(91)]
        self.assertIsNone(onset.leaning(stamps, up, [0.0] * 91))
        self.assertIsNotNone(onset.onset(stamps, up, [0.0] * 91))

    def test_leaning_agrees_with_classify(self):
        now = int(time.time())
        stamps = [now - 86400 * (90 - i) for i in range(91)]
        import random
        rng = random.Random(3)
        for _ in range(200):
            c = [100.0]
            for _ in range(90):
                c.append(c[-1] * (1 + rng.gauss(0.0012, 0.012)))
            call = trend.classify(c)
            lean = onset.leaning(stamps, c, [0.0] * 91)
            self.assertEqual(lean is not None,
                             call["label"] == "neutral"
                             and call["lean"] == "bullish")
            if lean:
                self.assertEqual(lean["score"], call["score"])


class ScanSplitTests(unittest.TestCase):
    """Leaning rows never appear in the bullish table."""

    def test_scan_separates_leaning_rows(self):
        bull = {"market": "US", "ticker": "A", "direction": "bullish",
                "since": 5, "currency": "USD", "turnover": None}
        lean = {"market": "US", "ticker": "B", "direction": "neutral",
                "lean": "bullish", "progress": 0.8, "currency": "USD",
                "turnover": None}
        lean2 = dict(lean, ticker="C", progress=0.9)
        with mock.patch.object(recent, "us_rows",
                               return_value=([bull, lean, lean2], {})), \
             mock.patch.object(recent, "crypto_rows", return_value=([], {})), \
             mock.patch.object(recent, "bond_rows", return_value=([], {})), \
             mock.patch.object(recent, "fund_rows", return_value=([], {})), \
             mock.patch.object(recent.markets, "php_per_usd",
                               return_value={"phpPerUsd": 60.0}):
            payload = recent.scan([], fetch_us_bars=lambda s: {})
        self.assertEqual([r["ticker"] for r in payload["rows"]], ["A"])
        self.assertEqual([r["ticker"] for r in payload["leaning"]], ["C", "B"])
        self.assertIn("2 leaning bullish", recent.summarize(payload))


if __name__ == "__main__":
    unittest.main()
