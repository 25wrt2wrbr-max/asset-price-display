"""A coin whose Binance pair stopped printing still charts the coin it names.

Measured 2026-11-10, the morning a reader asked why BEAM was in "Recently
bullish assets" while its price graph said Neutral:

* the table's row was judged on the crypto module's own bars -- Kraken's
  BEAMUSD, 0.00137 -> 0.004288 over three months (+212%), **bullish**;
* `/api/chart?symbol=BEAM-USD&range=3mo` served **Yahoo's** BEAM-USD --
  0.008857 -> 0.00633 (-28%), **neutral**. Yahoo quotes a different coin
  under that ticker.

The chart route's disagreement test could not catch it: it asked only
`crypto.latest_close`, which answers None while Binance's pair has stopped
printing (and caches that None for five minutes), so "no independent price"
meant "trust Yahoo". The row and the chart its click opened were two
different series -- invariant 1 broken.

The rule these tests pin: the chart asks the crypto module for the coin's own
chart once; that series is both the independent price for the test and the
chart to draw. It is only returned when a venue is *actually* trading the
coin, so a frozen delisted price is never that second opinion. When every
venue is silent, Yahoo stands and no verdict is invented. The wire is mocked.

Reopened 2026-11-11: the two coins' prices had *converged* -- Yahoo 0.005319
against Kraken 0.004457, 19.3% apart, inside the old 20% gap -- so the single
last close said "trust Yahoo" again while the windows read -37.7% (neutral)
and +225.8% (bullish). The test now reads the whole shared series: one coin at
two venues keeps a near-constant price ratio across the bars, two coins do
not. `_converged()` is that morning's measurement.
"""
import unittest
from unittest import mock

import server


def _series(first: float, last: float, count: int = 93,
            start: int = 1_786_233_600) -> list[dict]:
    """A daily close series, oldest first, with a steady drift."""
    step = (last / first) ** (1.0 / (count - 1))
    return [{"t": start + i * 86_400, "c": round(first * step ** i, 8)}
            for i in range(count)]


def _yahoo(last: float = 0.00633) -> dict:
    """A Yahoo crypto chart -- the colliding BEAM-USD, falling, neutral."""
    return {
        "symbol": "BEAM-USD", "name": "Beam USD", "currency": "USD",
        "exchange": "CCC", "type": "CRYPTOCURRENCY", "source": "Yahoo",
        "priceHint": 6, "points": _series(0.008857, last),
        "historyTail": [], "trend": {"label": "neutral", "score": -0.1696},
    }


def _coin(last: float = 0.004288) -> dict:
    """The crypto module's chart -- Kraken's Beam, rising, bullish."""
    points = _series(0.001373, last)
    return {
        "symbol": "BEAM-USD", "name": "Beam USD", "currency": "USD",
        "exchange": "Kraken", "type": "CRYPTOCURRENCY", "source": "Kraken",
        "priceHint": 6, "points": points,
        "volumes": [1.0] * len(points), "liveLastBar": True,
        "historyTail": [],
        "trend": {"label": "bullish", "score": 0.61},
    }


def _same_coin(yahoo: dict, scale: float = 0.998) -> dict:
    """Yahoo's own bars as a second venue would quote them: same shape, a hair
    of spread. A real second quote of one instrument tracks every bar -- the
    first build's "agrees" fixture merely landed near Yahoo's last close while
    rising from 0.001373, which is a different coin and now reads as one."""
    points = [{"t": p["t"], "c": round(p["c"] * scale, 8)}
              for p in yahoo["points"]]
    return {
        "symbol": "BEAM-USD", "name": "Beam USD", "currency": "USD",
        "exchange": "Binance", "type": "CRYPTOCURRENCY", "source": "Binance",
        "priceHint": 6, "points": points,
        "volumes": [1.0] * len(points), "liveLastBar": True,
        "historyTail": [],
        "trend": {"label": "neutral", "score": -0.1696},
    }


