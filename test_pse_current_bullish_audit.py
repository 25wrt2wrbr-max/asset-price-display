import datetime as dt
import unittest
from zoneinfo import ZoneInfo

import pse_current_bullish_audit as audit
import trend


AS_OF = dt.datetime(2026, 10, 30, 16, 40, tzinfo=ZoneInfo("Asia/Manila"))


def rows(count, delta=1, last_days_ago=1):
    result = []
    for i in range(count):
        day = AS_OF - dt.timedelta(days=last_days_ago + count - i - 1)
        result.append([int(day.timestamp()), 100., 100. + i * delta, 1000.])
    return result


class CurrentPseBullishAuditTests(unittest.TestCase):
    def test_uses_existing_classifier(self):
        series = rows(60)
        result = audit.inspect("PSE:X", series, AS_OF)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["trend"], trend.classify([r[2] for r in series]))
        self.assertEqual(result["trend"]["label"], "bullish")

    def test_current_day_bar_is_excluded(self):
        series = rows(60)
        series.append([int(AS_OF.timestamp()) - 1, 1., 1., 1.])
        result = audit.inspect("PSE:X", series, AS_OF)
        self.assertEqual(result["bars"], 60)
        self.assertEqual(result["last_close"], 159.)

    def test_short_and_stale_are_explicit(self):
        self.assertEqual(audit.inspect("PSE:X", rows(20), AS_OF)["status"], "short_window")
        stale = audit.inspect("PSE:X", rows(60, last_days_ago=8), AS_OF)
        self.assertEqual(stale["status"], "stale")
        self.assertIsNone(stale["trend"])
        self.assertEqual(audit.inspect("PSE:X", [], AS_OF)["status"], "insufficient_window")

    def test_invalid_close_not_treated_as_bearish(self):
        result = audit.inspect("PSE:X", [[int(AS_OF.timestamp()) - 90000, 1, float("nan")]], AS_OF)
        self.assertEqual(result["malformed_rows"], 1)
        self.assertIsNone(result["trend"])

    def test_flat_price_is_neutral(self):
        result = audit.inspect("PSE:X", rows(60, delta=0), AS_OF)
        self.assertEqual(result["trend"]["label"], "neutral")


if __name__ == "__main__":
    unittest.main()
