"""A series the source stopped printing is not a price, and is not a verdict.

The reader's report, 2026-11-07: "ATKR last price was October. wtf. don't show
me this. can you remove/filter those stale stocks available in app.ondo.finance?
i saw this ticker in 'Leaning bullish - not confirmed'".

Measured the same day, so the numbers are on the record:

* `ATKR` answered `/api/chart` with **51 bars ending 2026-10-16**, the price
  frozen at $94.96 (the company had been taken over), `lastBarBasis: "close"`;
* the classifier read those 51 bars as neutral +0.46 with `lean: "bullish"` and
  `onset.steady_lean` found it steady (held 5 of 5), so the sweep put it at the
  **top of the leaning table** at $94.96 -- a dead price presented as a
  near-miss to buy;
* the other 473 names on the shelf answered with a bar **0.3 days** old.

Three things are pinned here: the gap test itself (`stale_gap`, measured against
the clock for a live read and against the sweep's own moment for a copy read
back from disk), the United States leg leaving such a name off **both** tables
while the note names it, and the chart withholding the verdict and the odds
while saying how old the newest bar is. Only the market the rule was written for
is filtered -- the Philippine legs close for long holidays, so a calendar gap
there is a calendar fact.
"""

import time
import unittest
from unittest import mock

import recent
import server
import trend


NOW = 1_800_000_000.0        # a fixed clock: none of these depend on today
DAY = 86_400


def series(days=70, last_bar=None, step=1.0, volume=1_000_000):
    """A daily series whose newest bar sits at `last_bar` (default: just now)."""
    end = NOW - 60 if last_bar is None else last_bar
    stamps = [int(end - (days - 1 - i) * DAY) for i in range(days)]
    closes = [round(100.0 + i * step, 6) for i in range(days)]
    return stamps, closes, [volume] * days


def shelf(*tickers):
    return recent.ondolist._record({(t.lower() + "on") for t in tickers},
                                   1_700_000_000.0, False)


def fetch(bars_for):
    def _fetch(tickers):
        return {ticker: bars_for[ticker] for ticker in tickers
                if ticker in bars_for}
    return _fetch


def yahoo_card(last_bar, closes=None, symbol="ATKR"):
    """The shape `chart_data` is handed by `cached` for a Yahoo chart."""
    stamps, series_closes, volumes = series(last_bar=last_bar)
    points = [{"t": t, "c": c, "v": v}
              for t, c, v in zip(stamps, closes or series_closes, volumes)]
    return {
        "symbol": symbol,
        "name": "Atkore Inc",
        "currency": "USD",
        "exchange": "NYSE",
        "type": "EQUITY",
        "timezone": "America/New_York",
        "priceHint": 2,
        "previousClose": points[-2]["c"],
        "marketPrice": points[-1]["c"],
        "extendedLastBar": False,
        "livePrint": None,
        "session": None,
        "points": points,
        "historyTail": [],
        "source": "Yahoo",
    }


class GapTests(unittest.TestCase):
    def test_a_current_series_has_no_gap(self):
        stamps, _closes, _volumes = series(last_bar=NOW - 6 * 3600)
        with mock.patch.object(recent.time, "time", return_value=NOW):
            self.assertIsNone(recent.stale_gap(stamps))

    def test_a_series_that_stopped_three_weeks_ago_has_one(self):
        # ATKR itself: last bar 2026-10-16, measured 21.3 days later.
        stamps, _closes, _volumes = series(last_bar=NOW - 21 * DAY)
        with mock.patch.object(recent.time, "time", return_value=NOW):
            gap = recent.stale_gap(stamps)
        self.assertIsNotNone(gap)
        self.assertAlmostEqual(gap, 21.0, places=3)

    def test_the_boundary_is_five_days(self):
        with mock.patch.object(recent.time, "time", return_value=NOW):
            self.assertIsNone(recent.stale_gap([int(NOW - 5 * DAY)]))
            self.assertIsNotNone(recent.stale_gap([int(NOW - 5 * DAY - 60)]))

    def test_no_bars_is_not_a_stopped_series(self):
        # A fetch that answered nothing is `missing`, and it is counted there.
        # An absent series is not a negative verdict (invariant 3).
        self.assertIsNone(recent.stale_gap([]))
        self.assertIsNone(recent.stale_gap(None))

    def test_a_copy_is_judged_against_the_moment_it_was_swept(self):
        # A table swept six days ago holds six-day-old bars that were current
        # then. Judged against today it would read as a table of dead series --
        # a fetch-age fact dressed up as a stock's.
        swept_at = NOW - 6 * DAY
        row = {"market": "US", "ticker": "ACN", "last": int(swept_at - 3600)}
        kept, stale = recent.drop_stale([row], swept_at)
        self.assertEqual([r["ticker"] for r in kept], ["ACN"])
        self.assertEqual(stale, [])

    def test_a_row_stale_when_it_was_swept_is_dropped_and_named(self):
        swept_at = NOW - 6 * DAY
        row = {"market": "US", "ticker": "ATKR", "chartSymbol": "ATKR",
               "last": int(swept_at - 21 * DAY)}
        kept, stale = recent.drop_stale([row], swept_at)
        self.assertEqual(kept, [])
        self.assertEqual(stale[0]["ticker"], "ATKR")
        self.assertAlmostEqual(stale[0]["days"], 21, delta=1)
        self.assertEqual(len(stale[0]["lastBar"]), 10)   # YYYY-MM-DD

    def test_only_the_united_states_leg_is_re_filtered(self):
        # The PSE shuts from 23 December to 4 January, so a calendar gap there
        # is the exchange's calendar and not a dead series.
        swept_at = NOW
        ph = {"market": "Philippines", "ticker": "PHR", "last": int(NOW - 12 * DAY)}
        kept, stale = recent.drop_stale([ph], swept_at)
        self.assertEqual(kept, [ph])
        self.assertEqual(stale, [])


