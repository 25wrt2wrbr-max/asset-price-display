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


class SteadyLeanTests(unittest.TestCase):
    """The leaning table lists steady leans only (2026-11-07).

    Asked for by name after AAPL flickered: "is there a way to filter out
    'fragile' stocks like AAPL from being shown to me?". The rule is the
    table's, not the classifier's -- these tests pin that it never invents a
    label, only declines to list a flickering one.

    The series are searched, not hand-tuned: a seeded walk is scanned for the
    case it needs (a lean that held, a lean that just appeared), so the tests do
    not depend on one lucky array of numbers.
    """

    NOW = int(time.time())

    def series(self, closes):
        return ([self.NOW - 86400 * (len(closes) - 1 - i)
                 for i in range(len(closes))],
                closes, [0.0] * len(closes))

    def walk(self, seed, drift=0.0012, sigma=0.011, days=66):
        import random
        rng = random.Random(seed)
        closes = [100.0]
        for _ in range(days - 1):
            closes.append(closes[-1] * (1 + rng.gauss(drift, sigma)))
        return self.series(closes)

    def find(self, predicate, limit=400):
        for seed in range(limit):
            stamps, closes, volumes = self.walk(seed)
            if predicate(stamps, closes, volumes):
                return stamps, closes, volumes
        raise AssertionError("no seeded series satisfied the condition")

    def test_a_steady_lean_is_returned_with_its_record(self):
        stamps, closes, volumes = self.find(
            lambda s, c, v: onset.steady_lean(s, c, v) is not None)
        lean = onset.steady_lean(stamps, closes, volumes)
        self.assertEqual(lean["held"], onset.LEAN_HOLD_BARS)
        self.assertEqual(lean["holdBars"], onset.LEAN_HOLD_BARS)
        self.assertGreaterEqual(abs(lean["significance"]), onset.LEAN_MARGIN)

    def test_a_lean_that_just_appeared_is_held_back(self):
        # The row exists in `leaning` -- the chart will still say "leaning
        # bullish" -- and the table declines to list it, because it has not
        # held. This is the AAPL case: the tag is real and it flickers.
        stamps, closes, volumes = self.find(
            lambda s, c, v: onset.leaning(s, c, v) is not None
            and onset.steady_lean(s, c, v) is None)
        self.assertIsNotNone(onset.leaning(stamps, closes, volumes))
        self.assertIsNone(onset.steady_lean(stamps, closes, volumes))

    def test_a_lean_on_the_line_is_held_back_by_the_margin(self):
        stamps, closes, volumes = self.find(
            lambda s, c, v: onset.steady_lean(s, c, v) is not None)
        self.assertIsNone(onset.steady_lean(stamps, closes, volumes,
                                            margin=99.0))

    def test_an_earned_label_is_never_a_lean_row(self):
        # A clean climb earns Bullish outright; a flat series earns nothing.
        # Neither is a near-miss, whatever the steadiness rule says.
        climb = [100.0 + 0.35 * i for i in range(66)]
        self.assertIsNone(onset.steady_lean(*self.series(climb)))
        self.assertIsNone(onset.steady_lean(*self.series([100.0] * 66)))

    def test_the_constant_pair_is_the_one_measured(self):
        # 1.15 and 4-of-5: measured over 120 sessions on 464 shelf names to cut
        # the median name's tag flips from 4 to 0.
        self.assertEqual(onset.LEAN_MARGIN, 1.15)
        self.assertEqual((onset.LEAN_HOLD_BARS, onset.LEAN_HOLD_NEED), (5, 4))


class LeaningWalkTests(unittest.TestCase):
    def test_leaning_is_none_unless_neutral_and_leaning(self):
        now = int(time.time())
        up = [100 * 1.01 ** i for i in range(91)]
        stamps = [now - 86400 * (90 - i) for i in range(91)]
        self.assertIsNone(onset.leaning(stamps, up, [0.0] * 91))
        self.assertIsNotNone(onset.onset(stamps, up, [0.0] * 91))

    def test_leaning_agrees_with_classify(self):
        # The wall clock is pinned to midday and the comparison is made on the
        # window the walk itself reads. Both matter: a series stamped one bar
        # per 24 h, the newest at `now`, puts its oldest bar exactly on the
        # ninety-day cutoff, so whether it is inside the window turned on the
        # second of the day the suite happened to run -- the one test in this
        # file that was flaky. `leaning` never disagrees with `classify` on the
        # same bars; this pins that, not the boundary.
        now = (int(time.time()) // 86400) * 86400 + 43200
        stamps = [now - 86400 * (90 - i) for i in range(91)]
        import random
        rng = random.Random(3)
        for _ in range(200):
            c = [100.0]
            for _ in range(90):
                c.append(c[-1] * (1 + rng.gauss(0.0012, 0.012)))
            used = onset.window_now(stamps, len(c) - 1, days=onset.WINDOW_DAYS)
            call = trend.classify([c[i] for i in used], [0.0] * len(used))
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
