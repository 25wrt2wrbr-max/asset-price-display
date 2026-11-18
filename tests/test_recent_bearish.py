"""Bearish rows from the same scan as the bullish table.

A falling series is dated with the same walk and listed on `bearish`, not
among the bullish rows. A Philippine sweep that has not been asked for
bearish rows yet does not contribute a zero. The peso floor applies to a
bearish Philippine stock the same way it applies to a bullish one.
"""

import time
import unittest
from unittest import mock

import recent


def _series(step):
    end = time.time() - 60
    days = 70
    stamps = [int(end - (days - 1 - i) * 86_400) for i in range(days)]
    closes = [round(100.0 + i * step, 6) for i in range(days)]
    return stamps, closes, [1_000_000.0] * days


def _fetch(bars):
    def fetch(tickers):
        return {ticker: bars[ticker] for ticker in tickers if ticker in bars}
    return fetch


class UsDirectionTests(unittest.TestCase):
    def test_a_falling_name_is_bearish_and_a_rising_name_is_bullish(self):
        import ondolist
        shelf = ondolist._record({"nvdaon", "aaplon"}, 1.0, False)
        bars = {"NVDA": _series(1.0), "AAPL": _series(-1.0)}
        rows, _stats = recent.us_rows(_fetch(bars), shelf)
        by_ticker = {row["ticker"]: row["direction"] for row in rows}
        self.assertEqual(by_ticker, {"NVDA": "bullish", "AAPL": "bearish"})


class SplitTests(unittest.TestCase):
    def _scan(self, ph_rows=(), ph_bear=None, us_rows=()):
        with mock.patch.object(recent, "us_rows", return_value=(list(us_rows), {})), \
             mock.patch.object(recent, "rate_rows", return_value=([], {})), \
             mock.patch.object(recent, "ondo_portfolio_rows", return_value=([], {})), \
             mock.patch.object(recent, "crypto_rows", return_value=([], {})), \
             mock.patch.object(recent, "bond_rows", return_value=([], {})), \
             mock.patch.object(recent, "fund_rows", return_value=([], {})), \
             mock.patch.object(recent.markets, "php_per_usd",
                               return_value={"phpPerUsd": 58.0}):
            return recent.scan(list(ph_rows), fetch_us_bars=lambda symbols: {},
                               ph_sweep_bearish=ph_bear)

    def test_bearish_rows_leave_the_bullish_table(self):
        up = {"market": "US", "ticker": "NVDA", "direction": "bullish",
              "since": 200, "turnover": 10, "currency": "USD", "chartSymbol": "NVDA"}
        down = {"market": "US", "ticker": "AAPL", "direction": "bearish",
                "since": 300, "turnover": 9, "currency": "USD", "chartSymbol": "AAPL"}
        payload = self._scan(us_rows=[up, down])
        self.assertEqual([row["ticker"] for row in payload["rows"]], ["NVDA"])
        self.assertEqual([row["ticker"] for row in payload["bearish"]], ["AAPL"])
        self.assertIn("1 bearish", recent.summarize(payload))

    def test_an_old_philippine_sweep_is_not_read_as_no_bears(self):
        payload = self._scan(ph_bear=None, us_rows=[{
            "market": "US", "ticker": "NVDA", "direction": "bullish",
            "since": 1, "turnover": 1, "currency": "USD"}])
        self.assertFalse(payload["phBearish"])
        self.assertEqual(payload["bearish"], [])

    def test_a_measured_empty_philippine_bearish_list_is_a_zero(self):
        payload = self._scan(ph_bear=[], us_rows=[{
            "market": "US", "ticker": "NVDA", "direction": "bullish",
            "since": 1, "turnover": 1, "currency": "USD"}])
        self.assertTrue(payload["phBearish"])
        self.assertEqual(payload["bearish"], [])
        self.assertIn("0 bearish", recent.summarize(payload))

    def test_a_philippine_bear_from_the_sweep_is_listed(self):
        bear = {"market": "Philippines", "symbol": "PSE:TEL", "ticker": "TEL",
                "name": "PLDT", "kind": "EQUITY", "direction": "bullish",
                "since": 50, "run": 8, "currency": "PHP", "price": 1400.0,
                "turnover": 5_000_000.0, "chartSymbol": "PSE:TEL",
                "windowFirst": 1600.0}
        payload = self._scan(ph_bear=[bear])
        self.assertEqual(payload["rows"], [])
        row = payload["bearish"][0]
        self.assertEqual(row["ticker"], "TEL")
        self.assertEqual(row["direction"], "bearish")

    def test_a_thin_philippine_bear_is_hidden(self):
        bear = {"symbol": "PSE:PAL", "ticker": "PAL", "name": "PAL",
                "kind": "EQUITY", "since": 50, "run": 4, "currency": "PHP",
                "price": 4.0, "turnover": 100_000.0, "chartSymbol": "PSE:PAL"}
        payload = self._scan(ph_bear=[bear])
        self.assertEqual(payload["bearish"], [])
        self.assertEqual(payload["stats"]["Philippines"]["hidden"], 1)

    def test_a_note_without_the_key_does_not_invent_a_zero(self):
        note = recent.summarize({"rows": [{"ticker": "X"}], "leaning": []})
        self.assertNotIn("bearish", note)


if __name__ == "__main__":
    unittest.main()
