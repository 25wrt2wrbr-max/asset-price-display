import datetime
import unittest
from unittest import mock

import coinsph
import server


def _ts(day: str, hour: int = 0) -> int:
    """Epoch seconds for a UTC date, optionally at an hour into it."""
    parsed = datetime.datetime.strptime(day, "%Y-%m-%d")
    return int(parsed.replace(tzinfo=datetime.timezone.utc).timestamp()) + hour * 3600


def _point(day: str, close: float, hour: int = 0) -> dict:
    return {"t": _ts(day, hour), "c": close}


# Sunday 2026-11-01, 11:05 in Manila: the FX week shut on Friday evening and
# reopens Monday 05:00, so both weekend days are the stablecoin's to answer.
NOW = _ts("2026-11-01", 3)


class SymbolTests(unittest.TestCase):
    """The weekend reading belongs to the peso pair and nothing else."""

    def test_both_spellings_are_the_peso_pair(self):
        for symbol in ("PHP=X", "USDPHP=X", "php=x", " USDPHP=X "):
            self.assertTrue(coinsph.is_usd_php(symbol), symbol)

    def test_other_pairs_and_instruments_are_not(self):
        for symbol in ("EURPHP=X", "JPYPHP=X", "USDPHP", "PHP", "BTC-USD", ""):
            self.assertFalse(coinsph.is_usd_php(symbol), symbol)


class DayTests(unittest.TestCase):
    """A bar belongs to the Manila day it falls in, which is what lines the
    two sources up: Yahoo's Sunday 21:00 GMT reopen is Monday 05:00 in Manila."""

    def test_the_sunday_reopen_is_monday(self):
        self.assertEqual(coinsph.manila_day(_ts("2026-11-01", 21)),
                         _ts("2026-11-02"))

    def test_a_midnight_bar_keeps_its_own_date(self):
        self.assertEqual(coinsph.manila_day(_ts("2026-10-30")),
                         _ts("2026-10-30"))

    def test_weekends_are_saturday_and_sunday(self):
        self.assertTrue(coinsph.is_weekend(_ts("2026-10-31")))   # Saturday
        self.assertTrue(coinsph.is_weekend(_ts("2026-11-01")))   # Sunday
        self.assertFalse(coinsph.is_weekend(_ts("2026-10-30")))  # Friday
        self.assertFalse(coinsph.is_weekend(_ts("2026-11-02")))  # Monday


