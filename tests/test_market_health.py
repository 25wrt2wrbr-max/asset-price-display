"""The market health bar: verdict counts per market, not table rows.

Each leg counts every series it judged by the label its own chart carries.
A market with no count is absent, never a zero. The Philippine count needs
the sweep's bearish list, else neutral would swallow the bears.
"""

import time
import unittest
from unittest import mock

import recent


def _series(step, days=70):
    end = time.time() - 60
    stamps = [int(end - (days - 1 - i) * 86_400) for i in range(days)]
    closes = [round(100.0 + i * step, 6) for i in range(days)]
    return stamps, closes, [1_000_000.0] * days


class LegCountTests(unittest.TestCase):
    def test_us_leg_counts_every_judged_name(self):
        import ondolist
        shelf = ondolist._record({"nvdaon", "aaplon", "msfton", "ibmon"}, 1.0, False)
        flat = _series(0.0)
        bars = {"NVDA": _series(1.0), "AAPL": _series(-1.0), "MSFT": flat}
        # IBM does not answer: missing, so not in any count.
        rows, stats = recent.us_rows(
            lambda tickers: {t: bars[t] for t in tickers if t in bars}, shelf)
        self.assertEqual(stats["verdicts"],
                         {"bullish": 1, "bearish": 1, "neutral": 1})
        self.assertIn("IBM", stats["missing"])


class HealthTests(unittest.TestCase):
    def test_order_counts_and_absent_markets(self):
        stats = {
            "Crypto": {"verdicts": {"bullish": 2, "bearish": 5, "neutral": 93}},
            "US": {"verdicts": {"bullish": 10, "bearish": 20, "neutral": 400}},
            "US Treasury": {"universe": 7},                # older copy: no count
            "Philippine fund": {"verdicts": {"bullish": 0, "bearish": 0, "neutral": 0}},
        }
        health = recent.market_health(stats)
        self.assertEqual([m["market"] for m in health], ["US", "Crypto"])
        self.assertEqual(health[0], {"market": "US", "bullish": 10, "bearish": 20,
                                     "neutral": 400, "judged": 430})

    def _scan(self, ph_bear, universe=10, missing=()):
        bull = [{"market": "Philippines", "symbol": "PSE:ALI", "ticker": "ALI",
                 "name": "Ayala Land", "kind": "EQUITY", "since": 1, "run": 5,
                 "price": 30.0, "turnover": 5e6, "currency": "PHP"}]
        with mock.patch.object(recent, "us_rows", return_value=([], {})), \
             mock.patch.object(recent, "rate_rows", return_value=([], {})), \
             mock.patch.object(recent, "ondo_portfolio_rows", return_value=([], {})), \
             mock.patch.object(recent, "crypto_rows", return_value=([], {})), \
             mock.patch.object(recent, "bond_rows", return_value=([], {})), \
             mock.patch.object(recent, "fund_rows", return_value=([], {})), \
             mock.patch.object(recent.markets, "php_per_usd",
                               return_value={"phpPerUsd": 58.0}):
            return recent.scan(bull, fetch_us_bars=lambda s: {},
                               ph_sweep_bearish=ph_bear,
                               ph_sweep_stats={"universe": universe,
                                               "missing": list(missing)})

    def test_philippine_count_from_the_sweep(self):
        bear = [{"market": "Philippines", "symbol": "PSE:TEL", "ticker": "TEL",
                 "name": "PLDT", "kind": "EQUITY", "since": 1, "run": 5,
                 "price": 1300.0, "turnover": 5e7, "currency": "PHP"}]
        payload = self._scan(bear, universe=10, missing=["X", "Y"])
        self.assertEqual(payload["health"], [{
            "market": "Philippines", "bullish": 1, "bearish": 1,
            "neutral": 6, "judged": 8}])

    def test_old_sweep_without_bears_gets_no_philippine_count(self):
        self.assertEqual(self._scan(None)["health"], [])


if __name__ == "__main__":
    unittest.main()
