import datetime as dt
import unittest
from unittest import mock

import bearish_forecast_research as research


def sample(day, exit_day, outcome=-1, symbol="X", score=0.):
    return {"symbol": symbol, "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": [score, 0., 0., 0., 0., .5, 0.]}


class BearishResearchTests(unittest.TestCase):
    def test_candidates_abstain_when_required_inputs_missing(self):
        flags = research.flags(sample("2020-01-01", "2020-04-01", score=-.3), None, None, None)
        self.assertTrue(flags["weak_trend"])
        self.assertFalse(flags["local"])
        self.assertFalse(flags["momentum_contrarian"])
        self.assertFalse(flags["reversal_contrarian"])

    def test_directional_candidate_and_boundaries(self):
        s = sample("2020-01-01", "2020-04-01")
        self.assertTrue(research.flags(s, .55, .25, .49)["momentum_contrarian"])
        self.assertFalse(research.flags(s, .55, .25, .50)["momentum_contrarian"])
        self.assertTrue(research.flags(s, .55, .75, .49)["reversal_contrarian"])

    def test_no_candidate_without_sufficient_validation(self):
        s = sample("2020-01-01", "2020-04-01")
        s["flags"] = {name: True for name in research.CANDIDATES}
        self.assertIsNone(research.choose([s])[0])
        self.assertIsNone(research.choose([])[0])

    def test_validation_selection_ties_and_unchanged(self):
        rows = []
        for i in range(120):
            s = sample(f"2022-{1 + i % 6:02d}-01", "2022-12-01",
                       -1 if i < 70 else 0, f"X{i % 10}")
            s["flags"] = {name: False for name in research.CANDIDATES}
            s["flags"]["local"] = i < 60
            rows.append(s)
        winner, diagnostics = research.choose(rows)
        self.assertEqual(winner["rule"], "local")
        self.assertEqual(winner["hit_pct"], 100.)
        self.assertEqual(diagnostics[0]["baseline_pct"], 58.33)

    def test_validation_must_complete_before_test_year(self):
        rows = [sample("2022-01-01", "2022-04-01"),
                sample("2023-12-01", "2024-03-01"),
                sample("2024-01-01", "2024-04-01")]
        for row in rows:
            row["flags"] = {name: False for name in research.CANDIDATES}
        with mock.patch.object(research, "signal_flags", return_value=rows), \
             mock.patch.object(research, "choose", return_value=(None, [])) as choose:
            result = research.evaluate_samples(rows, {}, years=[2024])
        self.assertEqual(choose.call_args.args[0], rows[:1])
        self.assertEqual(result["test_n"], 1)
        self.assertEqual(result["candidate"]["n"], 0)

    def test_comparable_population_requires_local_history(self):
        rows = [sample("2024-01-01", "2024-04-01", symbol="A"),
                sample("2024-01-01", "2024-04-01", symbol="B")]
        for i, row in enumerate(rows):
            row["local_available"] = i == 0
            row["flags"] = {name: False for name in research.CANDIDATES}
        with mock.patch.object(research, "signal_flags", return_value=rows):
            result = research.evaluate_samples(rows, {}, years=[2024], require_local=True)
        self.assertEqual(result["test_n"], 1)

    def test_future_outcomes_do_not_change_earlier_signal_flags(self):
        current = sample("2020-01-01", "2020-04-01")
        future = sample("2020-02-01", "2020-05-01")
        with mock.patch.object(research.relative, "peer_returns", return_value={}), \
             mock.patch.object(research.relative, "relative_features", return_value=None):
            first = research.signal_flags([current, future], {})[0]["flags"]
            future["outcome"] = 1
            second = research.signal_flags([current, future], {})[0]["flags"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
