import datetime as dt
import unittest
from zoneinfo import ZoneInfo

import pse_backtest
import pse_outlook


class BacktestTests(unittest.TestCase):
    def test_calendar_horizon_handles_month_end(self):
        self.assertEqual(pse_backtest._months_after(dt.date(2024, 11, 30), 3),
                         dt.date(2025, 2, 28))
        self.assertEqual(pse_backtest._months_after(dt.date(2025, 1, 31), -6),
                         dt.date(2024, 7, 31))

    def test_next_open_and_holdout_boundary(self):
        tz = ZoneInfo("Asia/Manila")
        first = dt.date(2023, 1, 1)
        rows = []
        for i in range(1000):
            date = first + dt.timedelta(days=i)
            stamp = int(dt.datetime(date.year, date.month, date.day, 9, tzinfo=tz).timestamp())
            rows.append([stamp, 100.0, 110.0, 1000.0])
        data = {"collected_at": "test", "source": "test", "universe": ["PSE:X"],
                "missing": [], "bars": {"PSE:X": rows}}
        result = pse_backtest.evaluate(data)
        for period in ("development", "holdout"):
            values = result["results"][period]["all"]
            self.assertGreater(values["n"], 0)
            self.assertEqual(values["mean_return_pct"], 10.0)
            self.assertNotIn("continuously_bullish_pct", values)

    def test_context_uses_completed_history_and_rejects_stale(self):
        tz = ZoneInfo("Asia/Manila")
        today = dt.datetime(2026, 10, 30, 12, tzinfo=tz)
        points = []
        for i in range(400):
            date = (today - dt.timedelta(days=399 - i)).date()
            stamp = int(dt.datetime(date.year, date.month, date.day, 9, tzinfo=tz).timestamp())
            points.append({"t": stamp, "c": 100 + i})
        result = pse_outlook.context(points, today)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["asOf"], "2026-10-29")
        self.assertTrue(result["confirmed"])
        self.assertEqual(pse_outlook.context(points[:-20], today)["status"], "insufficient")
        self.assertEqual(pse_outlook.context(points[-100:], today)["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()
