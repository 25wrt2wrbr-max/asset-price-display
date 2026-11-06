import datetime
import unittest
from unittest import mock

import onset as onset_module
import phfunds
import recent


def ts(year, month, day):
    """Midnight UTC on a date, as the seconds every source is normalised to."""
    return int(datetime.datetime(year, month, day,
                                 tzinfo=datetime.timezone.utc).timestamp())


def series_of(start_day, closes):
    """Bars on consecutive *calendar* days from `start_day`, like a publisher's
    padded series: weekends included, values as given."""
    base = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    return [{"t": int((base + datetime.timedelta(days=start_day + i)).timestamp()),
             "c": close} for i, close in enumerate(closes)]


class UniverseTests(unittest.TestCase):
    def test_every_fund_has_one_identity(self):
        codes = [entry[0] for entry in phfunds.FUNDS]
        self.assertEqual(len(codes), len(set(codes)), "duplicate fund code")
        self.assertEqual(len(codes), 47)
        for code, name, category, source, key, currency in phfunds.FUNDS:
            with self.subTest(code=code):
                self.assertTrue(name and category and key)
                self.assertIn(source, {"uitf", "pifa", "bpi"})
                self.assertIn(currency, {"PHP", "USD", "EUR"})

    def test_a_bpi_fund_can_only_point_at_a_page_it_has(self):
        for code, _name, _category, source, key, _currency in phfunds.FUNDS:
            if source == "bpi":
                self.assertIn(key, phfunds.BPI_SLUGS)

    def test_symbols_round_trip(self):
        for code, _name, _category, _source, _key, _currency in phfunds.FUNDS:
            symbol = phfunds.symbol_for(code)
            self.assertEqual(phfunds.canonical(symbol), symbol)
            self.assertEqual(phfunds.canonical(code.lower()), symbol)
            self.assertTrue(phfunds.is_fund_symbol(symbol))
            self.assertEqual(phfunds.record(symbol)["code"], code)

    def test_other_instruments_are_not_funds(self):
        for symbol in ("AAPL", "PSE:TEL", "TVC:PH10Y", "BTC-USD", "", "FUND:NOPE"):
            with self.subTest(symbol=symbol):
                self.assertFalse(phfunds.is_fund_symbol(symbol))
                self.assertIsNone(phfunds.canonical(symbol))


class ParsingTests(unittest.TestCase):
    def test_toap_points_become_bars(self):
        document = {"data_point": [
            {"label": "Oct 29, 2026", "y": 222.45},
            {"label": "Oct 30, 2026", "y": 221.22},
            {"label": "nonsense", "y": 1.0},
            {"label": "Oct 31, 2026", "y": 0},
        ]}
        bars = phfunds._toap_bars(document)
        self.assertEqual(bars, [{"t": ts(2026, 10, 29), "c": 222.45},
                                {"t": ts(2026, 10, 30), "c": 221.22}])

    def test_pifa_dataset_becomes_bars(self):
        page = ("dataset = [ {date: 29, month: 10, year: 2026, value: 201.92},"
                " {date: 30, month: 10, year: 2026, value: 202.98},"
                " {date: 31, month: 2, year: 2026, value: 1.0} ];")
        bars = phfunds._pifa_bars(page)
        self.assertEqual(bars, [{"t": ts(2026, 10, 29), "c": 201.92},
                                {"t": ts(2026, 10, 30), "c": 202.98}])

    def test_bpi_model_is_a_json_string_inside_the_json(self):
        document = {"fundCode": "BPIPERAMM", "fundData":
                    '{"fundDataHistory": ['
                    '{"navpuValue": 1.48, "date": %d},'
                    '{"navpuValue": 1.49, "date": %d}]}' % (
                        ts(2026, 1, 5) * 1000, ts(2026, 1, 6) * 1000)}
        bars = phfunds._bpi_bars(document)
        self.assertEqual(bars, [{"t": ts(2026, 1, 5), "c": 1.48},
                                {"t": ts(2026, 1, 6), "c": 1.49}])

    def test_a_malformed_document_is_no_bars_not_an_exception(self):
        for document in ({}, {"fundData": "not json"}, {"fundData": None}):
            with self.subTest(document=document):
                self.assertEqual(phfunds._bpi_bars(document), [])


