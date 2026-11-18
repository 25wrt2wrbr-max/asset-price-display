"""The stored year of US bars, the closed-market pace, and stray cache copies."""

import datetime as dt
import json
import os
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import diskcache
import pse_outlook
import server
import us_bars

NY = ZoneInfo("America/New_York")


def ny(y, m, d, hour=12, minute=0):
    return dt.datetime(y, m, d, hour, minute, tzinfo=NY).timestamp()


def sessions(count, end=dt.date(2026, 11, 13)):
    """The last `count` weekday session-open stamps up to `end`, oldest first."""
    days, day = [], end
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= dt.timedelta(days=1)
    return [int(dt.datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY).timestamp())
            for d in reversed(days)]


def bars(stamps, start=100.0):
    return (list(stamps), [round(start + i * 0.5, 6) for i in range(len(stamps))],
            [1000 + i for i in range(len(stamps))])


def payload(series):
    stamps, closes, volumes = series
    return json.dumps({"chart": {"result": [{
        "meta": {"exchangeTimezoneName": "America/New_York", "currency": "USD",
                 "instrumentType": "EQUITY", "longName": "Test Co"},
        "timestamp": stamps,
        "indicators": {"quote": [{"close": closes, "volume": volumes}]},
    }]}})


class ClosedSinceTests(unittest.TestCase):
    def test_open_through_the_extended_day(self):
        self.assertIsNone(us_bars.closed_since(ny(2026, 11, 16, 4, 0)))
        self.assertIsNone(us_bars.closed_since(ny(2026, 11, 16, 19, 59)))

    def test_closed_overnight_and_at_the_weekend(self):
        friday_close = ny(2026, 11, 13, 20, 0)
        self.assertEqual(us_bars.closed_since(ny(2026, 11, 13, 21, 0)), friday_close)
        self.assertEqual(us_bars.closed_since(ny(2026, 11, 14, 12, 0)), friday_close)
        self.assertEqual(us_bars.closed_since(ny(2026, 11, 15, 23, 0)), friday_close)
        self.assertEqual(us_bars.closed_since(ny(2026, 11, 16, 3, 59)), friday_close)
        self.assertEqual(us_bars.closed_since(ny(2026, 11, 17, 2, 0)),
                         ny(2026, 11, 16, 20, 0))


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.full = bars(sessions(250))

    def cut(self, drop):
        return tuple(column[:-drop] for column in self.full)

    def tail(self, keep=22):
        return tuple(column[-keep:] for column in self.full)

    def test_a_cut_year_plus_the_tail_is_the_full_year(self):
        for drop in (1, 2, 5, 15):
            joined = us_bars.merge(self.cut(drop), self.tail(), "America/New_York")
            self.assertEqual(joined, self.full, drop)

    def test_the_stored_newest_bar_may_differ(self):
        base = self.cut(2)
        base[1][-1] += 3.0          # yesterday's after-hours price
        self.assertEqual(us_bars.merge(base, self.tail(), "America/New_York"), self.full)

    def test_a_forming_bar_stamped_at_its_last_trade_is_one_day(self):
        base = self.cut(1)
        base[0][-1] += 3 * 3600     # stored while the session was trading
        self.assertEqual(us_bars.merge(base, self.tail(), "America/New_York"), self.full)

    def test_a_changed_close_refuses(self):
        base = self.cut(2)
        base[1][-5] *= 0.5          # a split the stored year has not seen
        self.assertIsNone(us_bars.merge(base, self.tail(), "America/New_York"))

    def test_too_little_overlap_refuses(self):
        self.assertIsNone(us_bars.merge(self.cut(30), self.tail(), "America/New_York"))
        self.assertIsNone(us_bars.merge(self.cut(20), self.tail(), "America/New_York"))

    def test_a_missing_day_on_either_side_refuses(self):
        base = tuple(c[:-8] + c[-7:-2] for c in self.full)      # stored year lacks a day
        self.assertIsNone(us_bars.merge(base, self.tail(), "America/New_York"))
        tail = tuple(c[-22:-8] + c[-7:] for c in self.full)     # tail lacks a day
        self.assertIsNone(us_bars.merge(self.cut(2), tail, "America/New_York"))

    def test_a_stopped_series_joins_on_the_few_bars_its_month_has(self):
        for keep in (1, 2, 3):
            tail = tuple(c[-keep:] for c in self.full)
            self.assertEqual(us_bars.merge(self.full, tail, "America/New_York"),
                             self.full, keep)
        wrong = tuple(c[-2:] for c in self.full)
        wrong[1][0] += 1.0
        self.assertIsNone(us_bars.merge(self.full, wrong, "America/New_York"))

    def test_the_newest_day_may_be_printed_twice(self):
        def twice(series):
            return (series[0] + [series[0][-1] + 3600], series[1] + [series[1][-1] + 1],
                    series[2] + [series[2][-1]])
        live = twice(self.full)
        tail = tuple(c[-23:] for c in live)
        self.assertEqual(us_bars.merge(twice(self.cut(1)), tail, "America/New_York"), live)
        self.assertEqual(us_bars.merge(self.cut(1), tail, "America/New_York"), live)
        early = (self.full[0][:5] + [self.full[0][4] + 60] + self.full[0][5:],
                 self.full[1][:5] + [1.0] + self.full[1][5:],
                 self.full[2][:5] + [1] + self.full[2][5:])
        self.assertIsNone(us_bars.merge(early, self.tail(), "America/New_York"))

    def test_an_unusable_zone_refuses(self):
        self.assertIsNone(us_bars.merge(self.cut(2), self.tail(), "Not/AZone"))


