import datetime as dt
import unittest
from unittest import mock

import contrarian_gate_forecast_research as research


def sample(day, score=.6):
    return {"symbol": "X", "date": dt.date.fromisoformat(day),
            "exit": dt.date(2024, 7, 1), "outcome": 0,
            "features": [0.] * 10, "local_score": score}


class ContrarianTests(unittest.TestCase):
    def test_gates_partition_calls_when_available_and_ties_miss(self):
        rows = [sample("2024-01-01"), sample("2024-02-01"),
                sample("2024-03-01"), sample("2024-04-01", .1)]
        values = {1: .49, 2: .50, 3: None, 4: .49}
        with mock.patch.object(research.adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(research.regime, "market_gate", side_effect=lambda samples, day, direction: values[day.month]):
            result = research.evaluate_samples(rows, "bullish", [], years=[2024])
        self.assertEqual(result["asset_local"]["n"], 3)
        self.assertEqual(result["contrarian"]["n"], 1)
        self.assertEqual(result["regime_gate"]["n"], 1)
        self.assertEqual(result["contrarian"]["correct"], 0)
        self.assertEqual(result["gate_unavailable_n"], 1)


if __name__ == "__main__":
    unittest.main()
