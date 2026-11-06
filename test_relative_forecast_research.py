import datetime as dt
import unittest
from unittest import mock

import market_forecasts as model
import relative_forecast_research as relative


def sample(day, exit_day, symbol="X", outcome=1):
    return {"symbol": symbol, "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": [0.] * 13, "local_score": .4}


class RelativeForecastTests(unittest.TestCase):
    def test_peer_data_excludes_same_day_and_future_and_stale_data(self):
        start = dt.date(2023, 1, 1)
        dates = [start + dt.timedelta(days=i) for i in range(130)]
        prices = [100 + i for i in range(130)]
        day = dates[100]
        baseline = relative.peer_returns({"X": (dates, prices)}, day)
        changed = prices[:100] + [999999.] * 30
        self.assertEqual(relative.peer_returns({"X": (dates, changed)}, day), baseline)
        self.assertNotIn("X", relative.peer_returns({"X": (dates[:80], prices[:80])}, day))

    def test_current_asset_is_excluded_and_minimum_peers_is_enforced(self):
        current = sample("2024-01-01", "2024-04-01")
        peers = {f"S{i}": (0., 0.) for i in range(10)}
        peers["X"] = (99., 99.)
        self.assertEqual(relative.relative_features(current, peers), [0., 0., 0.])
        del peers["S0"]
        self.assertIsNone(relative.relative_features(current, peers))

    def test_train_and_validation_never_use_unfinished_outcomes(self):
        rows = [sample("2021-01-01", "2021-04-01"),
                sample("2021-12-01", "2022-03-01"),
                sample("2022-01-01", "2022-04-01"),
                sample("2023-12-01", "2024-03-01"),
                sample("2024-01-01", "2024-04-01")]
        with mock.patch.object(model, "train", return_value=None) as fit, \
             mock.patch.object(relative.adaptive, "choose", return_value=(None, [])) as choose:
            result = relative.evaluate_samples(rows, "bullish", [], years=[2024])
        self.assertEqual(fit.call_args.args[0], rows[:1])
        self.assertEqual(choose.call_args.args[1], rows[2:3])
        self.assertEqual(result["test_n"], 1)
        self.assertEqual(result["relative"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
