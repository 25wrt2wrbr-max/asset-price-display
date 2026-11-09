"""The newest point is the session trading now, not yesterday's close.

Measured 2026-11-03 at 04:15 New York: AAPL had printed 322.13 in pre-market
against a Monday close of 338.32. The chart ended at 338.32 labelled "close"
and stayed there until 09:30, because Yahoo ships no daily bar for the session
until it opens -- while its own `fulldayPrice` already carried the pre-market
print, and `full_day_close` rightly refused to date that Tuesday price to
Monday's bar.

These tests pin the answer: the print becomes a point of its own, stamped where
the day's real bar will land, drawn only while a window of that session is
open, worded by the clock, and never carried out of a disk copy.
"""

import datetime
import unittest
from unittest import mock

import server
import trend

ZONE = datetime.timezone.utc


def stamp(*args):
    """Epoch seconds for a UTC wall clock."""
    return int(datetime.datetime(*args, tzinfo=ZONE).timestamp())


# The fixture's sessions: Monday's bar, Tuesday's clock. All in UTC.
NOV2_OPEN = stamp(2026, 11, 2, 14, 30)     # Monday 09:30 New York
NOV2_CLOSE = stamp(2026, 11, 2, 21, 0)     # Monday 16:00 New York
NOV3_PRE = stamp(2026, 11, 3, 9, 0)        # Tuesday 04:00 New York
NOV3_OPEN = stamp(2026, 11, 3, 14, 30)     # Tuesday 09:30 New York
NOV3_CLOSE = stamp(2026, 11, 3, 21, 0)     # Tuesday 16:00 New York
NOV3_POST_END = stamp(2026, 11, 4, 1, 0)   # Tuesday 20:00 New York

PRE_MARKET = stamp(2026, 11, 3, 9, 15)     # 04:15 New York, pre-market open
AFTER_HOURS = stamp(2026, 11, 3, 22, 0)    # 17:00 New York, post open
REGULAR = stamp(2026, 11, 3, 15, 0)        # 10:00 New York, session trading
OVERNIGHT = stamp(2026, 11, 4, 6, 0)       # 01:00 New York, nothing trades


def bars(count=65, last=338.32):
    """`count` daily bars ending on Monday 2026-11-02, closing at `last`."""
    stamps, closes = [], []
    for i in range(count):
        day = datetime.datetime(2026, 11, 2, 14, 30, tzinfo=ZONE) \
            - datetime.timedelta(days=count - 1 - i)
        stamps.append(int(day.timestamp()))
        closes.append(round(last + (count - 1 - i) * 0.12, 6))
    closes[-1] = last
    return stamps, closes


def meta(**over):
    m = {
        "symbol": "AAPL",
        "longName": "Apple Inc.",
        "currency": "USD",
        "fullExchangeName": "NasdaqGS",
        "instrumentType": "EQUITY",
        "exchangeTimezoneName": "America/New_York",
        "priceHint": 2,
        "hasPrePostMarketData": True,
        "fulldayPrice": 322.13,
        "regularMarketPrice": 338.32,
        "regularMarketTime": NOV2_CLOSE + 1,
        "currentTradingPeriod": {
            "pre": {"start": NOV3_PRE, "end": NOV3_OPEN},
            "regular": {"start": NOV3_OPEN, "end": NOV3_CLOSE},
            "post": {"start": NOV3_CLOSE, "end": NOV3_POST_END},
        },
    }
    m.update(over)
    return m


def payload(**over):
    stamps, closes = bars()
    return {"chart": {"result": [{
        "meta": meta(**over),
        "timestamp": stamps,
        "indicators": {"quote": [{"close": closes,
                                  "volume": [1_000_000] * len(closes)}]},
    }]}}


def card(**meta_over):
    """The chart payload the page would be drawing, before the live point."""
    return server.slim_chart(payload(**meta_over), "AAPL")


class LivePrintTests(unittest.TestCase):
    """`live_print` -- the fetch-time half: which price, under which stamp."""

    def test_the_print_is_stamped_where_the_days_bar_will_land(self):
        out = server.live_print(meta(), NOV2_OPEN)
        self.assertEqual(out, {"t": NOV3_OPEN, "c": 322.13})

    def test_a_bar_of_the_session_trading_now_is_left_to_full_day_close(self):
        # The newest bar *is* Tuesday's, so `full_day_close` folds there; a
        # second point would duplicate the bar.
        self.assertIsNone(server.live_print(meta(), NOV3_OPEN))

    def test_an_instrument_without_an_extended_session_gets_none(self):
        self.assertIsNone(server.live_print(
            meta(hasPrePostMarketData=False), NOV2_OPEN))
        self.assertIsNone(server.live_print(meta(fulldayPrice=None), NOV2_OPEN))
        self.assertIsNone(server.live_print(
            meta(currentTradingPeriod={}), NOV2_OPEN))

    def test_a_dead_series_is_not_redrawn_as_todays_trading(self):
        stale = NOV2_OPEN - server.LIVE_BAR_GAP_DAYS * 86400 - 3600
        self.assertIsNone(server.live_print(meta(), stale))

    def test_a_weekend_of_gap_still_carries_the_monday_print(self):
        friday = NOV2_OPEN - 3 * 86400
        self.assertEqual(server.live_print(meta(), friday)["t"], NOV3_OPEN)


