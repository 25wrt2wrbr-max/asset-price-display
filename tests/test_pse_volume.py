"""The last *completed* trading day's traded value, on a PSE chart's display.

The reader asked for it by name -- "for PSE / Philippines stocks, on the main
price display also show last trading day's volume in PHP" -- then pinned the one
thing that could go wrong: "does this the volume only shows for the trading day
that has only been completed". Then, precisely: "when 3:15pm comes, will the
trading volume now give me the volume for today?"

So the rule is the exchange's own bell. The figure is `close * volume` on the
newest drawn bar that is a **finished** session, in pesos -- the same product
`bullish.py` and `onset.py` rank the tables on:

* before **15:15** Manila, today's bar is the session so far, so the figure is
  the previous session's;
* from **15:17** (the close plus the moment the closing print needs), today's
  bar is finished and its closing volume is the figure;
* a bar stamped in the future is never a session;
* on a holiday no bar is dated today, so the walk reaches the last day that
  actually traded -- no holiday calendar needed.

The provider marks nothing as final (TradingView carries today's candle from the
opening bell, which is why `pse_outlook` discards it outright), so the published
close is what decides.

What these tests pin:

* the most recent finished session is reported, and today's forming bar is not;
* 15:05 and 15:16 are still the previous session, 15:18 is today's;
* a series with nothing finished reports nothing at all;
* an index, a missing volume and a zero-volume bar read as missing, not PHP 0.00;
* a weekly chart ships none (a week's volume is not a trading day's value);
* the figure is decided at **read** time, so a payload fetched mid-session and
  served later is re-dated rather than frozen;
* both producers of the payload -- `chart()` and `_build_chart()` -- carry the
  aligned `volumes` the rule reads.

Every test pins the clock it means to test; none of them depends on when the
suite happens to run (a test that only passes before 3:15pm would be a bug in
the test). No browser and no network: the socket run is mocked, exactly as
`_history` would answer.
"""

import datetime
import time
import unittest
from unittest import mock

import pse
import pse_outlook
import server

DAY = 86400


def manila_day(stamp):
    return datetime.datetime.fromtimestamp(stamp, pse_outlook.MANILA).date()


def at(hour, minute, day=None, now=None):
    """An epoch second inside a Manila day (the day of `now` by default)."""
    base = time.time() if now is None else now
    d = day or datetime.datetime.fromtimestamp(base, pse_outlook.MANILA).date()
    return datetime.datetime(d.year, d.month, d.day, hour, minute,
                             tzinfo=pse_outlook.MANILA).timestamp()


def session_open(days_ago: int, now: float) -> int:
    """The stamp of a PSE daily bar `days_ago` days before `now`'s Manila date.

    PSE bars are stamped at the Manila open, 09:30, which is where TradingView
    puts them (measured on the saved charts: 1793323800 = 2026-10-30 09:30
    Manila).
    """
    today = datetime.datetime.fromtimestamp(now, pse_outlook.MANILA)
    open_ = today.replace(hour=9, minute=30, second=0, microsecond=0)
    return int(open_.timestamp()) - days_ago * DAY


def rows(closes, volumes, now, offset=1):
    """Socket-shaped rows: [stamp, open, high, low, close, volume].

    `offset` is how many days before today the **newest** bar sits: 1 ends the
    series on yesterday's session, 0 ends it on today's bar.
    """
    n = len(closes)
    out = []
    for i, close in enumerate(closes):
        stamp = session_open(offset + (n - 1 - i), now)
        volume = volumes[i]
        if volume is None:
            out.append([stamp, close, close, close, close])   # an index: 5 fields
        else:
            out.append([stamp, close, close, close, close, volume])
    return out


META = {"name": "PLDT Inc.", "currency": "PHP",
        "exchange": "Philippine Stock Exchange", "type": "stock",
        "pricescale": 100}


def envelope(bar_rows, meta=None):
    return {"kind": "ok", "bars": bar_rows, "meta": dict(META if meta is None else meta)}


def series(n=40, close=1300.0, volume=1000.0, now=None, today_bar=False):
    """A gently rising series ending yesterday, or carrying today's bar too."""
    now = now or time.time()
    closes = [close * (1 + 0.001 * i) for i in range(n)]
    volumes = [volume] * n
    if today_bar:
        closes = closes + [closes[-1] * 1.01]
        volumes = volumes + [volume * 3]      # a partial session, mid-accumulation
        return rows(closes, volumes, now, offset=0)
    return rows(closes, volumes, now, offset=1)


def charted(bar_rows, symbol="PSE:TEL", span="3mo", interval="1d"):
    with mock.patch.object(pse, "_history", return_value=envelope(bar_rows)):
        return pse.chart(symbol, span, interval)


