"""The peso floor must read a finished PSE session, not today's forming bar."""
import datetime
import unittest
from unittest import mock

import bullish
import pse
import pse_outlook

MANILA = pse_outlook.MANILA


def _stamp(y, m, d):
    return int(datetime.datetime(y, m, d, 9, 30, tzinfo=MANILA).timestamp())


class FinishedTurnover(unittest.TestCase):
    rows = [
        [_stamp(2026, 11, 13), 4.2, 4.3, 4.2, 4.27, 398000.0],
        [_stamp(2026, 11, 16), 4.2, 4.2, 4.2, 4.2, 95000.0],
    ]

    def _at(self, hour, minute):
        now = datetime.datetime(2026, 11, 16, hour, minute, tzinfo=MANILA)
        return mock.patch.object(pse.time, "time", return_value=now.timestamp())

    def test_midsession_uses_last_finished_day(self):
        with self._at(11, 50):
            value = bullish._finished_turnover(self.rows, 399000.0)
        self.assertAlmostEqual(value, 4.27 * 398000.0)

    def test_after_the_close_uses_today(self):
        with self._at(16, 0):
            value = bullish._finished_turnover(self.rows, 399000.0)
        self.assertAlmostEqual(value, 4.2 * 95000.0)

    def test_no_volume_keeps_fallback(self):
        rows = [[_stamp(2026, 11, 13), 1, 1, 1, 1.0]]
        with self._at(11, 50):
            self.assertEqual(bullish._finished_turnover(rows, None), None)


if __name__ == "__main__":
    unittest.main()
