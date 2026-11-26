"""Tests for the 2026-11-23 reliability, coverage, chart, and macOS additions."""

import datetime as dt
import http.client
import json
import os
import threading
import time
import unittest
import urllib.error
from http.server import ThreadingHTTPServer
from unittest import mock

import server  # noqa: F401
import chart_route
import diskcache
import http_handler
import nasdaq_bars
import notify
import pse_edge
import recent
import sectors


class DiskcacheTempRaceTests(unittest.TestCase):
    def test_prune_keeps_fresh_tmp_and_deletes_stale_tmp(self):
        d = diskcache.dir()
        os.makedirs(d, exist_ok=True)
        fresh = os.path.join(d, "active.123.456.tmp")
        stale = os.path.join(d, "abandoned.123.456.tmp")
        with open(fresh, "w", encoding="utf-8") as fh:
            fh.write("{}")
        with open(stale, "w", encoding="utf-8") as fh:
            fh.write("{}")
        old = time.time() - (diskcache.TMP_MAX_AGE + 60)
        os.utime(stale, (old, old))
        try:
            diskcache.prune()
            self.assertTrue(os.path.exists(fresh))
            self.assertFalse(os.path.exists(stale))
        finally:
            if os.path.exists(fresh):
                os.unlink(fresh)


class SectorsCacheTests(unittest.TestCase):
    def setUp(self):
        self._orig = (sectors._payload, sectors._built_at, sectors._built_epoch)

    def tearDown(self):
        sectors._payload, sectors._built_at, sectors._built_epoch = self._orig

    def test_seed_hydrates_from_diskcache(self):
        saved = {"rows": [{"symbol": "PSE:PSEI", "name": "PSEi", "points": []}],
                 "errors": {}, "checkedAt": 1000, "pending": False}
        diskcache.store(sectors.CACHE_KEY, saved)
        sectors._payload = {"pending": True, "rows": [], "errors": {}}
        sectors.seed()
        self.assertEqual(len(sectors._payload["rows"]), 1)
        self.assertTrue(sectors._payload["cached"])
        self.assertFalse(sectors._payload["pending"])

    def test_preload_batch_uses_epoch_clock_for_memo_hit(self):
        fake_chart = {"symbol": "PSE:PSEI", "points": [{"t": 1, "c": 100.0}, {"t": 2, "c": 101.0}],
                      "trend": {"label": "neutral"}, "source": "TradingView"}
        with mock.patch("pse.charts_many", return_value={"PSE:PSEI": fake_chart}):
            sectors._preload_batch()
        key = server.chart_key("PSE:PSEI", "3mo", "1d")
        hit = server._cache.get(key)
        self.assertIsNotNone(hit)
        self.assertLess(abs(time.time() - hit[0]), 5.0)


class NasdaqFallbackAndBreakerTests(unittest.TestCase):
    def test_breaker_stops_after_consecutive_transport_failures(self):
        calls = 0

        def boom(_url):
            nonlocal calls
            calls += 1
            raise urllib.error.URLError("offline")

        tickers = [f"T{i:02d}" for i in range(25)]
        with mock.patch.object(nasdaq_bars, "fetch_json", side_effect=boom):
            out = nasdaq_bars.fetch(tickers)
        self.assertEqual(out, {})
        # Breaker aborts well before trying all 25 tickers.
        self.assertLess(calls, 15)

    def test_chart_route_uses_nasdaq_fallback_on_upstream_error(self):
        today = dt.date(2026, 11, 20)
        rows = []
        for i in range(90):
            day = today - dt.timedelta(days=120 - i)
            if day.weekday() < 5:
                rows.append({"date": day.strftime("%m/%d/%Y"),
                             "close": f"${100.0 + i * 0.5:.2f}",
                             "volume": "1,000,000"})
        rows.reverse()
        payload = {"data": {"tradesTable": {"rows": rows}}}
        with mock.patch.object(server, "yahoo_chart",
                               side_effect=server.UpstreamError("moli down")), \
             mock.patch.object(nasdaq_bars, "fetch_json", return_value=payload), \
             mock.patch.object(server, "cached", side_effect=lambda _k, fn, **_kw: fn()):
            out = chart_route.chart_data("AAPL", "3mo", "1d")
        self.assertEqual(out["source"], "Nasdaq")
        self.assertEqual(out["symbol"], "AAPL")
        self.assertTrue(len(out["points"]) >= 20)
        self.assertEqual(len(out["barVolumes"]), len(out["points"]))


