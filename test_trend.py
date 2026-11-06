import math
import random
import unittest
from unittest import mock

import server
import trend


def walk(n, drift=0.0, seed=1, sigma=0.015):
    rnd = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] * math.exp(rnd.gauss(drift, sigma)))
    return closes


def labelled(closes):
    return trend.classify(closes)["label"] != "neutral"


class TrendConsistencyTests(unittest.TestCase):
    def test_volume_does_not_change_any_window(self):
        for n in (20, 49, 50, 62, 63, 64, 92):
            closes = [100 + i * 0.1 + (i % 3) * 0.2 for i in range(n)]
            self.assertEqual(trend.classify(closes, [1] * n),
                             trend.classify(closes, [100000] * n))

    def test_cached_chart_is_rescored_without_mutating_cache(self):
        points = [{"c": 100 + i * .1} for i in range(62)]
        cached = {"points": points, "trend": {"label": "bullish", "score": 1},
                  "cached": True, "fetchedAt": 1}
        with mock.patch.object(server, "cached", return_value=cached):
            result = server.chart_data("PSE:SMC", "3mo", "1d")
        self.assertEqual(result["trend"], trend.classify([p["c"] for p in points]))
        self.assertEqual(cached["trend"]["score"], 1)
        self.assertTrue(result["cached"])
        self.assertEqual(result["fetchedAt"], 1)

    def test_legacy_sweeps_are_not_seeded_as_new_verdicts(self):
        self.assertNotEqual(server.BULLISH_KEY, "bullish:scan")
        self.assertNotEqual(server.RECENT_KEY, "recent:scan")
        self.assertNotEqual(server.CRYPTO_KEY, "crypto:bullish")
        # Version 2 of the classifier: version-1 sweeps must not be served.
        for key in (server.BULLISH_KEY, server.RECENT_KEY, server.CRYPTO_KEY):
            self.assertTrue(key.endswith(":t2"), key)


class EvidenceTests(unittest.TestCase):
    """Fix 1: noise is not a trend."""

    def test_random_walks_are_rarely_labelled(self):
        for n in (8, 20, 63, 92):
            hits = sum(labelled(walk(n, seed=s)) for s in range(400))
            self.assertLess(hits / 400, 0.15, n)

    def test_a_real_trend_is_labelled(self):
        self.assertEqual(trend.classify(walk(63, drift=0.006))["label"], "bullish")
        self.assertEqual(trend.classify(walk(63, drift=-0.006))["label"], "bearish")

    def test_score_alone_is_not_enough(self):
        # A V that ends at its high has a big range/score but a drift t
        # nowhere near 1.96: it must not be called.
        down = [100 * 0.99 ** i for i in range(31)]
        up = [down[-1] * 1.0102 ** i for i in range(1, 33)]
        call = trend.classify(down + up)
        self.assertLess(abs(call["significance"]), trend.ENTER_T)
        self.assertEqual(call["label"], "neutral")


class HoldTests(unittest.TestCase):
    """Fix 4: a label holds through the band instead of flickering."""

    def test_a_label_holds_inside_the_band_and_says_so(self):
        rise = [100 * 1.004 ** i for i in range(60)]
        noise = walk(60, sigma=0.004, seed=3)
        closes = [r * n / 100 for r, n in zip(rise, noise)]
        self.assertEqual(trend.classify(closes)["label"], "bullish")
        # Fade until the window sits in the hold band but no longer enters.
        for k in range(1, 20):
            faded = closes + [closes[-1] * 0.997 ** i for i in range(1, k + 1)]
            call = trend.classify(faded)
            score, t = call["score"], call["significance"]
            in_hold = (trend.HOLD_SCORE <= score and trend.HOLD_T <= t
                       and not (score >= trend.ENTER_SCORE and t >= trend.ENTER_T))
            if in_hold:
                self.assertEqual(call["label"], "bullish")
                self.assertTrue(call["held"])
                self.assertEqual(call["confidence"], "holding")
                return
        self.fail("never reached the hold band")

    def test_the_hold_band_alone_does_not_start_a_label(self):
        with mock.patch.object(trend, "_evaluate",
                               return_value=(0.2, 1.5, {"momentum": .5, "trend": .1,
                                                        "efficiency": .1, "range": .1}, .5)):
            call = trend.classify([100.0] * 40)
        self.assertEqual(call["label"], "neutral")

    def test_one_print_cannot_flip_an_established_label(self):
        closes = walk(63, drift=0.004, seed=5, sigma=0.01)
        base = trend.classify(closes)
        self.assertEqual(base["label"], "bullish")
        lr = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        sigma = (sum((r - sum(lr) / len(lr)) ** 2 for r in lr) / len(lr)) ** 0.5
        for sign in (1, -1):
            nudged = closes[:-1] + [closes[-1] * math.exp(sign * sigma)]
            self.assertEqual(trend.classify(nudged)["label"], "bullish")


