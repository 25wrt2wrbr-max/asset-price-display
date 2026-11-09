"""The recent tables are the Ondo shelf, not a turnover ranking (2026-11-07).

Asked for by name: "the limit is just what's available @ app.ondo.finance, ok?
no longer trading volume, for both bullish list and 'leaning bullish - not
confirmed'", then "include all stocks & ETFs, and intelligent portfolios of
app.ondo.finance, in both scans".

Two properties carry the change, and each is pinned here:

* the **universe** is the shelf -- a name outside it is never fetched, a name
  inside it is fetched however thinly it trades, and the peso-volume floor does
  not apply to it (that floor survives for Philippine stocks alone, see
  `FloorTests`);
* the **portfolios** are judged on their own token price, on the chart's own
  ninety-day window, and a basket the shelf has stopped listing leaves the
  scan without being counted as an outage.

The one job the turnover ranking keeps is the fallback: with no readable shelf
there is no universe at all, and an outage must not empty the table.
"""

import time
import unittest
from unittest import mock

import ondo
import ondolist
import recent


def _shelf(*tickers, portfolios=()):
    """A shelf record holding one token per ticker, the way the site spells it."""
    return ondolist._record({(t.lower() + "on") for t in tickers},
                            1_800_000_000.0, False,
                            portfolios={(p.lower() + "on") for p in portfolios})


def _climbing(days=70, start=100.0, step=1.0, end=None, volume=1_000_000):
    """A rising daily series, newest bar at `end` (default: a minute ago)."""
    end = time.time() - 60 if end is None else end
    stamps = [int(end - (days - 1 - i) * 86_400) for i in range(days)]
    closes = [round(start + i * step, 6) for i in range(days)]
    return stamps, closes, [volume] * days


def _fake_fetch(bars_for, asked=None):
    """A `fetch_us_bars` double that answers from a dict and records the ask."""
    def fetch(tickers):
        if asked is not None:
            asked.append(list(tickers))
        out = {}
        for ticker in tickers:
            series = bars_for.get(ticker)
            if series is not None:
                out[ticker] = series
        return out
    return fetch


class UniverseTests(unittest.TestCase):
    def test_the_universe_is_the_shelf_and_nothing_else(self):
        asked = []
        bars = {"NVDA": _climbing(), "SPY": _climbing()}
        rows, stats = recent.us_rows(_fake_fetch(bars, asked),
                                     _shelf("NVDA", "SPY"))
        self.assertEqual(sorted(asked[0]), ["NVDA", "SPY"])
        self.assertEqual(stats["universe"], 2)
        self.assertTrue(stats["shelf"])
        self.assertEqual({row["ticker"] for row in rows}, {"NVDA", "SPY"})

    def test_a_name_outside_the_shelf_is_never_asked_for(self):
        # The reader's own complaint: ACN was dropped by a turnover cutoff, not
        # by a verdict. A name the shop does not list must not be scanned at
        # all -- and one it does list must be, however it ranks by turnover.
        asked = []
        bars = {"NVDA": _climbing()}
        recent.us_rows(_fake_fetch(bars, asked), _shelf("NVDA"))
        self.assertEqual(asked[0], ["NVDA"])

    def test_a_class_share_is_fetched_under_yahoos_spelling(self):
        asked = []
        bars = {"BRK-B": _climbing()}
        rows, _ = recent.us_rows(_fake_fetch(bars, asked), _shelf("BRK.B"))
        self.assertEqual(asked[0], ["BRK-B"])
        self.assertEqual([row["ticker"] for row in rows], ["BRK.B"])
        self.assertEqual([row["chartSymbol"] for row in rows], ["BRK-B"])

    def test_a_ticker_yahoo_cannot_price_is_counted_not_judged(self):
        bars = {"NVDA": _climbing()}
        rows, stats = recent.us_rows(_fake_fetch(bars), _shelf("NVDA", "ZZZZ"))
        self.assertEqual(stats["missing"], ["ZZZZ"])
        self.assertEqual([row["ticker"] for row in rows], ["NVDA"])

    def test_a_thin_name_is_still_a_row(self):
        # Volume is not the limit any more (2026-11-07). A name that traded a
        # handful of shares is judged on its price like any other.
        bars = {"NVDA": _climbing(volume=10)}
        rows, _ = recent.us_rows(_fake_fetch(bars), _shelf("NVDA"))
        self.assertEqual([row["ticker"] for row in rows], ["NVDA"])

    def test_yahoos_name_and_kind_replace_the_shelfs_placeholder(self):
        bars = {"NVDA": _climbing() + (
            {"name": "NVIDIA Corporation", "kind": "Common stock",
             "currency": "USD"},)}
        rows, _ = recent.us_rows(_fake_fetch(bars), _shelf("NVDA"))
        self.assertEqual(rows[0]["name"], "NVIDIA Corporation")

    def test_the_shelf_spelling_is_the_fallback_name(self):
        rows, _ = recent.us_rows(_fake_fetch({"NVDA": _climbing()}),
                                 _shelf("NVDA"))
        self.assertEqual(rows[0]["name"], "NVDA")

    def test_no_shelf_falls_back_to_the_turnover_universe(self):
        # An outage is not a listing fact: with no shelf there is no universe,
        # so the leg says it fell back instead of emptying the table.
        asked = []
        universe = [{"ticker": "AAPL", "chartSymbol": "AAPL", "name": "Apple",
                     "kind": "Common stock", "currency": "USD"}]
        with mock.patch.object(recent.markets, "us_universe",
                               return_value=universe) as scan:
            rows, stats = recent.us_rows(
                _fake_fetch({"AAPL": _climbing()}, asked), None)
        scan.assert_called_once()
        self.assertFalse(stats["shelf"])
        self.assertEqual([row["ticker"] for row in rows], ["AAPL"])

    def test_an_empty_shelf_is_an_error_not_an_empty_table(self):
        with self.assertRaises(recent.RecentError):
            recent.us_rows(_fake_fetch({}), _shelf())


