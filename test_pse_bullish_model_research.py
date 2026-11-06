import datetime as dt
import unittest
from unittest import mock

import pse_bullish_model_research as research


def sample(day, exit_day, outcome=1, label="bullish", symbol="X"):
    return {"symbol": symbol, "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": [.4, .02, .03, .1, .02, .8, .1], "app_label": label}


class PseBullishModelTests(unittest.TestCase):
    def test_features_do_not_use_future_outcome(self):
        row = sample("2022-01-01", "2022-04-01")
        old = research.features(row["features"])
        row["outcome"] = -1
        self.assertEqual(research.features(row["features"]), old)
        self.assertEqual(len(old), 15)

    def test_no_model_or_validation_abstains(self):
        self.assertEqual(research.choose(None, []), (None, []))

    def test_validation_uses_higher_close_only(self):
        rows = []
        for i in range(80):
            row = sample(f"2022-{1+i%8:02d}-01", "2022-12-01", 1 if i < 40 else 0, symbol=f"S{i%10}")
            row["model_features"] = [float(i)]
            rows.append(row)
        with mock.patch.object(research.model, "score", side_effect=lambda m, f: -f[0]):
            winner, diagnostics = research.choose({}, rows)
        self.assertIsNotNone(winner)
        self.assertEqual(diagnostics[0]["baseline_pct"], 50.)
        self.assertGreater(winner["hit_pct"], 50.)

    def test_fit_validation_embargo_and_only_bullish_output(self):
        rows = [sample("2021-01-01", "2021-04-01"),
                sample("2021-12-01", "2022-03-01"),
                sample("2022-01-01", "2022-04-01"),
                sample("2023-12-01", "2024-03-01"),
                sample("2024-01-01", "2024-04-01", label="neutral"),
                sample("2024-01-01", "2024-04-01", label="bullish")]
        with mock.patch.object(research.model, "train", return_value={}) as train, \
             mock.patch.object(research, "choose", return_value=({"threshold": .5}, [])) as choose, \
             mock.patch.object(research.model, "score", return_value=.9):
            result = research.evaluate(rows, years=[2024])
        self.assertEqual([s["date"] for s in train.call_args.args[0]], [rows[0]["date"]])
        self.assertEqual([s["date"] for s in choose.call_args.args[1]], [rows[2]["date"]])
        self.assertEqual(result["candidate"]["n"], 1)
        self.assertEqual(result["app_bullish"]["n"], 1)


if __name__ == "__main__":
    unittest.main()
