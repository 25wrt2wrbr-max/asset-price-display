import datetime as dt
import unittest
from unittest import mock

import peer_regime_forecast_research as research


def sample(day):
    return {"symbol": "X", "date": dt.date.fromisoformat(day),
            "exit": dt.date(2024, 7, 1), "outcome": 0,
            "features": [0.] * 10, "local_score": .6}


class PeerRegimeTests(unittest.TestCase):
    def test_gate_combinations_and_missing_values(self):
        rows = [sample(f"2024-0{i}-01") for i in range(1, 5)]
        ranks = {1: .25, 2: .75, 3: .25, 4: None}
        gates = {1: .49, 2: .5, 3: None, 4: .49}
        def features(s, peers):
            value = ranks[s["date"].month]
            return None if value is None else [0., value, 0.]
        with mock.patch.object(research.adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(research.relative, "peer_returns", return_value={}), \
             mock.patch.object(research.relative, "relative_features", side_effect=features), \
             mock.patch.object(research.regime, "market_gate", side_effect=lambda samples, day, direction: gates[day.month]):
            result = research.evaluate_samples(rows, "bearish", {}, years=[2024])
        self.assertEqual(result["momentum_contrarian"]["n"], 1)
        self.assertEqual(result["reversal_standard"]["n"], 1)
        self.assertEqual(result["momentum_contrarian"]["correct"], 0)
        self.assertEqual(result["input_unavailable_n"], 2)
        self.assertEqual(result["asset_local"]["n"], 4)


if __name__ == "__main__":
    unittest.main()