class ScanTests(unittest.TestCase):
    """The United States leg of both tables, with the clock pinned."""

    def us_rows(self, bars_for, names):
        with mock.patch.object(recent.time, "time", return_value=NOW):
            return recent.us_rows(fetch(bars_for), shelf(*names))

    def test_a_stale_name_is_on_neither_table(self):
        # ATKR's own case: neutral on its frozen window, in the bullish hold
        # band, steady -- and off the table anyway.
        bars = {"ATKR": series(last_bar=NOW - 21 * DAY),
                "ACN": series(last_bar=NOW - 6 * 3600)}
        rows, stats = self.us_rows(bars, ("ATKR", "ACN"))
        self.assertEqual([row["ticker"] for row in rows], ["ACN"])
        self.assertEqual([entry["ticker"] for entry in stats["stale"]], ["ATKR"])
        self.assertEqual(stats["stale"][0]["chartSymbol"], "ATKR")

    def test_a_stale_series_is_not_counted_as_an_outage(self):
        bars = {"ATKR": series(last_bar=NOW - 21 * DAY),
                "ACN": series(last_bar=NOW - 6 * 3600)}
        _rows, stats = self.us_rows(bars, ("ATKR", "ACN", "ZZZZ"))
        self.assertEqual(stats["missing"], ["ZZZZ"])   # the outage, and only it
        self.assertEqual(stats["universe"], 3)

    def test_a_series_three_days_behind_is_still_a_row(self):
        # A weekend plus a market holiday is three or four days, and a name
        # that has not traded since Friday is not a stopped name.
        bars = {"ACN": series(last_bar=NOW - 3 * DAY)}
        rows, stats = self.us_rows(bars, ("ACN",))
        self.assertEqual([row["ticker"] for row in rows], ["ACN"])
        self.assertEqual(stats["stale"], [])

    def test_the_note_names_what_left_the_table(self):
        payload = {"rows": [], "leaning": [], "stats": {"US": {
            "universe": 474, "missing": [], "shelf": True,
            "stale": [{"ticker": "ATKR", "chartSymbol": "ATKR",
                       "lastBar": "2026-10-16", "days": 21}]}}}
        note = recent.summarize(payload)
        self.assertIn("US: 474 scanned", note)
        self.assertIn("1 stale series hidden: ATKR (last bar 2026-10-16)", note)

    def test_a_long_list_of_stale_names_is_counted_not_recited(self):
        entries = [{"ticker": "T%d" % i, "lastBar": "2026-10-16", "days": 21}
                   for i in range(5)]
        note = recent.summarize({"rows": [], "leaning": [], "stats": {
            "US": {"universe": 474, "missing": [], "stale": entries}}})
        self.assertIn("5 stale series hidden", note)
        self.assertIn("and 2 more", note)


