"""A coin whose exchange stopped trading it must not chart as today's price.

Measured 2026-11-03, the morning a reader said "XMR price graph is old": Binance
keeps a delisted pair in `/api/v3/ticker/price` at its last price forever, so
`XMRUSDT` answered **$118.70** and `XMRUSDT`'s newest kline was **2024-02-20**,
while Monero traded at **$625.94** (Kraken `XMRUSD` 625.63, CoinGecko 625.39).
Because the ticker still "resolved to a chartable coin", the chart route drew
that 2024 window and the hero read $118.70.

The rule the tests pin: the **bars** decide whether a pair is trading, and a coin
its exchange has stopped trading is read from Kraken, which answers for all five
dead ones (XMR, DAI, BTT, BEAM, LIT -- each a live bar stamped today).

The wire is mocked here; the live routes are checked separately through
`/api/chart?symbol=XMR-USD` and friends.
"""
import calendar
import time
import unittest
import urllib.parse
from unittest import mock

import crypto


DAY_MS = 86_400_000


def _day_ms(day: str) -> int:
    """Epoch milliseconds for a UTC date at midnight."""
    return calendar.timegm(time.strptime(day, "%Y-%m-%d")) * 1000


def _today_open_s() -> int:
    """The UTC midnight that starts today, in seconds -- a forming daily bar."""
    return calendar.timegm(time.gmtime()[:3] + (0, 0, 0, 0, 0, 0))


def _utc_day(seconds: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(seconds))


def _binance_series(days: int, start: float, last_open_ms: int, step: float = 1.0):
    """Binance klines: `[open, o, h, l, close, volume, close]`, ms stamps."""
    rows = []
    for i in range(days):
        open_ms = last_open_ms - (days - 1 - i) * DAY_MS
        rows.append([open_ms, "0", "0", "0", str(start + i * step), "10.0",
                     open_ms + DAY_MS])
    return rows


def _kraken_series(days: int, start: float, last_open_s: int, step: float = 1.0,
                   interval_s: int = 86_400):
    """Kraken OHLC: `[time, o, h, l, close, vwap, volume, count]`, s stamps."""
    rows = []
    for i in range(days):
        open_s = last_open_s - (days - 1 - i) * interval_s
        rows.append([open_s, "0", "0", "0", str(start + i * step), "0",
                     "12.5", 7])
    return rows


class Wire:
    """A fake upstream: CoinGecko's index, Binance's pair list, bars, Kraken."""

    def __init__(self, klines=None, kraken=None,
                 pairs=("XMRUSDT", "BTCUSDT"), markets=None):
        self.klines = klines or {}
        self.kraken = kraken or {}
        self.pairs = pairs
        self.markets = markets
        self.calls: list[str] = []

    def __call__(self, url: str):
        self.calls.append(url)
        if url.startswith(crypto.COINGECKO_MARKETS):
            if self.markets is not None:
                return self.markets
            return [
                {"symbol": "XMR", "name": "Monero", "market_cap_rank": 12,
                 "id": "monero"},
                {"symbol": "BTC", "name": "Bitcoin", "market_cap_rank": 1,
                 "id": "bitcoin"},
            ]
        if url == crypto.BINANCE_TICKER:
            return [{"symbol": pair, "price": "1"} for pair in self.pairs]
        if url.startswith(crypto.BINANCE_KLINES):
            query = urllib.parse.parse_qs(url.split("?", 1)[1])
            return self.klines[query["symbol"][0]]
        if url.startswith(crypto.KRAKEN_OHLC):
            query = urllib.parse.parse_qs(url.split("?", 1)[1])
            pair = query["pair"][0]
            rows = self.kraken.get(pair)
            if rows is None:
                # Kraken's real answer for an unlisted pair: 200, and an error
                # list rather than a result.
                return {"error": ["EQuery:Unknown asset pair"], "result": {}}
            return {"error": [], "result": {pair: rows, "last": rows[-1][0]}}
        raise AssertionError("unrequested URL: " + url)

    def kraken_calls(self) -> list[str]:
        return [url for url in self.calls if url.startswith(crypto.KRAKEN_OHLC)]


