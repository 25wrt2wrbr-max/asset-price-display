import datetime as dt
import unittest
from unittest import mock

import neighbor_forecast_research as research


def sample(day, exit_day, symbol="X", outcome=1, value=0.):
    return {"symbol": symbol, "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": [value] * 7, "local_score": .6}


class NeighborTests(unittest.TestCase):
    def test_nearest_neighbors_ignore_unfinished_and_other_assets(self):
        current = sample("2024-01-01", "2024-04-01")
        history = [sample(f"2022-{i + 1:02d}-01", "2023-01-01", outcome=1) for i in range(12)]
        history += [sample(f"2023-{i + 1:02d}-01", "2023-12-01", outcome=0, value=1.) for i in range(12)]
        before = research.estimate(history, current, "bullish")
        history += [sample("2023-11-01", "2024-01-01", outcome=-1) for _ in range(30)]
        history += [sample("2023-01-01", "2023-04-01", symbol="Y", outcome=-1) for _ in range(30)]
        self.assertEqual(before, 1.)
        self.assertEqual(research.estimate(history, current, "bullish"), before)

    def test_ties_count_as_misses_and_too_few_abstains(self):
        current = sample("2024-01-01", "2024-04-01")
        history = [sample(f"2022-{i % 12 + 1:02d}-01", "2023-01-01", outcome=0) for i in range(24)]
        self.assertEqual(research.estimate(history, current, "bullish"), 0.)
        self.assertIsNone(research.estimate(history[:23], current, "bullish"))

    def test_no_neighbors_never_produces_call(self):
        current = sample("2024-01-01", "2024-04-01")
        current["features"] += [0.] * 3
        with mock.patch("adaptive_forecast_research.add_local_features", return_value=[current]):
            result = research.evaluate_samples([current], "bullish", [], years=[2024])
        self.assertEqual(result["neighbor"]["n"], 0)
        self.assertEqual(result["asset_local_same_eligible"]["n"], 1)
        self.assertEqual(result["neighbor_unavailable_n"], 1)


if __name__ == "__main__":
    unittest.main()
