"""The Ondo shelf, and the leaning table's filter onto it (2026-11-06).

The reader asked that the "Leaning bullish -- not confirmed" table keep only
what can be bought at app.ondo.finance: a United States row must have an Ondo
token, and the funds -- which that shelf does not carry at all -- keep no row.
Everything here pins one half of that: the sitemap read, the membership
question, and the two ways the filter must *not* act (an outage, and a market
the request never named).
"""

import unittest
from unittest import mock

import diskcache
import ondolist
import recent

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://app.ondo.finance</loc></url>
  <url><loc>https://app.ondo.finance/assets/nvdaon</loc></url>
  <url><loc>https://app.ondo.finance/assets/spyon</loc></url>
  <url><loc>https://app.ondo.finance/assets/von</loc></url>
  <url><loc>https://app.ondo.finance/assets/ousg</loc></url>
  <url><loc>https://app.ondo.finance/assets/brk.bon</loc></url>
  <url><loc>https://app.ondo.finance/assets/on</loc></url>
  <url><loc>https://app.ondo.finance/intelligent-portfolios/mag7xon</loc></url>
  <url><loc>https://app.ondo.finance/private-markets/opaipon</loc></url>
</urlset>
"""


def _shelf(*tickers):
    """A shelf record holding one token per ticker, the way the site spells it."""
    return ondolist._record({(t.lower() + "on") for t in tickers},
                            1_800_000_000.0, False)


class ParseTests(unittest.TestCase):
    def test_only_asset_urls_of_the_site_count(self):
        self.assertEqual(ondolist.parse(SITEMAP),
                         {"nvdaon", "spyon", "von", "ousg", "brk.bon", "on"})

    def test_a_bare_fund_ticker_is_kept_as_it_is_listed(self):
        # OUSG's page is /assets/ousg -- no `on` suffix to strip.
        self.assertIn("ousg", ondolist.parse(SITEMAP))

    def test_a_page_under_another_path_is_not_an_asset(self):
        self.assertNotIn("mag7xon", ondolist.parse(SITEMAP))

    def test_garbage_answers_nothing_rather_than_raising(self):
        self.assertEqual(ondolist.parse(""), set())
        self.assertEqual(ondolist.parse(None), set())


class CarriesTests(unittest.TestCase):
    def test_a_listed_ticker_is_carried(self):
        self.assertTrue(ondolist.carries("NVDA", _shelf("NVDA")))
        self.assertTrue(ondolist.carries("nvda", _shelf("nvda")))

    def test_an_unlisted_ticker_is_not(self):
        self.assertFalse(ondolist.carries("GILD", _shelf("NVDA", "SPY")))

    def test_a_class_share_is_tried_with_a_dash_too(self):
        self.assertTrue(ondolist.carries("BRK.B", _shelf("brk.b")))
        self.assertTrue(ondolist.carries("BRK-B", _shelf("brk.b")))

    def test_a_bare_fund_ticker_is_carried(self):
        shelf = ondolist._record({"ousg"}, 1_800_000_000.0, False)
        self.assertTrue(ondolist.carries("OUSG", shelf))

    def test_no_shelf_carries_nothing(self):
        # The caller checks for None first; this is the answer that must never
        # be read as "not listed" on its own.
        self.assertFalse(ondolist.carries("NVDA", None))


class ShelfTests(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        self.patch = mock.patch.multiple(
            diskcache,
            load=mock.Mock(side_effect=lambda key: self.saved.get(key)),
            store=mock.Mock(side_effect=lambda key, value: self.saved.update(
                {key: (1_800_000_000.0, value)})))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_a_fresh_copy_is_served_without_a_fetch(self):
        self.saved[ondolist.CACHE_KEY] = (
            1_800_000_000.0, {"slugs": ["nvdaon"]})
        with mock.patch.object(ondolist, "_fetch") as fetch:
            shelf = ondolist.shelf(now=1_800_000_100.0)
        fetch.assert_not_called()
        self.assertEqual(shelf["slugs"], ["nvdaon"])
        self.assertFalse(shelf["cached"])

    def test_a_stale_copy_is_refetched_and_stored(self):
        self.saved[ondolist.CACHE_KEY] = (1_000.0, {"slugs": ["oldon"]})
        with mock.patch.object(ondolist, "_fetch", return_value=SITEMAP):
            shelf = ondolist.shelf(now=1_800_000_000.0)
        self.assertIn("nvdaon", shelf["slugs"])
        self.assertEqual(shelf["fetchedAt"], 1_800_000_000.0)
        self.assertIn("brk.bon", self.saved[ondolist.CACHE_KEY][1]["slugs"])

    def test_a_failed_fetch_falls_back_and_says_it_is_cached(self):
        self.saved[ondolist.CACHE_KEY] = (1_700_000_000.0, {"slugs": ["nvdaon"]})
        with mock.patch.object(ondolist, "_fetch", side_effect=OSError("down")):
            shelf = ondolist.shelf(now=1_700_000_000.0 + ondolist.CACHE_TTL + 60)
        self.assertEqual(shelf["slugs"], ["nvdaon"])
        self.assertTrue(shelf["cached"])

    def test_a_failed_fetch_with_no_copy_answers_none(self):
        with mock.patch.object(ondolist, "_fetch", side_effect=OSError("down")):
            self.assertIsNone(ondolist.shelf(now=1_800_000_000.0))

    def test_a_copy_past_the_keep_age_is_not_shown(self):
        old = 1_800_000_000.0 - ondolist.CACHE_KEEP - 1
        self.saved[ondolist.CACHE_KEY] = (old, {"slugs": ["nvdaon"]})
        with mock.patch.object(ondolist, "_fetch", side_effect=OSError("down")):
            self.assertIsNone(ondolist.shelf(now=1_800_000_000.0))

    def test_saved_never_touches_the_network(self):
        with mock.patch.object(ondolist, "_fetch") as fetch:
            self.assertIsNone(ondolist.saved())
        fetch.assert_not_called()


def _lean(market, ticker):
    return {"market": market, "ticker": ticker, "lean": "bullish"}


class ActionableTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            _lean("US", "NVDA"),
            _lean("US", "GILD"),
            _lean("US", "BRK.B"),
            _lean("Philippine fund", "ALFM-PESO"),
            _lean("Philippines", "PHR"),
            _lean("Crypto", "ZECUSDT"),
        ]

    def test_the_united_states_rows_keep_only_listed_tickers(self):
        kept = recent.actionable(self.rows, _shelf("NVDA", "BRK.B"))
        self.assertEqual([(r["market"], r["ticker"]) for r in kept],
                         [("US", "NVDA"), ("US", "BRK.B"),
                          ("Philippines", "PHR"), ("Crypto", "ZECUSDT")])

    def test_the_funds_keep_no_row(self):
        kept = recent.actionable(self.rows, _shelf("NVDA", "BRK.B", "GILD"))
        self.assertNotIn("Philippine fund", {r["market"] for r in kept})

    def test_other_markets_are_untouched(self):
        kept = recent.actionable(self.rows, _shelf())
        self.assertEqual({r["market"] for r in kept}, {"Philippines", "Crypto"})

    def test_an_outage_keeps_every_row(self):
        self.assertEqual(recent.actionable(self.rows, None), self.rows)


if __name__ == "__main__":
    unittest.main()
