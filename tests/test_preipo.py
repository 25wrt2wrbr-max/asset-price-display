"""Tests for the pre-IPO splice (`preipo.py`): ANT's chart starts in August."""

import datetime as dt
import json
import unittest
from unittest import mock

import server  # noqa: F401
import preipo


def days(*items):
    return [{"day": dt.date(*day).isoformat(), "o": close, "h": close,
             "l": close, "c": close}
            for *day, close in items]


# The perp's shape around the IPO: a Friday, the weekend, the pricing Monday,
# then the first two sessions the exchange itself printed.
ROWS = days(
    (2026, 8, 19, 1801.5),         # the market's first bar
    (2026, 11, 13, 1782.4),        # a Friday
    (2026, 11, 14, 1779.9),        # Saturday: the perp prints, the listing does not
    (2026, 11, 15, 1777.2),        # Sunday
    (2026, 11, 16, 1685.8),
    (2026, 11, 17, 1700.2),
    (2026, 11, 18, 1717.8),        # the bar the IPO price anchors to
    (2026, 11, 19, 1657.0),        # the exchange's own first session
    (2026, 11, 20, 1563.4),
)

PAYLOAD = {
    "symbol": "ANT",
    "timezone": "America/New_York",
    "points": [
        {"t": 1795098600, "c": 97.17},      # 2026-11-19 09:30 New York
        {"t": 1795185000, "c": 88.91},      # 2026-11-20
        {"t": 1795444200, "c": 87.33},      # 2026-11-23
    ],
    "barVolumes": [857312300, 399561400, 253005331],
}


class PreipoSpliceTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(preipo, "bars", return_value=list(ROWS))
        self.bars = patcher.start()
        self.addCleanup(patcher.stop)

    def test_nothing_is_added_for_a_symbol_this_module_does_not_know(self):
        for name in ("SPY", "PSE:ANT", "ANTPHP=X", ""):
            self.assertIs(preipo.extend(PAYLOAD, name), PAYLOAD)

    def test_boundary_of_the_ticker_map(self):
        self.assertEqual(preipo.ticker(" ant "), "ANT")
        self.assertEqual(preipo.ticker("ant"), "ANT")
        self.assertEqual(preipo.ticker("ANTX"), "")

    def test_weekly_charts_are_left_alone(self):
        self.assertIs(preipo.extend(PAYLOAD, "ANT", "1wk"), PAYLOAD)

    def test_the_anchor_bar_closes_at_the_ipo_price(self):
        out = preipo.extend(PAYLOAD, "ANT")
        self.assertEqual(out["preipo"]["anchor"], "2026-11-18")
        self.assertEqual(out["preipo"]["ipoPrice"], 83.00)
        # 1,717.8 was the last bar before the listing; it must land on $83.00.
        anchored = [p for p in out["points"] if p["t"] < 1795098600]
        self.assertAlmostEqual(max(anchored, key=lambda p: p["t"])["c"], 83.00, places=6)

    def test_every_pre_listing_ratio_is_kept(self):
        out = preipo.extend(PAYLOAD, "ANT")
        converted = {p["t"]: p["c"] for p in out["points"]}
        factor = 83.00 / 1717.8
        stamp = preipo._stamp(dt.date(2026, 11, 13), preipo._zone("America/New_York"))
        self.assertAlmostEqual(converted[stamp], 1782.4 * factor, places=6)

    def test_weekends_are_dropped_and_exchange_bars_win(self):
        out = preipo.extend(PAYLOAD, "ANT")
        zone = preipo._zone("America/New_York")
        kept = {dt.datetime.fromtimestamp(p["t"], zone).date() for p in out["points"]}
        self.assertNotIn(dt.date(2026, 11, 14), kept)   # Saturday
        self.assertNotIn(dt.date(2026, 11, 15), kept)   # Sunday
        # The perp's own 11-19 and 11-20 bars are not drawn twice over.
        self.assertEqual(len(out["points"]), len(PAYLOAD["points"]) + 5)
        self.assertEqual(out["preipo"]["bars"], 5)

    def test_the_join_is_flat_in_time(self):
        out = preipo.extend(PAYLOAD, "ANT")
        stamps = [p["t"] for p in out["points"]]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual(out["preipo"]["from"], "2026-08-19")

    def test_volumes_stay_aligned_to_the_exchange_bars_only(self):
        out = preipo.extend(PAYLOAD, "ANT")
        # Deliberately short, so `chartVolumes` answers null and the page shows
        # no volume tag: perp contracts are not share volumes.
        self.assertEqual(out["barVolumes"], PAYLOAD["barVolumes"])
        self.assertNotEqual(len(out["barVolumes"]), len(out["points"]))

    def test_a_failed_fetch_leaves_the_chart_exactly_as_it_was(self):
        self.bars.side_effect = server.UpstreamError("Entropy: offline")
        self.assertIs(preipo.extend(PAYLOAD, "ANT"), PAYLOAD)

    def test_no_bar_before_the_first_session_means_no_splice(self):
        self.bars.return_value = days((2026, 11, 19, 1657.0))
        self.assertIs(preipo.extend(PAYLOAD, "ANT"), PAYLOAD)

    def test_a_payload_with_no_bars_is_untouched(self):
        empty = {"points": []}
        self.assertIs(preipo.extend(empty, "ANT"), empty)

    def test_fetched_bars_survive_the_disk_copy(self):
        """A `date` key made every write to `.cache/` fail silently."""
        answer = mock.MagicMock()
        answer.__enter__.return_value.read.return_value = json.dumps(
            [{"t": 1795098600000, "o": "1", "h": "2", "l": "1", "c": "1.5"}]
        ).encode()
        with mock.patch.object(preipo.urllib.request, "urlopen", return_value=answer):
            rows = preipo._fetch("io:ANTH")
        self.assertEqual(rows[0]["day"], "2026-11-19")
        json.dumps(rows)           # raises if a non-JSON value slipped in


if __name__ == "__main__":
    unittest.main()
