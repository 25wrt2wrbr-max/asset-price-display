import datetime as dt
import math
import unittest
from unittest import mock

import benchmark_forecast_research as research
import market_forecasts as model


class BenchmarkTests(unittest.TestCase):
    def test_benchmark_never_reads_same_day_or_later(self):
        first = dt.date(2024, 1, 1)
        rows = []
        for i in range(110):
            day = first + dt.timedelta(days=i)
            stamp = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp())
            rows.append([stamp, None, 100 + i, None])
        signal = first + dt.timedelta(days=100)
        baseline = research.benchmark_features(rows, "UTC", signal)
        modified = [r[:] for r in rows]
        for i in range(100, len(modified)):
            modified[i][2] = 9999999
        self.assertEqual(research.benchmark_features(modified, "UTC", signal), baseline)
        self.assertTrue(all(math.isfinite(x) for x in baseline))

    def test_benchmark_staleness_abstains(self):
        stamp = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp())
        self.assertIsNone(research.benchmark_features([[stamp, None, 100, None]], "UTC", dt.date(2024, 2, 1)))

    def test_fold_excludes_uncompleted_training_and_validation(self):
        def sample(day, exit_day):
            return {"symbol": "X", "date": dt.date.fromisoformat(day),
                    "exit": dt.date.fromisoformat(exit_day), "outcome": 1,
                    "features": [0.] * 13, "local_score": .4}
        rows = [sample("2021-01-01", "2021-04-01"),
                sample("2021-12-01", "2022-03-01"),
                sample("2022-01-01", "2022-04-01"),
                sample("2023-12-01", "2024-03-01"),
                sample("2024-01-01", "2024-04-01")]
        with mock.patch.object(model, "train", return_value=None) as fit, \
             mock.patch.object(research.adaptive, "choose", return_value=(None, [])) as choose:
            result = research.evaluate_samples(rows, "bullish", [], [], years=[2024])
        self.assertEqual(fit.call_args.args[0], rows[:1])
        self.assertEqual(choose.call_args.args[1], rows[2:3])
        self.assertEqual(result["test_n"], 1)
        self.assertEqual(result["abstained"], 1)


if __name__ == "__main__":
    unittest.main()