class WindowTests(unittest.TestCase):
    """Fixes 5 and 7: every bar counts, the oldest barely does."""

    def test_every_drawn_bar_counts(self):
        # The first month of a 92-bar chart used to be ignored.
        early = [100 * 1.01 ** i for i in range(29)]
        late = [early[-1] * (1 + 0.002 * ((-1) ** i)) for i in range(1, 64)]
        closes = early + late
        self.assertNotEqual(trend.classify(closes)["score"],
                            trend.classify(closes[-63:])["score"])
        self.assertEqual(trend.classify(closes)["bars"], 92)

    def test_the_oldest_bar_barely_moves_the_call(self):
        changed = 0
        for s in range(200):
            closes = walk(64, drift=0.002, seed=s)
            changed += (trend.classify(closes)["label"]
                        != trend.classify(closes[1:])["label"])
        self.assertLess(changed / 200, 0.03)

    def test_short_windows_get_a_call_and_need_more_evidence(self):
        for n in (1, 2, 3):
            self.assertEqual(trend.classify(walk(n))["label"], "neutral")
        steep = [100 * 1.03 ** i * (1 + 0.004 * ((-1) ** i)) for i in range(8)]
        self.assertEqual(trend.classify(steep)["label"], "bullish")
        # The same per-bar evidence is discounted more over fewer bars.
        self.assertLess(trend._tcrit(60, trend._Z95), trend._tcrit(7, trend._Z95))

    def test_stale_prints_do_not_pass_for_a_trend(self):
        # A thin name that repeats each print: positive autocorrelation.
        rnd = random.Random(9)
        closes, price = [], 100.0
        for _ in range(21):
            step = math.exp(rnd.gauss(0.002, 0.02))
            for _ in range(3):
                price *= step ** (1 / 3)
                closes.append(price)
        # Equal weights isolate the correction: t without it is the textbook
        # sum / (sigma sqrt m), read against the same small-sample penalty.
        with mock.patch.object(trend, "_ramp", side_effect=lambda m: [1.0] * m):
            _, t = trend._stats(closes)
        lr = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        m = len(lr)
        mu = sum(lr) / m
        sd = (sum((r - mu) ** 2 for r in lr) / (m - 1)) ** 0.5
        naive = (sum(lr) / (sd * m ** 0.5)
                 * trend._Z95 / trend._tcrit(m - 1, trend._Z95))
        self.assertGreater(abs(naive), 0)
        self.assertLess(abs(t), abs(naive) / 1.3)

    def test_flat_and_steady_series(self):
        flat = trend.classify([100.0] * 60)
        self.assertEqual(flat["label"], "neutral")
        self.assertIsNone(flat["components"]["momentum"])
        steady = trend.classify([100 * 1.001 ** i for i in range(60)])
        self.assertEqual(steady["label"], "bullish")
        self.assertIsNone(steady["components"]["momentum"])


class RealTimeTests(unittest.TestCase):
    """Fix 8: the live bar is named, and a stale copy never claims live."""

    def test_a_forming_binance_bar_reads_live_unless_from_disk(self):
        data = {"points": [{"t": 1, "c": 1.0}], "liveLastBar": True}
        self.assertEqual(server.last_bar_basis(data), "live")
        self.assertEqual(server.last_bar_basis(dict(data, cached=True)), "close")


if __name__ == "__main__":
    unittest.main()
