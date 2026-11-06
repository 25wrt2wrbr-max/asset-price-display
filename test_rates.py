import math
import unittest
from unittest import mock

import rates
import recent


def _series(closes, start=1_700_000_000):
    """(stamps, closes, volumes) for a synthetic daily series."""
    stamps = [start + i * 86_400 for i in range(len(closes))]
    return stamps, [float(c) for c in closes], [0.0] * len(closes)


class SearchTests(unittest.TestCase):
    """A reader finds a contract by ticker, by tenor, or by the name it goes by."""

    def test_a_ticker_finds_its_own_contract(self):
        for contract in rates.CONTRACTS:
            self.assertEqual([row["symbol"] for row in
                              rates.search_contracts(contract["ticker"])],
                             [contract["symbol"]])
            self.assertEqual(rates.named_contracts(contract["ticker"].lower()),
                             [contract["symbol"]])

    def test_the_words_a_reader_types_find_the_thirty_year(self):
        # The queries the search route could not answer before: Yahoo's index
        # returns Korean ETFs and KB funds for both of them, because the
        # contract's own name carries neither "30" nor "year".
        for query in ("30-year treasury bond", "30 year treasury",
                      "30 year bond", "the long bond", "t-bond",
                      "Treasury Bond Futures", "30Y"):
            self.assertEqual([row["symbol"] for row in
                              rates.search_contracts(query)],
                             ["ZB=F"], query)
            self.assertEqual(rates.named_contracts(query), ["ZB=F"], query)

    def test_a_tenor_finds_only_that_tenor(self):
        self.assertEqual(rates.named_contracts("10-year note"), ["ZN=F"])
        self.assertEqual(rates.named_contracts("5 year"), ["ZF=F"])
        self.assertEqual(rates.named_contracts("2 yr note"), ["ZT=F"])

    def test_a_neighbouring_number_is_not_a_match(self):
        # "2 year" is a phrase; "12 year" is not the two-year.
        self.assertEqual(rates.named_contracts("12 year"), [])
        self.assertEqual(rates.named_contracts("20 year"), [])

    def test_ultra_outranks_the_plain_tenor(self):
        self.assertEqual(rates.named_contracts("ultra 10 year"),
                         ["TN=F", "ZN=F"])

    def test_the_class_word_is_not_specific(self):
        # "treasury" names the asset class, so it fills in the curve but must
        # not reorder Yahoo's own answer; "treasury futures" asks for the
        # curve and does.
        self.assertEqual(rates.named_contracts("treasury"), [])
        self.assertEqual([row["symbol"] for row in
                          rates.search_contracts("treasury")],
                         ["ZT=F", "Z3N=F", "ZF=F", "ZN=F", "TN=F"])
        self.assertEqual(len(rates.named_contracts("treasury futures")),
                         len(rates.CONTRACTS))

    def test_an_unrelated_query_finds_nothing(self):
        for query in ("apple", "zebra", "bond", "", "   ", "zbx"):
            self.assertEqual(rates.search_contracts(query), [], query)
            self.assertEqual(rates.named_contracts(query), [], query)

    def test_a_supplement_row_looks_like_yahoos(self):
        row = rates.search_contracts("zb")[0]
        self.assertEqual(sorted(row), ["exchange", "name", "symbol", "type"])
        self.assertEqual(row["type"], "FUTURE")
        self.assertEqual(row["exchange"], "Chicago Board of Trade")


class PriceHintTests(unittest.TestCase):
    """A Treasury quote's decimals are a property of its fraction."""

    def test_thirty_seconds_need_five_decimals(self):
        self.assertEqual(rates.price_hint([107.65625, 109.09375]), 5)

    def test_a_sixty_fourth_needs_six(self):
        self.assertEqual(rates.price_hint([106.640625]), 6)

    def test_an_eighth_needs_three(self):
        self.assertEqual(rates.price_hint([108.125]), 3)

    def test_no_bars_falls_back_to_two(self):
        self.assertEqual(rates.price_hint([]), 2)
        self.assertEqual(rates.price_hint(None), 2)


class RateRowTests(unittest.TestCase):
    """A Treasury future is a price: the classifier's own label, not a yield."""

    def _rows(self, make_bars, contracts=None):
        contracts = contracts or (rates.CONTRACTS[-2],)   # ZB, the thirty-year
        fetcher_calls = []

        def fetcher(symbols):
            fetcher_calls.append(list(symbols))
            return {c["symbol"]: make_bars(c) for c in contracts
                    if make_bars(c) is not None}

        with mock.patch.object(recent.rates, "CONTRACTS", contracts):
            rows, stats = recent.rate_rows(fetcher)
        return rows, stats, fetcher_calls

    def test_a_bullish_contract_is_a_row(self):
        closes = [100 + i for i in range(80)]
        rows, stats, calls = self._rows(lambda c: _series(closes))
        row = rows[0]
        self.assertEqual(row["market"], "US Treasury")
        self.assertEqual(row["ticker"], "ZB")
        self.assertEqual(row["chartSymbol"], "ZB=F")
        self.assertEqual(row["direction"], "bullish")
        # A price, so nothing is inverted and there is no yield note.
        self.assertNotIn("note", row)
        self.assertEqual(row["price"], 179.0)
        # A contract's volume is a count of contracts, not money.
        self.assertIsNone(row["turnover"])
        self.assertEqual((stats["universe"], stats["count"]), (1, 1))
        self.assertEqual(stats["missing"], [])
        # One call, for the curve's symbols.
        self.assertEqual(calls, [["ZB=F"]])

    def test_a_falling_contract_is_not_a_row(self):
        closes = [200 - i for i in range(80)]
        rows, stats, _calls = self._rows(lambda c: _series(closes))
        self.assertEqual([r for r in rows if not r.get("lean")], [])
        self.assertEqual((stats["universe"], stats["count"]), (1, 0))

    def test_a_missing_contract_is_missing_not_bearish(self):
        rows, stats, _calls = self._rows(lambda c: None)
        self.assertEqual(rows, [])
        self.assertEqual(stats["missing"], ["ZB"])
        self.assertEqual((stats["universe"], stats["count"]), (1, 0))

    def test_the_window_is_yahoos_own_three_months(self):
        # The chart route asks Yahoo for `range=3mo`, so the walk must read
        # that same window -- the same rule every other row on the table keeps.
        closes = [100 * math.exp(0.004 * i) for i in range(90)]
        with mock.patch.object(
                recent.onset_module, "onset",
                return_value={"price": 1.0, "since": 1, "run": 2,
                              "censored": False, "manner": "turn",
                              "turnMove": 0.1, "score": 0.5, "bars": 90,
                              "last": 2, "turnover": None}) as walk:
            self._rows(lambda c: _series(closes))
        self.assertEqual(walk.call_args.kwargs["months"],
                         recent.onset_module.WINDOW_MONTHS)


if __name__ == "__main__":
    unittest.main()
