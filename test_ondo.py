"""OUSG, the token Yahoo has no spelling for, and the price behind it.

Measured 2026-11-02, the day a reader typed "ousg" into the search box and got
nothing: `/v1/finance/search?q=ousg` answered 200 with an empty quote list,
`/lookup?query=ousg` reported `total: 0`, and every chart spelling of the symbol
(`OUSG`, `OUSG-USD`, `OUSG29256-USD`) was a 404 -- while the sibling `USDY29256-USD`
exists, so this is a gap in the index and not an outage.

The tests pin what a reader is offered and what the chart says about the newest
point, with the wire mocked out. The live route is checked separately against
`/api/search?q=ousg` and `/api/chart?symbol=ONDO:OUSG`.
"""
import json
import time
import unittest
from unittest import mock

import ondo
import onset
import probability


def _document(symbol="OUSG", days=90, start=116.0, step=0.011, end=None,
              chain="ethereum"):
    """DeFiLlama's chart document -> one point a day, ending at `end`.

    The series accrues the way the real one does: a short-term Treasury fund's
    per-token value steps up, it does not oscillate.
    """
    end = time.time() - 60 if end is None else end
    prices = []
    for i in range(days):
        stamp = int(end - (days - 1 - i) * 86_400)
        prices.append({"timestamp": stamp, "price": round(start + i * step, 6)})
    address = ondo.TOKENS[0]["address"] if symbol == "OUSG" else "0xdead"
    return {"coins": {"%s:%s" % (chain, address): {"symbol": symbol,
                                                   "prices": prices}}}


class SearchTests(unittest.TestCase):
    """A query the index cannot answer still has to find the token."""

    def test_its_ticker_finds_it(self):
        rows = ondo.search_tokens("ousg")
        self.assertEqual([row["symbol"] for row in rows], ["ONDO:OUSG"])
        self.assertEqual(rows[0]["name"],
                         "Ondo Short-Term U.S. Government Bond Fund")

    def test_the_words_a_reader_types_find_it(self):
        for query in ("OUSG", "ousg", "ondo short term",
                      "short-term treasury", "tokenized treasury"):
            self.assertEqual([row["symbol"] for row in
                              ondo.search_tokens(query)],
                             ["ONDO:OUSG"], query)

    def test_the_issuer_word_lists_the_tokens(self):
        # "ondo" is the shop's own name, so it answers with the shop's tokens
        # rather than with one of them -- the fund first, the portfolios after
        # it, in the order they are declared. Every row is an `ONDO:` symbol,
        # because none of these has a Yahoo listing to fall back on.
        rows = ondo.search_tokens("ondo")
        self.assertEqual(rows[0]["symbol"], "ONDO:OUSG")
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row["symbol"].startswith("ONDO:"), row)

    def test_a_portfolio_is_findable_by_its_own_code(self):
        rows = ondo.search_tokens("mag7x")
        self.assertEqual([row["symbol"] for row in rows], ["ONDO:MAG7X"])
        self.assertEqual(rows[0]["type"], ondo.PORTFOLIO)

    def test_another_ondo_product_is_not_this_one(self):
        # Yahoo lists the tokenized stocks itself (`QQQON-USD`), so "ondo qqq"
        # must not be answered with a Treasury fund.
        for query in ("ondo qqq", "onda", "ousga", "", "   ", "spy"):
            self.assertEqual(ondo.search_tokens(query), [], query)

    def test_a_supplement_row_looks_like_yahoos(self):
        row = ondo.search_tokens("ousg")[0]
        self.assertEqual(sorted(row), ["exchange", "name", "symbol", "type"])
        self.assertEqual(row["exchange"], "Ondo")
        self.assertEqual(row["type"], "Tokenized fund")


class IdentityTests(unittest.TestCase):
    """Which spellings are the token's, and which are left to Yahoo."""

    def test_the_prefixed_symbol_is_the_token(self):
        self.assertTrue(ondo.is_ondo_symbol("ONDO:OUSG"))
        self.assertTrue(ondo.is_ondo_symbol(" ONDO:ousg "))
        self.assertEqual(ondo.canonical("ondo:ousg"), "ONDO:OUSG")

    def test_a_bare_ticker_is_left_to_the_chart_route(self):
        # `canonical` is what the route keys on *before* Yahoo. A bare `OUSG`
        # must not shadow a listing that might one day be Yahoo's own; `alias`
        # is the spelling the route tries only after Yahoo refuses.
        self.assertFalse(ondo.is_ondo_symbol("OUSG"))
        self.assertIsNone(ondo.canonical("OUSG"))
        self.assertEqual(ondo.alias("ousg"), "ONDO:OUSG")
        self.assertIsNone(ondo.alias("qqq"))

    def test_an_unknown_prefix_is_a_verdict_not_a_chart(self):
        for symbol in ("ONDO:USDY", "ONDO:", "ONDO"):
            self.assertFalse(ondo.is_ondo_symbol(symbol), symbol)
            with self.assertRaises(ondo.OndoNotFound):
                ondo.record(symbol)


