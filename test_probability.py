"""Tests for the chart-only predictive model, not empirical calibration."""
import datetime as dt
import math
import random
import unittest

import probability as model


def payload(mean=0.0, sd=0.02, n=91, kind="CRYPTOCURRENCY"):
    rng = random.Random(7)
    noise = [rng.gauss(0, sd) for _ in range(n)]
    center = sum(noise) / n
    start = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
    close = 100.0
    points = [{"t": start.timestamp(), "c": close}]
    day = start
    for r in noise:
        day += dt.timedelta(days=1)
        if kind != "CRYPTOCURRENCY":
            while day.weekday() >= 5:
                day += dt.timedelta(days=1)
        close *= math.exp(mean + r - center)
        points.append({"t": day.timestamp(), "c": close})
    return {"type": kind, "interval": "1d", "points": points}


class ProbabilityTests(unittest.TestCase):
    def test_exact_predictive_formula(self):
        r = model.estimate(payload(mean=0.001))
        h, n = r["horizonBars"], r["observations"]
        expected_sd = r["dailySigma"] * math.sqrt(h + h*h/n)
        expected = model.norm_cdf((h*0.001-math.log1p(.002))/expected_sd)
        self.assertAlmostEqual(r["predictiveSigma"], expected_sd)
        self.assertEqual(r["probability"], round(expected, 4))

    def test_rising_chart_has_higher_odds(self):
        down, flat, up = [model.estimate(payload(mean=m))["probability"]
                          for m in (-.002, 0, .002)]
        self.assertLess(down, flat)
        self.assertLess(flat, .5)
        self.assertGreater(up, .5)

    def test_same_volatility_opposite_return_changes_odds(self):
        a, b = [model.estimate(payload(mean=m)) for m in (-.001, .001)]
        self.assertAlmostEqual(a["dailySigma"], b["dailySigma"])
        self.assertLess(a["probability"], b["probability"])

    def test_uncertainty_in_mean_is_included(self):
        r = model.estimate(payload(mean=.001))
        self.assertGreater(r["predictiveSigma"], r["dailySigma"]*math.sqrt(r["horizonBars"]))

    def test_crypto_calendar_is_calendar_days(self):
        self.assertEqual(model.estimate(payload())["horizonBars"], 92)

    def test_equity_calendar_is_weekdays(self):
        r = model.estimate(payload(kind="EQUITY"))
        self.assertGreaterEqual(r["horizonBars"], 63)
        self.assertLessEqual(r["horizonBars"], 66)

    def test_costs_reduce_odds(self):
        r = model.estimate(payload())
        self.assertLess(r["probability"], .5)

    def test_scale_invariant(self):
        a = payload(mean=.001)
        b = payload(mean=.001)
        for p in b["points"]:
            p["c"] *= 1000
        self.assertEqual(model.estimate(a)["probability"], model.estimate(b)["probability"])

    def test_badge_is_not_an_input(self):
        p = payload()
        r = model.estimate(p)
        p["trend"] = {"score": 1, "label": "bullish"}
        self.assertEqual(model.estimate(p), r)

    def test_unknown_and_yield_are_missing(self):
        for changes in ({"yieldSeries": True}, {"type": "OPTION"}):
            p = payload(); p.update(changes)
            self.assertIsNone(model.estimate(p))

    def test_future_uses_its_own_chart(self):
        p = payload(mean=.001, kind="FUTURE")
        p["symbol"] = "RBJ27.NYM"
        r = model.estimate(p)
        self.assertIsNotNone(r)
        self.assertEqual(r["class"], "future")
        self.assertGreater(r["probability"], .5)
        self.assertGreaterEqual(r["horizonBars"], 63)
        self.assertLessEqual(r["horizonBars"], 66)
        self.assertEqual(r["cost"], .002)

    def test_short_and_constant_series_are_missing(self):
        self.assertIsNone(model.estimate(payload(n=19)))
        self.assertIsNone(model.estimate(payload(sd=0)))
        self.assertIsNone(model.estimate(payload(mean=.001, sd=0)))

    def test_invalid_prices_are_not_silently_bridged(self):
        for bad in (None, 0, -1, float("nan"), float("inf"), True):
            p = payload(); p["points"][20]["c"] = bad
            self.assertIsNone(model.estimate(p))

    def test_invalid_timestamps_are_missing(self):
        for bad in (None, float("inf"), -1e100):
            p = payload(); p["points"][-1]["t"] = bad
            self.assertIsNone(model.estimate(p))

    def test_weekly_and_unordered_bars_are_missing(self):
        p = payload(); p["interval"] = "1wk"
        self.assertIsNone(model.estimate(p))
        p = payload(); p["points"].reverse()
        self.assertIsNone(model.estimate(p))
        p = payload()
        for i, point in enumerate(p["points"]):
            point["t"] = p["points"][0]["t"] + i*7*86400
        self.assertIsNone(model.estimate(p))

    def test_bounds(self):
        for mean in (-1, 1):
            r = model.estimate(payload(mean=mean))
            self.assertGreaterEqual(r["probability"], .01)
            self.assertLessEqual(r["probability"], .99)


if __name__ == "__main__":
    unittest.main()