class CleanTests(unittest.TestCase):
    def test_weekends_are_dropped_and_days_deduped(self):
        # 2026-10-29 is a Thursday. Friday + the padded weekend, plus a duplicate
        # stamp carrying the corrected value.
        bars = [{"t": ts(2026, 10, 29), "c": 222.45},
                {"t": ts(2026, 10, 30), "c": 221.22},
                {"t": ts(2026, 10, 31), "c": 221.22},
                {"t": ts(2026, 11, 1), "c": 221.22},
                {"t": ts(2026, 10, 30), "c": 221.99}]
        cleaned = phfunds.clean(bars, now=ts(2026, 11, 2))
        self.assertEqual(cleaned, [{"t": ts(2026, 10, 29), "c": 222.45},
                                   {"t": ts(2026, 10, 30), "c": 221.99}])

    def test_the_future_is_dropped(self):
        bars = [{"t": ts(2026, 10, 29), "c": 1.0},
                {"t": ts(2026, 11, 2), "c": 2.0}]
        cleaned = phfunds.clean(bars, now=ts(2026, 10, 31))
        self.assertEqual([bar["c"] for bar in cleaned], [1.0])

    def test_history_is_trimmed_to_the_walk_span(self):
        # One weekday bar per week for two years: everything older than
        # `HISTORY_DAYS` is gone, and what is left is oldest first.
        stamps = [ts(2025, 1, 6) + 7 * 86400 * i for i in range(100)]
        cleaned = phfunds.clean([{"t": stamp, "c": 1.0 + i}
                                 for i, stamp in enumerate(stamps)],
                                now=ts(2026, 10, 30))
        self.assertTrue(cleaned)
        self.assertGreaterEqual(cleaned[0]["t"], ts(2026, 10, 30) - phfunds.HISTORY_DAYS * 86400)
        self.assertEqual(cleaned, sorted(cleaned, key=lambda bar: bar["t"]))

    def test_non_positive_values_are_not_bars(self):
        bars = [{"t": ts(2026, 10, 29), "c": 0}, {"t": ts(2026, 10, 30), "c": -1}]
        self.assertEqual(phfunds.clean(bars, now=ts(2026, 10, 31)), [])


class PriceHintTests(unittest.TestCase):
    def test_two_decimals_and_four_are_both_honoured(self):
        self.assertEqual(phfunds.price_hint([{"c": 221.22}]), 2)
        self.assertEqual(phfunds.price_hint([{"c": 48.1186}]), 4)
        self.assertEqual(phfunds.price_hint([{"c": 10.73}]), 2)

    def test_the_clamp_keeps_float_noise_from_asking_for_eight(self):
        self.assertEqual(phfunds.price_hint([{"c": 202.98000000000002}]), 4)


class SeriesCacheTests(unittest.TestCase):
    """`series()` is the one path a row and a chart both read.

    Three ages decide what happens: inside `CACHE_TTL` the publisher is not
    asked; past it the publisher is asked; if it does not answer, a copy up to
    `CACHE_KEEP` old is shown *and flagged*, and with nothing worth showing the
    call raises.
    """

    def setUp(self):
        self.code = "BPI-INFRA"
        self.bars = [{"t": ts(2026, 10, 29), "c": 222.45}]

    def test_a_fresh_copy_skips_the_fetch(self):
        with mock.patch.object(phfunds, "cached_bars",
                               return_value=(self.bars, 60)), \
             mock.patch.object(phfunds, "_fetch") as fetch:
            bars, age, stale = phfunds.series(self.code)
        fetch.assert_not_called()
        self.assertEqual((bars, age, stale), (self.bars, 60, False))

    def test_a_stale_copy_is_refetched_and_stored(self):
        fresh = [{"t": ts(2026, 10, 30), "c": 221.22}]
        with mock.patch.object(phfunds, "cached_bars",
                               return_value=(self.bars, phfunds.CACHE_TTL + 10)), \
             mock.patch.object(phfunds, "_fetch", return_value=fresh), \
             mock.patch.object(phfunds, "store_bars") as store:
            bars, age, stale = phfunds.series(self.code)
        self.assertEqual((bars, age, stale), (fresh, 0.0, False))
        store.assert_called_once_with(self.code, fresh)

    def test_an_outage_falls_back_to_a_copy_and_says_so(self):
        with mock.patch.object(phfunds, "cached_bars",
                               return_value=(self.bars, phfunds.CACHE_TTL + 600)), \
             mock.patch.object(phfunds, "_fetch",
                               side_effect=phfunds.FundError("down")):
            bars, age, stale = phfunds.series(self.code)
        self.assertEqual((bars, age, stale),
                         (self.bars, phfunds.CACHE_TTL + 600, True))

    def test_an_outage_with_nothing_worth_showing_raises(self):
        with mock.patch.object(phfunds, "cached_bars",
                               return_value=(self.bars, phfunds.CACHE_KEEP + 1)), \
             mock.patch.object(phfunds, "_fetch",
                               side_effect=phfunds.FundError("down")):
            with self.assertRaises(phfunds.FundError):
                phfunds.series(self.code)

    def test_an_unknown_code_is_a_verdict_not_an_outage(self):
        with self.assertRaises(phfunds.FundNotFound):
            phfunds.series("NOPE")