class ParseTests(unittest.TestCase):
    """The document is the source; a wrong one must not become a chart."""

    def test_points_become_bars_oldest_first(self):
        bars = ondo._parse(_document(days=3), "ethereum:" + ondo.TOKENS[0]["address"])
        self.assertEqual([bar["c"] for bar in bars], [116.0, 116.011, 116.022])
        self.assertEqual(bars, sorted(bars, key=lambda bar: bar["t"]))

    def test_rows_without_a_usable_price_are_dropped(self):
        doc = _document(days=3)
        prices = doc["coins"]["ethereum:" + ondo.TOKENS[0]["address"]]["prices"]
        prices.insert(1, {"timestamp": 1, "price": 0})
        prices.append({"timestamp": 2})
        bars = ondo._parse(doc, "ethereum:" + ondo.TOKENS[0]["address"])
        self.assertEqual(len(bars), 3)

    def test_an_answer_about_another_contract_is_not_this_series(self):
        with self.assertRaises(ondo.OndoError):
            ondo._parse(_document(), "ethereum:0xnotthis")

    def test_an_empty_document_is_an_outage(self):
        for document in ({}, None, {"coins": {}}):
            with self.assertRaises(ondo.OndoError):
                ondo._parse(document, "ethereum:" + ondo.TOKENS[0]["address"])


class ChartTests(unittest.TestCase):
    """The payload the page draws, and what it claims about the newest bar."""

    def chart(self, document=None, span="3mo", interval="1d", **kwargs):
        document = _document(**kwargs) if document is None else document
        with mock.patch.object(ondo, "_get_json", return_value=document):
            return ondo.chart("ONDO:OUSG", span, interval)

    def test_the_three_month_window_is_what_is_drawn(self):
        payload = self.chart(days=90)
        self.assertEqual(payload["symbol"], "ONDO:OUSG")
        self.assertEqual(payload["currency"], "USD")
        self.assertEqual(payload["exchange"], "Ondo")
        self.assertEqual(payload["type"], "Tokenized fund")
        self.assertEqual(payload["source"], "DeFiLlama")
        # Three months of daily points, and the badge reads the very bars drawn.
        self.assertGreaterEqual(len(payload["points"]), 85)
        self.assertLessEqual(len(payload["points"]), 92)
        self.assertEqual(payload["marketPrice"], payload["points"][-1]["c"])
        self.assertIsNotNone(payload["trend"])

    def test_a_longer_span_is_clipped_to_what_the_source_serves(self):
        # `span=600` answers HTTP 400 upstream, so a 5-year request must ask for
        # the 500 days that exist rather than failing the symbol.
        with mock.patch.object(ondo, "_get_json",
                               return_value=_document(days=500)) as get:
            ondo.chart("ONDO:OUSG", "5y", "1d")
        self.assertIn("span=500", get.call_args[0][0])

    def test_each_span_asks_for_its_own_days(self):
        for span, days in (("1mo", 30), ("3mo", 90), ("6mo", 180), ("1y", 365)):
            with mock.patch.object(ondo, "_get_json",
                                   return_value=_document(days=days)) as get:
                ondo.chart("ONDO:OUSG", span, "1d")
            # A few days more than the chart draws: the badge's steadiness reading
        # looks back over the sessions behind the window (`onset.decorate`).
        self.assertIn("span=%d" % (days + onset.LEAN_HOLD_BARS),
                      get.call_args[0][0], span)

    def test_a_fresh_point_is_the_price_trading_now(self):
        payload = self.chart()
        self.assertTrue(payload["liveLastBar"])

    def test_a_copy_from_a_previous_session_is_not_called_live(self):
        payload = self.chart(end=time.time() - 2 * 86_400)
        self.assertFalse(payload["liveLastBar"])

    def test_a_weekly_chart_is_not_trimmed_and_not_called_live(self):
        payload = self.chart(days=90, interval="1wk")
        self.assertFalse(payload["liveLastBar"])
        # 90 daily points are 13 whole weeks and a bit: the aggregation keeps
        # one bar per week rather than trimming the boundary.
        self.assertLess(len(payload["points"]), 20)
        self.assertGreater(len(payload["points"]), 10)

    def test_the_quote_carries_the_decimals_the_price_needs(self):
        self.assertEqual(ondo.price_hint([{"c": 116.11}, {"c": 117.1}]), 2)
        self.assertEqual(ondo.price_hint([{"c": 117.1063}]), 4)
        # A source's float noise must not ask for six decimals on a $117 quote.
        self.assertEqual(ondo.price_hint([{"c": 117.106259}]), 4)
        self.assertEqual(ondo.price_hint([]), 2)

    def test_an_unknown_symbol_is_a_verdict(self):
        with self.assertRaises(ondo.OndoNotFound):
            ondo.chart("ONDO:NOTREAL", "3mo", "1d")


class ProbabilityTests(unittest.TestCase):
    """A tokenized fund keeps a calendar week and pays a swap's round trip."""

    def test_the_token_gets_its_own_class(self):
        payload = {"type": "Tokenized fund", "source": "DeFiLlama"}
        self.assertEqual(probability.asset_class(payload), "token")
        self.assertEqual(probability.CLASSES["token"]["label"],
                         "tokenized fund")
        self.assertEqual(probability.CLASSES["token"]["cost"], 0.0020)

    def test_the_horizon_is_calendar_days_not_weekdays(self):
        # The token trades on chain every day, so three months is ~92 sessions,
        # the same calendar crypto keeps.
        end = time.time() - 60
        points = [{"t": int(end - (40 - i) * 86_400), "c": 100 + i * 0.01}
                  for i in range(40)]
        estimate = probability.estimate({"type": "Tokenized fund",
                                         "interval": "1d", "points": points})
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate["class"], "token")
        self.assertGreaterEqual(estimate["horizonBars"], 90)


if __name__ == "__main__":
    unittest.main()
