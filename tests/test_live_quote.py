import unittest

import live_quote


class NewestPrintTest(unittest.TestCase):
    def test_newest_minute_close_wins_over_nulls(self):
        p = {"chart": {"result": [{"meta": {"regularMarketPrice": 10.0, "regularMarketTime": 100},
                                   "timestamp": [100, 160, 220],
                                   "indicators": {"quote": [{"close": [10.0, 10.5, None]}]}}]}}
        self.assertEqual(live_quote.newest_print(p), {"price": 10.5, "t": 160})

    def test_meta_print_newer_than_last_bar(self):
        p = {"chart": {"result": [{"meta": {"fulldayPrice": 11.0, "regularMarketTime": 200},
                                   "timestamp": [100], "indicators": {"quote": [{"close": [10.0]}]}}]}}
        self.assertEqual(live_quote.newest_print(p), {"price": 11.0, "t": 200})

    def test_nothing_usable(self):
        self.assertIsNone(live_quote.newest_print({"chart": {"result": None}}))

    def test_routing(self):
        self.assertTrue(live_quote.is_yahoo_symbol("GME"))
        self.assertFalse(live_quote.is_yahoo_symbol("PSE:PSEI"))


if __name__ == "__main__":
    unittest.main()
