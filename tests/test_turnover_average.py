"""The 5-session average of value traded, and where each market's forming
session starts (`turnover.py`)."""

import datetime as dt
import unittest
from zoneinfo import ZoneInfo

import turnover

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc


class AverageTests(unittest.TestCase):
    def test_last_five_before_the_cutoff(self):
        stamps = list(range(10))
        closes = [2.0] * 10
        volumes = [float(i) for i in range(10)]
        # Bars 8 and 9 are forming: the five before are 3..7.
        self.assertAlmostEqual(turnover.average(stamps, closes, volumes, cutoff=8),
                               2.0 * (3 + 4 + 5 + 6 + 7) / 5)
        self.assertAlmostEqual(turnover.average(stamps, closes, volumes),
                               2.0 * (5 + 6 + 7 + 8 + 9) / 5)

    def test_missing_volume_is_skipped_not_zero(self):
        out = turnover.average([1, 2, 3], [1.0, 1.0, 1.0], [10.0, None, 20.0])
        self.assertAlmostEqual(out, 15.0)

    def test_no_volume_at_all(self):
        self.assertIsNone(turnover.average([1, 2], [1.0, 1.0], [0.0, 0.0]))
        self.assertIsNone(turnover.average([1, 2], [1.0, 1.0], None))
        self.assertIsNone(turnover.average([], [], []))

    def test_fewer_than_five_sessions(self):
        self.assertAlmostEqual(turnover.average([1, 2], [1.0, 3.0], [1.0, 1.0]), 2.0)


class CutoffTests(unittest.TestCase):
    def ts(self, *a, tz):
        return dt.datetime(*a, tzinfo=tz).timestamp()

    def test_crypto_today_utc_is_forming(self):
        now = self.ts(2026, 11, 22, 23, 43, tz=UTC)
        self.assertEqual(turnover.crypto_cutoff(now), self.ts(2026, 11, 22, tz=UTC))

    def test_new_york_open_day(self):
        friday = (2026, 11, 20)
        self.assertEqual(turnover.ny_cutoff(self.ts(*friday, 11, 0, tz=NY)),
                         self.ts(*friday, tz=NY))
        self.assertEqual(turnover.ny_cutoff(self.ts(*friday, 16, 10, tz=NY)),
                         self.ts(*friday, tz=NY))
        self.assertIsNone(turnover.ny_cutoff(self.ts(*friday, 16, 20, tz=NY)))

    def test_new_york_weekend_and_holiday(self):
        self.assertIsNone(turnover.ny_cutoff(self.ts(2026, 11, 21, 12, 0, tz=NY)))
        self.assertIsNone(turnover.ny_cutoff(self.ts(2026, 11, 26, 12, 0, tz=NY)))  # Thanksgiving


if __name__ == "__main__":
    unittest.main()
