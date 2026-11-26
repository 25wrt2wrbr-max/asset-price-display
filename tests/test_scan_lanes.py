"""The sweep's legs run side by side; one failing leg loses only itself,
the browser legs never overlap, and stats keep the old order."""

import threading
import time
import unittest
from unittest import mock

import recent


class LaneTests(unittest.TestCase):
    def test_failure_is_contained_and_browser_legs_do_not_overlap(self):
        active = {"n": 0, "max": 0}
        lock = threading.Lock()

        def browser(result):
            def leg(*_a, **_k):
                with lock:
                    active["n"] += 1
                    active["max"] = max(active["max"], active["n"])
                time.sleep(0.05)
                with lock:
                    active["n"] -= 1
                return result
            return leg

        def boom():
            raise RuntimeError("crypto down")

        row = {"market": "US", "ticker": "A", "direction": "bullish", "since": 1,
               "turnover": None, "currency": "USD"}
        with mock.patch.object(recent, "us_rows", browser(([row], {"universe": 1}))), \
             mock.patch.object(recent, "rate_rows", browser(([], {"universe": 7}))), \
             mock.patch.object(recent, "bond_rows", browser(([], {"universe": 3}))), \
             mock.patch.object(recent, "ondo_portfolio_rows", return_value=([], {})), \
             mock.patch.object(recent, "crypto_rows", boom), \
             mock.patch.object(recent, "fund_rows", return_value=([], {})), \
             mock.patch.object(recent.markets, "php_per_usd",
                               return_value={"phpPerUsd": 58.0}):
            payload = recent.scan([], fetch_us_bars=lambda s: {})
        self.assertEqual(active["max"], 1)
        self.assertEqual(payload["errors"], {"Crypto": "crypto down"})
        self.assertEqual([r["ticker"] for r in payload["rows"]], ["A"])
        self.assertEqual(list(payload["stats"]),
                         ["Philippines", "US", "US Treasury", "Ondo portfolio",
                          "Philippine bond", "Philippine fund"])

    def test_no_fetcher_fails_only_the_yahoo_legs(self):
        with mock.patch.object(recent, "ondo_portfolio_rows", return_value=([], {})), \
             mock.patch.object(recent, "crypto_rows", return_value=([{
                 "market": "Crypto", "ticker": "X", "direction": "bullish",
                 "since": 1, "currency": "USD"}], {})), \
             mock.patch.object(recent, "bond_rows", return_value=([], {})), \
             mock.patch.object(recent, "fund_rows", return_value=([], {})), \
             mock.patch.object(recent.markets, "php_per_usd",
                               return_value={"phpPerUsd": 58.0}):
            payload = recent.scan([], fetch_us_bars=None)
        self.assertEqual(payload["errors"], {"US": "no bar fetcher was given",
                                             "US Treasury": "no bar fetcher was given"})


if __name__ == "__main__":
    unittest.main()
