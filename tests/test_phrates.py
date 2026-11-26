"""Peso cash rates strip: policy change date, bill freshness, outages."""
import unittest
from unittest import mock

import server  # noqa: F401  (loads first)
import deskpack
import memo
import phrates
import pse

DAY = 86400
# Daily bill bars stamped 22:00 UTC = 06:00 Manila the next day.
T0 = 1795039200        # 2026-11-19 06:00 Manila


def bars(closes, start=T0, step=DAY):
    return [[start + i * step, c, c, c, c] for i, c in enumerate(closes)]


POLICY_BARS = [[1787788800, 5.0, 5.0, 5.0, 5.0],   # 2026-08-27 00:00 UTC
               [1792627200, 5.5, 5.5, 5.5, 5.5]]   # 2026-10-22 00:00 UTC


class BuildTests(unittest.TestCase):
    def test_policy_since_is_the_change_bar_in_manila(self):
        row = phrates.policy_row(POLICY_BARS)
        self.assertEqual(row, {"rate": 5.5, "since": "2026-10-22", "previous": 5.0})

    def test_policy_unchanged_bars_keep_the_first_date(self):
        rows = POLICY_BARS + [[1792627200 + 30 * DAY, 5.5, 5.5, 5.5, 5.5]]
        self.assertEqual(phrates.policy_row(rows)["since"], "2026-10-22")

    def test_bill_moves_and_week_change(self):
        row = phrates.bill_row("TVC:PH03MY", "3 months",
                               bars([6.40, 6.38, 6.39, 6.38, 6.53, 6.54, 6.58]))
        self.assertEqual(row["yield"], 6.58)
        self.assertEqual(row["asOf"], "2026-11-25")
        self.assertIsNone(row["unchangedSince"])
        self.assertAlmostEqual(row["changeWeek"], 6.58 - 6.38, places=3)

    def test_bill_carried_forward_says_when_it_last_moved(self):
        row = phrates.bill_row("TVC:PH01Y", "1 year", bars([6.8, 6.9, 6.92, 6.92, 6.92]))
        self.assertEqual(row["unchangedSince"], "2026-11-21")

    def test_missing_tenor_is_left_out_not_zero(self):
        out = phrates.build({phrates.POLICY: POLICY_BARS,
                             "TVC:PH03MY": bars([6.5, 6.52])})
        self.assertEqual([b["tenor"] for b in out["bills"]], ["3 months"])
        self.assertIn("TVC:PH01Y", out["missing"])
        self.assertNotIn(phrates.POLICY, out["missing"])

    def test_cash_history_is_the_3_month_bill_by_manila_day(self):
        out = phrates.build({"TVC:PH03MY": bars([6.4, 6.5])})
        self.assertEqual(out["cashHistory"], [["2026-11-19", 6.4], ["2026-11-20", 6.5]])
        self.assertEqual(phrates.build({phrates.POLICY: POLICY_BARS})["cashHistory"], [])

    def test_nothing_arrived_is_an_outage(self):
        with self.assertRaises(pse.PseError):
            phrates.build({})


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        server._cache.pop(phrates.KEY, None)
        server._flights.pop(phrates.KEY, None)

    tearDown = setUp

    def test_outage_serves_the_saved_copy(self):
        good = phrates.build({phrates.POLICY: POLICY_BARS})
        server.diskcache.store(phrates.KEY, good)
        # The memo answers from the saved copy at once and refreshes behind
        # it; the refresh is stubbed so no browser starts during the test.
        with mock.patch.object(pse, "history_many", return_value={}), \
                mock.patch.object(memo, "_revalidate_worker"):
            out = phrates.snapshot()
        self.assertEqual(out["policy"]["rate"], 5.5)
        self.assertTrue(out.get("cached"))

    def test_outage_with_no_saved_copy_is_an_error_not_zeros(self):
        server.diskcache.store(phrates.KEY, None)
        with mock.patch.object(pse, "history_many", return_value={}):
            with self.assertRaises(pse.PseError):
                phrates.snapshot()

    def test_digest_reads_the_same_saved_copy(self):
        server.diskcache.store(phrates.KEY, phrates.build({phrates.POLICY: POLICY_BARS}))
        bsp = deskpack.bsp_policy()
        self.assertEqual(bsp["rrp"], "5.50%")
        self.assertEqual(bsp["since"], "2026-10-22")
        self.assertEqual(deskpack.btr_auctions(), [])


if __name__ == "__main__":
    unittest.main()
