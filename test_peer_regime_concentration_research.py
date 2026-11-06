import datetime as dt
import unittest

import peer_regime_concentration_research as research


def row(day, symbol, outcome):
    return ({"date": dt.date.fromisoformat(day), "symbol": symbol, "outcome": outcome}, "bearish")


class ConcentrationTests(unittest.TestCase):
    def test_exclusion_counts_and_ties(self):
        calls = [row("2023-01-01", "A", -1), row("2023-02-01", "A", 0),
                 row("2024-01-01", "B", 1)]
        groups = research.group_stats(calls, "bearish", lambda s: s["symbol"])
        self.assertEqual(groups[0]["hit_pct"], 50.)
        self.assertEqual(groups[0]["without_group_hit_pct"], 0.)
        self.assertEqual(groups[1]["without_group_hit_pct"], 50.)
        self.assertEqual(research.analyze(calls, "bearish")["selected_only"]["correct"], 1)
        self.assertNotIn("coverage_pct", research.analyze(calls, "bearish")["selected_only"])

    def test_empty_group_is_safe(self):
        self.assertEqual(research.group_stats([], "bullish", lambda s: s["symbol"]), [])


if __name__ == "__main__":
    unittest.main()