class FillTests(unittest.TestCase):
    """Coins.ph's Saturdays and Sundays stand in for the days FX did not trade."""

    BARS = {
        _ts("2026-10-29"): 63.56,
        _ts("2026-10-30"): 63.63,
        _ts("2026-10-31"): 63.56,
        _ts("2026-11-01"): 63.49,
    }

    def _fill(self, points, bars=None, now=NOW):
        payload = self.BARS if bars is None else bars
        with mock.patch.object(coinsph, "daily",
                               return_value=(payload, 0.0, False)):
            return coinsph.fill(points, now=now)

    def test_the_forming_saturday_bar_is_replaced_by_the_stablecoins(self):
        # Yahoo stamps its newest daily FX bar at the moment it last refreshed,
        # which on a Saturday puts Friday's close under a Saturday date.
        points = [_point("2026-10-29", 63.836),
                  _point("2026-10-30", 63.597),
                  _point("2026-10-31", 63.72, hour=3)]
        filled, stamps, _age = self._fill(points)
        self.assertEqual([p["c"] for p in filled], [63.836, 63.597, 63.56, 63.49])
        self.assertEqual(stamps, [_ts("2026-10-31"), _ts("2026-11-01")])

    def test_both_weekend_days_are_added_when_yahoo_ends_on_friday(self):
        # Monday morning in Manila before 05:00: the FX week has not reopened,
        # so Yahoo still ends on Friday, but the weekend happened.
        points = [_point("2026-10-29", 63.836), _point("2026-10-30", 63.597)]
        filled, stamps, _age = self._fill(points, now=_ts("2026-11-02", 2))
        self.assertEqual([p["t"] for p in filled][-2:],
                         [_ts("2026-10-31"), _ts("2026-11-01")])
        self.assertEqual(len(stamps), 2)

    def test_a_weekday_is_never_touched(self):
        points = [_point("2026-10-29", 63.836), _point("2026-10-30", 63.597)]
        filled, _stamps, _age = self._fill(points)
        self.assertIn({"t": _ts("2026-10-29"), "c": 63.836}, filled)
        self.assertIn({"t": _ts("2026-10-30"), "c": 63.597}, filled)

    def test_days_before_the_drawn_window_are_not_added(self):
        points = [_point("2026-10-30", 63.597)]
        filled, stamps, _age = self._fill(points)
        self.assertEqual([p["t"] for p in filled][0], _ts("2026-10-30"))
        self.assertEqual(stamps, [_ts("2026-10-31"), _ts("2026-11-01")])

    def test_a_future_day_is_not_drawn(self):
        points = [_point("2026-10-30", 63.597)]
        filled, stamps, _age = self._fill(points, now=_ts("2026-10-31", 12))
        self.assertEqual(stamps, [_ts("2026-10-31")])
        self.assertEqual(len(filled), 2)

    def test_nothing_to_fill_leaves_the_series_alone(self):
        # Midweek, with a stablecoin series that has no weekend inside the window.
        bars = {_ts("2026-10-28"): 63.9, _ts("2026-10-29"): 63.56}
        points = [_point("2026-10-29", 63.836), _point("2026-10-30", 63.597)]
        filled, stamps, _age = self._fill(points, bars=bars, now=_ts("2026-10-30", 12))
        self.assertEqual(filled, points)
        self.assertEqual(stamps, [])

    def test_the_returned_series_is_sorted(self):
        points = [_point("2026-10-30", 63.597),
                  _point("2026-11-02", 63.488)]
        filled, _stamps, _age = self._fill(points, now=_ts("2026-11-02", 12))
        stamps = [p["t"] for p in filled]
        self.assertEqual(stamps, sorted(stamps))

    def test_an_outage_keeps_yahoos_bars(self):
        points = [_point("2026-10-30", 63.597)]
        with mock.patch.object(coinsph, "daily", side_effect=coinsph.CoinsError("down")):
            with self.assertRaises(coinsph.CoinsError):
                coinsph.fill(points, now=NOW)


class ServerWiringTests(unittest.TestCase):
    """The chart payload carries the weekend bars, and its badge reads them."""

    def _card(self):
        return {
            "symbol": "USDPHP=X",
            "name": "USD/PHP",
            "points": [_point("2026-10-29", 63.836),
                       _point("2026-10-30", 63.597),
                       _point("2026-10-31", 63.72, hour=3)],
            "trend": None,
            "source": "Yahoo",
        }

    def test_the_payload_names_every_weekend_bar(self):
        filled = [_point("2026-10-29", 63.836), _point("2026-10-30", 63.597),
                  _point("2026-10-31", 63.56), _point("2026-11-01", 63.49)]
        with mock.patch.object(coinsph, "fill", return_value=(
                filled, [_ts("2026-10-31"), _ts("2026-11-01")], 12.0)):
            out = server.weekend_proxy(self._card())
        self.assertEqual(out["points"], filled)
        self.assertEqual(out["weekendProxy"]["stamps"],
                         [_ts("2026-10-31"), _ts("2026-11-01")])
        self.assertEqual(out["weekendProxy"]["pair"], "USDC/PHP")
        self.assertEqual(out["weekendProxy"]["source"], "Coins.ph")
        self.assertEqual(out["weekendProxy"]["price"], 63.49)
        self.assertEqual(out["weekendProxy"]["age"], 12)

    def test_the_newest_weekend_bar_says_whose_price_it_is(self):
        filled = [_point("2026-10-30", 63.597), _point("2026-11-01", 63.49)]
        card = self._card()
        card["points"] = filled
        card["weekendProxy"] = {"source": "Coins.ph", "pair": "USDC/PHP",
                                "stamps": [_ts("2026-10-31"), _ts("2026-11-01")]}
        self.assertEqual(server.last_bar_basis(card, now=NOW), "weekend")

    def test_a_weekday_newest_bar_keeps_its_own_basis(self):
        card = self._card()
        card["weekendProxy"] = {"stamps": [_ts("2026-10-31")]}
        self.assertEqual(server.last_bar_basis(card, now=NOW), "close")

    def test_an_unfillable_symbol_is_returned_unchanged(self):
        card = self._card()
        with mock.patch.object(coinsph, "fill", side_effect=coinsph.CoinsError("down")):
            self.assertIs(server.weekend_proxy(card), card)
        with mock.patch.object(coinsph, "fill", return_value=(
                card["points"], [], 0.0)):
            self.assertIs(server.weekend_proxy(card), card)


