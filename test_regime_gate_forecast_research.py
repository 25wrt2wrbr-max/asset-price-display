import datetime as dt
import unittest
from unittest import mock

import regime_gate_forecast_research as research


def sample(day, exit_day, symbol="X", outcome=1):
    return {"symbol": symbol, "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": [0.] * 10, "local_score": .6}


class RegimeGateTests(unittest.TestCase):
    def test_no_same_day_or_future_outcomes_and_ties_are_misses(self):
        day = dt.date(2024, 1, 1)
        history = [sample(f"2023-{i % 9 + 1:02d}-01", "2023-12-01", f"X{i % 10}", i % 2)
                   for i in range(108)]
        value = research.market_gate(history, day, "bullish")
        self.assertEqual(value, .5)
        history.extend([sample("2023-10-01", "2024-01-01", f"X{i % 10}") for i in range(100)])
        self.assertEqual(research.market_gate(history, day, "bullish"), value)

    def test_sparse_or_old_history_abstains(self):
        day = dt.date(2024, 1, 1)
        self.assertIsNone(research.market_gate([sample("2020-01-01", "2020-04-01")], day, "bearish"))

    def test_unavailable_gate_abstains_even_when_local_calls(self):
        current = sample("2024-01-01", "2024-04-01")
        with mock.patch("adaptive_forecast_research.add_local_features", return_value=[current]):
            result = research.evaluate_samples([current], "bullish", [], years=[2024])
        self.assertEqual(result["gated"]["n"], 0)
        self.assertEqual(result["asset_local_same_eligible"]["n"], 1)
        self.assertEqual(result["gate_unavailable_n"], 1)


if __name__ == "__main__":
    unittest.main()
