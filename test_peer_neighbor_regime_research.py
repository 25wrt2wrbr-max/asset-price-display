import datetime as dt
import unittest
from unittest import mock

import peer_neighbor_regime_research as research


def sample(day, score=.6):
    return {"symbol": "X", "date": dt.date.fromisoformat(day),
            "exit": dt.date(2024, 7, 1), "outcome": 0,
            "features": [0.] * 10, "local_score": score}


class PeerNeighborRegimeTests(unittest.TestCase):
    def test_call_requires_all_inputs_and_ties_are_misses(self):
        rows = [sample(f"2024-0{i}-01") for i in range(1, 5)]
        ranks = {1: .25, 2: .75, 3: .25, 4: None}
        gates = {1: .49, 2: .49, 3: .5, 4: .49}
        def values(s, peers):
            rank = ranks[s["date"].month]
            return None if rank is None else [0., rank, 0.]
        with mock.patch.object(research.adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(research.relative, "peer_returns", return_value={}), \
             mock.patch.object(research.relative, "relative_features", side_effect=values), \
             mock.patch.object(research.regime, "market_gate", side_effect=lambda samples, day, direction: gates[day.month]), \
             mock.patch.object(research.neighbor, "estimate", return_value=.6):
            result = research.evaluate_samples(rows, "bearish", {}, years=[2024])
        self.assertEqual(result["neighbor_momentum_contrarian"]["n"], 1)
        self.assertEqual(result["neighbor_reversal_contrarian"]["n"], 1)
        self.assertEqual(result["neighbor_momentum_contrarian"]["correct"], 0)
        self.assertEqual(result["neighbor_contrarian"]["n"], 3)
        self.assertEqual(result["input_unavailable_n"], 1)

    def test_exclusion_rebuilds_peer_and_observation_inputs(self):
        raw = {"universe": {"PARA": "us_equity", "ABC": "us_equity"},
               "bars": {"PARA": [1], "ABC": [2]}, "timezones": {}}
        with mock.patch.object(research.targeted, "observations", return_value=([], {})) as observations, \
             mock.patch.object(research.relative, "prepare_bars", return_value={}) as prepare, \
             mock.patch.object(research, "evaluate_samples", return_value={"test_n": 0}):
            result = research.evaluate_market(raw, "us_equity", "bearish", {"PARA"})
        self.assertEqual(observations.call_args.args[0]["bars"], {"ABC": [2]})
        self.assertEqual(prepare.call_args.args[0], {"ABC": [2]})
        self.assertEqual(result["excluded"], ["PARA"])


if __name__ == "__main__":
    unittest.main()
