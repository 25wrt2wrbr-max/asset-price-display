import datetime as dt
import unittest
from unittest import mock

import pooled_forecast_research as pooled


def sample(day, exit_day, symbol="X", outcome=1):
    return {"symbol": symbol, "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": [.1, 0., .1, 0., .1, .6, 0.], "local_score": .6}


class PooledForecastTests(unittest.TestCase):
    def test_small_history_abstains(self):
        self.assertIsNone(pooled.estimate(pooled.build_state([], "bullish"), sample("2024-01-01", "2024-04-01")))

    def test_ties_are_not_successes(self):
        history = [sample(f"2022-{1+i%12:02d}-01", "2023-01-01", f"X{i%10}", 0) for i in range(200)]
        state = pooled.build_state(history, "bullish")
        state["months"] = 18
        self.assertEqual(pooled.estimate(state, sample("2024-01-01", "2024-04-01", "X0")), 0.)

    def test_augmented_features_do_not_change_regime_lookup(self):
        history = [sample(f"2022-{1+i%12:02d}-01", "2023-01-01", f"X{i%10}") for i in range(200)]
        state = pooled.build_state(history, "bullish")
        state["months"] = 18
        current = sample("2024-01-01", "2024-04-01", "X0")
        base = pooled.estimate(state, current)
        current["features"] += [.3, .2, .1]
        self.assertEqual(pooled.estimate(state, current), base)

    def test_exits_same_day_and_future_are_never_in_training(self):
        samples = [sample("2023-01-01", "2023-04-01"),
                   sample("2023-10-01", "2024-01-01"),
                   sample("2024-01-01", "2024-04-01")]
        with mock.patch("adaptive_forecast_research.add_local_features", return_value=[samples[-1]]), \
             mock.patch.object(pooled, "build_state", wraps=pooled.build_state) as build:
            result = pooled.evaluate_samples(samples, "bullish", [], [], years=[2024])
        self.assertEqual(build.call_args.args[0], [samples[0]])
        self.assertEqual(result["test_n"], 1)
        self.assertEqual(result["abstained"], 1)


if __name__ == "__main__":
    unittest.main()
