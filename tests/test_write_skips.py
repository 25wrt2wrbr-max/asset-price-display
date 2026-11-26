"""2026-11-25: the quote fast path off the chart memo, and writes skipped
when nothing changed (alarms, watch state, watchlist)."""

import time
import unittest
from unittest import mock

import server
import live_quote
import notify
import watchlist


class QuoteFastPathTests(unittest.TestCase):
    SYM = "ZZFAST"

    def setUp(self):
        live_quote._memo.clear()
        self.key = server.chart_key(self.SYM, live_quote.CHART_SPAN, live_quote.CHART_INTERVAL)

    def tearDown(self):
        live_quote._memo.clear()
        with server._cache_lock:
            server._cache.pop(self.key, None)

    def _put(self, age, data):
        with server._cache_lock:
            server._cache[self.key] = (time.time() - age, data)

    def _live_chart(self, **extra):
        return dict({"symbol": self.SYM, "liveLastBar": True,
                     "points": [{"t": 1, "c": 10.0}, {"t": 2, "c": 12.5}]}, **extra)

    def test_fresh_live_chart_answers_without_a_browser(self):
        self._put(1.0, self._live_chart())
        with mock.patch.object(live_quote, "_fetch") as fetch:
            got = live_quote.quote(self.SYM.lower())
        fetch.assert_not_called()
        self.assertEqual(got["price"], 12.5)
        self.assertEqual(got["symbol"], self.SYM)
        self.assertEqual(set(got), {"price", "t", "symbol"})

    def test_old_chart_takes_the_normal_path(self):
        self._put(live_quote.QUOTE_TTL + 5, self._live_chart())
        answer = {"price": 13.0, "t": 99, "symbol": self.SYM}
        with mock.patch.object(live_quote, "_fetch", return_value=answer) as fetch:
            got = live_quote.quote(self.SYM)
        fetch.assert_called_once_with(self.SYM)
        self.assertEqual(got, answer)

    def test_closed_basis_takes_the_normal_path(self):
        self._put(1.0, {"symbol": self.SYM, "points": [{"t": 1, "c": 10.0}]})
        answer = {"price": 13.0, "t": 99, "symbol": self.SYM}
        with mock.patch.object(live_quote, "_fetch", return_value=answer) as fetch:
            got = live_quote.quote(self.SYM)
        fetch.assert_called_once()
        self.assertEqual(got, answer)

    def test_disk_fallback_copy_takes_the_normal_path(self):
        self._put(1.0, self._live_chart(cached=True))
        answer = {"price": 13.0, "t": 99, "symbol": self.SYM}
        with mock.patch.object(live_quote, "_fetch", return_value=answer) as fetch:
            live_quote.quote(self.SYM)
        fetch.assert_called_once()


class AlarmWriteTests(unittest.TestCase):
    def setUp(self):
        self._saved = notify._alarms
        notify._alarms = [{"id": "z1", "symbol": "ZZALARM", "target": 100.0, "last": 90.0,
                           "fired": None}]

    def tearDown(self):
        notify._alarms = self._saved

    def test_same_price_does_not_write(self):
        with mock.patch.object(notify.diskcache, "store_plain") as store, \
                mock.patch.object(notify, "send"):
            notify.check_alarms("ZZALARM", 90.0)
            store.assert_not_called()
            notify.check_alarms("ZZALARM", 95.0)
            store.assert_called_once()
            notify.check_alarms("ZZALARM", 101.0)
            self.assertEqual(store.call_count, 2)
            self.assertTrue(notify._alarms[0]["fired"])


class WatchStateWriteTests(unittest.TestCase):
    def setUp(self):
        self._saved = notify._watch_state
        notify._watch_state = {}

    def tearDown(self):
        notify._watch_state = self._saved

    def test_writes_only_when_the_badge_changes(self):
        def chart(label, c):
            return {"symbol": "ZZWATCH", "points": [{"t": 1, "c": c}], "trend": {"label": label}}
        with mock.patch.object(notify.diskcache, "store_plain") as store, \
                mock.patch.object(notify, "send") as send:
            notify.observe_chart("ZZWATCH", chart("neutral", 1.0), {"ZZWATCH"})
            self.assertEqual(store.call_count, 1)          # first sighting
            notify.observe_chart("ZZWATCH", chart("neutral", 2.0), {"ZZWATCH"})
            self.assertEqual(store.call_count, 1)          # same label: no write
            notify.observe_chart("ZZWATCH", chart("bullish", 3.0), {"ZZWATCH"})
            self.assertEqual(store.call_count, 2)
            send.assert_called_once()
        self.assertEqual(notify._watch_state["ZZWATCH"]["label"], "bullish")


class WatchlistWriteTests(unittest.TestCase):
    def setUp(self):
        self._items, self._union = watchlist._watch_items, watchlist._watch_union

    def tearDown(self):
        watchlist._watch_items, watchlist._watch_union = self._items, self._union

    def test_unchanged_list_skips_the_write(self):
        with mock.patch.object(watchlist.diskcache, "store_plain") as store:
            watchlist.record_watchlist(["ZZA", "ZZB"])
            self.assertEqual(store.call_count, 1)
            watchlist.record_watchlist(["zza", "ZZB"])
            self.assertEqual(store.call_count, 1)
            self.assertEqual(watchlist.union_watchlist(), ["ZZA", "ZZB"])
            watchlist.record_watchlist([{"symbol": "ZZA", "name": "Renamed"}, "ZZB"])
            self.assertEqual(store.call_count, 2)
            watchlist.record_watchlist(["ZZB", "ZZA"])
            self.assertEqual(store.call_count, 3)


if __name__ == "__main__":
    unittest.main()
