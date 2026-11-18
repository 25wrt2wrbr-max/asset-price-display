import datetime as dt
import unittest

import pse_bullish_local_research as research


class PseLocalTests(unittest.TestCase):
    def test_filters_never_override_existing_bullish_label(self):
        for label in ("neutral", "bearish"):
            self.assertFalse(any(research.decide({"app_label": label}, .9, .9).values()))

    def test_unknown_historical_scores_abstain(self):
        flags = research.decide({"app_label": "bullish"}, None, None)
        self.assertTrue(flags["app_bullish"])
        self.assertFalse(flags["local"])
        self.assertFalse(flags["neighbor"])
        self.assertFalse(flags["both"])

    def test_future_and_same_day_outcomes_do_not_enter_history(self):
        current = {"symbol": "X", "date": dt.date(2024, 1, 1), "exit": dt.date(2024, 4, 1),
                   "features": [0.] * 7, "outcome": 1, "app_label": "bullish"}
        history = [dict(current, date=dt.date(2023, 1, 1), exit=dt.date(2024, 1, 1)) for _ in range(30)]
        self.assertIsNone(research.local.estimate(history, current, "bullish"))
        self.assertIsNone(research.neighbor.estimate(history, current, "bullish"))


if __name__ == "__main__":
    unittest.main()
