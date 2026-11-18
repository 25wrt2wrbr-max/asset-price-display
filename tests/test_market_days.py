"""Exchange holidays, and the two sweep paces that read them."""

import datetime as dt
import json
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import market_days
import pse
import pse_outlook
import server
import us_bars

NY = ZoneInfo("America/New_York")
D = dt.date

# nyse.com/markets/hours-calendars, read 2026-11-18.
NYSE_PUBLISHED = {
    2026: {D(2026, 1, 1), D(2026, 1, 19), D(2026, 2, 16), D(2026, 4, 3),
           D(2026, 5, 25), D(2026, 6, 19), D(2026, 7, 3), D(2026, 9, 7),
           D(2026, 11, 26), D(2026, 12, 25)},
    2027: {D(2027, 1, 1), D(2027, 1, 18), D(2027, 2, 15), D(2027, 3, 26),
           D(2027, 5, 31), D(2027, 6, 18), D(2027, 7, 5), D(2027, 9, 6),
           D(2027, 11, 25), D(2027, 12, 24)},
    # New Year's Day 2028 is a Saturday and is not observed.
    2028: {D(2028, 1, 17), D(2028, 2, 21), D(2028, 4, 14), D(2028, 5, 29),
           D(2028, 6, 19), D(2028, 7, 4), D(2028, 9, 4), D(2028, 11, 23),
           D(2028, 12, 25)},
}

# A slice of what TradingView sent for PSE:PSEI on 2026-11-18.
PSE_LIST = ("20251231,20260101,20260217,20260320,20260402,20260403,20260409,"
            "20260501,20260527,20260612,20260821,20260831,20261102,20261130,"
            "20261208,20261224,20261225,20261230,20261231")


def ny(y, m, d, hour=12, minute=0):
    return dt.datetime(y, m, d, hour, minute, tzinfo=NY).timestamp()


def manila(y, m, d, hour, minute=0):
    return dt.datetime(y, m, d, hour, minute, tzinfo=pse_outlook.MANILA).timestamp()


class NyseRules(unittest.TestCase):
    def test_matches_the_published_calendar(self):
        for year, days in NYSE_PUBLISHED.items():
            self.assertEqual(set(market_days.nyse_holidays(year)), days, year)

    def test_new_year_on_saturday_keeps_friday_open(self):
        self.assertTrue(market_days.nyse_open_day(D(2027, 12, 31)))
        self.assertFalse(market_days.nyse_open_day(D(2028, 1, 1)))   # Saturday

    def test_ordinary_days(self):
        self.assertTrue(market_days.nyse_open_day(D(2026, 11, 27)))  # early close
        self.assertFalse(market_days.nyse_open_day(D(2026, 11, 21)))  # Saturday


class NyseClosedStretch(unittest.TestCase):
    def test_holiday_is_closed_since_the_day_before(self):
        wed_close = ny(2026, 11, 25, 20, 0)
        self.assertEqual(us_bars.closed_since(ny(2026, 11, 26, 4, 0)), wed_close)
        self.assertEqual(us_bars.closed_since(ny(2026, 11, 26, 12, 0)), wed_close)
        self.assertEqual(us_bars.closed_since(ny(2026, 11, 26, 22, 0)), wed_close)
        self.assertIsNone(us_bars.closed_since(ny(2026, 11, 27, 12, 0)))

    def test_monday_holiday_reaches_back_to_friday(self):
        fri_close = ny(2027, 1, 15, 20, 0)
        self.assertEqual(us_bars.closed_since(ny(2027, 1, 18, 12, 0)), fri_close)
        self.assertEqual(us_bars.closed_since(ny(2027, 1, 19, 3, 0)), fri_close)
        self.assertIsNone(us_bars.closed_since(ny(2027, 1, 19, 4, 0)))

    def test_good_friday_weekend(self):
        thu_close = ny(2026, 4, 2, 20, 0)
        self.assertEqual(us_bars.closed_since(ny(2026, 4, 4, 12, 0)), thu_close)

    def test_settled_name_waits_through_a_holiday(self):
        record = {"tz": "America/New_York", "readAt": ny(2026, 11, 26, 9, 0)}
        self.assertTrue(us_bars.settled(record, "AAPL", ny(2026, 11, 26, 9, 30)))
        self.assertFalse(us_bars.settled(record, "ZB=F", ny(2026, 11, 26, 9, 30)))


