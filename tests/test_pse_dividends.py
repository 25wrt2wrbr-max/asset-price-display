"""PSE Edge dividend list: parsing, paging, matching rows to tickers."""

import datetime as dt
import time
import unittest
from unittest import mock

import diskcache
import pse_dividends as P
import pse_edge


def row(company, cmpy, security, kind, rate, ex, record="Nov 24, 2026",
        pay="Dec 9, 2026", circular="C00001-2026"):
    return (f'<tr><td><a href="/companyInformation/form.do?cmpy_id={cmpy}">{company}</a></td>'
            f"<td>{security}</td><td>{kind}</td><td>{rate}</td>"
            f'<td class="alignC">{ex}</td><td class="alignC">{record}</td>'
            f'<td class="alignC">{pay}</td>'
            f"<td><a href=\"#viewer\" onclick=\"openPopup('x');return false;\">{circular}</a></td></tr>")


def page(*rows):
    return ("<table><thead><tr><th>Company Name</th><th>Type of Security</th></tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table>")


PAGE1 = page(
    row("Alpha Corp.", 11, "COMMON", "Cash", "Php 1.10 per share", "Dec 04, 2026", circular="C3"),
    row("Alpha Corp.", 11, "ALPPA", "Cash", "P0.39/share", "Nov 20, 2026", circular="C2"),
    row("Beta Inc.", 22, "COMMON", "Stock", "10% stock dividend", "Nov 3, 2026", circular="C1"),
)
PAGE2 = page(
    row("Alpha Corp.", 11, "COMMON", "Cash", "1.05", "Sep 11, 2026", circular="C0"),
    row("Old Co.", 33, "COMMON", "Cash", "Php0.10", "Jan 2, 2024", circular="C-old"),
)
DIRECTORY = {"ALP": {"ticker": "ALP", "company": "11"}, "BET": {"ticker": "BET", "company": "22"}}


class ParseTests(unittest.TestCase):
    def test_rate_forms(self):
        cases = {
            "Php0.60": (0.6, "PHP"), "Php 2.0625 per share": (2.0625, "PHP"),
            "P0.35/share": (0.35, "PHP"), "PhP0.049": (0.049, "PHP"),
            "Php/0.054": (0.054, "PHP"), "0.1112/share": (0.1112, "PHP"),
            "$0.0114 per share (USD)": (0.0114, "USD"), "CAD 0.485": (0.485, "CAD"),
            "COMMON AT P0.50 PER SHARE": (0.5, "PHP"), "MWP6A – P1.00": (1.0, "PHP"),
            "Philippine Pesos: Four centavos (0.04)": (0.04, "PHP"),
            "two numbers 1 and 2": (None, None),
            "Php0.60 (approx. US$0.01)": (None, None),
            "P1.00 regular and P0.50 special": (None, None),
            "0.25 per share, CADIZ branch": (0.25, "PHP"),
            "0.0114 per share (USD)": (0.0114, "USD"),
        }
        for text, want in cases.items():
            self.assertEqual(P.parse_rate(text, "Cash"), want, text)
        self.assertEqual(P.parse_rate("10%", "Stock"), (None, None))

    def test_page(self):
        rows = P.parse_page(PAGE1)
        self.assertEqual(len(rows), 3)          # the header row is skipped
        first = rows[0]
        self.assertEqual(first["company_id"], "11")
        self.assertEqual(first["ex"], "2026-12-04")
        self.assertEqual(first["pay"], "2026-12-09")
        self.assertEqual((first["amount"], first["currency"]), (1.1, "PHP"))
        self.assertEqual(rows[2]["amount"], None)


class FetchTests(unittest.TestCase):
    def test_pages_stop_past_the_history_floor(self):
        asked = []
        pages = {1: PAGE1, 2: PAGE2, 3: PAGE1}
        rows = P.fetch_all(today=dt.date(2026, 11, 26),
                           fetch_page=lambda n: asked.append(n) or pages[n])
        self.assertEqual(asked, [1, 2])         # page 2 reached past the floor
        self.assertNotIn("C-old", [r["circular"] for r in rows])
        self.assertEqual(len(rows), 4)

    def test_empty_list_is_an_error(self):
        with self.assertRaises(pse_edge.EdgeError):
            P.fetch_all(fetch_page=lambda n: "<table></table>")

    def test_failure_falls_back_to_the_stored_copy(self):
        stored = [{"ex": "2026-11-20"}]
        with mock.patch.object(diskcache, "load", return_value=(time.time() - 99999, stored)), \
             mock.patch.object(P, "fetch_all", side_effect=pse_edge.EdgeError("down")):
            rows, _, cached = P.listing()
        self.assertEqual(rows, stored)
        self.assertTrue(cached)

    def test_after_a_failure_the_stored_copy_is_served_without_asking(self):
        stored = [{"ex": "2026-11-20"}]
        with mock.patch.object(diskcache, "load", return_value=(time.time() - 99999, stored)), \
             mock.patch.object(P, "_last_failure", 0.0), \
             mock.patch.object(P, "fetch_all", side_effect=pse_edge.EdgeError("down")) as fetch:
            P.listing()
            rows, _, cached = P.listing()
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(rows, stored)
        self.assertTrue(cached)


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.rows = P.parse_page(PAGE1) + P.parse_page(PAGE2)

    def test_common_rows_by_company_id_preferred_by_code(self):
        alp = P.events_for("ALP", self.rows, DIRECTORY)
        self.assertEqual([e["ex"] for e in alp], ["2026-09-11", "2026-12-04"])
        pref = P.events_for("ALPPA", self.rows, DIRECTORY)
        self.assertEqual([e["circular"] for e in pref], ["C2"])
        self.assertEqual(P.events_for("ZZZ", self.rows, DIRECTORY), [])

    def test_ticker_forms(self):
        self.assertEqual(P.ticker_of("PSE:BDO"), "BDO")
        self.assertEqual(P.ticker_of("edge:tel"), "TEL")
        self.assertEqual(P.ticker_of("glopa.ps"), "GLOPA")
        self.assertIsNone(P.ticker_of("AAPL"))
        self.assertIsNone(P.ticker_of("PSE:M_O"))

    def test_payload_next_and_not_pse(self):
        with mock.patch.object(P, "listing", return_value=(self.rows, 1.0, False)), \
             mock.patch.object(pse_edge, "directory", return_value=DIRECTORY):
            out = P.for_symbol("PSE:ALP", today=dt.date(2026, 11, 26))
        self.assertEqual(out["next"]["ex"], "2026-12-04")
        self.assertEqual(out["coverFrom"], "2024-01-02")
        self.assertTrue(out["complete"])
        with self.assertRaises(LookupError):
            P.for_symbol("AAPL")


if __name__ == "__main__":
    unittest.main()
