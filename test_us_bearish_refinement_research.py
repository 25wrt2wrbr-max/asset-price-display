import datetime as dt
import unittest
from unittest import mock

import us_bearish_refinement_research as research


def sample(day, exit_day, outcome=-1, symbol="X", prior=True):
    return {"symbol": symbol, "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": [0.] * 7, "model_features": [0.] * 17,
            "rules": {"six_month": 0., "year_momentum": 0.},
            "flags": {"momentum_contrarian": prior}}


class UsRefinementTests(unittest.TestCase):
    def test_missing_model_abstains(self):
        self.assertEqual(research.select(None, []), (None, []))

    def test_ties_are_incorrect(self):
        rows = [sample(f"2022-{1+i%6:02d}-01", "2022-12-01", 0, f"S{i%5}") for i in range(40)]
        with mock.patch.object(research.model, "score", return_value=.5):
            winner, diagnostics = research.select({}, rows)
        self.assertIsNone(winner)
        self.assertEqual(diagnostics[0]["hit_pct"], 0.)

    def test_fit_and_validation_embargo_and_prior_subset(self):
        rows = [sample("2021-01-01", "2021-04-01"),
                sample("2021-12-01", "2022-03-01"),
                sample("2022-01-01", "2022-04-01"),
                sample("2023-12-01", "2024-03-01"),
                sample("2024-01-01", "2024-04-01", prior=False),
                sample("2024-01-01", "2024-04-01")]
        with mock.patch.object(research.model, "train", return_value={}) as train, \
             mock.patch.object(research, "select", return_value=({"threshold": .5}, [])) as select, \
             mock.patch.object(research.model, "score", return_value=.9):
            result = research.evaluate(rows, years=[2024])
        self.assertEqual([s["date"] for s in train.call_args.args[0]], [rows[0]["date"]])
        self.assertEqual([s["date"] for s in select.call_args.args[1]], [rows[2]["date"]])
        self.assertEqual(result["candidate"]["n"], 1)
        self.assertEqual(result["previous"]["n"], 1)

    def test_features_do_not_depend_on_outcome(self):
        row = sample("2024-01-01", "2024-04-01")
        old = research.features(row, .6)
        row["outcome"] = 1
        self.assertEqual(old, research.features(row, .6))

    def test_validation_selection_requires_lift_over_previous_calls(self):
        rows = []
        for i in range(80):
            row = sample(f"2022-{1+i%8:02d}-01", "2022-12-01", -1 if i < 50 else 1, f"S{i%10}")
            row["model_features"] = [float(i)]
            rows.append(row)
        with mock.patch.object(research.model, "score", side_effect=lambda fitted, f: -f[0]):
            choice, diagnostics = research.select({}, rows)
        self.assertEqual(diagnostics[0]["baseline_pct"], 62.5)
        self.assertIsNotNone(choice)
        self.assertGreater(choice["hit_pct"], 62.5)

    def test_insufficient_months_prevent_threshold_selection(self):
        rows = [sample("2022-01-01", "2022-04-01", -1, f"S{i%10}") for i in range(80)]
        with mock.patch.object(research.model, "score", return_value=.5):
            choice, diagnostics = research.select({}, rows)
        self.assertIsNone(choice)
        self.assertTrue(all(not d["qualifies"] for d in diagnostics))


if __name__ == "__main__":
    unittest.main()
