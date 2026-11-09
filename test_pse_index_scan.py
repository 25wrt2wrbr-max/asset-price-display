"""The PSEi is scanned with the stocks, and the notes say how many were scanned.

Two requests from the reader, 2026-11-09:

* "i think you should still include PSEi in the appropriate sections if it is
  currently bullish or leaning bullish";
* "add this '249 common shares, 11 preferred shares, 1 ETF, 1 closed-end fund'
  scanned in philippines in the small text note in both sections ... the user
  has no way of knowing if you really scanned many philippines stocks and not
  just 10".

The index used to be dropped from `bullish._universe`, so its own chart could
never put it on either table however it trended. It is scanned now, through the
same walk as the stocks -- the only way a row and the chart it opens can agree
(invariant 1).

What these tests pin:

* the scan's universe includes the index, and `kinds` counts it;
* an index row carries no board lot and no traded value, whatever its price --
  it is not bought in board lots and has no shares to trade;
* an index that leans gets a leaning row under the same rule;
* the note under each table names the makeup of the scan, in a fixed order,
  and says nothing invented when the sweep's account of its universe is absent.

No browser and no network: the scanner and the socket are mocked.
"""

import time
import unittest
from unittest import mock

import bullish
import recent

INDEX = {"symbol": "PSE:PSEI", "ticker": "PSEI", "name": "PSEi Index",
         "kind": "INDEX", "cap": None}
STOCK = {"symbol": "PSE:TEL", "ticker": "TEL", "name": "PLDT Inc.",
         "kind": "EQUITY", "cap": 1.0}

KINDS = {"EQUITY": 249, "PREFERRED": 11, "ETF": 1, "CLOSEDEND": 1, "INDEX": 1}
UNIVERSE = 263


def series(n=270, start=100.0, step=1.004, volume=None, now=None):
    """Bars in the socket's shape: [stamp, open, high, low, close(, volume)].

    An index row from the socket carries five columns -- there is no volume to
    report -- which is exactly why the scan must not read one.
    """
    now = int(time.time()) if now is None else now
    rows = []
    close = start
    for i in range(n):
        close *= step
        row = [now - (n - 1 - i) * 86400, close, close, close, close]
        if volume is not None:
            row.append(volume)
        rows.append(row)
    return rows


def scan_payload():
    index = {"ordered": [INDEX, STOCK],
             "by_symbol": {INDEX["symbol"]: INDEX, STOCK["symbol"]: STOCK}}
    bars = {"PSE:PSEI": series(volume=None),
            "PSE:TEL": series(volume=10_000)}
    with mock.patch.object(bullish.pse, "stocks_index", return_value=index), \
         mock.patch.object(bullish.pse, "history_many", return_value=bars):
        return bullish.scan()


class IndexScanTests(unittest.TestCase):

    def test_the_index_is_in_the_universe_and_counted(self):
        payload = scan_payload()
        self.assertEqual(payload["universe"], 2)
        self.assertEqual(payload["kinds"], {"INDEX": 1, "EQUITY": 1})

    def test_a_bullish_index_is_a_row_like_any_other(self):
        payload = scan_payload()
        tickers = [row["ticker"] for row in payload["rows"]]
        self.assertIn("PSEI", tickers)
        row = next(r for r in payload["rows"] if r["ticker"] == "PSEI")
        self.assertEqual(row["kind"], "INDEX")
        self.assertEqual(row["chartSymbol"], "PSE:PSEI")
        self.assertGreater(row["run"], 0)

    def test_an_index_row_has_no_board_lot_and_no_traded_value(self):
        # The price is a level, not a quote: 100 board lots of it is a cheque
        # the exchange does not sell, and a level times no shares is not cash.
        payload = scan_payload()
        row = next(r for r in payload["rows"] if r["ticker"] == "PSEI")
        self.assertIsNone(row["lot"])
        self.assertIsNone(row["lotCost"])
        self.assertIsNone(row["turnover"])

    def test_a_stock_still_carries_its_board_lot(self):
        payload = scan_payload()
        row = next(r for r in payload["rows"] if r["ticker"] == "TEL")
        self.assertIsNotNone(row["lot"])
        self.assertGreater(row["lotCost"], 0)
        self.assertGreater(row["turnover"], 0)

    def test_a_leaning_index_is_a_leaning_row_without_a_lot(self):
        lean = {"price": 5771.58, "score": 0.2, "significance": 1.3,
                "progress": 0.8, "bars": 63, "last": int(time.time()),
                "turnover": 0.0, "window": [100.0, 101.0],
                "held": 4, "holdBars": 5}
        index = {"ordered": [INDEX],
                 "by_symbol": {INDEX["symbol"]: INDEX}}
        bars = {"PSE:PSEI": series(volume=None)}
        with mock.patch.object(bullish.pse, "stocks_index", return_value=index), \
             mock.patch.object(bullish.pse, "history_many", return_value=bars), \
             mock.patch.object(bullish, "onset", return_value=None), \
             mock.patch.object(bullish.onset_module, "steady_lean",
                               return_value=lean):
            payload = bullish.scan()
        self.assertEqual(payload["rows"], [])
        row = payload["leaning"][0]
        self.assertEqual(row["ticker"], "PSEI")
        self.assertIsNone(row["lot"])
        self.assertIsNone(row["lotCost"])
        self.assertIsNone(row["turnover"])


