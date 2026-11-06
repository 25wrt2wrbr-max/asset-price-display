import datetime as dt
import unittest
from unittest import mock

import consensus_forecast_research as research


def sample(symbol, local_score):
    return {"symbol": symbol, "date": dt.date(2024, 1, 1),
            "exit": dt.date(2024, 4, 1), "outcome": 0,
            "features": [0.] * 10, "local_score": local_score}


class ConsensusTests(unittest.TestCase):
    def test_requires_both_calls_and_ties_are_misses(self):
        rows = [sample("A", .6), sample("B", .4), sample("C", .6)]
        def scores(history, current, direction):
            return {"A": .6, "B": .6, "C": None}[current["symbol"]]
        with mock.patch.object(research.adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(research.neighbor, "estimate", side_effect=scores), \
             mock.patch.object(research.regime, "market_gate", return_value=None):
            result = research.evaluate_samples(rows, "bullish", [], years=[2024])
        self.assertEqual(result["consensus"]["n"], 1)
        self.assertEqual(result["consensus"]["correct"], 0)
        self.assertEqual(result["asset_local"]["n"], 2)
        self.assertEqual(result["neighbor"]["n"], 2)
        self.assertEqual(result["regime_gate"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