class Base(unittest.TestCase):
    """Every test starts from a cold module -- the index, pairs and closes are
    module-level caches, and a warm one would answer for the wrong wire."""

    def setUp(self):
        crypto._index_cache = (0.0, None)
        crypto._pairs_cache = (0.0, None)
        crypto._close_cache.clear()

    def wired(self, **kwargs):
        wire = Wire(**kwargs)
        patcher = mock.patch.object(crypto, "_get_json", wire)
        patcher.start()
        self.addCleanup(patcher.stop)
        return wire

    def dead_xmr(self):
        """XMRUSDT as Binance actually answers it: bars stop 2024-02-20."""
        return {"XMRUSDT": _binance_series(90, 118.70,
                                           _day_ms("2024-02-20"))}

    def live_xmr(self):
        """Kraken's XMRUSD as it actually answers: 720 rows to today."""
        return {"XMRUSD": _kraken_series(100, 600.0, _today_open_s())}


class TheOldGraphTests(Base):
    """The defect itself: a delisted pair drawn as though it were today."""

    def test_a_delisted_pair_is_charted_from_kraken(self):
        self.wired(klines=self.dead_xmr(), kraken=self.live_xmr())
        data = crypto.chart("XMR-USD", "3mo", "1d")
        self.assertEqual(data["source"], "Kraken")
        self.assertEqual(data["exchange"], "Kraken")

    def test_the_newest_point_is_today_and_the_hero_is_krakens_price(self):
        self.wired(klines=self.dead_xmr(), kraken=self.live_xmr())
        data = crypto.chart("XMR-USD", "3mo", "1d")
        self.assertEqual(_utc_day(data["points"][-1]["t"]), _utc_day(int(time.time())))
        self.assertAlmostEqual(data["marketPrice"], 699.0, places=6)
        self.assertTrue(data["liveLastBar"])   # today's bar is still forming

    def test_the_frozen_binance_price_is_never_drawn(self):
        self.wired(klines=self.dead_xmr(), kraken=self.live_xmr())
        closes = [p["c"] for p in crypto.chart("XMR-USD", "3mo", "1d")["points"]]
        self.assertNotIn(118.70, closes)
        self.assertNotIn(118.7, closes)

    def test_a_pair_that_is_trading_never_asks_kraken(self):
        today = _today_open_s() * 1000
        wire = self.wired(klines={"BTCUSDT": _binance_series(90, 76000.0, today)},
                          kraken=self.live_xmr())
        data = crypto.chart("BTC-USD", "3mo", "1d")
        self.assertEqual(data["source"], "Binance")
        self.assertEqual(wire.kraken_calls(), [])

    def test_neither_venue_trading_means_no_chart_rather_than_an_old_one(self):
        self.wired(klines=self.dead_xmr(), kraken={})
        with self.assertRaises(crypto.CryptoError) as caught:
            crypto.chart("XMR-USD", "3mo", "1d")
        message = str(caught.exception)
        self.assertIn("Binance", message)
        self.assertIn("Kraken", message)
        self.assertIn("2024-02-20", message)

    def test_a_delisted_pair_is_not_a_second_opinion_about_yahoos_price(self):
        # This is what made Yahoo's correct 625.94 look like the wrong
        # instrument and threw the live chart away for the frozen one.
        self.wired(klines=self.dead_xmr(), kraken=self.live_xmr())
        self.assertAlmostEqual(crypto.latest_close("XMR-USD"), 698.0, places=6)

    def test_with_no_venue_trading_the_close_is_unknown(self):
        self.wired(klines=self.dead_xmr(), kraken={})
        self.assertIsNone(crypto.latest_close("XMR-USD"))