class KindNoteTests(unittest.TestCase):
    """The note spells out what was scanned, so the reader can check the sweep."""

    def test_the_breakdown_reads_in_a_fixed_order(self):
        self.assertEqual(
            recent.kinds_line(KINDS),
            "249 common shares, 11 preferred shares, 1 ETF, "
            "1 closed-end fund, 1 index")

    def test_singulars_and_plurals(self):
        self.assertEqual(recent.kinds_line({"EQUITY": 1, "ETF": 2}),
                         "1 common share, 2 ETFs")

    def test_a_kind_outside_the_vocabulary_is_still_counted(self):
        # A figure whose job is honesty about coverage must not lose a listing
        # just because it has no name here.
        self.assertEqual(recent.kinds_line({"EQUITY": 3, "WARRANT": 2}),
                         "3 common shares, 2 other listings")

    def test_no_universe_says_nothing(self):
        self.assertIsNone(recent.ph_scan_line({}))

    def test_the_scan_line_names_the_count_and_the_makeup(self):
        self.assertEqual(
            recent.ph_scan_line({"universe": UNIVERSE, "kinds": KINDS}),
            "Philippines: 263 scanned (249 common shares, 11 preferred shares, "
            "1 ETF, 1 closed-end fund, 1 index)")


class NoteTests(unittest.TestCase):
    """Both notes print the same sentence about the same scan."""

    def scan(self):
        rows = [{"symbol": "PSE:TEL", "chartSymbol": "PSE:TEL",
                 "ticker": "TEL", "name": "PLDT Inc.", "kind": "EQUITY",
                 "price": 1118.0, "currency": "PHP", "since": 5, "run": 3,
                 "turnover": 10_000_000.0}]
        with mock.patch.object(recent, "us_rows", return_value=([], {})), \
             mock.patch.object(recent, "rate_rows", return_value=([], {})), \
             mock.patch.object(recent, "ondo_portfolio_rows",
                               return_value=([], {})), \
             mock.patch.object(recent, "crypto_rows", return_value=([], {})), \
             mock.patch.object(recent, "bond_rows", return_value=([], {})), \
             mock.patch.object(recent, "fund_rows", return_value=([], {})), \
             mock.patch.object(recent.markets, "php_per_usd",
                               return_value={"phpPerUsd": 63.0}):
            return recent.scan(rows, fetch_us_bars=lambda symbols: {},
                               ph_sweep_stats={"universe": UNIVERSE,
                                               "kinds": KINDS, "missing": []})

    def test_the_note_under_recently_bullish_says_what_was_scanned(self):
        payload = self.scan()
        note = recent.summarize(payload)
        self.assertIn("Philippines: 263 scanned (249 common shares, "
                      "11 preferred shares, 1 ETF, 1 closed-end fund, "
                      "1 index), 1 bullish", note)

    def test_the_payload_carries_the_same_sentence_for_the_other_table(self):
        payload = self.scan()
        self.assertEqual(payload["phScan"],
                         "Philippines: 263 scanned (249 common shares, "
                         "11 preferred shares, 1 ETF, 1 closed-end fund, "
                         "1 index)")

    def test_the_hidden_count_still_prints(self):
        rows = [{"symbol": "PSE:PAL", "chartSymbol": "PSE:PAL",
                 "ticker": "PAL", "name": "PAL Holdings", "kind": "EQUITY",
                 "price": 2.0, "currency": "PHP", "since": 5, "run": 3,
                 "turnover": 311_040.0}]
        with mock.patch.object(recent, "us_rows", return_value=([], {})), \
             mock.patch.object(recent, "rate_rows", return_value=([], {})), \
             mock.patch.object(recent, "ondo_portfolio_rows",
                               return_value=([], {})), \
             mock.patch.object(recent, "crypto_rows", return_value=([], {})), \
             mock.patch.object(recent, "bond_rows", return_value=([], {})), \
             mock.patch.object(recent, "fund_rows", return_value=([], {})), \
             mock.patch.object(recent.markets, "php_per_usd",
                               return_value={"phpPerUsd": 63.0}):
            payload = recent.scan(rows, fetch_us_bars=lambda symbols: {},
                                  ph_sweep_stats={"universe": UNIVERSE,
                                                  "kinds": KINDS})
        note = recent.summarize(payload)
        self.assertIn("1 below ₱1,000,000 volume hidden", note)


if __name__ == "__main__":
    unittest.main()
