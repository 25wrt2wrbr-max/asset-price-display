"""The search box has to reach a ticker whose Yahoo query the index refuses.

Measured 2026-11-02: `/v1/finance/search?q=vtv` answers **HTTP 500** on both
query hosts, with and without parameters, while `VTV` charts normally and the
query `vt` lists it third. VTV is one of the largest US ETFs and the search box
could not reach it: the route raised on the 500 before any supplement ran, so
the reader was shown an error rather than a row.

The fix is `server.probe_ticker` -- when Yahoo's index answers nothing, the
query is handed to the chart route as a *symbol*, and a row is offered only for
a symbol that route draws. These tests pin the parts that decide what a reader
is offered, with the browser mocked out; the live route is checked separately
against `/api/search?q=vtv`.
"""
import json
import unittest
from unittest import mock

import server


def _chart_body(symbol="VTV", instrument="ETF", name="Vanguard Morningstar Value ETF",
                exchange="NYSEArca", bars=5, code="PCX"):
    return json.dumps({"chart": {"result": [{
        "meta": {
            "symbol": symbol,
            "instrumentType": instrument,
            "longName": name,
            "shortName": name,
            "fullExchangeName": exchange,
            "exchangeName": code,
        },
        "timestamp": [1_700_000_000 + i * 86_400 for i in range(bars)],
        "indicators": {"quote": [{"close": [1.0] * bars}]},
    }], "error": None}})


class ProbeTests(unittest.TestCase):
    """What a query the search index refused resolves to, and when it resolves."""

    def probe(self, text, body=None, status=200):
        body = _chart_body() if body is None else body
        with mock.patch.object(server, "moli_get",
                               return_value=(status, body)) as get:
            return server.probe_ticker(text), get

    def test_a_refused_ticker_resolves_to_its_own_row(self):
        row, get = self.probe("vtv")
        self.assertEqual(row, {
            "symbol": "VTV",
            "name": "Vanguard Morningstar Value ETF",
            "exchange": "NYSEArca",
            "type": "ETF",
        })
        # The probe asks the chart route, which is the route a click will use,
        # so a row can never be offered for something that cannot be drawn.
        self.assertIn("/v8/finance/chart/VTV?", get.call_args[0][0])

    def test_the_row_reports_the_symbol_the_route_resolved(self):
        # Case is the reader's; the symbol is Yahoo's.
        row, _ = self.probe("vtv", body=_chart_body(symbol="VTV"))
        self.assertEqual(row["symbol"], "VTV")

    def test_a_class_share_is_probed_in_the_spelling_that_charts(self):
        # `BRK.B` is a 404 on the chart route; `BRK-B` is the listing.
        row, get = self.probe("brk.b", body=_chart_body(
            symbol="BRK-B", instrument="EQUITY", name="Berkshire Hathaway Inc."))
        self.assertEqual(row["symbol"], "BRK-B")
        self.assertIn("/BRK-B?", get.call_args[0][0])

    def test_a_futures_contract_and_an_index_are_percent_encoded(self):
        for typed, encoded in (("gc=f", "GC%3DF"), ("^gspc", "%5EGSPC")):
            _, get = self.probe(typed, body=_chart_body(symbol="GC=F",
                                                        instrument="FUTURE"))
            self.assertIn(f"/{encoded}?", get.call_args[0][0], typed)

    def test_a_prose_query_is_never_sent_to_the_chart_route(self):
        for text in ("vanguard value", "the long bond", "30-year treasury bond"):
            row, get = self.probe(text)
            self.assertIsNone(row, text)
            get.assert_not_called()

    def test_a_prose_query_falls_back_to_its_first_word(self):
        # "vtv etf" is a query the index answers with nothing at all; the
        # ticker the reader led with is a fair reading of it, and the row prints
        # the instrument's full name so the guess is visible as one.
        row, get = self.probe("vtv etf")
        self.assertEqual(row["symbol"], "VTV")
        self.assertIn("/VTV?", get.call_args[0][0])

    def test_a_dead_ticker_stays_a_dead_end(self):
        for body, status in ((None, 404),
                             (json.dumps({"chart": {"result": None}}), 200),
                             (json.dumps({"chart": {"result": [
                                 {"meta": {"symbol": "ZZZQQQ"}, "timestamp": []}]}}), 200)):
            row, _ = self.probe("zzzqqq", body=body, status=status)
            self.assertIsNone(row, (status, body))

    def test_a_type_search_would_not_have_offered_is_not_offered_here(self):
        row, _ = self.probe("$gspc", body=_chart_body(symbol="$GSPC",
                                                     instrument="MONEY"))
        self.assertIsNone(row)

    def test_a_non_json_answer_resolves_to_nothing(self):
        row, _ = self.probe("vtv", body="<html>500</html>", status=200)
        self.assertIsNone(row)

    def test_a_row_without_history_is_not_offered(self):
        row, _ = self.probe("vtv", body=_chart_body(bars=0))
        self.assertIsNone(row)

    def test_every_offered_type_is_one_the_route_already_keeps(self):
        # `_chart_meta_row` filters on the same vocabulary Yahoo's search rows
        # are filtered on, so a probe can never introduce a type the page has
        # not seen. A body with instrumentType "" resolves to no row at all.
        row, _ = self.probe("vtv", body=_chart_body(instrument=""))
        self.assertIsNone(row)
        for kind in server.KEEP_QUOTE_TYPES:
            row, _ = self.probe("vtv", body=_chart_body(instrument=kind))
            self.assertEqual(row["type"], kind)


if __name__ == "__main__":
    unittest.main()
