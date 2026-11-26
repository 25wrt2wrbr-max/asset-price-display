"""Desk pack server helpers, Yahoo 429 circuit, overnight moves."""

import time
import unittest
from unittest import mock

import server  # noqa: F401 — must load before memo
import diskcache
import deskpack
import moli_client
import memo


class DeskpackEnrichTests(unittest.TestCase):
    def test_enrich_digest_adds_desk_fields(self):
        digest = {"ok": True, "summary": "test"}
        fake_server = mock.Mock()
        fake_server.saved_watchlist.return_value = []
        fake_server.WARM_SPAN = "3mo"
        fake_server.WARM_INTERVAL = "1d"
        fake_server.chart_key = server.chart_key
        with mock.patch.object(deskpack, "bsp_policy", return_value={"rrp": "5%"}), \
                mock.patch.object(deskpack, "btr_auctions", return_value=[]), \
                mock.patch.object(deskpack, "overnight_moves", return_value=[{"symbol": "SPY", "pct": 1.0}]):
            out = deskpack.enrich_digest(digest, fake_server)
        self.assertIn("overnightMoves", out)
        self.assertIn("commodities", out)
        self.assertIn("asean", out)
        self.assertEqual(out["bsp"]["rrp"], "5%")
        self.assertTrue(out["pulseHints"])


class YahooCircuitTests(unittest.TestCase):
    def setUp(self):
        moli_client.reset_yahoo_circuit()

    def tearDown(self):
        # An open circuit is module state: left open, it makes every later
        # test that reads Yahoo fail with "cooling" instead of its own result.
        moli_client.reset_yahoo_circuit()

    def test_trip_opens_cool_window(self):
        for _ in range(moli_client.YAHOO_429_TRIP):
            moli_client._note_yahoo_status(429)
        st = moli_client.yahoo_cool_status()
        self.assertTrue(st["cooling"])
        self.assertIsNotNone(st["coolUntil"])

    def test_moli_get_raises_while_cooling(self):
        for _ in range(moli_client.YAHOO_429_TRIP):
            moli_client._note_yahoo_status(429)
        url = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
        with self.assertRaises(moli_client.UpstreamError):
            moli_client.moli_get(url)

    def test_200_resets_streak(self):
        moli_client._note_yahoo_status(429)
        moli_client._note_yahoo_status(429)
        moli_client._note_yahoo_status(200)
        st = moli_client.yahoo_cool_status()
        self.assertEqual(st["streak429"], 0)
        self.assertFalse(st["cooling"])


class OvernightMovesTests(unittest.TestCase):
    def test_overnight_from_disk_charts(self):
        sym = "CL=F"
        key = server.chart_key(sym, server.WARM_SPAN, server.WARM_INTERVAL)
        chart = {
            "symbol": sym,
            "name": "WTI",
            "points": [{"t": 1, "c": 70.0}, {"t": 2, "c": 71.4}],
        }
        diskcache.store(key, chart)
        fake_server = mock.Mock()
        fake_server.saved_watchlist.return_value = []
        fake_server.WARM_SPAN = server.WARM_SPAN
        fake_server.WARM_INTERVAL = server.WARM_INTERVAL
        fake_server.chart_key = server.chart_key
        moves = deskpack.overnight_moves(fake_server)
        row = next(r for r in moves if r["symbol"] == sym)
        self.assertEqual(row["pct"], 2.0)


class MemoSwrTests(unittest.TestCase):
    def test_expired_memo_returns_disk_while_revalidating(self):
        key = "test:swr:v1"
        payload = {"symbol": "TEST", "points": [{"t": 1, "c": 1.0}]}
        diskcache.store(key, payload)
        server._cache[key] = (time.time() - 9999, dict(payload))
        calls = []

        def produce():
            calls.append(1)
            time.sleep(0.05)
            return {"symbol": "TEST", "points": [{"t": 2, "c": 2.0}]}

        out = memo.cached(key, produce, ttl=1.0)
        self.assertTrue(out.get("revalidate"))
        self.assertEqual(out.get("cacheError"), "revalidating")
        time.sleep(0.2)
        hit = server._cache.get(key)
        self.assertTrue(hit)
        self.assertEqual(hit[1]["points"][-1]["c"], 2.0)
        self.assertEqual(calls, [1])


class ChaosOutageTests(unittest.TestCase):
    """A transport failure must rescue disk — never become 'not bullish'."""

    def test_transient_raises_serve_disk_not_empty_verdict(self):
        key = "test:chaos:outage:v1"
        good = {
            "symbol": "CHAOS",
            "trend": {"label": "bullish", "score": 0.4},
            "points": [{"t": 1, "c": 10.0}, {"t": 2, "c": 11.0}],
        }
        diskcache.store(key, good)
        server._cache.pop(key, None)

        def produce():
            raise server.UpstreamError("forced outage")

        out = memo.cached(key, produce, ttl=1.0)
        self.assertTrue(out.get("cached"))
        self.assertEqual(out["trend"]["label"], "bullish")
        self.assertIn("cacheError", out)

    def test_cooling_yahoo_is_transient(self):
        self.assertTrue(memo.is_transient(moli_client.UpstreamError("Yahoo cooling")))


if __name__ == "__main__":
    unittest.main()