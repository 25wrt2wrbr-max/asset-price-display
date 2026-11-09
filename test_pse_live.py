"""The PSE chart's newest point is the price trading now, and says so.

The reader put it plainly: "i want the live price to be the live price from
source". TradingView's daily payload already carries **today's candle from the
opening bell**, so a PSE chart's newest point *is* the last trade during the
session -- the reading cost nothing to get, but the page could not act on it,
because nothing in the payload said the bar was still forming. `lastBarBasis`
therefore read every PSE chart as `close`, and the page's own clock only
re-reads a settled chart every fifteen minutes. So the live number was on
screen, up to a quarter of an hour old, and labelled a close.

`pse.session_window` ships the exchange's own session with the payload (the
same 9:30-15:15 schedule `completed_trade` reads), and `server.last_bar_basis`
turns that into `live` while the bell is open. What these tests pin:

* today's bar is a forming session, with the window the exchange publishes;
* yesterday's bar is not, and a weekly bar never is;
* a payload read inside the session reads `live`, and after the bell reads
  `close` -- decided at **read** time, from the payload's own stamps;
* a disk fallback never reads live, because a copy hours old is not a price;
* both producers of the payload carry the session, so the single-symbol route
  and the batched one cannot disagree.

Every test pins the clock it means to test; none depends on when the suite runs,
and none touches the network (the socket run is mocked).
"""

import datetime
import time
import unittest
from unittest import mock

import pse
import pse_outlook
import server

DAY = 86400

META = {"name": "PLDT Inc.", "currency": "PHP",
        "exchange": "Philippine Stock Exchange", "type": "stock",
        "pricescale": 100}


def at(hour, minute, day=None, now=None):
    """An epoch second inside a Manila day (the day of `now` by default)."""
    base = time.time() if now is None else now
    d = day or datetime.datetime.fromtimestamp(base, pse_outlook.MANILA).date()
    return datetime.datetime(d.year, d.month, d.day, hour, minute,
                             tzinfo=pse_outlook.MANILA).timestamp()


def bar_stamp(days_ago: int, now: float) -> int:
    """A PSE daily bar's stamp: the 09:30 Manila open, `days_ago` days back."""
    today = datetime.datetime.fromtimestamp(now, pse_outlook.MANILA)
    open_ = today.replace(hour=9, minute=30, second=0, microsecond=0)
    return int(open_.timestamp()) - days_ago * DAY


def rows(closes, volumes, now, offset=1):
    """Socket-shaped rows, newest bar `offset` days before today."""
    n = len(closes)
    out = []
    for i, close in enumerate(closes):
        stamp = bar_stamp(offset + (n - 1 - i), now)
        if volumes[i] is None:
            out.append([stamp, close, close, close, close])
        else:
            out.append([stamp, close, close, close, close, volumes[i]])
    return out


def series(n=40, close=1300.0, volume=1000.0, now=None, today_bar=False):
    now = now or time.time()
    closes = [close * (1 + 0.001 * i) for i in range(n)]
    volumes = [volume] * n
    if today_bar:
        closes = closes + [closes[-1] * 1.01]
        volumes = volumes + [volume * 3]
        return rows(closes, volumes, now, offset=0)
    return rows(closes, volumes, now, offset=1)


def envelope(bar_rows):
    return {"kind": "ok", "bars": bar_rows, "meta": dict(META)}


def charted(bar_rows, symbol="PSE:TEL", span="3mo", interval="1d"):
    with mock.patch.object(pse, "_history", return_value=envelope(bar_rows)):
        return pse.chart(symbol, span, interval)


