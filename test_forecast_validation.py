import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import forecast_collect
import forecast_extended_validation as extended
import forecast_validation as fv


class ForecastValidationTests(unittest.TestCase):
    def test_calendar_month_end_and_direction_bins(self):
        self.assertEqual(fv.months_after(dt.date(2024, 11, 30), 3), dt.date(2025, 2, 28))
        self.assertEqual(fv.score_bin(-0.45), 1)
        self.assertEqual(fv.score_bin(0.45), 6)

    def test_monthly_outcome_is_close_to_close_and_ties_are_neither(self):
        zone = ZoneInfo("Asia/Manila")
        start = dt.date(2023, 1, 1)
        rows = []
        for n in range(450):
            day = start + dt.timedelta(days=n)
            stamp = int(dt.datetime(day.year, day.month, day.day, 9, tzinfo=zone).timestamp())
            rows.append([stamp, 999, 100, None])
        data = {"bars": {"PSE:X": rows}}
        samples, _ = fv.observations(data)
        self.assertTrue(samples)
        self.assertTrue(all(s["outcome"] == 0 for s in samples))
        self.assertEqual(fv.summary(samples, {s["bin"]: {"direction": "bullish"} for s in samples})["bullish"]["hit_pct"], 0)

    def test_embargo_uses_only_outcomes_before_evaluation(self):
        def sample(date, exit):
            return {"symbol": "X", "date": dt.date.fromisoformat(date),
                    "exit": dt.date.fromisoformat(exit), "bin": 0, "outcome": 1}
        samples = [sample("2024-09-01", "2024-12-01"),
                   sample("2024-10-01", "2025-01-01"),
                   sample("2025-01-01", "2025-04-01")]
        with mock.patch.object(fv, "observations", return_value=(samples, {})), \
             mock.patch.object(fv, "calibrate", return_value={}) as calibrate:
            result = fv.evaluate({"bars": {}}, years=[2025])
        self.assertEqual(calibrate.call_args.args[0], samples[:1])
        self.assertEqual(result["folds"][0]["evaluation"]["n"], 1)
        self.assertEqual(result["folds"][0]["latest_training_exit"], "2024-12-01")

    def test_insufficient_training_abstains(self):
        self.assertTrue(all(v["direction"] is None for v in fv.calibrate([]).values()))

    def test_collector_excludes_incomplete_local_day(self):
        utc = dt.timezone.utc
        today = dt.datetime(2026, 10, 30, 18, tzinfo=utc)
        stamps = [int(dt.datetime(2026, 10, d, 14, tzinfo=utc).timestamp()) for d in (29, 30)]
        payload = {"chart": {"result": [{"meta": {"exchangeTimezoneName": "America/New_York"},
                   "timestamp": stamps, "indicators": {"quote": [{"close": [10, 11]}]}}]}}
        zone, rows = forecast_collect.clean(payload, today)
        self.assertEqual(zone, "America/New_York")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], 10)

    def test_extended_accuracy_counts_ties_as_errors_and_abstentions(self):
        date = dt.date(2025, 1, 1)
        calls = [({"date": date, "symbol": "A", "outcome": 1}, "bullish"),
                 ({"date": date, "symbol": "B", "outcome": 0}, "bullish"),
                 ({"date": date, "symbol": "C", "outcome": -1}, None)]
        result = extended.direction_metrics(calls, "bullish")
        self.assertEqual(result["n"], 2)
        self.assertEqual(result["hit_pct"], 50)
        self.assertFalse(result["meets_51_pct_observed"])
        self.assertEqual(result["coverage_pct"], 66.67)

    def test_extended_walk_forward_never_trains_on_overlapping_outcome(self):
        def sample(date, exit, outcome):
            return {"symbol": "X", "date": dt.date.fromisoformat(date),
                    "exit": dt.date.fromisoformat(exit), "bin": 0, "outcome": outcome}
        samples = [sample("2023-01-01", "2023-04-01", 1),
                   sample("2023-12-01", "2024-03-01", -1),
                   sample("2024-01-01", "2024-04-01", 1)]
        calibrations = []

        def fit(train):
            calibrations.append(list(train))
            return {0: {"direction": "bullish"}}

        with mock.patch.object(extended, "YEARS", [2024]), \
             mock.patch.object(fv, "observations", return_value=(samples, {})), \
             mock.patch.object(fv, "calibrate", side_effect=fit):
            result = extended.evaluate({"bars": {}, "universe": [], "missing": []})
        self.assertEqual(calibrations, [samples[:1]])
        self.assertEqual(result["folds"][0]["latest_training_exit"], "2023-04-01")
        self.assertEqual(result["bullish"]["hit_pct"], 100)
        self.assertEqual(result["combined"]["always_up_same_calls_pct"], 100)
        self.assertEqual(result["combined"]["always_down_same_calls_pct"], 0)


if __name__ == "__main__":
    unittest.main()