class FetchUsBarsStoreTests(unittest.TestCase):
    def setUp(self):
        us_bars.reset()
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"APD_CACHE_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(us_bars.reset)
        self.full = bars(sessions(250))
        self.asked = []
        self.status = 200
        self.series = self.full

    def answer(self, urls):
        self.asked.append(list(urls))
        out = {}
        for url in urls:
            if self.status != 200:
                out[url] = (self.status, "{}")
            elif "range=1mo" in url:
                out[url] = (200, payload(tuple(c[-22:] for c in self.series)))
            else:
                out[url] = (200, payload(self.series))
        return out

    def fetch(self, now, tickers=("AAPL",)):
        with mock.patch.object(server, "moli_batch_get", side_effect=self.answer), \
                mock.patch.object(server.nasdaq_bars, "fetch", return_value={}):
            return server.fetch_us_bars(list(tickers), now=now)

    def spans(self):
        return ["1y" if "range=1y" in u else "1mo" for call in self.asked for u in call]

    def test_first_the_year_then_only_the_month(self):
        monday = ny(2026, 11, 16, 10, 0)
        first = self.fetch(monday)
        second = self.fetch(monday + 900)
        self.assertEqual(self.spans(), ["1y", "1mo"])
        self.assertEqual(first["AAPL"][:3], self.full)
        self.assertEqual(second["AAPL"][:3], self.full)
        self.assertEqual(second["AAPL"][3]["name"], "Test Co")

    def test_a_new_bar_arrives_through_the_month(self):
        monday = ny(2026, 11, 16, 10, 0)
        self.series = tuple(c[:-1] for c in self.full)
        self.fetch(monday)
        self.series = self.full
        self.assertEqual(self.fetch(monday + 900)["AAPL"][:3], self.full)
        self.assertEqual(self.spans(), ["1y", "1mo"])

    def test_the_year_is_asked_again_after_a_day(self):
        monday = ny(2026, 11, 16, 10, 0)
        self.fetch(monday)
        self.fetch(monday + us_bars.FULL_EVERY + 1)
        self.assertEqual(self.spans(), ["1y", "1y"])

    def test_a_changed_close_downloads_the_year_again(self):
        monday = ny(2026, 11, 16, 10, 0)
        self.fetch(monday)
        self.series = (self.full[0], [c / 2 for c in self.full[1]], self.full[2])
        out = self.fetch(monday + 900)
        self.assertEqual(self.spans(), ["1y", "1mo", "1y"])
        self.assertEqual(out["AAPL"][1], self.series[1])

    def test_a_failed_month_is_an_outage_not_the_stored_year(self):
        monday = ny(2026, 11, 16, 10, 0)
        self.fetch(monday)
        self.status = 503
        self.assertEqual(self.fetch(monday + 900), {})

    def test_no_such_instrument_forgets_the_stored_year(self):
        monday = ny(2026, 11, 16, 10, 0)
        self.fetch(monday)
        self.status = 404
        self.assertEqual(self.fetch(monday + 900), {})
        self.assertIsNone(us_bars.get("AAPL"))

    def test_an_empty_month_keeps_the_stored_year(self):
        monday = ny(2026, 11, 16, 10, 0)
        self.fetch(monday)
        empty = json.dumps({"chart": {"result": [{
            "meta": {"exchangeTimezoneName": "America/New_York"},
            "indicators": {"quote": [{}]}}]}})
        with mock.patch.object(server, "moli_batch_get",
                               side_effect=lambda urls: {u: (200, empty) for u in urls}):
            out = server.fetch_us_bars(["AAPL"], now=monday + 900)
        self.assertEqual(out["AAPL"][:3], self.full)
        us_bars.reset()             # the same empty answer for a full year is a verdict
        with mock.patch.object(server, "moli_batch_get",
                               side_effect=lambda urls: {u: (200, empty) for u in urls}):
            self.assertEqual(server.fetch_us_bars(["AAPL"], now=monday), {})

    def test_closed_market_reads_once_an_hour(self):
        after = ny(2026, 11, 13, 20, 30)            # Friday, close settled
        self.fetch(after)
        self.assertEqual(self.fetch(after + 900)["AAPL"][:3], self.full)
        self.assertEqual(self.fetch(after + 1800)["AAPL"][:3], self.full)
        self.assertEqual(len(self.asked), 1)        # served from the store
        self.fetch(after + us_bars.CLOSED_REREAD + 1)
        self.assertEqual(len(self.asked), 2)

    def test_a_read_from_before_the_close_is_not_enough(self):
        self.fetch(ny(2026, 11, 13, 19, 50))
        self.fetch(ny(2026, 11, 13, 20, 5))         # closed, but not settled
        self.fetch(ny(2026, 11, 13, 20, 20))
        self.assertEqual(len(self.asked), 3)

    def test_open_market_and_futures_are_always_read(self):
        monday = ny(2026, 11, 16, 10, 0)
        self.fetch(monday)
        self.fetch(monday + 900)
        self.assertEqual(len(self.asked), 2)
        self.asked.clear()
        after = ny(2026, 11, 13, 20, 30)
        self.fetch(after, tickers=("ZB=F",))
        self.fetch(after + 900, tickers=("ZB=F",))
        self.assertEqual(len(self.asked), 2)

    def test_the_year_survives_a_restart(self):
        monday = ny(2026, 11, 16, 10, 0)
        self.fetch(monday)
        with us_bars._lock:
            us_bars._base = None                    # a new process
        self.fetch(monday + 900)
        self.assertEqual(self.spans(), ["1y", "1mo"])