class PortfolioTests(unittest.TestCase):
    def _bars(self, days=70):
        end = time.time() - 60
        return [{"t": int(end - (days - 1 - i) * 86_400),
                 "c": round(5.0 + i * 0.01, 6)} for i in range(days)]

    def test_every_portfolio_on_the_shelf_is_judged(self):
        tokens = ondo.portfolio_tokens()
        listed = [token["ticker"] for token in tokens]
        with mock.patch.object(ondo, "bars_for", return_value=self._bars()):
            rows, stats = recent.ondo_portfolio_rows(_shelf(portfolios=listed))
        self.assertEqual({row["ticker"] for row in rows}, set(listed))
        self.assertEqual({row["market"] for row in rows}, {"Ondo portfolio"})
        self.assertEqual(stats["missing"], [])
        self.assertEqual(stats["universe"], len(listed))

    def test_a_neutral_basket_is_scanned_but_not_a_row(self):
        # A basket that is neither bullish nor leaning bullish is not a row --
        # and the note still has to say it was looked at, so `universe` counts
        # the judged, not the kept.
        flat = [{"t": int(time.time()) - 60 - (59 - i) * 86_400, "c": 5.0}
                for i in range(60)]
        with mock.patch.object(ondo, "bars_for", return_value=flat):
            rows, stats = recent.ondo_portfolio_rows(
                _shelf(portfolios=["MAG7X"]))
        self.assertEqual(rows, [])
        self.assertEqual(stats, {"universe": 1, "missing": []})

    def test_a_portfolio_row_opens_its_own_chart(self):
        with mock.patch.object(ondo, "bars_for", return_value=self._bars()):
            rows, _ = recent.ondo_portfolio_rows(
                _shelf(portfolios=["MAG7X"]))
        row = rows[0]
        self.assertEqual(row["chartSymbol"], row["symbol"])
        self.assertTrue(row["symbol"].startswith("ONDO:"))
        self.assertEqual(row["ticker"], "MAG7X")
        self.assertEqual(row["kind"], ondo.PORTFOLIO)

    def test_a_portfolio_has_no_traded_volume(self):
        with mock.patch.object(ondo, "bars_for", return_value=self._bars()):
            rows, _ = recent.ondo_portfolio_rows(_shelf(portfolios=["MAG7X"]))
        self.assertIsNone(rows[0]["turnover"])

    def test_a_basket_off_the_shelf_is_not_scanned(self):
        # Not a fetch failure and not a verdict: the shop stopped selling it.
        with mock.patch.object(ondo, "bars_for", return_value=self._bars()):
            rows, stats = recent.ondo_portfolio_rows(_shelf(portfolios=["YLD5"]))
        self.assertEqual([row["ticker"] for row in rows], ["YLD5"])
        self.assertEqual(stats["missing"], [])
        self.assertEqual(stats["universe"], 1)

    def test_an_unreadable_portfolio_is_counted_not_judged(self):
        def bars_for(token, span):
            if token["ticker"] == "MAG7X":
                raise ondo.OndoError("wire down")
            return self._bars()

        with mock.patch.object(ondo, "bars_for", side_effect=bars_for):
            rows, stats = recent.ondo_portfolio_rows(
                _shelf(portfolios=["MAG7X", "BRAIN"]))
        self.assertEqual(stats["missing"], ["MAG7X"])
        self.assertEqual([row["ticker"] for row in rows], ["BRAIN"])

    def test_no_shelf_still_judges_the_known_portfolios(self):
        # The tokens are a fixed list in `ondo.py`; the shelf only decides
        # which of them is on sale. With no shelf, the list stands.
        with mock.patch.object(ondo, "bars_for", return_value=self._bars()):
            rows, _ = recent.ondo_portfolio_rows(None)
        self.assertEqual({row["ticker"] for row in rows},
                         {token["ticker"] for token in ondo.portfolio_tokens()})


