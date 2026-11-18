import datetime as dt
import unittest
from unittest import mock

import peer_regime_baseline_research as research


def sample(day, local_score):
    return {"symbol": "X", "date": dt.date.fromisoformat(day),
            "exit": dt.date(2024, 7, 1), "outcome": 0,
            "features": [0.] * 10, "local_score": local_score}


class BaselineTests(unittest.TestCase):
    def test_rule_does_not_require_local_call_and_missing_inputs_abstain(self):
        rows = [sample("2024-01-01", .1), sample("2024-02-01", .6), sample("2024-03-01", .6)]
        ranks = {1: .25, 2: .75, 3: None}
        def relative(s, peers):
            value = ranks[s["date"].month]
            return None if value is None else [0., value, 0.]
        with mock.patch.object(research.adaptive, "add_local_features", return_value=rows), \
             mock.patch.object(research.relative, "peer_returns", return_value={}), \
             mock.patch.object(research.relative, "relative_features", side_effect=relative), \
             mock.patch.object(research.regime, "market_gate", return_value=.49):
            result = research.evaluate_samples(rows, "bearish", {}, years=[2024])
        self.assertEqual(result["momentum_contrarian"]["n"], 1)
        self.assertEqual(result["momentum_contrarian"]["correct"], 0)
        self.assertEqual(result["momentum_local_contrarian"]["n"], 0)
        self.assertEqual(result["reversal_local_contrarian"]["n"], 1)
        self.assertEqual(result["input_unavailable_n"], 1)

    def test_excluded_ticker_absent_from_samples_and_peers(self):
        raw = {"universe": {"PARA": "us_equity", "ABC": "us_equity"},
               "bars": {"PARA": [1], "ABC": [2]}, "timezones": {}}
        with mock.patch.object(research.targeted, "observations", return_value=([], {})) as observations, \
             mock.patch.object(research.relative, "prepare_bars", return_value={}) as prepare, \
             mock.patch.object(research, "evaluate_samples", return_value={"test_n": 0}):
            research.evaluate_market(raw, "us_equity", "bearish", {"PARA"})
        self.assertEqual(observations.call_args.args[0]["bars"], {"ABC": [2]})
        self.assertEqual(prepare.call_args.args[0], {"ABC": [2]})


if __name__ == "__main__":
    unittest.main()
