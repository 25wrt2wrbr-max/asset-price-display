import datetime as dt
import unittest
from unittest import mock

import peer_regime_sensitivity_research as research


def sample(day, exit_day, symbol="X", outcome=-1):
    return {"symbol": symbol, "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": [0.] * 10, "local_score": .6}


class SensitivityTests(unittest.TestCase):
    def test_delayed_peer_dates_and_nonoverlapping_calls(self):
        rows = [sample("2024-01-01", "2024-04-01"),
                sample("2024-02-01", "2024-05-01"),
                sample("2024-04-01", "2024-07-01"),
                sample("2024-04-02", "2024-07-02", outcome=0)]
        with mock.patch.object(research.adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(research.regime, "market_gate", return_value=.4), \
             mock.patch.object(research.relative, "peer_returns", return_value={}) as peers, \
             mock.patch.object(research.relative, "relative_features", return_value=[0., .8, 0.]):
            result = research.evaluate_samples(rows, "bearish", "currency", {}, years=[2024])
        self.assertEqual(result["original"]["n"], 4)
        self.assertEqual(result["original"]["correct"], 3)
        self.assertEqual(result["original_nonoverlap_calls"]["n"], 2)
        self.assertEqual(result["original_nonoverlap_calls"]["correct"], 1)
        self.assertNotIn("coverage_pct", result["original_nonoverlap_calls"])
        self.assertIn(mock.call({}, dt.date(2023, 12, 29)), peers.call_args_list)


if __name__ == "__main__":
    unittest.main()