class VenueShapeTests(Base):
    """Kraken's row shape, rewritten so one drawing path reads both venues."""

    def rows(self, interval="1d", count=30):
        patcher = mock.patch.object(
            crypto, "_kraken_raw",
            lambda base, interval_: _kraken_series(count, 600.0,
                                                   _today_open_s(),
                                                   interval_s=(86_400 if
                                                               interval_ == "1d"
                                                               else 7 * 86_400)))
        patcher.start()
        self.addCleanup(patcher.stop)
        return crypto._kraken_rows("XMR", interval, count)

    def test_the_close_of_a_bar_is_one_interval_after_its_open(self):
        daily = self.rows("1d")
        self.assertEqual(daily[-1][6] - daily[-1][0], DAY_MS)
        weekly = self.rows("1w")
        self.assertEqual(weekly[-1][6] - weekly[-1][0], 7 * DAY_MS)

    def test_the_newest_row_is_the_interval_still_forming(self):
        daily = self.rows("1d")
        self.assertGreater(daily[-1][6] / 1000, time.time())

    def test_the_volume_travels_with_the_bar(self):
        daily = self.rows("1d")
        self.assertEqual(daily[-1][5], 12.5)

    def test_an_unknown_pair_is_a_no_and_not_an_outage(self):
        # Kraken answers an unlisted pair with HTTP 200 and an error list.
        self.wired(kraken={})
        self.assertEqual(crypto._kraken_rows("NOPE", "1d", 10), [])

    def test_the_dollar_quote_falls_through_to_the_tether_one(self):
        # `BTTUSD` exists and `BTTUSDT` does not; the other way round for some.
        wire = self.wired(klines=self.dead_xmr(),
                          kraken={"XMRUSDT": _kraken_series(10, 600.0,
                                                            _today_open_s())})
        rows = crypto._kraken_rows("XMR", "1d", 10)
        self.assertTrue(rows)
        asked = [urllib.parse.parse_qs(url.split("?", 1)[1])["pair"][0]
                 for url in wire.kraken_calls()]
        self.assertEqual(asked, ["XMRUSD", "XMRUSDT"])

    def test_kraken_answers_at_most_720_rows(self):
        # A five-year request gets the two years that exist, and claims no more.
        self.wired(klines=self.dead_xmr(),
                   kraken={"XMRUSD": _kraken_series(900, 600.0, _today_open_s())})
        data = crypto.chart("XMR-USD", "5y", "1d")
        self.assertEqual(len(data["points"]), crypto.KRAKEN_MAX_BARS)

    def test_a_weekly_chart_asks_kraken_for_weekly_bars(self):
        wire = self.wired(klines=self.dead_xmr(),
                          kraken={"XMRUSD": _kraken_series(20, 600.0,
                                                           _today_open_s(),
                                                           interval_s=7 * 86_400)})
        data = crypto.chart("XMR-USD", "3mo", "1wk")
        self.assertEqual(len(data["points"]), 90 // 7)
        self.assertIn("interval=10080", wire.kraken_calls()[0])


class FreshnessTests(Base):
    """"The pair exists" is not "the pair trades" -- five days of silence."""

    def row(self, close_ms: float):
        open_ms = close_ms - DAY_MS
        return [[open_ms, "0", "0", "0", "1.0", "1.0", close_ms]]

    def test_a_forming_bar_is_trading(self):
        self.assertTrue(crypto._is_trading(self.row((time.time() + 3600) * 1000)))

    def test_a_bar_closed_yesterday_is_trading(self):
        self.assertTrue(crypto._is_trading(self.row((time.time() - 86_400) * 1000)))

    def test_silence_past_the_bound_is_not(self):
        self.assertFalse(crypto._is_trading(
            self.row((time.time() - 6 * 86_400) * 1000)))

    def test_no_bars_at_all_is_not_trading(self):
        self.assertFalse(crypto._is_trading([]))

    def test_the_bound_is_five_days(self):
        self.assertEqual(crypto.STALE_BAR_DAYS, 5)

    def test_the_stamp_says_which_day_the_series_stopped(self):
        # Binance's own close stamp is 23:59:59.999 of the bar's day; the bar's
        # day is the open stamp, wherever the close lands.
        bar = [_day_ms("2024-02-20"), "0", "0", "0", "1.0", "1.0",
               _day_ms("2024-02-20") + DAY_MS - 1000]
        self.assertEqual(crypto.last_bar_date([bar]), "2024-02-20")


class TickerEncodingTests(Base):
    """Binance lists pairs whose base asset is not ASCII (`币安人生USDT`)."""

    def test_the_ticker_is_percent_encoded_in_the_url(self):
        wire = self.wired(klines={"币安人生USDT": _binance_series(
            2, 1.0, _today_open_s() * 1000)})
        crypto._klines("币安人生USDT", "1d", 2)
        self.assertIn("%E5%B8%81%E5%AE%89%E4%BA%BA%E7%94%9FUSDT", wire.calls[0])

    def test_a_plain_ticker_is_unchanged(self):
        wire = self.wired(klines={"XMRUSDT": _binance_series(
            2, 1.0, _today_open_s() * 1000)})
        crypto._klines("XMRUSDT", "1d", 2)
        self.assertIn("symbol=XMRUSDT&", wire.calls[0])


if __name__ == "__main__":
    unittest.main()
