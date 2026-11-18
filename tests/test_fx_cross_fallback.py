"""A dollar-less peso cross Yahoo refuses (AEDPHP=X, SARPHP=X) is built from its legs."""
import unittest
from unittest import mock

import server
import chart_route


def legs(symbol, span, interval):
    rate = {"PHP=X": 60.0, "AED=X": 3.6725, "SAR=X": 3.75}[symbol]
    return {"points": [{"t": 1000 + i * 86400, "c": rate} for i in range(5)]}


class CrossFallback(unittest.TestCase):
    def run_symbol(self, symbol):
        with mock.patch.object(server, "cached", lambda url, produce: produce()), \
             mock.patch.object(server, "yahoo_chart", side_effect=LookupError("none")), \
             mock.patch.object(server, "chart_data", legs):
            return chart_route.chart_data(symbol, "3mo", "1d")

    def test_aed_and_sar_are_divided_out_of_the_legs(self):
        for symbol, peg in (("AEDPHP=X", 3.6725), ("SARPHP=X", 3.75)):
            out = self.run_symbol(symbol)
            self.assertAlmostEqual(out["points"][-1]["c"], 60.0 / peg, places=4)
            self.assertEqual(out["symbol"], symbol)

    def test_unknown_cross_still_fails(self):
        with mock.patch.object(server, "cached", lambda url, produce: produce()), \
             mock.patch.object(server, "yahoo_chart", side_effect=LookupError("none")), \
             mock.patch.object(server, "chart_data", side_effect=LookupError("leg")):
            with self.assertRaises(LookupError):
                chart_route.chart_data("ZZZPHP=X", "3mo", "1d")


if __name__ == "__main__":
    unittest.main()