class ParseTests(unittest.TestCase):
    """The endpoint answers in milliseconds; a day key is a second."""

    ROW_SATURDAY = [1793404800000, "63.63", "63.63", "63.53", "63.56",
                    "29215848.87", 1793491199999, "1863048791.539", 24240,
                    "12871876.76", "821015167.64"]

    def test_a_millisecond_stamp_becomes_the_right_day(self):
        bars = coinsph._parse([self.ROW_SATURDAY])
        self.assertEqual(list(bars), [_ts("2026-10-31")])
        self.assertEqual(bars[_ts("2026-10-31")], 63.56)

    def test_a_row_with_no_trade_is_skipped(self):
        zero = list(self.ROW_SATURDAY)
        zero[4] = "0"
        bars = coinsph._parse([zero, self.ROW_SATURDAY])
        self.assertEqual(list(bars), [_ts("2026-10-31")])

    def test_no_usable_rows_is_an_outage_not_an_empty_weekend(self):
        for rows in ([], "not json", [[None, "1", "1", "1", None]]):
            with self.assertRaises(coinsph.CoinsError):
                coinsph._parse(rows)


class DailyTests(unittest.TestCase):
    """One fetch serves every span, and a stale copy is reported as stale."""

    def setUp(self):
        patcher = mock.patch.object(coinsph, "_cache", None)
        patcher.start()
        self.addCleanup(patcher.stop)
        loader = mock.patch.object(coinsph.diskcache, "load", return_value=None)
        self.load = loader.start()
        self.addCleanup(loader.stop)
        storer = mock.patch.object(coinsph.diskcache, "store")
        self.store = storer.start()
        self.addCleanup(storer.stop)

    def _series(self):
        return {_ts("2026-10-31"): 63.56, _ts("2026-11-01"): 63.49}

    def test_a_warm_copy_answers_without_asking_again(self):
        with mock.patch.object(coinsph, "_fetch", return_value=self._series()) as fetch:
            first, age, stale = coinsph.daily()
            second, _age, _stale = coinsph.daily()
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first, self._series())
        self.assertFalse(stale)
        self.assertLess(age, coinsph.CACHE_TTL)
        self.store.assert_called_once()

    def test_an_outage_serves_the_copy_it_already_holds(self):
        with mock.patch.object(coinsph, "_fetch", return_value=self._series()):
            coinsph.daily()
        # Age the held copy past the refresh window but inside the keep window.
        coinsph._cache = (coinsph._cache[0] - coinsph.CACHE_TTL - 1, coinsph._cache[1])
        with mock.patch.object(coinsph, "_fetch",
                               side_effect=coinsph.CoinsError("down")):
            bars, age, stale = coinsph.daily()
        self.assertEqual(bars, self._series())
        self.assertTrue(stale)
        self.assertGreater(age, coinsph.CACHE_TTL)

    def test_an_outage_with_only_a_stale_disk_copy_reports_it(self):
        coinsph.diskcache.load.return_value = (
            __import__("time").time() - 2 * coinsph.DAY,
            {str(k): v for k, v in self._series().items()})
        with mock.patch.object(coinsph, "_fetch",
                               side_effect=coinsph.CoinsError("down")):
            bars, age, stale = coinsph.daily()
        self.assertEqual(bars, self._series())
        self.assertTrue(stale)
        self.assertGreater(age, coinsph.DAY)

    def test_an_outage_with_nothing_raises(self):
        with mock.patch.object(coinsph, "_fetch",
                               side_effect=coinsph.CoinsError("down")):
            with self.assertRaises(coinsph.CoinsError):
                coinsph.daily()


if __name__ == "__main__":
    unittest.main()