def _converged() -> tuple[dict, dict]:
    """Yahoo's BEAM-USD and Kraken's Beam, measured 2026-11-11.

    Newest closes 0.005319 / 0.004457 -- 19.3% apart, inside the old 20% gap
    -- while the windows read -37.7% (neutral) and +225.8% (bullish).
    """
    yahoo = _yahoo(last=0.005319)
    yahoo["points"] = _series(0.008544, 0.005319)
    coin = _coin(last=0.004457)
    coin["points"] = _series(0.001368, 0.004457)
    return yahoo, coin


class WrongInstrumentTests(unittest.TestCase):
    """The disagreement test, on its own."""

    def test_a_non_crypto_chart_is_never_rerouted(self):
        data = {"type": "EQUITY", "points": [{"t": 1, "c": 10.0}]}
        with mock.patch.object(server.crypto, "latest_close") as probe:
            self.assertFalse(server.yahoo_is_wrong("BEAM-USD", data, _coin(), True))
        probe.assert_not_called()

    def test_no_points_is_not_a_verdict(self):
        self.assertFalse(server.yahoo_is_wrong(
            "BEAM-USD", {"type": "CRYPTOCURRENCY"}, _coin(), True))

    def test_the_coins_own_live_series_decides(self):
        # Kraken's Beam is 0.004288 against Yahoo's 0.00633 -- 47% apart, and
        # the two windows travel in opposite directions.
        self.assertTrue(server.yahoo_is_wrong("BEAM-USD", _yahoo(), _coin(), True))
        # The same coin quoted by a second venue is not a collision.
        yahoo = _yahoo()
        self.assertFalse(server.yahoo_is_wrong(
            "BEAM-USD", yahoo, _same_coin(yahoo), True))

    def test_prices_that_converged_are_still_a_collision(self):
        # 2026-11-11: the newest closes are inside the old 20% gap, so the
        # single-price test missed it. The windows still give it away.
        yahoo, coin = _converged()
        gap = (abs(yahoo["points"][-1]["c"] - coin["points"][-1]["c"])
               / coin["points"][-1]["c"])
        self.assertLess(gap, server.REROUTE_GAP)
        self.assertTrue(server.yahoo_is_wrong("BEAM-USD", yahoo, coin, True))

    def test_a_constant_offset_is_still_a_level_disagreement(self):
        # Same shape, a venue quoting the coin 30% dear: the ratio is flat,
        # so the shape test says "one coin" and the level test still fires.
        yahoo = _yahoo()
        self.assertTrue(server.yahoo_is_wrong(
            "BEAM-USD", yahoo, _same_coin(yahoo, scale=1.30), True))

    def test_stamps_that_do_not_line_up_fall_back_to_the_last_close(self):
        # Too few shared bars for a shape reading: the one price both series
        # carry still decides, and no second upstream read is made.
        yahoo, coin = _yahoo(), _coin()
        coin["points"] = [dict(p, t=p["t"] + 1) for p in coin["points"]]
        with mock.patch.object(server.crypto, "latest_close") as probe:
            self.assertTrue(server.yahoo_is_wrong(
                "BEAM-USD", yahoo, coin, True))
        probe.assert_not_called()

    def test_every_venue_silent_keeps_yahoo(self):
        # `tried` says the chart read was made and answered nothing. There is
        # no independent price and no second upstream read.
        with mock.patch.object(server.crypto, "latest_close") as probe:
            self.assertFalse(server.yahoo_is_wrong(
                "BEAM-USD", _yahoo(), None, True))
        probe.assert_not_called()

    def test_a_standalone_call_still_uses_the_cached_close(self):
        # Backwards-compatible default: no chart supplied, no attempt made.
        with mock.patch.object(server.crypto, "latest_close",
                               return_value=0.00630):
            self.assertFalse(server.yahoo_is_wrong("BEAM-USD", _yahoo()))
        with mock.patch.object(server.crypto, "latest_close",
                               return_value=0.004288):
            self.assertTrue(server.yahoo_is_wrong("BEAM-USD", _yahoo()))

    def test_a_malformed_coin_chart_does_not_invent_a_price(self):
        with mock.patch.object(server.crypto, "latest_close") as probe:
            self.assertFalse(server.yahoo_is_wrong(
                "BEAM-USD", _yahoo(), {"points": [{"t": 1}]}, True))
        probe.assert_not_called()