class ChartPayloadTests(unittest.TestCase):
    def _bars(self):
        # 120 weekday bars rising steadily, so the window and the classifier
        # have something real to read.
        day = datetime.datetime(2026, 5, 4, tzinfo=datetime.timezone.utc)
        bars = []
        while len(bars) < 120:
            if day.weekday() < 5:
                bars.append({"t": int(day.timestamp()), "c": 100.0 + len(bars)})
            day += datetime.timedelta(days=1)
        return bars

    def test_the_window_is_the_one_the_row_walks(self):
        bars = self._bars()
        payload = phfunds._chart_payload("BPI-INFRA", bars, "3mo", "1d")
        stamps = [point["t"] for point in payload["points"]]
        expected = onset_module.window_now([bar["t"] for bar in bars],
                                           len(bars) - 1, days=90)
        self.assertEqual(len(stamps), len(expected))
        self.assertEqual(stamps, [bars[i]["t"] for i in expected])
        self.assertEqual(payload["marketPrice"], payload["points"][-1]["c"])
        self.assertEqual(payload["currency"], "PHP")
        self.assertTrue(payload["fundSeries"])
        self.assertNotIn("unit", payload)      # a NAVPU is money, not a percent

    def test_the_badge_reads_the_points_drawn(self):
        payload = phfunds._chart_payload("BPI-INFRA", self._bars(), "3mo", "1d")
        closes = [point["c"] for point in payload["points"]]
        self.assertEqual(payload["trend"]["label"],
                         phfunds.trend.classify(closes)["label"])

    def test_a_weekly_chart_is_not_trimmed_to_a_day_boundary(self):
        payload = phfunds._chart_payload("BPI-INFRA", self._bars(), "3mo", "1wk")
        weeks = {(datetime.datetime.fromtimestamp(point["t"], datetime.timezone.utc)
                  .isocalendar()[:2]) for point in payload["points"]}
        self.assertEqual(len(weeks), len(payload["points"]))

    def test_a_served_fallback_chart_says_how_old_it_is(self):
        bars = self._bars()
        with mock.patch.object(phfunds, "series",
                               return_value=(bars, 7200.0, True)):
            payload = phfunds.chart("BPI-INFRA")
        self.assertEqual(payload["stale"], 7200)
        # The same three stamps a disk rescue carries, so the page dates the
        # reading and a copy stored from this payload cannot pass as fresh.
        self.assertTrue(payload["cached"])
        self.assertIn("fetchedAt", payload)
        self.assertIn("cacheError", payload)

    def test_a_fresh_chart_carries_no_rescue_stamps(self):
        bars = self._bars()
        with mock.patch.object(phfunds, "series", return_value=(bars, 30.0, False)):
            payload = phfunds.chart("BPI-INFRA")
        self.assertEqual(payload["stale"], 0)
        self.assertNotIn("cached", payload)


