"""The peso floor reads a 5-session average of finished PSE sessions.

Today's forming bar is left out until the close; then the average is the
mean of close x volume over the last five finished sessions (2026-11-23).
"""
import datetime
import unittest
from unittest import mock

import bullish
import pse_outlook

MANILA = pse_outlook.MANILA


def _stamp(y, m, d):
    return int(datetime.datetime(y, m, d, 9, 30, tzinfo=MANILA).timestamp())


class FinishedTurnover(unittest.TestCase):
    rows = [
        [_stamp(2026, 11, 13), 4.2, 4.3, 4.2, 4.27, 398000.0],
        [_stamp(2026, 11, 16), 4.2, 4.2, 4.2, 4.2, 95000.0],
    ]

    def _at(self, day, hour, minute):
        now = datetime.datetime(2026, 11, day, hour, minute, tzinfo=MANILA)
        return mock.patch.object(bullish.time, "time", return_value=now.timestamp())

    def test_midsession_leaves_out_today(self):
        with self._at(16, 11, 50):
            value = bullish._finished_turnover(self.rows)
        self.assertAlmostEqual(value, 4.27 * 398000.0)

    def test_after_the_close_counts_today(self):
        with self._at(16, 16, 0):
            value = bullish._finished_turnover(self.rows)
        self.assertAlmostEqual(value, (4.27 * 398000.0 + 4.2 * 95000.0) / 2)

    def test_last_five_finished_sessions(self):
        days = [10, 11, 12, 13, 16, 17, 18]          # weekdays, Nov 2026
        rows = [[_stamp(2026, 11, d), 1, 1, 1, 10.0, 1000.0 * d] for d in days]
        with self._at(18, 10, 0):                    # the 18th is still trading
            value = bullish._finished_turnover(rows)
        # Finished: 11, 12, 13, 16, 17 (the 10th is the sixth back).
        self.assertAlmostEqual(value, 10.0 * 1000.0 * (11 + 12 + 13 + 16 + 17) / 5)

    def test_zero_volume_day_counts_as_zero(self):
        rows = [[_stamp(2026, 11, 12), 1, 1, 1, 2.0, 100.0],
                [_stamp(2026, 11, 13), 1, 1, 1, 2.0, 0.0]]
        with self._at(16, 10, 0):
            self.assertAlmostEqual(bullish._finished_turnover(rows), 100.0)

    def test_no_volume_is_none(self):
        rows = [[_stamp(2026, 11, 13), 1, 1, 1, 1.0]]
        with self._at(16, 11, 50):
            self.assertIsNone(bullish._finished_turnover(rows))


if __name__ == "__main__":
    unittest.main()