class LivePointTests(unittest.TestCase):
    """`live_point` -- the read-time half: when it is drawn, and as what."""

    def test_the_chart_ends_on_the_pre_market_print(self):
        before = card()
        self.assertEqual(before["points"][-1]["c"], 338.32)
        out = server.live_point(before, now=PRE_MARKET)
        self.assertEqual(len(out["points"]), len(before["points"]) + 1)
        self.assertEqual(out["points"][-1], {"t": NOV3_OPEN, "c": 322.13})
        self.assertEqual(server.last_bar_basis(out, now=PRE_MARKET), "pre")

    def test_the_bars_it_appends_to_are_not_mutated(self):
        before = card()
        kept = len(before["points"])
        server.live_point(before, now=PRE_MARKET)
        self.assertEqual(len(before["points"]), kept)
        self.assertNotIn("livePointStamp", before)

    def test_nothing_is_drawn_when_nothing_is_trading(self):
        # 01:00 New York: the post session is over and Yahoo reports the
        # regular close again, so there is no print to draw.
        before = card()
        out = server.live_point(before, now=OVERNIGHT)
        self.assertIs(out, before)
        self.assertEqual(server.last_bar_basis(out, now=OVERNIGHT), "close")

    def test_after_the_bell_the_point_is_the_after_hours_print(self):
        out = server.live_point(card(), now=AFTER_HOURS)
        self.assertEqual(out["points"][-1]["c"], 322.13)
        self.assertEqual(server.last_bar_basis(out, now=AFTER_HOURS), "after")

    def test_the_point_never_reads_as_a_settled_close(self):
        # A memo entry fetched at 09:28 can still be served at 09:31, when the
        # regular window is open but the print is still the pre-market one.
        out = server.live_point(card(), now=PRE_MARKET)
        self.assertEqual(server.last_bar_basis(out, now=REGULAR), "pre")

    def test_the_real_bar_replaces_the_point_instead_of_doubling_it(self):
        live = card()
        live["points"].append({"t": NOV3_OPEN, "c": 320.0})
        out = server.live_point(live, now=REGULAR)
        self.assertIs(out, live)
        self.assertEqual(len(out["points"]), len(live["points"]))

    def test_a_disk_copy_invents_no_price(self):
        before = dict(card(), cached=True, fetchedAt=NOV2_CLOSE)
        out = server.live_point(before, now=PRE_MARKET)
        self.assertIs(out, before)
        self.assertEqual(server.last_bar_basis(out, now=PRE_MARKET), "close")


class ShippedPayloadTests(unittest.TestCase):
    def test_a_daily_chart_ships_the_print_and_a_weekly_one_does_not(self):
        daily = server.slim_chart(payload(), "AAPL", "3mo", "1d")
        self.assertEqual(daily["livePrint"], {"t": NOV3_OPEN, "c": 322.13})
        weekly = server.slim_chart(payload(), "AAPL", "3mo", "1wk")
        self.assertIsNone(weekly["livePrint"])

    def test_the_route_draws_it_and_rescores_the_drawn_series(self):
        before = card()
        with mock.patch.object(server, "cached", return_value=before), \
                mock.patch.object(server.time, "time", return_value=PRE_MARKET):
            out = server.chart_data("AAPL", "3mo", "1d")
        self.assertEqual(out["points"][-1], {"t": NOV3_OPEN, "c": 322.13})
        self.assertEqual(out["lastBarBasis"], "pre")
        # The badge is the classifier's call on the drawn series, plus the
        # steady-lean decoration every chart carries now (`onset.decorate`).
        # The trading fields are compared as the classifier wrote them; the
        # decoration is allowed to add its own and to withhold a lean.
        call = trend.classify([p["c"] for p in out["points"]])
        for field in ("label", "score", "significance", "progress", "bars"):
            self.assertEqual(out["trend"][field], call[field], field)
        self.assertEqual(out["trend"]["leanRaw"], call["lean"])
        self.assertIn("steady", out["trend"])


if __name__ == "__main__":
    unittest.main()