class NoteTests(unittest.TestCase):
    def test_the_note_says_the_united_states_leg_was_the_shelf(self):
        note = recent.summarize({"rows": [], "leaning": [],
                                 "stats": {"US": {"universe": 478,
                                                  "missing": [], "shelf": True}}})
        self.assertIn("US: 478 scanned", note)

    def test_the_note_names_a_fallback_as_one(self):
        note = recent.summarize({"rows": [], "leaning": [],
                                 "stats": {"US": {"universe": 130,
                                                  "missing": [], "shelf": False}}})
        self.assertIn("US (turnover universe): 130 scanned", note)

    def test_the_note_no_longer_claims_a_volume_floor(self):
        note = recent.summarize({"rows": [], "leaning": [], "stats": {}})
        self.assertNotIn("volume hidden", note)


class FloorTests(unittest.TestCase):
    """The peso floor survives for Philippine stocks, and only for them.

    Asked for by name, 2026-11-07: "there should still be a volume floor for
    philippines stocks. PHP1M". PAL is the case that made it visible -- bullish
    at +0.77 on ₱311,040 -- so it is hidden from the table, and the note has to
    say so, because a row that is bullish on its own chart and absent from the
    table with no explanation is what the reader objected to in the first place.
    """

    PAL = {"market": "Philippines", "symbol": "PSE:PAL", "ticker": "PAL",
           "name": "PAL Holdings, Inc.", "kind": "EQUITY",
           "direction": "bullish", "since": 1792373400, "run": 14,
           "currency": "PHP", "price": 4.32, "turnover": 311_040.0,
           "chartable": True}
    PHR = dict(PAL, symbol="PSE:PHR", ticker="PHR", name="PH Resorts",
               price=0.475, turnover=2_422_500.0, since=1792373401)

    def scan(self, rows, sweep_leaning=(), us_rows=()):
        with mock.patch.object(recent, "us_rows", return_value=(list(us_rows), {})), \
             mock.patch.object(recent, "rate_rows", return_value=([], {})), \
             mock.patch.object(recent, "ondo_portfolio_rows",
                               return_value=([], {})), \
             mock.patch.object(recent, "crypto_rows", return_value=([], {})), \
             mock.patch.object(recent, "bond_rows", return_value=([], {})), \
             mock.patch.object(recent, "fund_rows", return_value=([], {})), \
             mock.patch.object(recent.markets, "php_per_usd",
                               return_value={"phpPerUsd": 63.0}):
            return recent.scan(list(rows),
                               fetch_us_bars=lambda symbols: {},
                               ph_sweep_leaning=list(sweep_leaning),
                               ondo_shelf=_shelf("NVDA"))

    def test_a_philippine_stock_under_one_million_is_hidden(self):
        payload = self.scan([self.PAL])
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["stats"]["Philippines"]["hidden"], 1)

    def test_a_philippine_stock_over_one_million_stays(self):
        payload = self.scan([self.PAL, self.PHR])
        self.assertEqual([row["ticker"] for row in payload["rows"]], ["PHR"])

    def test_a_thin_philippine_leaning_row_is_hidden_too(self):
        # The floor is a rule about the market, not about one of the two tables.
        lean = dict(self.PAL, direction="neutral", lean="bullish",
                    progress=0.6, score=0.2, significance=1.1)
        payload = self.scan([], sweep_leaning=[lean])
        self.assertEqual(payload["leaning"], [])
        self.assertEqual(payload["stats"]["Philippines"]["hidden"], 1)

    def test_the_note_says_what_the_floor_hid(self):
        payload = self.scan([self.PAL])
        payload["note"] = recent.summarize(payload)
        self.assertIn("· 1 below ₱1,000,000 volume hidden", payload["note"])

    def test_an_ondo_row_is_not_floored(self):
        # The shelf is the limit there; a swing of ₱311k does not apply.
        thin = dict(self.PAL, market="US", symbol="ACN", ticker="ACN",
                    name="Accenture plc", currency="USD", turnover=18_000.0)
        with mock.patch.object(recent.markets, "php_per_usd",
                               return_value={"phpPerUsd": 63.0}):
            payload = self.scan([], us_rows=[thin])
        self.assertEqual([row["ticker"] for row in payload["rows"]], ["ACN"])


if __name__ == "__main__":
    unittest.main()
