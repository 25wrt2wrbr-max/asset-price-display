import datetime as dt
import unittest
from unittest import mock

import peer_filter_forecast_research as research


def sample(day, outcome=0):
    return {"symbol": "X", "date": dt.date.fromisoformat(day),
            "exit": dt.date(2024, 7, 1), "outcome": outcome,
            "features": [0.] * 10, "local_score": .6}


class PeerFilterTests(unittest.TestCase):
    def test_bearish_filters_have_opposite_rank_and_missing_abstains(self):
        rows = [sample("2024-01-01"), sample("2024-02-01"), sample("2024-03-01")]
        def features(s, peers):
            return {1: [0., .25, 0.], 2: [0., .75, 0.], 3: None}[s["date"].month]
        with mock.patch.object(research.adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(research.neighbor, "estimate", return_value=.6), \
             mock.patch.object(research.relative, "peer_returns", return_value={}), \
             mock.patch.object(research.relative, "relative_features", side_effect=features):
            result = research.evaluate_samples(rows, "bearish", {}, years=[2024])
        self.assertEqual(result["momentum_local"]["n"], 1)
        self.assertEqual(result["reversal_neighbor"]["n"], 1)
        self.assertEqual(result["momentum_local"]["correct"], 0)
        self.assertEqual(result["asset_local"]["n"], 3)
        self.assertEqual(result["peer_unavailable_n"], 1)


if __name__ == "__main__":
    unittest.main()
