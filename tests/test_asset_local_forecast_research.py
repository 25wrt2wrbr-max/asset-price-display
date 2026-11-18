import datetime as dt
import unittest

import asset_local_forecast_research as local


def s(date, exit, symbol="X", outcome=1, features=None):
    return {"date": dt.date.fromisoformat(date), "exit": dt.date.fromisoformat(exit),
            "symbol": symbol, "outcome": outcome,
            "features": features or [.1, 0, .1, 0, .1, .6, 0]}


class AssetLocalTests(unittest.TestCase):
    def test_too_little_history_abstains(self):
        current = s("2024-01-01", "2024-04-01")
        self.assertIsNone(local.estimate([], current, "bullish"))

    def test_ignores_future_outcomes_and_other_assets(self):
        current = s("2024-01-01", "2024-04-01")
        history = [s("2020-01-01", "2020-04-01", outcome=1) for _ in range(24)]
        baseline = local.estimate(history, current, "bullish")
        ignored = [s("2023-12-01", "2024-03-01", outcome=-1) for _ in range(20)]
        ignored += [s("2020-01-01", "2020-04-01", symbol="Y", outcome=-1) for _ in range(20)]
        self.assertEqual(local.estimate(history + ignored, current, "bullish"), baseline)
        self.assertEqual(baseline["score"], 1.)

    def test_unchanged_price_is_not_a_correct_direction(self):
        current = s("2024-01-01", "2024-04-01")
        history = [s("2020-01-01", "2020-04-01", outcome=0) for _ in range(24)]
        self.assertEqual(local.estimate(history, current, "bullish")["score"], 0.)
        self.assertEqual(local.estimate(history, current, "bearish")["score"], 0.)


if __name__ == "__main__":
    unittest.main()
