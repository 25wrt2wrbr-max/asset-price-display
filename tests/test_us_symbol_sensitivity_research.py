import unittest
from unittest import mock

import us_symbol_sensitivity_research as research


class SymbolSensitivityTests(unittest.TestCase):
    def test_symbol_excluded_from_observations_and_peer_universe(self):
        raw = {"universe": {"PARA": "us_equity", "ABC": "us_equity", "BTC-USD": "crypto"},
               "bars": {"PARA": [1], "ABC": [2], "BTC-USD": [3]}, "timezones": {}}
        with mock.patch.object(research.targeted, "observations", return_value=([], {})) as observations, \
             mock.patch.object(research.relative, "prepare_bars", return_value={}) as prepare, \
             mock.patch.object(research.peer_regime, "evaluate_samples", return_value={"test_n": 0}):
            result = research.evaluate_subset(raw, {"PARA"})
        self.assertEqual(observations.call_args.args[0]["bars"], {"ABC": [2]})
        self.assertEqual(prepare.call_args.args[0], {"ABC": [2]})
        self.assertEqual(result["requested"], 1)
        self.assertEqual(result["received"], 1)


if __name__ == "__main__":
    unittest.main()
