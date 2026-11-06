import datetime as dt
import unittest
from unittest import mock

import pse_bull_fund_bear_research as research


def sample(outcome, symbol="X", day="2022-01-01", exit_day="2022-04-01", label="bullish"):
    return {"symbol": symbol, "date": dt.date.fromisoformat(day),
            "exit": dt.date.fromisoformat(exit_day), "outcome": outcome,
            "features": [.5, 0., 0., .1, .01, .8, 0.], "app_label": label}


class PseBullFundBearTests(unittest.TestCase):
    def test_bullish_candidates_never_override_app_label(self):
        for label in ("neutral", "bearish"):
            result = research.make_flags(sample(1, label=label), "bullish", .9, .9, None)
            self.assertFalse(any(result.values()))
        self.assertTrue(research.make_flags(sample(1), "bullish", .9, .9, None)["bull_local_peer_momentum"])

    def test_missing_inputs_abstain_for_local_peer_and_market_rules(self):
        bull = research.make_flags(sample(1), "bullish", None, None, None)
        self.assertTrue(bull["bull"])
        self.assertFalse(bull["bull_local"])
        self.assertFalse(bull["bull_peer_momentum"])
        bear = research.make_flags(sample(-1), "bearish", None, None, None)
        self.assertFalse(bear["momentum_contrarian"])

    def test_selector_uses_bullish_subset_as_baseline(self):
        rows = []
        for i in range(120):
            row = sample(1 if i < 65 else -1, f"S{i % 10}", f"2022-{1 + i % 6:02d}-01")
            row["flags"] = {name: False for name in research.PSE_RULES}
            row["flags"]["bull"] = True
            row["flags"]["bull_strong"] = i < 50
            rows.append(row)
        choice, diagnostics = research.choose(rows, research.PSE_RULES, "bullish")
        self.assertEqual(choice["rule"], "bull_strong")
        self.assertEqual(diagnostics[0]["base_pct"], 54.17)

    def test_unchanged_is_not_success(self):
        rows = []
        for i in range(60):
            row = sample(0, f"S{i % 10}", f"2022-{1 + i % 6:02d}-01")
            row["flags"] = {name: True for name in research.PSE_RULES}
            rows.append(row)
        winner, diagnostics = research.choose(rows, research.PSE_RULES, "bullish")
        self.assertIsNone(winner)
        self.assertEqual(diagnostics[0]["hit_pct"], 0.)

    def test_validation_cannot_use_incomplete_outcome(self):
        rows = [sample(1, day="2022-01-01", exit_day="2022-04-01"),
                sample(1, day="2023-12-01", exit_day="2024-03-01"),
                sample(1, day="2024-01-01", exit_day="2024-04-01")]
        for row in rows:
            row["flags"] = {name: False for name in research.PSE_RULES}
        with mock.patch.object(research, "choose", return_value=(None, [])) as choose:
            result = research.evaluate_rows(rows, "bullish", years=[2024])
        self.assertEqual(choose.call_args.args[0], rows[:1])
        self.assertEqual(result["test_n"], 1)

    def test_no_validation_abstains(self):
        self.assertEqual(research.choose([], research.PSE_RULES, "bullish"), (None, []))

    def test_future_outcome_does_not_affect_earlier_flags(self):
        first = sample(1, day="2020-01-01", exit_day="2020-04-01")
        later = sample(-1, day="2020-02-01", exit_day="2020-05-01")
        with mock.patch.object(research.relative, "peer_returns", return_value={}), \
             mock.patch.object(research.relative, "relative_features", return_value=None):
            before = research.reconstruct([first, later], {}, "bullish")[0]["flags"]
            later["outcome"] = 1
            after = research.reconstruct([first, later], {}, "bullish")[0]["flags"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