class CompletedTradeTests(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.mid_session = at(10, 17, now=self.now)
        self.after_bell = at(15, 20, now=self.now)

    def test_the_newest_finished_session_is_the_one_reported(self):
        payload = charted(series(volume=1234.0, now=self.now))
        stamp, shares, value = pse.completed_trade(
            payload["points"], payload["volumes"], now=self.mid_session)
        self.assertEqual(shares, 1234.0)
        self.assertAlmostEqual(value, payload["points"][-1]["c"] * 1234.0)
        self.assertEqual(stamp, payload["points"][-1]["t"])
        self.assertLess(manila_day(stamp), manila_day(self.mid_session))

    def test_todays_bar_is_skipped_while_the_exchange_trades(self):
        payload = charted(series(volume=1000.0, now=self.now, today_bar=True))
        points, volumes = payload["points"], payload["volumes"]
        self.assertEqual(manila_day(points[-1]["t"]), manila_day(self.mid_session))
        stamp, shares, value = pse.completed_trade(points, volumes,
                                                   now=self.mid_session)
        # The forming bar traded 3,000 shares; the figure must be yesterday's.
        self.assertEqual(shares, 1000.0)
        self.assertEqual(stamp, points[-2]["t"])
        self.assertAlmostEqual(value, points[-2]["c"] * 1000.0)

    def test_todays_bar_counts_once_the_bell_has_gone(self):
        # pse.com.ph closes at 3:15pm; from then on today's bar is a finished
        # session and its closing volume is the answer.
        payload = charted(series(volume=1000.0, now=self.now, today_bar=True))
        points, volumes = payload["points"], payload["volumes"]
        stamp, shares, value = pse.completed_trade(points, volumes,
                                                   now=self.after_bell)
        self.assertEqual(stamp, points[-1]["t"])
        self.assertEqual(shares, 3000.0)
        self.assertAlmostEqual(value, points[-1]["c"] * 3000.0)

    def test_the_bell_is_three_fifteen_not_three_o_clock(self):
        # The closing VWAP session runs 15:00-15:15, so 15:05 is still a forming
        # bar; 15:16 is past the close but inside the moment the closing print
        # needs; 15:18 is the first honest answer.
        payload = charted(series(volume=1000.0, now=self.now, today_bar=True))
        points, volumes = payload["points"], payload["volumes"]
        for minute, expected in ((5, points[-2]["t"]), (16, points[-2]["t"]),
                                 (18, points[-1]["t"])):
            stamp, _, _ = pse.completed_trade(points, volumes,
                                              now=at(15, minute, now=self.now))
            self.assertEqual(stamp, expected, f"15:{minute:02d}")

    def test_a_holiday_falls_back_to_the_last_session_that_traded(self):
        # No bar is dated today on a holiday, so no holiday calendar is needed:
        # the walk reaches the last day that actually traded, before and after
        # the bell alike.
        payload = charted(series(volume=1000.0, now=self.now))   # ends yesterday
        points, volumes = payload["points"], payload["volumes"]
        for when in (at(10, 0, now=self.now), at(16, 0, now=self.now)):
            self.assertEqual(
                pse.completed_trade(points, volumes, now=when)[0], points[-1]["t"])

    def test_nothing_finished_reports_nothing(self):
        # A fresh listing whose only bar is today's: before the bell there is no
        # finished session to describe, and inventing one from a forming bar is
        # the bug this rule exists to prevent.
        payload = charted(series(6, volume=500.0, now=self.now, today_bar=True),
                          symbol="PSE:NEW", span="1mo")
        points, volumes = payload["points"][-1:], payload["volumes"][-1:]
        self.assertEqual(pse.completed_trade(points, volumes, now=self.mid_session),
                         (None, None, None))

    def test_a_bar_ahead_of_the_clock_is_refused_too(self):
        # A stamp in the future is not a session either, even after the bell.
        future = int(self.now) + 2 * DAY
        points = [{"t": future, "c": 10.0}, {"t": future - DAY, "c": 10.0}]
        self.assertEqual(pse.completed_trade(points, [100.0, 100.0],
                                             now=self.now), (None, None, None))

    def test_an_index_has_no_volume_to_report(self):
        payload = charted(rows([100.0 + i for i in range(40)], [None] * 40,
                               self.now), symbol="PSE:PSEI")
        self.assertEqual(pse.completed_trade(payload["points"], payload["volumes"],
                                            now=self.after_bell),
                         (None, None, None))

    def test_a_zero_volume_session_is_missing_not_zero(self):
        payload = charted(series(volume=0.0, now=self.now))
        self.assertEqual(pse.completed_trade(payload["points"], payload["volumes"],
                                            now=self.after_bell),
                         (None, None, None))

    def test_the_helper_refuses_rather_than_inventing(self):
        self.assertEqual(pse.completed_trade([], [], now=self.now),
                         (None, None, None))
        points = [{"t": session_open(1, self.now), "c": 2.0}]
        self.assertEqual(pse.completed_trade(points, [None], now=self.now),
                         (None, None, None))
        self.assertEqual(pse.completed_trade(points, [0.0], now=self.now),
                         (None, None, None))
        self.assertEqual(pse.completed_trade(points, [5.0], now=self.now),
                         (points[0]["t"], 5.0, 10.0))

    def test_both_producers_ship_the_volumes_the_rule_reads(self):
        bar_rows = series(volume=777.0, now=self.now)
        single = charted(bar_rows)
        batched = pse._build_chart("PSE:TEL", bar_rows, dict(META), "3mo", "1d")
        for payload in (single, batched):
            self.assertEqual(len(payload["volumes"]), len(payload["points"]))
            self.assertEqual(payload["volumes"][-1], 777.0)
        self.assertEqual(
            pse.completed_trade(single["points"], single["volumes"], now=self.now),
            pse.completed_trade(batched["points"], batched["volumes"], now=self.now))


class PayloadRouteTests(unittest.TestCase):
    """`chart_data` makes the call at read time, so it is asked with a clock."""

    def setUp(self):
        self.now = time.time()
        self.mid_session = at(10, 17, now=self.now)
        self.after_bell = at(15, 20, now=self.now)

    def payload(self, today_bar=True, symbol="PSE:TEL"):
        bar_rows = series(61, close=100.0, volume=250.0, now=self.now,
                          today_bar=today_bar)
        points = [{"t": r[0], "c": r[4]} for r in bar_rows]
        volumes = [r[5] for r in bar_rows]
        return {"symbol": symbol, "currency": "PHP", "source": "TradingView",
                "marketPrice": points[-1]["c"], "points": points,
                "volumes": volumes,
                "longTermContext": {"status": "insufficient"},
                "trend": {"label": "neutral", "score": 0.0}}

    def chart_at(self, payload, when, span="3mo", interval="1d",
                 symbol="PSE:TEL"):
        with mock.patch.object(server, "cached", return_value=payload), \
                mock.patch.object(server.time, "time", return_value=when):
            return server.chart_data(symbol, span, interval)

    def test_the_route_reports_yesterday_then_today_across_the_bell(self):
        payload = self.payload()
        before = self.chart_at(payload, self.mid_session)
        after = self.chart_at(payload, self.after_bell)
        self.assertEqual(before["tradedDay"], payload["points"][-2]["t"])
        self.assertEqual(before["tradedShares"], 250.0)
        self.assertAlmostEqual(before["tradedTurnover"],
                               payload["points"][-2]["c"] * 250.0)
        # Same stored payload, read after the bell: today's bar is now final.
        self.assertEqual(after["tradedDay"], payload["points"][-1]["t"])
        self.assertEqual(after["tradedShares"], 750.0)
        self.assertAlmostEqual(after["tradedTurnover"],
                               payload["points"][-1]["c"] * 750.0)

    def test_the_decision_is_made_at_read_time_not_fetch_time(self):
        # A payload stored while today's bar existed keeps today's bar in it;
        # read the next day, the bar that was "today" is a finished session and
        # the figure must move to it instead of staying a day behind for ever.
        payload = self.payload()
        fetched = self.chart_at(payload, self.mid_session)
        next_day = self.chart_at(payload, at(10, 0, now=self.now + DAY))
        self.assertGreater(next_day["tradedDay"], fetched["tradedDay"])
        self.assertEqual(next_day["tradedDay"], payload["points"][-1]["t"])
        self.assertEqual(next_day["tradedShares"], 750.0)

    def test_the_route_refuses_a_weekly_bar(self):
        payload = self.payload(today_bar=False)
        out = self.chart_at(payload, self.after_bell, span="3mo", interval="1wk")
        self.assertNotIn("tradedTurnover", out)

    def test_a_non_pse_payload_is_untouched(self):
        payload = {"symbol": "AAPL", "currency": "USD", "source": "Yahoo",
                   "points": [{"t": 1, "c": 100.0 + i} for i in range(62)],
                   "trend": {"label": "neutral", "score": 0.0}}
        out = self.chart_at(payload, self.after_bell, symbol="AAPL")
        self.assertNotIn("tradedTurnover", out)
        self.assertNotIn("tradedShares", out)
        self.assertNotIn("tradedDay", out)


if __name__ == "__main__":
    unittest.main()
