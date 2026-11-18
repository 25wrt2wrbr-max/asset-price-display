import datetime as dt
import unittest
import urllib.error
from unittest import mock

import nasdaq_bars

PAYLOAD = {"data": {"tradesTable": {"rows": [
    {"date": "11/13/2026", "close": "$356.27", "volume": "40,027,470"},
    {"date": "11/12/2026", "close": "$354.88", "volume": "31,874,980"},
    {"date": "bad", "close": "$1.00", "volume": "1"},
    {"date": "11/11/2026", "close": "N/A", "volume": "5"},
]}}}


class ParseTests(unittest.TestCase):
    def test_rows_become_ascending_bars_and_junk_is_dropped(self):
        rows = nasdaq_bars.parse_rows(PAYLOAD)
        self.assertEqual([r[1] for r in rows], [354.88, 356.27])
        self.assertEqual(rows[1][2], 40_027_470.0)
        self.assertLess(rows[0][0], rows[1][0])
        day = dt.datetime.fromtimestamp(rows[1][0], dt.timezone.utc)
        self.assertEqual(day.date(), dt.date(2026, 11, 13))

    def test_empty_or_odd_payloads(self):
        self.assertEqual(nasdaq_bars.parse_rows({}), [])
        self.assertEqual(nasdaq_bars.parse_rows({"data": {"tradesTable": {"rows": None}}}), [])


class HistoryTests(unittest.TestCase):
    def test_etf_is_tried_after_an_empty_stock_answer(self):
        empty = {"data": {"tradesTable": {"rows": None}}}
        with mock.patch.object(nasdaq_bars, "fetch_json", side_effect=[empty, PAYLOAD]) as get:
            out = nasdaq_bars.history("SPY", dt.date(2026, 11, 16))
        self.assertEqual(len(out[0]), 2)
        self.assertIn("assetclass=stocks", get.call_args_list[0].args[0])
        self.assertIn("assetclass=etf", get.call_args_list[1].args[0])

    def test_transport_failure_is_none_not_an_empty_series(self):
        with mock.patch.object(nasdaq_bars, "fetch_json", side_effect=urllib.error.URLError("down")) as get:
            self.assertIsNone(nasdaq_bars.history("AAPL"))
        self.assertEqual(get.call_count, 1)        # did not go on to try another class

    def test_only_plain_us_tickers_are_asked(self):
        with mock.patch.object(nasdaq_bars, "fetch_json") as get:
            for odd in ("ZB=F", "USDPHP=X", "^GSPC", "BTC-USD", "toolongsymbol"):
                self.assertIsNone(nasdaq_bars.history(odd))
        get.assert_not_called()

    def test_class_share_dash_becomes_the_dot_spelling(self):
        with mock.patch.object(nasdaq_bars, "fetch_json", return_value=PAYLOAD) as get:
            nasdaq_bars.history("BRK-B", dt.date(2026, 11, 16))
        self.assertIn("/BRK.B/", get.call_args.args[0])

    def test_fetch_marks_the_source_and_leaves_failures_out(self):
        def fake(url):
            if "/AAPL/" in url:
                return PAYLOAD
            raise urllib.error.URLError("down")
        with mock.patch.object(nasdaq_bars, "fetch_json", side_effect=fake):
            out = nasdaq_bars.fetch(["AAPL", "MSFT"])
        self.assertEqual(list(out), ["AAPL"])
        stamps, closes, volumes, meta = out["AAPL"]
        self.assertEqual(len(stamps), len(closes))
        self.assertEqual(meta["fallback"], "Nasdaq")


if __name__ == "__main__":
    unittest.main()
