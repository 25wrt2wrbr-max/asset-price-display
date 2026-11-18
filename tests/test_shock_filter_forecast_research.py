import datetime as dt
import unittest
from unittest import mock

import shock_filter_forecast_research as research


def sample(day, outcome=0):
    return {"symbol": "X", "date": dt.date.fromisoformat(day),
            "exit": dt.date(2024, 7, 1), "outcome": outcome,
            "features": [0.] * 10, "local_score": .6}


class ShockFilterTests(unittest.TestCase):
    def test_benchmark_ignores_same_day_future_and_stale(self):
        first = dt.date(2023, 1, 1)
        dates = [first + dt.timedelta(days=i) for i in range(60)]
        prices = [100. + i for i in range(60)]
        day = dates[40]
        original = research.prior_benchmark_return((dates, prices), day)
        changed = prices[:40] + [1.] * 20
        self.assertEqual(research.prior_benchmark_return((dates, changed), day), original)
        self.assertIsNone(research.prior_benchmark_return((dates[:30], prices[:30]), day))

    def test_filter_requires_negative_return_and_ties_miss(self):
        rows = [sample("2024-01-01"), sample("2024-02-01"), sample("2024-03-01")]
        returns = {1: -.01, 2: 0., 3: None}
        with mock.patch.object(research.adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(research.neighbor, "estimate", return_value=.6), \
             mock.patch.object(research, "prior_benchmark_return", side_effect=lambda prepared, day: returns[day.month]):
            result = research.evaluate_samples(rows, "bullish", ([], []), years=[2024])
        self.assertEqual(result["shock_local"]["n"], 1)
        self.assertEqual(result["shock_local"]["correct"], 0)
        self.assertEqual(result["shock_neighbor"]["n"], 1)
        self.assertEqual(result["asset_local"]["n"], 3)
        self.assertEqual(result["missing_benchmark_n"], 1)


if __name__ == "__main__":
    unittest.main()
