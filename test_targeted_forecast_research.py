import datetime as dt
import unittest
from unittest import mock

import targeted_forecast_research as research


def sample(date, exit_date, outcome=1, value=1.0, symbol="X"):
    return {"date": dt.date.fromisoformat(date), "exit": dt.date.fromisoformat(exit_date),
            "outcome": outcome, "symbol": symbol, "features": [0.] * 7,
            "rules": {name: value for name in research.RULES}}


class TargetedForecastTests(unittest.TestCase):
    def test_reference_is_strictly_past_and_respects_staleness(self):
        dates = [dt.date(2023, 1, 2), dt.date(2023, 7, 2), dt.date(2024, 1, 2)]
        prices = [100., 120., 200.]
        self.assertAlmostEqual(research.reference(dates, prices, 2, 6), __import__("math").log(200 / 120))
        self.assertIsNone(research.reference(dates, prices, 0, 6))
        self.assertIsNone(research.reference([dt.date(2023, 1, 2), dt.date(2023, 7, 20)], [100., 120.], 1, 6))

    def test_selection_rejects_inadequate_training(self):
        winner, diagnostics = research.select([], [], "bearish")
        self.assertIsNone(winner)
        self.assertEqual(diagnostics, [])

    def test_selection_uses_validation_only_after_training_threshold(self):
        train = [sample("2020-01-01", "2020-04-01", value=i) for i in range(200)]
        validation = []
        for i in range(200):
            # 100 selected cases beat the overall base rate.
            validation.append(sample(f"2022-{1 + i % 12:02d}-01", "2022-12-31",
                                     outcome=1 if i >= 100 else -1, value=i,
                                     symbol=f"X{i % 10}"))
        winner, candidates = research.select(train, validation, "bullish")
        self.assertIsNotNone(winner)
        self.assertEqual(winner["quantile"], .5)
        self.assertEqual(winner["hit_pct"], 100.)
        self.assertEqual(len(candidates), len(research.RULES) * len(research.QUANTILES))

    def test_each_fold_excludes_overlapping_outcomes(self):
        samples = [sample("2021-01-01", "2021-04-01"),
                   sample("2021-12-01", "2022-03-01"),
                   sample("2022-01-01", "2022-04-01"),
                   sample("2023-12-01", "2024-03-01"),
                   sample("2024-01-01", "2024-04-01")]
        with mock.patch.object(research, "select", return_value=(None, [])) as selector:
            result = research.evaluate_samples(samples, "currency", "bearish", [], years=[2024])
        self.assertEqual(selector.call_args.args[0], samples[:1])
        self.assertEqual(selector.call_args.args[1], samples[2:3])
        self.assertEqual(result["test_n"], 1)
        self.assertEqual(result["abstained"], 1)

    def test_rule_values_are_invariant_to_price_scale(self):
        window = [100 + i + (i % 4) for i in range(60)]
        a = research.rule_values(window, .1, .2)
        b = research.rule_values([x * 50 for x in window], .1, .2)
        for key in research.RULES:
            self.assertAlmostEqual(a[key], b[key])


if __name__ == "__main__":
    unittest.main()
