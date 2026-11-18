import datetime as dt
import unittest
from unittest import mock

import tree_forecast_research as tree


def sample(day, exit_day, outcome=1, features=None):
    return {"symbol": "X", "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": features if features is not None else [0.] * 10,
            "local_score": .4}


class TreeForecastTests(unittest.TestCase):
    def test_tree_learns_non_linear_partition_and_ties_are_misses(self):
        rows = [sample("2020-01-01", "2020-04-01", 1 if i >= 100 else 0, [float(i)]) for i in range(200)]
        trained = tree.train(rows, "bullish")
        self.assertEqual(tree.score(trained, [0.]), 0.)
        self.assertEqual(tree.score(trained, [199.]), 1.)

    def test_invalid_feature_width_and_insufficient_data(self):
        self.assertIsNone(tree.train([], "bullish"))
        rows = [sample("2020-01-01", "2020-04-01", features=[0.]) for _ in range(200)]
        rows[-1]["features"] = [0., 1.]
        with self.assertRaises(ValueError):
            tree.train(rows, "bullish")

    def test_fit_and_validation_exclude_uncompleted_outcomes(self):
        rows = [sample("2021-01-01", "2021-04-01"),
                sample("2021-12-01", "2022-03-01"),
                sample("2022-01-01", "2022-04-01"),
                sample("2023-12-01", "2024-03-01"),
                sample("2024-01-01", "2024-04-01")]
        with mock.patch.object(tree, "train", return_value=None) as train, \
             mock.patch.object(tree, "choose", return_value=(None, [])) as choose:
            result = tree.evaluate_samples(rows, "bullish", [], years=[2024])
        self.assertEqual(train.call_args.args[0], rows[:1])
        self.assertEqual(choose.call_args.args[1], rows[2:3])
        self.assertEqual(result["test_n"], 1)
        self.assertEqual(result["tree"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
