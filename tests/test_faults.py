import io
import unittest
from unittest import mock

import faults
import recent
import tv


class NoteTests(unittest.TestCase):
    def setUp(self):
        faults.reset()

    def tearDown(self):
        faults.reset()

    def _lines(self, calls, clock):
        out = io.StringIO()
        with mock.patch.object(faults.sys, "stderr", out), \
             mock.patch.object(faults.time, "time", side_effect=clock):
            for where, exc in calls:
                faults.note(where, exc)
        return out.getvalue().splitlines()

    def test_the_first_failure_is_printed_with_its_reason(self):
        lines = self._lines([("bond cache write", OSError("disk  full"))], [100.0])
        self.assertEqual(lines, ["  quiet failure: bond cache write: OSError: disk full"])

    def test_repeats_are_held_back_then_counted(self):
        calls = [("Nasdaq bars", ValueError("a"))] * 4
        lines = self._lines(calls, [0.0, 1.0, 2.0, faults.REPEAT + 1.0])
        self.assertEqual(len(lines), 2)
        self.assertIn("and 2 more like it", lines[1])
        self.assertEqual(faults.counts["Nasdaq bars"], 4)

    def test_a_different_kind_or_place_is_its_own_line(self):
        lines = self._lines([("a", ValueError("x")), ("a", KeyError("x")),
                             ("b", ValueError("x"))], [0.0, 0.0, 0.0])
        self.assertEqual(len(lines), 3)

    def test_it_never_raises(self):
        class Broken(Exception):
            def __str__(self):
                raise RuntimeError("no text")
        faults.note("anywhere", Broken())


class BondStoreTests(unittest.TestCase):
    def test_freshly_fetched_bond_bars_are_kept(self):
        # The row used to call a store that did not exist in its module, and the
        # error was swallowed, so a fetched yield series was never kept.
        bars = [{"t": 1, "c": 5.0}, {"t": 2, "c": 5.1}]
        with mock.patch.object(recent, "BONDS", (("TVC:PH02Y", "2-year"),)), \
             mock.patch.object(recent, "_cached_bonds", return_value=(None, 0.0)), \
             mock.patch.object(tv, "histories", return_value={"TVC:PH02Y": bars}), \
             mock.patch.object(tv, "store_bars") as store:
            recent.bond_rows()
        store.assert_called_once_with("TVC:PH02Y", bars)


if __name__ == "__main__":
    unittest.main()