class FundRowTests(unittest.TestCase):
    def _answers(self, closes_by_code):
        return {code: {"bars": series_of(200, closes), "age": 0.0, "stale": False}
                for code, closes in closes_by_code.items()}

    def test_only_bullish_funds_become_rows(self):
        rising = [float(i) for i in range(1, 200)]
        falling = [float(i) for i in range(200, 1, -1)]
        answers = self._answers({"BPI-INFRA": rising, "ALFM-PESO": falling})
        with mock.patch.object(phfunds, "refresh", return_value=answers):
            rows, stats = recent.fund_rows()
        codes = [row["ticker"] for row in rows]
        self.assertIn("BPI-INFRA", codes)
        # A fund that answered and is not bullish is not a row -- and it is not
        # "missing" either, which is the distinction the whole table turns on.
        self.assertNotIn("ALFM-PESO", codes)
        self.assertNotIn("ALFM-PESO", stats["missing"])
        # A fund that did not answer at all is missing, never a bearish verdict.
        self.assertIn("BPI-HLTH", stats["missing"])
        self.assertNotIn("BPI-HLTH", codes)
        self.assertEqual(stats["universe"], len(phfunds.FUNDS))

    def test_an_outage_is_missing_rather_than_bearish(self):
        answers = {"BPI-INFRA": phfunds.FundError("publisher down")}
        with mock.patch.object(phfunds, "refresh", return_value=answers):
            rows, stats = recent.fund_rows()
        self.assertNotIn("BPI-INFRA", [row["ticker"] for row in rows])
        self.assertIn("BPI-INFRA", stats["missing"])

    def test_a_row_carries_no_turnover_and_its_own_precision(self):
        answers = self._answers({"ALFM-GMAI": [48.1 + i * 0.0011 for i in range(200)]})
        with mock.patch.object(phfunds, "refresh", return_value=answers):
            rows, _stats = recent.fund_rows()
        row = next(row for row in rows if row["ticker"] == "ALFM-GMAI")
        self.assertIsNone(row["turnover"])
        self.assertIsNone(row["turnoverPhp"])
        self.assertEqual(row["priceHint"], 4)
        self.assertEqual(row["market"], "Philippine fund")
        self.assertEqual(row["chartSymbol"], "FUND:ALFM-GMAI")
        self.assertTrue(row["chartable"])
        self.assertEqual(row["currency"], "PHP")

    def test_the_row_and_its_chart_see_the_same_bars(self):
        # Invariant 1: the row's verdict must be the chart's verdict. Both read
        # `phfunds`'s copy of the series; this pins that they still agree.
        rising = [100.0 + i * 0.5 for i in range(160)]
        answers = self._answers({"BPI-INFRA": rising})
        with mock.patch.object(phfunds, "refresh", return_value=answers), \
             mock.patch.object(phfunds, "series",
                               return_value=(answers["BPI-INFRA"]["bars"], 0.0, False)):
            rows, _stats = recent.fund_rows()
            payload = phfunds.chart("BPI-INFRA")
        row = next(row for row in rows if row["ticker"] == "BPI-INFRA")
        self.assertEqual(row["direction"], payload["trend"]["label"])
        self.assertEqual(row["price"], payload["points"][-1]["c"])
        self.assertEqual(row["last"], payload["points"][-1]["t"])
        self.assertEqual(row["since"],
                         onset_module.onset([b["t"] for b in answers["BPI-INFRA"]["bars"]],
                                            [b["c"] for b in answers["BPI-INFRA"]["bars"]],
                                            [0.0] * len(rising), want="bullish")["since"])

    def test_a_stale_reading_travels_with_the_row(self):
        answers = {"BPI-INFRA": {"bars": series_of(200, [1.0 + i * .1 for i in range(200)]),
                                 "age": 7200.0, "stale": True}}
        with mock.patch.object(phfunds, "refresh", return_value=answers):
            rows, _stats = recent.fund_rows()
        self.assertEqual(rows[0]["stale"], 7200)


class ChartsManyTests(unittest.TestCase):
    def test_a_verdict_and_an_outage_are_told_apart(self):
        answers = {
            "BPI-INFRA": {"bars": series_of(200, [1.0 + i * .1 for i in range(200)]),
                          "age": 0.0, "stale": False},
            "ALFM-PESO": phfunds.FundError("down"),
        }
        with mock.patch.object(phfunds, "refresh", return_value=answers):
            out = phfunds.charts_many(["FUND:BPI-INFRA", "FUND:ALFM-PESO", "NOPE"])
        self.assertIsInstance(out["FUND:BPI-INFRA"], dict)
        self.assertIsInstance(out["FUND:ALFM-PESO"], phfunds.FundError)
        self.assertIsInstance(out["NOPE"], phfunds.FundNotFound)


class SearchTests(unittest.TestCase):
    def test_a_code_query_finds_its_fund(self):
        rows = phfunds.search_funds("BPI-HLTH")
        self.assertEqual(rows[0]["symbol"], "FUND:BPI-HLTH")

    def test_a_name_query_finds_the_funds_that_match(self):
        symbols = [row["symbol"] for row in phfunds.search_funds("money market")]
        self.assertIn("FUND:ALFM-MM", symbols)
        self.assertTrue(all(symbol.startswith("FUND:") for symbol in symbols))

    def test_every_matched_word_must_appear(self):
        self.assertEqual(phfunds.search_funds("health bond"), [])


if __name__ == "__main__":
    unittest.main()
