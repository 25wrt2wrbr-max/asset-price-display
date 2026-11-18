import datetime as dt
import math
import unittest
from unittest import mock

import market_forecast_backtest as backtest
import market_forecast_exploratory as explore
import market_forecasts as model


def sample(day, exit_day, outcome, features=None):
    return {"symbol": "X", "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": features or [0.] * len(model.FEATURES)}


class MarketForecastTests(unittest.TestCase):
    def test_features_are_scale_free_and_validate_input(self):
        prices = [100 + i + (i % 4) for i in range(60)]
        for a, b in zip(model.features(prices), model.features([x * 100 for x in prices])):
            self.assertAlmostEqual(a, b)
        for invalid in (prices[:49], prices[:-1] + [math.inf], prices[:-1] + [0]):
            with self.assertRaises(ValueError):
                model.features(invalid)

    def test_insufficient_fit_abstains(self):
        self.assertIsNone(model.train([], "bullish"))
        self.assertIsNone(model.fit_direction([], [], "bearish"))
        self.assertIsNone(model.predict({"bearish": None}, [0.] * len(model.FEATURES)))

    def test_ties_are_not_positive_training_examples(self):
        # With all features constant, half wins and half ties produce a 50% score.
        rows = [sample("2020-01-01", "2020-04-01", i % 2)
                for i in range(model.MIN_FIT)]
        fitted = model.train(rows, "bullish")
        self.assertAlmostEqual(model.score(fitted, rows[0]["features"]), .5, places=6)

    def test_conflicting_forecasts_abstain(self):
        fake = {"validation": {"threshold": .6}}
        with mock.patch.object(model, "score", return_value=.7):
            self.assertIsNone(model.predict({"bullish": fake, "bearish": fake}, [0.]))
            self.assertEqual(model.predict({"bullish": fake, "bearish": None}, [0.]), "bullish")

    def test_fit_validation_and_test_have_separate_completed_outcomes(self):
        rows = [sample("2021-01-01", "2021-04-01", 1),
                sample("2021-12-01", "2022-03-01", 1),
                sample("2022-01-01", "2022-04-01", 1),
                sample("2023-12-01", "2024-03-01", 1),
                sample("2024-01-01", "2024-04-01", 1)]
        with mock.patch.object(backtest, "observations", return_value=(rows, {})), \
             mock.patch.object(model, "fit_direction", return_value=None) as fit:
            result = backtest.evaluate({"bars": {}, "universe": []}, ("bullish",), years=[2024])
        args = fit.call_args.args
        self.assertEqual(args[0], rows[:1])
        self.assertEqual(args[1], rows[2:3])
        self.assertEqual(result["test_n"], 1)
        self.assertEqual(result["abstained"], 1)

    def test_exploratory_selects_only_from_validation_with_minimum_coverage(self):
        rows = []
        for i in range(100):
            s = sample(f"2022-{1 + i % 10:02d}-01", "2023-04-01", 1 if i < 60 else -1)
            s["symbol"] = f"X{i % 10}"
            rows.append(s)
        with mock.patch.object(model, "score", return_value=.4):
            winner, choices = explore.threshold_diagnostics({"direction": "bullish"}, rows)
        self.assertEqual(winner["quantile"], 0)
        self.assertEqual(winner["hit_pct"], 60)
        self.assertEqual(len(choices), len(explore.QUANTILES))

    def test_exploratory_fit_and_validation_exclude_incomplete_outcomes(self):
        rows = [sample("2021-01-01", "2021-04-01", 1),
                sample("2021-12-01", "2022-03-01", 1),
                sample("2022-01-01", "2022-04-01", 1),
                sample("2023-12-01", "2024-03-01", 1),
                sample("2024-01-01", "2024-04-01", 1)]
        with mock.patch.object(model, "train", return_value=None) as fit, \
             mock.patch.object(explore, "threshold_diagnostics", return_value=(None, [])) as validate:
            result = explore.evaluate_samples(rows, ("bullish",), years=[2024])
        self.assertEqual(fit.call_args.args[0], rows[:1])
        self.assertEqual(validate.call_args.args[1], rows[2:3])
        self.assertEqual(result["test_n"], 1)
        self.assertEqual(result["abstained"], 1)


if __name__ == "__main__":
    unittest.main()
