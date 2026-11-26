"""The row warmer re-reads a row hourly while its market is shut (2026-11-24)."""

import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import server
import warm

NY = ZoneInfo("America/New_York")
MANILA = ZoneInfo("Asia/Manila")


def at(y, m, d, h, mi, zone):
    return dt.datetime(y, m, d, h, mi, tzinfo=zone).timestamp()


SATURDAY = at(2026, 11, 28, 12, 0, NY)


class ClosedPaceTests(unittest.TestCase):
    def test_us_share_saved_after_the_close_waits_an_hour(self):
        saved = at(2026, 11, 27, 21, 0, NY)   # Friday, after 20:00 + settle
        self.assertEqual(warm.row_stale_after("AAPL", saved, SATURDAY),
                         server.ROW_CLOSED_STALE_AFTER)
        self.assertEqual(warm.row_stale_after("BRK-B", saved, SATURDAY),
                         server.ROW_CLOSED_STALE_AFTER)

    def test_us_copy_from_before_the_close_is_due_at_the_normal_pace(self):
        saved = at(2026, 11, 27, 15, 0, NY)   # Friday, mid-session
        self.assertEqual(warm.row_stale_after("AAPL", saved, SATURDAY),
                         server.ROW_STALE_AFTER)

    def test_us_open_hours_keep_the_normal_pace(self):
        now = at(2026, 11, 24, 11, 0, NY)
        self.assertEqual(warm.row_stale_after("AAPL", now - 600, now),
                         server.ROW_STALE_AFTER)

    def test_pse_night_and_midday(self):
        night = at(2026, 11, 24, 22, 0, MANILA)
        self.assertEqual(warm.row_stale_after("PSE:TEL", at(2026, 11, 24, 16, 0, MANILA), night),
                         server.ROW_CLOSED_STALE_AFTER)
        # Saved before the close settled: due at the normal pace.
        self.assertEqual(warm.row_stale_after("PSE:TEL", at(2026, 11, 24, 15, 0, MANILA), night),
                         server.ROW_STALE_AFTER)
        noon = at(2026, 11, 24, 11, 30, MANILA)
        self.assertEqual(warm.row_stale_after("PSE:TEL", noon - 600, noon),
                         server.ROW_STALE_AFTER)

    def test_other_markets_are_never_paced(self):
        for sym in ("BTC-USD", "PAXG-USD", "ZB=F", "USDPHP=X", "FUND:BPI-MM", "TVC:PH10Y", "^GSPC", None):
            self.assertEqual(warm.row_stale_after(sym, SATURDAY - 100, SATURDAY),
                             server.ROW_STALE_AFTER, sym)

    def test_row_fresh_uses_the_symbol_pace(self):
        server._warm_due.clear()
        saved = at(2026, 11, 27, 21, 0, NY)
        now = saved + 1800                    # 30 min later, still closed
        with mock.patch.object(warm.diskcache, "load", return_value=(saved, {})):
            self.assertTrue(warm.row_fresh("k-aapl", now, "AAPL"))
            self.assertFalse(warm.row_fresh("k-btc", now, "BTC-USD"))
        server._warm_due.clear()


if __name__ == "__main__":
    unittest.main()