class PseHaltsTests(unittest.TestCase):
    HTML = """
    <table><tbody>
      <tr><td>RCR</td><td>Halt</td><td>Nov 23, 2026</td><td>9:30 a.m.</td><td>Nov 23, 2026</td><td>10:30 a.m.</td><td>DN00184-2026</td></tr>
      <tr><td>BRNP</td><td>Suspension</td><td>Nov 4, 2026</td><td>9:00 AM</td><td>TBA</td><td>TBA</td><td>C07712-2026</td></tr>
      <tr><td>TECH, TCB2A</td><td>Suspension</td><td>Nov 1, 2026</td><td>9:00 AM</td><td>-</td><td>-</td><td>C07700-2026</td></tr>
      <tr><td>OLD</td><td>Halt</td><td>Oct 10, 2026</td><td>9:30 a.m.</td><td>Oct 10, 2026</td><td>10:30 a.m.</td><td>DN00100-2026</td></tr>
      <tr><td>BADDATE</td><td>Halt</td><td>Oct 10, 2026</td><td>9:30 a.m.</td><td>Sept 10, 2026</td><td>10:30 a.m.</td><td>DN00101-2026</td></tr>
    </tbody></table>
    """

    def test_parse_halts_page(self):
        got = pse_edge.parse_halts_page(self.HTML, today=dt.date(2026, 11, 23))
        self.assertIn("BRNP", got)
        self.assertTrue(got["BRNP"]["active"])
        self.assertEqual(got["BRNP"]["action"], "Suspension")
        self.assertIn("RCR", got)
        self.assertFalse(got["RCR"]["active"])
        self.assertTrue(got["RCR"]["sameDay"])
        self.assertIn("TECH", got)
        self.assertIn("TCB2A", got)
        self.assertNotIn("OLD", got)
        self.assertNotIn("BADDATE", got)

    def test_edge_history_many_breaker(self):
        calls = 0

        def fail(_sym):
            nonlocal calls
            calls += 1
            raise pse_edge.EdgeError("https://edge.pse.com.ph did not answer (timed out)")

        with mock.patch.object(pse_edge, "bars", side_effect=fail):
            out = pse_edge.history_many([f"PSE:S{i}" for i in range(20)])
        self.assertEqual(out, {})
        self.assertEqual(calls, pse_edge.BREAKER_LIMIT)


class HealthHistoryTests(unittest.TestCase):
    def test_records_daily_history_and_overwrites_same_day(self):
        h1 = [{"market": "US", "bullish": 10, "bearish": 5, "neutral": 85, "judged": 100}]
        h2 = [{"market": "US", "bullish": 15, "bearish": 5, "neutral": 80, "judged": 100}]
        recent.record_health_history(h1, today="2026-11-22")
        recent.record_health_history(h1, today="2026-11-23")
        hist = recent.record_health_history(h2, today="2026-11-23")
        self.assertEqual(len(hist["US"]), 2)
        self.assertEqual(hist["US"][0]["bullPct"], 10.0)
        self.assertEqual(hist["US"][1]["bullPct"], 15.0)


class NotifyAndRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), http_handler.Handler)
        cls.srv.daemon_threads = True
        cls.port = cls.srv.server_port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        data = r.read()
        ctype = r.getheader("Content-Type")
        c.close()
        return r.status, ctype, data

    def test_manifest_and_trend_js_served(self):
        st, ctype, raw = self._req("GET", "/static/manifest.webmanifest")
        self.assertEqual(st, 200)
        self.assertIn("application/manifest+json", ctype)
        doc = json.loads(raw)
        self.assertEqual(doc["display"], "standalone")

        st2, _ct2, raw2 = self._req("GET", "/export/trend.js")
        self.assertEqual(st2, 200)
        self.assertIn(b"classify", raw2)

    def test_alarms_sync_and_digest_routes(self):
        alarms_body = json.dumps([
            {"id": "a1", "symbol": "AAPL", "name": "Apple", "target": 250.0, "last": 240.0}
        ])
        st, _, raw = self._req("POST", "/api/alarms", alarms_body)
        self.assertEqual(st, 200)
        self.assertEqual(len(json.loads(raw)["alarms"]), 1)

        with mock.patch.object(notify, "send") as send:
            fired = notify.check_alarms("AAPL", 252.0, None, "USD")
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["fired"]["dir"], "up")
        send.assert_called_once()

        st2, _, raw2 = self._req("GET", "/api/digest")
        self.assertEqual(st2, 200)
        dig = json.loads(raw2)
        self.assertTrue(dig["ok"])
        self.assertEqual(len(dig["alarms"]["fired"]), 1)

        st3, ctype3, raw3 = self._req("GET", "/api/digest?format=text")
        self.assertEqual(st3, 200)
        self.assertIn("text/plain", ctype3)
        self.assertIn(b"AAPL", raw3)

    def test_observe_chart_notifies_only_on_flip(self):
        notify._watch_state = {}
        payload1 = {"symbol": "TESTSYM", "name": "Test Co", "points": [{"t": 1, "c": 100.0}],
                    "trend": {"label": "neutral"}}
        payload2 = {"symbol": "TESTSYM", "name": "Test Co", "points": [{"t": 2, "c": 110.0}],
                    "trend": {"label": "bullish"}}
        with mock.patch.object(notify, "send") as send:
            notify.observe_chart("TESTSYM", payload1, {"TESTSYM"})
            send.assert_not_called()
            notify.observe_chart("TESTSYM", payload2, {"TESTSYM"})
            send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
