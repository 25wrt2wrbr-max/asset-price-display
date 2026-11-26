"""PSE Edge parsing: the directory page and the chart JSON (no network)."""

import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import pse_edge

PAGE = """
<span class="count">[1 / 6] [Total 284]</span>
<table class="list"><tbody>
<tr><td><a href="#" onclick="cmDetail('69','127');return false;">Globe Telecom, Inc.</a></td>
<td><a href="#" onclick="cmDetail('69','127');return false;">GLO</a></td>
<td>Services</td><td>Telecommunications</td><td>Aug 11, 1975</td></tr>
<tr><td><a onclick="cmDetail('9','9')">First Metro ETF &amp; Co.</a></td>
<td><a onclick="cmDetail('9','9')">FMETF</a></td><td>ETF</td><td>ETF</td><td>x</td></tr>
<tr><td>no ids here</td><td>XX</td><td>Services</td></tr>
</tbody></table>
"""

CHART = {"chartData": [
    {"OPEN": 1350.0, "VALUE": 74921675.0, "CLOSE": 1303.0,
     "CHART_DATE": "Nov 20, 2026 00:00:00", "HIGH": 1350.0, "LOW": 1290.0},
    {"OPEN": 1361.0, "VALUE": 100.0, "CLOSE": 1350.0,
     "CHART_DATE": "Nov 18, 2026 00:00:00", "HIGH": 1376.0, "LOW": 1342.0},
    {"OPEN": 1361.0, "VALUE": 103836325.0, "CLOSE": 1350.0,       # repeat: last wins
     "CHART_DATE": "Nov 18, 2026 00:00:00", "HIGH": 1376.0, "LOW": 1342.0},
    {"OPEN": 1.0, "VALUE": 5.0, "CLOSE": 0.0,                       # bad price
     "CHART_DATE": "Nov 19, 2026 00:00:00", "HIGH": 1.0, "LOW": 1.0},
    {"OPEN": 1.0, "CLOSE": 2.0, "CHART_DATE": "garbage", "HIGH": 1.0, "LOW": 1.0},
], "tableData": []}


class DirectoryParse(unittest.TestCase):
    def test_rows(self):
        rows = pse_edge.parse_directory_page(PAGE)
        self.assertEqual([r["ticker"] for r in rows], ["GLO", "FMETF"])
        self.assertEqual(rows[0], {"ticker": "GLO", "name": "Globe Telecom, Inc.",
                                   "sector": "Services", "company": "69",
                                   "security": "127"})
        self.assertEqual(rows[1]["name"], "First Metro ETF & Co.")


class ChartParse(unittest.TestCase):
    def test_rows_sorted_deduped_and_stamped_like_the_socket(self):
        rows = pse_edge.parse_chart(CHART)
        self.assertEqual(len(rows), 2)
        manila = ZoneInfo("Asia/Manila")
        self.assertEqual(rows[-1][0], int(dt.datetime(2026, 11, 20, 9, 30,
                                                      tzinfo=manila).timestamp()))
        self.assertEqual(rows[-1][0], 1795138200)        # the socket's own stamp
        self.assertAlmostEqual(rows[0][5] * rows[0][4], 103836325.0)
        self.assertEqual(rows[-1][1:5], [1350.0, 1350.0, 1290.0, 1303.0])

    def test_empty_answer_is_no_rows(self):
        self.assertEqual(pse_edge.parse_chart({"chartData": []}), [])
        self.assertEqual(pse_edge.parse_chart(None), [])


class BarsMissing(unittest.TestCase):
    def test_empty_series_is_an_error_not_no_bars(self):
        with mock.patch.object(pse_edge, "directory",
                               return_value={"GLO": {"company": "1", "security": "2"}}), \
             mock.patch.object(pse_edge.diskcache, "load", return_value=None), \
             mock.patch.object(pse_edge, "_request", return_value=b'{"chartData": []}'):
            with self.assertRaises(pse_edge.EdgeError):
                pse_edge.bars("GLO", fresh=True)
            self.assertEqual(pse_edge.history_many(["PSE:GLO"]), {})

    def test_unlisted_ticker(self):
        with mock.patch.object(pse_edge, "directory", return_value={}), \
             mock.patch.object(pse_edge.diskcache, "load", return_value=None):
            with self.assertRaises(pse_edge.EdgeError):
                pse_edge.bars("MERB")


class SplitGuard(unittest.TestCase):
    def rows(self, closes):
        return [[i, 0, 0, 0, c, 1.0] for i, c in enumerate(closes)]

    def test_a_halving_is_suspect(self):
        self.assertEqual(pse_edge.suspect_split(self.rows([10, 10, 5, 5])), 2)

    def test_a_big_rise_is_not(self):
        self.assertIsNone(pse_edge.suspect_split(self.rows([10, 10, 20, 20])))

    def test_a_small_fall_is_not(self):
        self.assertIsNone(pse_edge.suspect_split(self.rows([1.55, 1.30, 1.28])))

    def test_only_recent_bars(self):
        old = [10, 5] + [5] * pse_edge.SPLIT_LOOKBACK
        self.assertIsNone(pse_edge.suspect_split(self.rows(old)))


if __name__ == "__main__":
    unittest.main()
