import http.client
import hashlib
import json
import os
import re
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import diskcache
import recent
import server
import us_bars

BARS = ([1, 2, 3], [10.0, 11.0, 12.0], [5, 5, 5])


class FetchUsBarsFallbackTests(unittest.TestCase):
    def setUp(self):
        us_bars.reset()     # no stored year, and no read of the disk copy

    def test_a_moli_outage_falls_back_to_nasdaq(self):
        meta = {"name": "", "kind": "", "currency": "USD", "fallback": "Nasdaq"}
        with mock.patch.object(server, "moli_batch_get", side_effect=server.UpstreamError("moli down")), \
                mock.patch.object(server.nasdaq_bars, "fetch", return_value={"AAPL": BARS + (meta,)}) as second:
            out = server.fetch_us_bars(["AAPL", "MSFT"])
        second.assert_called_once_with(["AAPL", "MSFT"])
        self.assertEqual(list(out), ["AAPL"])

    def test_yahoo_saying_no_such_instrument_is_not_second_guessed(self):
        def answer(urls):
            return {u: (404, "{}") for u in urls}
        with mock.patch.object(server, "moli_batch_get", side_effect=answer), \
                mock.patch.object(server.nasdaq_bars, "fetch") as second:
            out = server.fetch_us_bars(["NOPE"])
        second.assert_not_called()
        self.assertEqual(out, {})

    def test_a_failing_fallback_leaves_the_tickers_missing(self):
        with mock.patch.object(server, "moli_batch_get", side_effect=server.UpstreamError("down")), \
                mock.patch.object(server.nasdaq_bars, "fetch", side_effect=RuntimeError("also down")):
            self.assertEqual(server.fetch_us_bars(["AAPL"]), {})


class MarketStatusTests(unittest.TestCase):
    def test_states(self):
        stats = {
            "US": {"universe": 10, "missing": [], "fallback": []},
            "Crypto": {"universe": 10, "missing": ["A", "B"]},
            "Philippine fund": {"universe": 3, "missing": ["X", "Y", "Z"]},
            "US Treasury": {"universe": 7, "missing": [], "fallback": ["ZB=F"]},
        }
        errors = {"Philippine bond": "socket closed"}
        rows = [{"market": "US", "last": 100}, {"market": "US", "last": 300}]
        out = {m["market"]: m for m in recent.market_status(stats, errors, rows)}
        self.assertEqual(out["US"]["state"], "live")
        self.assertEqual(out["US"]["asOf"], 300)
        self.assertEqual(out["Crypto"]["state"], "partial")
        self.assertEqual(out["Philippine fund"]["state"], "offline")
        self.assertEqual(out["US Treasury"]["state"], "fallback")
        self.assertEqual(out["Philippine bond"]["state"], "offline")
        self.assertEqual(out["Philippine bond"]["detail"], "socket closed")

    def test_summary_names_the_fallback(self):
        note = recent.summarize({"rows": [], "stats": {"US": {"universe": 4, "fallback": ["A", "B"]}}})
        self.assertIn("2 read from Nasdaq closes", note)


class DiskcacheByteCapTests(unittest.TestCase):
    def test_oldest_files_go_first_when_over_the_byte_cap(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"APD_CACHE_DIR": tmp}), \
                mock.patch.object(diskcache, "MAX_BYTES", 2500):
            for age, name in ((300, "a"), (200, "b"), (100, "c")):
                path = os.path.join(tmp, name + ".json")
                with open(path, "w") as f:
                    f.write("x" * 1000)
                stamp = os.stat(path).st_mtime - age
                os.utime(path, (stamp, stamp))
            diskcache.prune()
            self.assertEqual(sorted(os.listdir(tmp)), ["b.json", "c.json"])


class StaticAllowlistTests(unittest.TestCase):
    def get(self, path, *, content=False, headers=None):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
            conn.request("GET", path, headers=headers or {})
            response = conn.getresponse()
            body = response.read()
            if content:
                return response.status, response.headers, body
            return response.status
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join()

    def test_page_and_assets_are_served(self):
        for path in ("/", "/index.html", "/static/app.css", "/static/core.js"):
            self.assertEqual(self.get(path), 200, path)

    def test_previous_copy_cannot_revalidate_into_a_mixed_page(self):
        code, headers, html = self.get("/", content=True, headers={
            "If-Modified-Since": "Fri, 01 Jan 2100 00:00:00 GMT"})
        self.assertEqual((code, headers['Cache-Control']), (200, 'no-store'))
        assets = re.findall(r'(?:src|href)="(static/[^" ]+)"', html.decode())
        self.assertTrue(any('chart.js?' in url for url in assets))
        for url in assets:
            path, version = url.split('?v=')
            with open(path, 'rb') as f:
                self.assertEqual(version, hashlib.sha256(f.read()).hexdigest()[:16])
        chart = next(url for url in assets if 'chart.js?' in url)
        self.assertIn(b'function drawTrend()', self.get('/' + chart, content=True)[2])

    def test_source_cache_and_listings_are_not(self):
        for path in ("/server.py", "/.cache/x.json", "/static/", "/static", "/README.md", "/tests/test_quality.py"):
            self.assertEqual(self.get(path), 404, path)


class WatchlistAndWarmTests(unittest.TestCase):
    def test_record_watchlist_replaces_instead_of_appending(self):
        server.record_watchlist(["AAPL", "MSFT"])
        self.assertEqual(server.union_watchlist(), ["AAPL", "MSFT"])
        server.record_watchlist(["MSFT"])
        self.assertEqual(server.union_watchlist(), ["MSFT"])
        server.record_watchlist([])
        self.assertEqual(server.union_watchlist(), [])

    def test_due_rows_includes_leaning_and_watch_rows(self):
        server._warm_due.clear()
        bull = {"rows": [{"chartSymbol": "PSE:TEL"}], "leaning": [{"chartSymbol": "PSE:BDO"}]}
        rec = {"rows": [{"chartSymbol": "AAPL"}], "bearish": [{"chartSymbol": "NVDA"}], "leaning": [{"chartSymbol": "MSFT"}]}
        queue = server.due_rows(bull, ["BTC-USD"], 1000.0, rec)
        self.assertEqual([sym for _key, sym in queue], ["BTC-USD", "PSE:TEL", "PSE:BDO", "AAPL", "NVDA", "MSFT"])


if __name__ == "__main__":
    unittest.main()