def forget_pse():
    """No list in memory or on disk (the record is a plain, never-aged one)."""
    market_days.diskcache.store_plain(market_days.PSE_KEY, "")
    market_days.reset()


class PseList(unittest.TestCase):
    def setUp(self):
        forget_pse()
        self.addCleanup(forget_pse)

    def test_parse_skips_junk(self):
        days = market_days.parse_holidays("20261225, 2026122,abcdefgh,20261340,,20261230")
        self.assertEqual(days, {D(2026, 12, 25), D(2026, 12, 30)})

    def test_empty_list_does_not_wipe_a_good_one(self):
        market_days.remember_pse(PSE_LIST)
        market_days.remember_pse("")
        market_days.remember_pse(None)
        self.assertTrue(market_days.pse_holiday(D(2026, 12, 8)))

    def test_list_survives_a_restart(self):
        market_days.remember_pse(PSE_LIST)
        market_days.reset()
        self.assertTrue(market_days.pse_holiday(D(2026, 11, 30)))
        self.assertTrue(market_days.pse_open_day(D(2026, 11, 27)))

    def test_unknown_days_read_open(self):
        self.assertTrue(market_days.pse_open_day(D(2027, 12, 30)))

    def test_batch_socket_hands_the_list_over(self):
        envelope = {"kind": "ok", "bars": {"PSE:TEL": [[1, 1, 1, 1, 1, 1]]},
                    "meta": {"PSE:TEL": {}}, "holidays": PSE_LIST}
        with mock.patch.object(pse, "_run_batch", return_value=json.dumps(envelope)):
            bars, meta = pse._fetch_chunk_raw(["PSE:TEL"], "1D", 5)
        self.assertIn("PSE:TEL", bars)
        self.assertTrue(market_days.pse_holiday(D(2026, 12, 24)))

    def test_bond_run_does_not_speak_for_the_exchange(self):
        envelope = {"kind": "ok", "bars": [[1, 1, 1, 1, 1]], "meta": {},
                    "holidays": PSE_LIST}
        with mock.patch.object(pse, "_run", return_value=json.dumps(envelope)):
            pse._history("TVC:PH10Y", "1D", 5)
        self.assertFalse(market_days.pse_holiday(D(2026, 12, 24)))
        with mock.patch.object(pse, "_run", return_value=json.dumps(envelope)):
            pse._history("PSE:TEL", "1D", 5)
        self.assertTrue(market_days.pse_holiday(D(2026, 12, 24)))


class PsePace(unittest.TestCase):
    def setUp(self):
        forget_pse()
        self.addCleanup(forget_pse)
        market_days.remember_pse(PSE_LIST)

    def test_holiday_session_hours_take_the_closed_pace(self):
        self.assertEqual(server.bullish_pause(manila(2026, 12, 8, 11, 0)),
                         server.BULL_CLOSED_TTL)

    def test_ordinary_session_keeps_the_normal_pace(self):
        self.assertEqual(server.bullish_pause(manila(2026, 12, 9, 11, 0)),
                         server.BULL_TTL)

    def test_next_bell_skips_the_holiday(self):
        # 09:00 on Christmas Eve: without the list the wait would end at the
        # 09:30 bell; the exchange is shut, so the hourly cap applies.
        self.assertEqual(server.bullish_pause(manila(2026, 12, 24, 9, 0)),
                         server.BULL_CLOSED_TTL)
        # 09:00 on an ordinary Wednesday: the wait still ends at the bell.
        self.assertEqual(server.bullish_pause(manila(2026, 12, 9, 9, 0)), 1800)

    def test_without_a_list_a_holiday_reads_open(self):
        forget_pse()
        self.assertEqual(server.bullish_pause(manila(2026, 12, 8, 11, 0)),
                         server.BULL_TTL)


if __name__ == "__main__":
    unittest.main()
