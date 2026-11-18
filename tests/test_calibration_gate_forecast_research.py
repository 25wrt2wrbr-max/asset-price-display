import datetime as dt
import unittest
from unittest import mock

import calibration_gate_forecast_research as research


def sample(day, exit_day, symbol="X", outcome=1, score=.6):
    return {"symbol": symbol, "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": [0.] * 10, "local_score": score}


class CalibrationGateTests(unittest.TestCase):
    def test_only_previous_completed_calls_count_and_ties_miss(self):
        day = dt.date(2024, 1, 1)
        history = [sample(f"2023-{i % 9 + 1:02d}-01", "2023-12-01", f"X{i % 10}", i % 2)
                   for i in range(90)]
        self.assertEqual(research.calibration_gate(history, day, "bullish"), .5)
        history.extend(sample("2023-10-01", "2024-01-01", f"X{i % 10}") for i in range(100))
        self.assertEqual(research.calibration_gate(history, day, "bullish"), .5)

    def test_gate_only_receives_historical_local_calls(self):
        selected = sample("2023-01-01", "2023-04-01", outcome=-1)
        not_selected = sample("2023-02-01", "2023-05-01", score=.1)
        same_day_exit = sample("2023-10-01", "2024-01-01")
        current = sample("2024-01-01", "2024-04-01")
        rows = [selected, not_selected, same_day_exit, current]
        with mock.patch.object(research.adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(research, "calibration_gate", return_value=None) as gate:
            result = research.evaluate_samples(rows, "bullish", [], years=[2024])
        self.assertEqual(gate.call_args.args[0], [selected])
        self.assertEqual(result["calibration_gate"]["n"], 0)
        self.assertEqual(result["asset_local"]["n"], 1)
        self.assertEqual(result["gate_unavailable_n"], 1)


if __name__ == "__main__":
    unittest.main()