class ChartTests(unittest.TestCase):
    """The chart: the line is drawn, the verdict and the odds are not."""

    def route(self, card, span="3mo", interval="1d", symbol="ATKR"):
        with mock.patch.object(server, "cached", return_value=card), \
                mock.patch.object(server.time, "time", return_value=NOW):
            return server.chart_data(symbol, span, interval)

    def test_a_stopped_series_carries_no_verdict_and_no_odds(self):
        out = self.route(yahoo_card(NOW - 21 * DAY))
        self.assertEqual(out["staleDays"], 21)
        self.assertEqual(len(out["staleBar"]), 10)
        self.assertIsNone(out["trend"])
        self.assertIsNone(out["profitProbability"])
        # The history that exists is still drawn: this is a statement about the
        # series, not a fetch that failed.
        self.assertGreater(len(out["points"]), 40)

    def test_a_current_series_keeps_its_verdict_and_gains_no_stale_fields(self):
        out = self.route(yahoo_card(NOW - 6 * 3600), symbol="ACN")
        self.assertNotIn("staleDays", out)
        self.assertNotIn("staleBar", out)
        self.assertIsNotNone(out["trend"])
        self.assertIsNotNone(out["profitProbability"])

    def test_the_verdict_withheld_is_the_decorated_one_it_would_have_shown(self):
        # Not a second classifier: with the clock moved back to before the
        # series stopped, the same card answers the classifier's own call.
        fresh = yahoo_card(NOW - 21 * DAY)
        out = self.route(fresh)
        self.assertIsNone(out["trend"])
        self.assertIsNotNone(trend.classify([p["c"] for p in fresh["points"]]))

    def test_a_copys_stale_claim_is_dropped_when_the_series_is_current(self):
        # The payload is decided from the drawn bars and the clock on every
        # read, never carried -- the same rule `lastBarBasis` follows.
        card = dict(yahoo_card(NOW - 6 * 3600), staleDays=21,
                    staleBar="2026-10-16")
        out = self.route(card)
        self.assertNotIn("staleDays", out)
        self.assertNotIn("staleBar", out)
        self.assertIsNotNone(out["trend"])

    def test_a_weekly_bar_is_not_a_session_late(self):
        # A weekly bar is stamped at the start of its week, so its age says
        # nothing about whether the instrument is still printing.
        out = self.route(yahoo_card(NOW - 21 * DAY), interval="1wk")
        self.assertNotIn("staleDays", out)
        self.assertIsNotNone(out["trend"])

    def test_another_source_is_left_alone(self):
        # The PSE, the funds and the bonds close for long holidays. Their own
        # rules decide freshness; this one is about the US market's calendar.
        card = yahoo_card(NOW - 21 * DAY, symbol="PSE:TEL")
        card["source"] = "TradingView"
        out = self.route(card, symbol="PSE:TEL")
        self.assertNotIn("staleDays", out)
        self.assertIsNotNone(out["trend"])


class SeedTests(unittest.TestCase):
    """A copy read back from disk must not put the row back on screen."""

    def seed(self, payload, fetched_at):
        saved = server._recent_state.copy()
        self.addCleanup(server._recent_state.update, saved)
        with mock.patch.object(server.diskcache, "load",
                               return_value=(fetched_at, payload)), \
                mock.patch.object(server.ondolist, "saved", return_value=None):
            server._recent_state["payload"] = None
            server.seed_recent()
            return server.recent_state()

    def row(self, ticker, last):
        return {"market": "US", "symbol": ticker, "chartSymbol": ticker,
                "ticker": ticker, "name": ticker, "kind": "Common stock",
                "price": 94.96, "currency": "USD", "direction": "neutral",
                "lean": "bullish", "score": 0.46, "progress": 0.86,
                "bars": 51, "last": int(last), "turnover": None,
                "chartable": True}

    # A stored copy always holds rows; the leaning list is the half that is
    # being tested here, so one fund row stands in for the table itself.
    FUND = {"market": "Philippine fund", "symbol": "FUND:BPI-INFRA",
            "ticker": "BPI-INFRA", "name": "BPI Philippine Infrastructure Fund",
            "kind": "Net asset value", "price": 1.53, "currency": "PHP",
            "direction": "bullish", "since": 1792373400, "run": 30,
            "turnover": None, "chartable": True}

    def test_a_stale_row_is_dropped_from_the_seeded_leaning_list(self):
        swept = NOW - 6 * DAY
        payload = {"rows": [dict(self.FUND)],
                   "stats": {"US": {"universe": 474, "missing": [],
                                    "shelf": True}},
                   "leaning": [self.row("ATKR", swept - 21 * DAY),
                               self.row("ACN", swept - 3600)]}
        out = self.seed(payload, swept)
        self.assertEqual([row["ticker"] for row in out["leaning"]], ["ACN"])
        note = out["note"]
        self.assertIn("1 stale series hidden: ATKR", note)

    def test_a_current_row_survives_even_in_a_copy_a_week_old(self):
        # Judged against the sweep's own moment: bars swept last week were
        # current when they were fetched, and the table is not a lie for it.
        swept = NOW - 7 * DAY
        payload = {"rows": [dict(self.FUND)],
                   "stats": {"US": {"universe": 474, "missing": [],
                                    "shelf": True}},
                   "leaning": [self.row("ACN", swept - 3600)]}
        out = self.seed(payload, swept)
        self.assertEqual([row["ticker"] for row in out["leaning"]], ["ACN"])
        self.assertNotIn("stale series hidden", out["note"])


if __name__ == "__main__":
    unittest.main()