class SessionWindowTests(unittest.TestCase):
    def setUp(self):
        self.now = time.time()

    def test_todays_bar_is_a_forming_session_between_the_bells(self):
        win = pse.session_window(bar_stamp(0, self.now), "1d", now=self.now)
        self.assertTrue(win["formingBar"])
        self.assertTrue(win["coversLastBar"])
        self.assertEqual(win["regular"],
                         [int(at(9, 30, now=self.now)),
                          int(at(15, 15, now=self.now))])

    def test_yesterdays_bar_is_a_settled_close(self):
        win = pse.session_window(bar_stamp(1, self.now), "1d", now=self.now)
        self.assertFalse(win["formingBar"])
        self.assertFalse(win["coversLastBar"])

    def test_a_weekly_bar_ships_no_session(self):
        # A week's candle is not a trading day's price, and the page asks for
        # `1d` only -- refusing is cheaper than a rule that would be wrong.
        self.assertIsNone(
            pse.session_window(bar_stamp(0, self.now), "1wk", now=self.now))

    def test_an_unreadable_stamp_ships_no_session(self):
        for bad in (None, "yesterday", 10 ** 30):
            self.assertIsNone(pse.session_window(bad, "1d", now=self.now))


class BasisTests(unittest.TestCase):
    """`last_bar_basis` is the one place the claim is made, at read time."""

    def setUp(self):
        self.now = time.time()
        self.mid_session = at(10, 17, now=self.now)
        self.after_bell = at(15, 20, now=self.now)

    def test_a_bar_dated_today_reads_live_while_the_exchange_trades(self):
        payload = charted(series(volume=250.0, now=self.now, today_bar=True))
        self.assertEqual(server.last_bar_basis(payload, now=self.mid_session),
                         "live")

    def test_the_same_payload_reads_close_after_the_bell(self):
        payload = charted(series(volume=250.0, now=self.now, today_bar=True))
        self.assertEqual(server.last_bar_basis(payload, now=self.after_bell),
                         "close")

    def test_the_same_payload_reads_close_the_next_morning(self):
        # The window is an absolute stamp, so a payload fetched yesterday
        # expires on its own -- the fact is re-read, never remembered.
        payload = charted(series(volume=250.0, now=self.now, today_bar=True))
        tomorrow = self.mid_session + DAY
        self.assertEqual(server.last_bar_basis(payload, now=tomorrow), "close")

    def test_a_series_ending_yesterday_never_reads_live(self):
        payload = charted(series(volume=250.0, now=self.now))
        self.assertEqual(server.last_bar_basis(payload, now=self.mid_session),
                         "close")

    def test_a_disk_fallback_is_never_live(self):
        payload = charted(series(volume=250.0, now=self.now, today_bar=True))
        payload["cached"] = True
        payload["fetchedAt"] = int(self.now) - 3600
        self.assertEqual(server.last_bar_basis(payload, now=self.mid_session),
                         "close")

    def test_both_producers_ship_the_session(self):
        bar_rows = series(volume=250.0, now=self.now, today_bar=True)
        single = charted(bar_rows)
        batched = pse._build_chart("PSE:TEL", bar_rows, dict(META), "3mo", "1d")
        self.assertEqual(single["session"], batched["session"])
        self.assertTrue(batched["session"]["formingBar"])

    def test_the_route_carries_the_basis_through_to_the_page(self):
        payload = charted(series(volume=250.0, now=self.now, today_bar=True))
        payload.update({"longTermContext": {"status": "insufficient"},
                        "trend": {"label": "neutral", "score": 0.0}})
        for when, expected in ((self.mid_session, "live"),
                               (self.after_bell, "close")):
            with mock.patch.object(server, "cached", return_value=dict(payload)), \
                    mock.patch.object(server.time, "time", return_value=when):
                out = server.chart_data("PSE:TEL", "3mo", "1d")
            self.assertEqual(out["lastBarBasis"], expected)

    def test_a_weekly_pse_chart_stays_a_close(self):
        payload = charted(series(volume=250.0, now=self.now, today_bar=True),
                          interval="1wk")
        self.assertIsNone(payload["session"])
        self.assertEqual(server.last_bar_basis(payload, now=self.mid_session),
                         "close")


if __name__ == "__main__":
    unittest.main()
