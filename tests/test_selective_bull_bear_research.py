import datetime as dt
import unittest
from unittest import mock

import selective_bull_bear_research as research


def row(day="2023-01-01", exit_day="2023-04-01", outcome=1, symbol="X", label="bullish"):
    return {"date": dt.date.fromisoformat(day), "exit": dt.date.fromisoformat(exit_day),
            "outcome": outcome, "symbol": symbol, "app_label": label,
            "features": [.5, 0., -.1, .1, .01, .8, 0.]}


class SelectiveTests(unittest.TestCase):
    def test_all_bull_filters_require_actual_bull_label(self):
        for label in ("bearish", "neutral"):
            flags = research.flags(row(label=label), "bullish", .8, .9, .1)
            self.assertFalse(any(flags.values()))

    def test_fund_filters_require_previous_call(self):
        f = research.flags(row(), "bearish", .7, .9, .1)
        self.assertFalse(any(f.values()))
        f = research.flags(row(), "bearish", .7, .1, .1)
        self.assertTrue(f["baseline"])
        self.assertTrue(f["prior_strong_local"])
        self.assertFalse(f["prior_short_up"])

    def test_insufficient_validation_abstains(self):
        self.assertIsNone(research.choose([], dt.date(2024, 1, 1), "bullish"))

    def test_selector_rejects_pending_and_same_day_outcomes(self):
        rows = []
        for i in range(60):
            r = row(day=f"2023-{1+i%6:02d}-01", exit_day="2023-12-31", outcome=1 if i < 30 else -1, symbol=f"S{i%10}")
            r["flags"] = {name: i < 30 for name in research.PSE_RULES}
            r["flags"]["baseline"] = True
            rows.append(r)
        day = dt.date(2024, 1, 1)
        choice = research.choose(rows, day, "bullish")
        self.assertIsNotNone(choice)
        self.assertEqual(choice["correct"], 30)
        self.assertEqual(choice["base_n"], 60)
        for r in rows[:30]:
            r["exit"] = day
        self.assertIsNone(research.choose(rows, day, "bullish"))

    def test_candidate_only_uses_choice_and_same_date_baseline(self):
        rows = [row(day="2024-01-01", exit_day="2024-04-01")]
        rows[0]["flags"] = {"baseline": True, "bull_local": True}
        with mock.patch.object(research, "choose", return_value={"rule": "bull_local", "n": 30, "correct": 20, "base_n": 40, "base_correct": 21, "latest_exit": "2023-12-31"}):
            result = research.evaluate_rows(rows, "bullish", years=[2024])
        self.assertEqual(result["candidate"]["n"], 1)
        self.assertEqual(result["previous_active_dates"]["n"], 1)


if __name__ == "__main__":
    unittest.main()
