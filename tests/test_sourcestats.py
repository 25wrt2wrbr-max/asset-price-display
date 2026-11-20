"""sourcestats: the per-source tally behind /api/sources and status.html."""

import json
import os
import tempfile
import unittest
from unittest import mock

import sourcestats
import moli_client


class SourceStatsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="apd-srcstats-")
        self.env = mock.patch.dict(os.environ, {"APD_CACHE_DIR": self.dir})
        self.env.start()
        sourcestats.reset()

    def tearDown(self):
        sourcestats.reset()
        self.env.stop()

    def row(self, name, now=None):
        snap = sourcestats.snapshot(now=now)
        return next(r for r in snap["sources"] if r["source"] == name)

    def test_name_for_maps_hosts(self):
        self.assertEqual(sourcestats.name_for(
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"), "Yahoo Finance")
        self.assertEqual(sourcestats.name_for(
            "https://data-api.binance.vision/api/v3/klines"), "Binance")
        self.assertEqual(sourcestats.name_for("https://example.org/x"), "example.org")
        self.assertEqual(sourcestats.name_for("Moli browser"), "Moli browser")

    def test_known_sources_listed_before_use(self):
        row = self.row("Nasdaq")
        self.assertEqual(row["state"], "unused")
        self.assertEqual(row["month"]["calls"], 0)
        self.assertIsNone(row["month"]["failRate"])

    def test_timed_records_success_and_failure(self):
        with sourcestats.timed("https://api.nasdaq.com/a"):
            pass
        with self.assertRaises(ValueError):
            with sourcestats.timed("https://api.nasdaq.com/b"):
                raise ValueError("boom")
        row = self.row("Nasdaq")
        self.assertEqual(row["state"], "failing")
        self.assertEqual(row["today"]["calls"], 2)
        self.assertEqual(row["today"]["failed"], 1)
        self.assertEqual(row["today"]["failRate"], 0.5)
        self.assertIn("boom", row["lastError"])
        self.assertIsNotNone(row["month"]["avgSeconds"])

    def test_recovery_reads_ok(self):
        sourcestats.record("Binance", failed=1, error="down", now=1000.0)
        sourcestats.record("Binance", ok=1, now=1001.0)
        row = self.row("Binance", now=1002.0)
        self.assertEqual(row["state"], "ok")
        self.assertIsNone(row["lastError"] if row["lastFailAt"] is None else None)

    def test_days_survive_restart_and_old_days_drop(self):
        now = 1_800_000_000.0
        old = now - 40 * 86400
        sourcestats.record("CoinGecko", ok=1, seconds=0.5, now=old)
        sourcestats.record("CoinGecko", ok=2, failed=1, seconds=1.5, now=now)
        sourcestats.flush()
        with open(os.path.join(self.dir, sourcestats.FILE_NAME)) as handle:
            self.assertIn("CoinGecko", json.load(handle))
        sourcestats.reset()
        row = self.row("CoinGecko", now=now)
        self.assertEqual(row["month"]["calls"], 3)     # the 40-day-old call is outside
        self.assertEqual(row["month"]["failed"], 1)
        self.assertEqual(row["month"]["slowestSeconds"], 1.5)

    def test_recording_never_raises(self):
        with mock.patch.object(sourcestats, "_today", side_effect=RuntimeError("x")):
            sourcestats.record("Binance", ok=1)          # swallowed

    def test_yahoo_batch_counts_each_url(self):
        urls = ["https://query1.finance.yahoo.com/v8/finance/chart/%s" % s
                for s in ("A", "B", "C")]
        envelope = json.dumps({urls[0]: {"status": 200, "body": "{}"},
                               urls[1]: {"status": 404, "body": "{}"},
                               urls[2]: {"status": 429, "body": ""}})
        with mock.patch.object(moli_client, "_moli_run", return_value=envelope):
            moli_client.moli_batch_get(urls)
        row = self.row("Yahoo Finance")
        self.assertEqual(row["today"]["calls"], 3)       # a 404 is an answer
        self.assertEqual(row["today"]["failed"], 1)
        self.assertEqual(self.row("Moli browser")["today"]["calls"], 1)

    def test_browser_outage_blames_moli_not_yahoo(self):
        urls = ["https://query1.finance.yahoo.com/v8/finance/chart/A",
                "https://query1.finance.yahoo.com/v8/finance/chart/B"]
        with mock.patch.object(moli_client, "_moli_run",
                               side_effect=moli_client.UpstreamError("no browser")):
            with self.assertRaises(moli_client.UpstreamError):
                moli_client.moli_batch_get(urls)
        self.assertEqual(self.row("Yahoo Finance")["state"], "unused")
        self.assertEqual(self.row("Moli browser")["state"], "failing")

    def test_source_saying_no_is_an_answer(self):
        import crypto
        with self.assertRaises(crypto.CryptoError):
            with sourcestats.timed("https://data-api.binance.vision/x"):
                raise crypto.CryptoError("HTTP 400")
        with self.assertRaises(crypto.CryptoError):
            with sourcestats.timed("https://data-api.binance.vision/y"):
                raise crypto.CryptoError("HTTP 429")
        row = self.row("Binance")
        self.assertEqual((row["today"]["calls"], row["today"]["failed"]), (2, 1))

    def test_bad_file_is_kept_aside_and_bad_days_skipped(self):
        path = os.path.join(self.dir, sourcestats.FILE_NAME)
        with open(path, "w") as handle:
            json.dump({"Binance": {"last": {}, "days": {"2026-01-01": [1, 2]}}}, handle)
        self.assertEqual(self.row("Binance")["state"], "unused")   # no crash
        sourcestats.reset()
        with open(path, "w") as handle:
            handle.write("{not json")
        self.row("Binance")
        self.assertTrue(os.path.exists(path + ".bad"))

    def test_fallback_host_not_counted_as_yahoo(self):
        url = "https://api.coingecko.com/api/v3/coins"
        with mock.patch.object(moli_client, "_moli_run",
                               return_value=json.dumps({"status": 200, "body": "{}"})):
            moli_client.moli_get(url)
        self.assertEqual(self.row("Yahoo Finance")["state"], "unused")


if __name__ == "__main__":
    unittest.main()
