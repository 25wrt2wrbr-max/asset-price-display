import unittest

import onset


def series(closes):
    """Daily bars a day apart, starting at a fixed stamp."""
    base = 1700000000
    return [base + onset.DAY * i for i in range(len(closes))]


class TurnTests(unittest.TestCase):
    """`onset.turn`: did the series move, or did only the window's base?"""

    def test_a_real_turn_reads_turn(self):
        # Twenty bars rising 10%: the run began because the price moved.
        closes = [100.0] * 40 + [100.0 * (1.10 ** (i / 20)) for i in range(1, 21)]
        manner, move = onset.turn(closes, len(closes) - 1, "bullish")
        self.assertEqual(manner, "turn")
        self.assertGreater(move, onset.TURN_MOVE)

    def test_a_standing_still_series_reads_flat(self):
        # Flat for the whole lookback: nothing moved, so the window's oldest
        # bar leaving is the only thing that can have changed the return.
        closes = [100.0] * 60
        manner, move = onset.turn(closes, len(closes) - 1, "bullish")
        self.assertEqual(manner, "flat")
        self.assertAlmostEqual(move, 0.0)

    def test_drifting_the_other_way_reads_against(self):
        closes = [100.0] * 40 + [100.0 * (0.98 ** (i / 20)) for i in range(1, 21)]
        manner, move = onset.turn(closes, len(closes) - 1, "bullish")
        self.assertEqual(manner, "against")
        self.assertLess(move, -onset.TURN_MOVE)

    def test_the_move_is_signed_in_the_runs_own_direction(self):
        # A falling yield is a bullish bond: the same falling series must read
        # a turn for want="bearish" and "against" for want="bullish".
        closes = [100.0] * 40 + [100.0 * (0.90 ** (i / 20)) for i in range(1, 21)]
        last = len(closes) - 1
        bear, bear_move = onset.turn(closes, last, "bearish")
        bull, bull_move = onset.turn(closes, last, "bullish")
        self.assertEqual(bear, "turn")
        self.assertEqual(bull, "against")
        self.assertAlmostEqual(bear_move, -bull_move)

    def test_no_history_behind_the_run_is_no_reading(self):
        # A run starting on the oldest bar fetched, or with fewer than
        # TURN_BARS behind it, has nothing to read. Absent, not guessed.
        closes = [100.0 + i for i in range(30)]
        for start in (0, onset.TURN_BARS - 1):
            self.assertEqual(onset.turn(closes, start, "bullish"), (None, None))

    def test_the_threshold_is_inclusive_at_the_boundary(self):
        closes = [100.0] * 40 + [100.0 * (1 + onset.TURN_MOVE)]
        manner, move = onset.turn(closes, len(closes) - 1, "bullish")
        self.assertEqual(manner, "turn")
        self.assertAlmostEqual(move, onset.TURN_MOVE)


class OnsetMannerTests(unittest.TestCase):
    """The manner rides on the walk, and never changes its label or date."""

    def test_manner_is_reported_and_does_not_change_the_verdict(self):
        # A fall and then a sharp recovery: the bullish run begins part-way
        # through, with bars behind it to read. The label, date and run are
        # whatever the walk said before; the manner is a reading beside them.
        closes = ([100.0 - 0.1 * i for i in range(130)]            # 100 -> 87
                  + [87.0 * (1.02 ** i) for i in range(1, 71)])    # recovery
        stamps = series(closes)
        vols = [1000.0] * len(closes)
        call = onset.onset(stamps, closes, vols, "bullish")
        self.assertIsNotNone(call)
        self.assertFalse(call["censored"])
        self.assertEqual(call["since"], stamps[-call["run"]])
        self.assertEqual(call["manner"], "turn")
        self.assertGreater(call["turnMove"], onset.TURN_MOVE)
        # The label over the same bars still comes from the one classifier.
        self.assertEqual(onset.label(closes, vols,
                                     onset.window_now(stamps, len(closes) - 1)),
                         "bullish")

    def test_a_run_into_the_data_floor_is_censored(self):
        # A money-market rise is bullish in every window, so the walk walks
        # off the end of the data. It stops where the short prefix can no
        # longer carry a directional call (the damping wall below
        # MIN_RETURNS + 1 bars), which is the fetched history running out --
        # a floor, not an exact date. Used to report censored=False with an
        # exact-looking date 13 days after the history begins.
        closes = [100.0 * (1.01 ** i) for i in range(260)]
        stamps = series(closes)
        call = onset.onset(stamps, closes, [1000.0] * len(closes), "bullish")
        self.assertTrue(call["censored"])
        self.assertLessEqual(call["run"], len(closes))
        # A censored run has no manner: there is nothing behind its first bar.
        self.assertIsNone(call["manner"])
        self.assertIsNone(call["turnMove"])

    def test_flat_series_yields_no_turn(self):
        # A dead-flat price cannot be bullish, so the walk answers None and
        # there is no manner to report -- a missing call is not a verdict.
        closes = [100.0] * 120
        stamps = series(closes)
        self.assertIsNone(
            onset.onset(stamps, closes, [1000.0] * len(closes), "bullish"))


if __name__ == "__main__":
    unittest.main()
