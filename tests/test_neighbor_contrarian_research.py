import datetime as dt
import unittest
from unittest import mock

import neighbor_contrarian_research as research


def sample(day, local_score=.6):
    return {"symbol": "X", "date": dt.date.fromisoformat(day),
            "exit": dt.date(2024, 7, 1), "outcome": 0,
            "features": [0.] * 10, "local_score": local_score}


class NeighborContrarianTests(unittest.TestCase):
    def test_gate_and_neighbor_are_required_ties_miss(self):
        rows = [sample("2024-01-01"), sample("2024-02-01"), sample("2024-03-01"), sample("2024-04-01")]
        gates = {1: .49, 2: .50, 3: None, 4: .49}
        scores = {1: .6, 2: .6, 3: .6, 4: None}
        with mock.patch.object(research.adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(research.regime, "market_gate", side_effect=lambda samples, day, direction: gates[day.month]), \
             mock.patch.object(research.neighbor, "estimate", side_effect=lambda hist, s, direction: scores[s["date"].month]):
            result = research.evaluate_samples(rows, "bullish", [], years=[2024])
        self.assertEqual(result["neighbor_contrarian"]["n"], 1)
        self.assertEqual(result["neighbor_contrarian"]["correct"], 0)
        self.assertEqual(result["neighbor"]["n"], 3)
        self.assertEqual(result["local_contrarian"]["n"], 2)
        self.assertEqual(result["gate_unavailable_n"], 1)


if __name__ == "__main__":
    unittest.main()