class ChartRouteTests(unittest.TestCase):
    """The route draws the same series the recent table judges."""

    def _run(self, yahoo, coin):
        """`chart_data` with the wire mocked and `cached` running the producer."""
        def inline(key, producer):
            return producer()
        with mock.patch.object(server, "cached", side_effect=inline), \
             mock.patch.object(server, "yahoo_chart", return_value=yahoo), \
             mock.patch.object(server.crypto, "try_chart",
                               return_value=coin) as ask, \
             mock.patch.object(server.crypto, "latest_close") as close:
            out = server.chart_data("BEAM-USD", "3mo", "1d")
        return out, ask, close

    def test_the_chart_draws_the_coins_own_series(self):
        out, ask, close = self._run(_yahoo(), _coin())
        self.assertEqual(out["source"], "Kraken")
        self.assertAlmostEqual(out["points"][-1]["c"], 0.004288, places=8)
        self.assertEqual(out["trend"]["label"], "bullish")
        self.assertEqual(ask.call_count, 1)   # one chart read, not two
        close.assert_not_called()             # not dependent on a cached None

    def test_a_coin_that_agrees_with_yahoo_keeps_yahoo(self):
        yahoo = _yahoo()
        out, ask, close = self._run(yahoo, _same_coin(yahoo))
        self.assertEqual(out["source"], "Yahoo")
        self.assertEqual(ask.call_count, 1)
        close.assert_not_called()

    def test_a_converged_collision_draws_the_coins_own_series(self):
        # 2026-11-11: inside the old 20% gap, but two different windows.
        yahoo, coin = _converged()
        out, ask, close = self._run(yahoo, coin)
        self.assertEqual(out["source"], "Kraken")
        self.assertAlmostEqual(out["points"][-1]["c"], 0.004457, places=8)
        self.assertEqual(out["trend"]["label"], "bullish")
        self.assertEqual(ask.call_count, 1)
        close.assert_not_called()

    def test_every_venue_silent_keeps_yahoo_rather_than_a_dead_series(self):
        # The 2026-11-03 rule: a frozen delisted price is not a second opinion.
        # With no live crypto chart at all, Yahoo's answer stands.
        out, ask, close = self._run(_yahoo(), None)
        self.assertEqual(out["source"], "Yahoo")
        self.assertEqual(ask.call_count, 1)
        close.assert_not_called()

    def test_a_non_crypto_chart_is_untouched(self):
        equity = {"symbol": "AAPL", "type": "EQUITY", "source": "Yahoo",
                  "points": _series(300.0, 340.0), "historyTail": []}
        out, ask, close = self._run(equity, None)
        self.assertEqual(out["source"], "Yahoo")
        ask.assert_not_called()
        close.assert_not_called()


class WarmerTests(unittest.TestCase):
    """The row warmer applies the same rule with one upstream read."""

    def test_a_colliding_ticker_is_replaced_in_the_warm_copy(self):
        with mock.patch.object(server.crypto, "try_chart",
                               return_value=_coin()) as ask, \
             mock.patch.object(server.crypto, "latest_close") as close:
            self.assertEqual(server._reroute_crypto("BEAM-USD", _yahoo())["source"],
                             "Kraken")
        self.assertEqual(ask.call_count, 1)
        close.assert_not_called()

    def test_a_coin_that_agrees_keeps_its_warm_yahoo_copy(self):
        yahoo = _yahoo()
        with mock.patch.object(server.crypto, "try_chart",
                               return_value=_same_coin(yahoo)) as ask:
            self.assertIsNone(server._reroute_crypto("BEAM-USD", yahoo))
        self.assertEqual(ask.call_count, 1)

    def test_a_converged_collision_is_replaced_in_the_warm_copy(self):
        yahoo, coin = _converged()
        with mock.patch.object(server.crypto, "try_chart",
                               return_value=coin) as ask:
            self.assertEqual(server._reroute_crypto("BEAM-USD", yahoo)["source"],
                             "Kraken")
        self.assertEqual(ask.call_count, 1)


if __name__ == "__main__":
    unittest.main()
