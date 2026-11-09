"""The table prints the window's move, not some other window's (2026-11-07).

Asked for by name: "i also want the three-month move printed on each row like
+8.4%".

The figure has to be the chart's own, or a row and the chart its click opens
would disagree about how the window went. `onset.onset` already computes the
window it scores; it now also returns that window's first close
(`windowFirst`), beside the newest close it has always returned as `price`. The
pair is the same one the chart's hero delta prints ("+12.95% three-month move,
since Jul 31").

It is shipped as two prices rather than as a move because the unit differs: a
stock or a fund moves in per cent, a bond **yield** moves in percentage points.
A yield's row gets no move at all — the level is the figure and the direction
column carries the call — so `bond_rows` ships `windowMove: None` and the page
prints a dash. That was asked for by name: "for bonds, the most important thing
is yield. changes don't mean shit. + the bearish or bullish judgment".
"""

import time
import unittest
from unittest import mock

import onset
import recent


def _series(days=140, start=100.0, step=0.5, end=None):
    """A daily series whose newest bar is an hour old."""
    end = time.time() - 3600 if end is None else end
    stamps = [int(end - (days - 1 - i) * 86_400) for i in range(days)]
    closes = [round(start + i * step, 6) for i in range(days)]
    return stamps, closes, [1_000_000.0] * days


class OnsetWindowFirstTests(unittest.TestCase):
    def test_the_first_close_is_the_window_the_badge_scored(self):
        stamps, closes, volumes = _series()
        call = onset.onset(stamps, closes, volumes, want="bullish")
        self.assertIsNotNone(call)
        used = onset.window_now(stamps, len(closes) - 1)
        self.assertEqual(call["window"], len(used))
        self.assertEqual(call["windowFirst"], closes[used[0]])
        self.assertEqual(call["price"], closes[-1])
        # The pair really is the drawn window's move.
        self.assertAlmostEqual(call["price"] / call["windowFirst"] - 1,
                               closes[-1] / closes[used[0]] - 1, places=12)

    def test_a_calendar_month_window_ships_its_own_first_close(self):
        stamps, closes, volumes = _series()
        call = onset.onset(stamps, closes, volumes, want="bullish", months=3)
        self.assertIsNotNone(call)
        used = onset.window_now(stamps, len(closes) - 1, months=3)
        self.assertEqual(call["windowFirst"], closes[used[0]])


class PriceRowMoveTests(unittest.TestCase):
    def test_a_price_row_carries_the_relative_move(self):
        stamps, closes, volumes = _series(start=100.0, step=0.5)
        call = onset.onset(stamps, closes, volumes, want="bullish")
        row = recent._price_row("Crypto", "X-USD", "X-USD", "XUSDT", "X",
                                "Coin", "USD", call)
        self.assertAlmostEqual(row["windowMove"],
                               round(closes[-1] / call["windowFirst"] - 1, 6),
                               places=6)
        self.assertGreater(row["windowMove"], 0)

    def test_a_row_with_no_window_ships_no_move(self):
        row = recent._price_row("Crypto", "X-USD", "X-USD", "XUSDT", "X",
                                "Coin", "USD",
                                {"price": 10.0, "since": 1, "run": 1,
                                 "censored": False, "manner": None,
                                 "turnMove": None, "score": 0.3, "bars": 63,
                                 "last": 2, "turnover": None})
        self.assertIsNone(row["windowMove"])


class BondRowTests(unittest.TestCase):
    def test_a_yield_row_carries_no_window_move(self):
        # Asked for by name: "for bonds, the most important thing is yield.
        # changes don't mean shit. + the bearish or bullish judgment". The yield
        # is the row's price and the bond-price call is its direction; a move
        # between them would be a figure about a figure.
        stamps, closes, volumes = _series(days=150, start=6.5, step=-0.004)
        bars = [{"t": t, "c": c} for t, c in zip(stamps, closes)]

        with mock.patch.object(recent, "_cached_bonds",
                               side_effect=lambda symbol: (bars, 0.0)), \
             mock.patch.object(recent, "BONDS",
                               [("TVC:PH10Y", "10-year")]):
            rows, stats = recent.bond_rows()

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["currency"], "%")
        self.assertIsNone(row["windowMove"])
        # The level is still the row's price, and the revision is still its own.
        self.assertEqual(row["price"], closes[-1])
        self.assertEqual(row["direction"], "bullish")
        self.assertEqual(row["note"], "yield falling")


class SweepRowMoveTests(unittest.TestCase):
    def test_a_philippine_row_carries_the_sweeps_own_window(self):
        rows = recent.ph_rows([{
            "symbol": "PSE:TEL", "chartSymbol": "PSE:TEL", "ticker": "TEL",
            "name": "PLDT", "kind": "Common stock", "price": 1400.0,
            "currency": "PHP", "since": 1_790_000_000, "run": 5,
            "censored": False, "manner": "turn", "turnMove": 0.04,
            "score": 0.5, "bars": 63, "last": 1_790_100_000,
            "turnover": 2_000_000.0, "windowFirst": 1300.0,
        }])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["windowMove"], round(1400.0 / 1300.0 - 1, 6))


if __name__ == "__main__":
    unittest.main()
