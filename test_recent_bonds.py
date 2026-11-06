import unittest
from unittest import mock

import recent
import server


class BondRowTests(unittest.TestCase):
    """A bond row is a falling yield, and only a falling yield."""

    def _rows(self, label, score=0.5):
        bars = [{"t": 1, "c": 5.0}, {"t": 2, "c": 5.1}]
        with mock.patch.object(recent, "BONDS", (("TVC:PH02Y", "2-year"),)), \
             mock.patch.object(recent, "_cached_bonds", return_value=(bars, 0)), \
             mock.patch.object(recent.onset_module, "current", return_value={
                 "label": label, "score": score, "bars": 2}), \
             mock.patch.object(recent.onset_module, "onset", return_value={
                 "since": 1, "run": 2, "censored": False,
                 "anchored": True, "manner": "turn", "turnMove": 0.0875,
                 "score": score, "window": 2}) as walk:
            rows, stats = recent.bond_rows()
        return rows, stats, walk

    def test_a_falling_yield_is_a_bullish_row(self):
        rows, stats, walk = self._rows("bearish", score=-0.47)
        row = rows[0]
        self.assertEqual(row["direction"], "bullish")
        self.assertEqual(row["note"], "yield falling")
        # The score is the bond-price reading: the yield's own is negated.
        self.assertEqual(row["score"], 0.47)
        self.assertEqual((row["since"], row["run"]), (1, 2))
        # The manner rides along untouched: it describes the yield's own move,
        # signed in the direction the walk was asked for.
        self.assertEqual((row["manner"], row["turnMove"]), ("turn", 0.0875))
        self.assertEqual(walk.call_args.kwargs["want"], "bearish")
        self.assertEqual(stats["missing"], [])
        self.assertEqual((stats["universe"], stats["count"]), (1, 1))

    def test_a_rising_yield_is_not_a_row(self):
        rows, stats, walk = self._rows("bullish", score=0.51)
        self.assertEqual(rows, [])
        self.assertEqual((stats["universe"], stats["count"]), (1, 0))
        # No date to walk to: a row that is not here needs no run.
        walk.assert_not_called()

    def test_a_flat_yield_is_not_a_row(self):
        rows, stats, walk = self._rows("neutral", score=0.1)
        self.assertEqual(rows, [])
        self.assertEqual((stats["universe"], stats["count"]), (1, 0))
        walk.assert_not_called()

    def test_the_note_counts_scanned_and_kept(self):
        payload = {"rows": [{"ticker": "PH02Y"}],
                   "stats": {"Philippine bond": {"universe": 3, "count": 1,
                                                 "missing": []}},
                   "fx": {"phpPerUsd": 63.6}}
        self.assertIn("Philippine bond: 3 scanned, 1 bullish",
                      recent.summarize(payload))
        empty = dict(payload, rows=[],
                     stats={"Philippine bond": {"universe": 3, "count": 0,
                                                "missing": []}})
        self.assertIn("Philippine bond: 3 scanned", recent.summarize(empty))


class SeededBondTests(unittest.TestCase):
    """A stored copy must not put a bearish tenor back on the table."""

    def _seed(self, key, payload):
        state = {"payload": None, "started": 0.0}

        def load(name):
            return (100, payload) if name == key else None

        with mock.patch.object(server, "_recent_state", state), \
             mock.patch.object(server.diskcache, "load", side_effect=load):
            server.seed_recent()
        return state

    def test_legacy_cache_is_converted_without_mutating_original(self):
        legacy = {"rows": [
            {"market": "Philippine bond", "direction": "bearish",
             "score": 0.5, "note": "yield falling", "since": 123},
            {"market": "US", "direction": "bullish", "score": 0.6},
        ], "stats": {"Philippine bond": {"count": 1, "missing": []}}}
        state = self._seed(server.OLDER_RECENT_KEY, legacy)
        bond, stock = state["payload"]["rows"]
        # A falling yield stored the yield's own way reads as a bond price.
        self.assertEqual((bond["direction"], bond["score"], bond["since"]),
                         ("bullish", -0.5, 123))
        self.assertEqual(stock, legacy["rows"][1])
        self.assertEqual(legacy["rows"][0]["direction"], "bearish")
        self.assertTrue(state["payload"]["cached"])

    def test_current_cache_is_not_inverted_again(self):
        current = {"rows": [
            {"market": "Philippine bond", "direction": "bullish",
             "score": 0.5, "note": "yield falling", "since": 7},
            {"market": "US", "direction": "bullish", "score": 0.6},
        ], "stats": {"Philippine bond": {"universe": 3, "count": 1,
                                         "missing": []}}}
        state = self._seed(server.LEGACY_RECENT_KEY, current)
        bond = state["payload"]["rows"][0]
        self.assertEqual((bond["direction"], bond["score"]), ("bullish", 0.5))

    def test_a_stored_bearish_tenor_is_dropped(self):
        stored = {"rows": [
            {"market": "Philippine bond", "ticker": "PH02Y",
             "direction": "bearish", "score": -0.47, "since": 9},
            {"market": "US", "ticker": "MSFT", "direction": "bullish",
             "since": 8},
        ], "stats": {"Philippine bond": {"count": 1, "missing": []}}}
        state = self._seed(server.LEGACY_RECENT_KEY, stored)
        rows = state["payload"]["rows"]
        self.assertEqual([row["ticker"] for row in rows], ["MSFT"])
        # The note is rebuilt from what is actually drawn, not from the copy.
        self.assertIn("Philippine bond: 3 scanned", state["payload"]["note"])
        self.assertNotIn("Philippine bond: 1", state["payload"]["note"])
        # The stored copy itself is untouched.
        self.assertEqual(stored["rows"][0]["direction"], "bearish")


if __name__ == "__main__":
    unittest.main()
