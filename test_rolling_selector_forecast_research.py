import datetime as dt
import unittest
from unittest import mock

import rolling_selector_forecast_research as research


def sample(day, exit_day, symbol="X", outcome=1, score=.6):
    return {"symbol": symbol, "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": [0.] * 10, "local_score": score}


class RollingSelectorTests(unittest.TestCase):
    def test_selector_ignores_same_day_and_future_outcomes(self):
        day = dt.date(2024, 1, 1)
        rows = [sample(f"2023-{i % 9 + 1:02d}-01", "2023-12-01", f"X{i % 10}", i % 2)
                for i in range(90)]
        history = {"local": rows}
        self.assertEqual(research.select(history, day, "bullish"), "local")
        history["local"] += [sample("2023-10-01", "2024-01-01", f"X{i % 10}", -1) for i in range(100)]
        self.assertEqual(research.select(history, day, "bullish"), "local")

    def test_selection_uses_only_reconstructed_completed_calls(self):
        old = sample("2023-01-01", "2023-04-01")
        same_day = sample("2023-10-01", "2024-01-01")
        current = sample("2024-01-01", "2024-04-01")
        rows = [old, same_day, current]
        with mock.patch.object(research.adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(research.neighbor, "estimate", return_value=None), \
             mock.patch.object(research.regime, "market_gate", return_value=None), \
             mock.patch.object(research, "select", return_value="local") as choose:
            result = research.evaluate_samples(rows, "bullish", years=[2024])
        # The historical dictionary is mutated over time, so inspect the
        # final call, which is made before adding current-day predictions.
        self.assertEqual(choose.call_args.args[0]["local"], [old])
        self.assertEqual(result["selector"]["n"], 1)
        self.assertEqual(result["neighbor"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
