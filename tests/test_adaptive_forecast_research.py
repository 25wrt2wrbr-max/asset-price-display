import datetime as dt
import unittest
from unittest import mock

import adaptive_forecast_research as adaptive
import market_forecasts
import targeted_forecast_research as targeted


def sample(date, exit_date, outcome=1):
    return {"symbol": "X", "date": dt.date.fromisoformat(date),
            "exit": dt.date.fromisoformat(exit_date), "outcome": outcome,
            "features": [0.] * 7,
            "rules": {name: 0. for name in targeted.RULES}}


class AdaptiveTests(unittest.TestCase):
    def test_local_feature_uses_only_completed_history(self):
        history = [sample("2020-01-01", "2020-04-01") for _ in range(24)]
        current = sample("2024-01-01", "2024-04-01")
        future = [sample("2023-12-01", "2024-03-01", -1) for _ in range(10)]
        a = adaptive.add_local_features(history + [current], "bullish")[-1]
        b = next(s for s in adaptive.add_local_features(history + [current] + future, "bullish")
                 if s["date"] == current["date"])
        self.assertEqual(a["local_score"], b["local_score"])
        self.assertEqual(len(a["features"]), 10)

    def test_test_outcomes_do_not_reach_fit_or_validation(self):
        rows = [sample("2021-01-01", "2021-04-01"),
                sample("2021-12-01", "2022-03-01"),
                sample("2022-01-01", "2022-04-01"),
                sample("2023-12-01", "2024-03-01"),
                sample("2024-01-01", "2024-04-01")]
        for s in rows:
            s["local_score"] = .6
        with mock.patch.object(adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(market_forecasts, "train", return_value=None) as fit, \
             mock.patch.object(adaptive, "choose", return_value=(None, [])) as choose:
            result = adaptive.evaluate_samples(rows, "bullish", [], years=[2024])
        self.assertEqual(fit.call_args.args[0], rows[:1])
        self.assertEqual(choose.call_args.args[1], rows[2:3])
        self.assertEqual(result["test_n"], 1)
        self.assertEqual(result["abstained"], 1)


if __name__ == "__main__":
    unittest.main()