class BullishPauseTests(unittest.TestCase):
    def at(self, y, m, d, hour, minute=0):
        return dt.datetime(y, m, d, hour, minute, tzinfo=pse_outlook.MANILA).timestamp()

    def test_normal_pace_while_the_exchange_trades(self):
        self.assertEqual(server.bullish_pause(self.at(2026, 11, 16, 9, 30)), server.BULL_TTL)
        self.assertEqual(server.bullish_pause(self.at(2026, 11, 16, 15, 30)), server.BULL_TTL)

    def test_hourly_when_closed(self):
        self.assertEqual(server.bullish_pause(self.at(2026, 11, 16, 16, 0)), 3600)
        self.assertEqual(server.bullish_pause(self.at(2026, 11, 14, 11, 0)), 3600)

    def test_never_sleeps_past_the_opening_bell(self):
        self.assertEqual(server.bullish_pause(self.at(2026, 11, 16, 9, 10)), 1200)
        self.assertEqual(server.bullish_pause(self.at(2026, 11, 16, 9, 29, )), 60)
        self.assertEqual(server.bullish_pause(self.at(2026, 11, 15, 23, 0)), 3600)


class StrayCopyTests(unittest.TestCase):
    def test_prune_removes_duplicates_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"APD_CACHE_DIR": tmp}):
            diskcache.store("a-key", {"x": 1})
            diskcache.store_plain("a-list", ["y"])
            real = [n for n in os.listdir(tmp) if not n.endswith(".plain.json")][0]
            stray = real[:-5] + " 2.json"
            other = "notes 2.json"
            for name in (stray, other):
                with open(os.path.join(tmp, name), "w") as fh:
                    fh.write("{}")
            self.assertEqual(diskcache.count(), 2)   # the real one and "notes 2"
            diskcache.prune()
            left = set(os.listdir(tmp))
            self.assertNotIn(stray, left)
            self.assertIn(other, left)
            self.assertIn(real, left)
            self.assertEqual(diskcache.load("a-key")[1], {"x": 1})
            self.assertEqual(diskcache.load_plain("a-list"), ["y"])


if __name__ == "__main__":
    unittest.main()
