"""The crypto leg reads the ranking, not a top slice (2026-11-07).

The page used to carry three tables -- "Recently bullish assets", "Most traded
crypto - 24 hours" and "Bullish Philippine stocks" -- and the reader asked for
them in one: "I think we can combine ... in one table/section", then "the idea
is just to show me which assets are bullish right now".

Making that true without losing a row is the job of `recent.crypto_rows`:

* the crypto table's own walk reached far down the turnover ranking (it kept
  walking until ten bullish coins were found), while the recent table read only
  its first twenty-five candidates. Merged, the shallow read would have dropped
  the one bullish coin of 2026-11-07 -- BEAMUSDT, $0.74M traded, roughly 200th
  -- so the leg now judges the whole chartable ranking;
* the **leaning** rows are still read from the first twenty-five only, because
  the leaning table did not absorb anything and widening the leg must not
  change it;
* the rolling day's change is neither a filter nor a figure on the row: the
  reader asked for the three-month reading only (2026-11-07).

Every test mocks the two upstream calls, so the suite never asks Binance or
CoinGecko anything.
"""

import unittest
from unittest import mock

import recent


def _candidate(index, change=1.0):
    return {
        "symbol": f"COIN{index}-USD",
        "ticker": f"COIN{index}USDT",
        "name": f"Coin {index}",
        "rank": index,
        "turnover": 1_000_000.0 / (index + 1),
        "change": change,
    }


def _chart(symbol, price_hint=2):
    return {
        "symbol": symbol,
        # Four points are all `_series` needs; the two onset calls are mocked,
        # so the bars never reach the classifier in these tests.
        "points": [{"t": 1_792_000_000 + i * 86_400, "c": 1.0 + i}
                   for i in range(4)],
        "volumes": [1.0, 1.0, 1.0, 1.0],
        "marketPrice": 4.0,
        "priceHint": price_hint,
    }


def _bullish_call():
    return {
        "price": 4.0, "since": 1_792_000_000, "run": 4, "censored": False,
        "manner": "turn", "turnMove": 0.05, "score": 0.4, "bars": 63,
        "last": 1_792_259_200, "turnover": 1_000_000.0,
        # Doubled over the window, so the row's move is exactly +100%.
        "windowFirst": 2.0,
    }


def _lean():
    return {
        "price": 4.0, "score": 0.18, "significance": 1.2, "progress": 0.7,
        "bars": 63, "last": 1_792_259_200, "turnover": 1_000_000.0,
        "held": 5, "holdBars": 5,
    }


class CryptoLegTests(unittest.TestCase):
    def _run(self, candidates, bullish_at=None, lean_at=None, price_hint=2):
        """`crypto_rows` over mocked upstreams.

        `bullish_at` and `lean_at` are candidate indices: the classifier doubles
        are called once per candidate, in the ranking's order, so the counter is
        the index and the other candidates read None (judged, not bullish, not
        leaning).
        """
        asked = []
        seen = {"onset": 0, "lean": 0}

        def fake_chart(symbol, span, interval):
            asked.append(symbol)
            return _chart(symbol, price_hint)

        def fake_onset(stamps, closes, volumes, want=None, **kwargs):
            index = seen["onset"]
            seen["onset"] += 1
            return _bullish_call() if index == bullish_at else None

        def fake_lean(stamps, closes, volumes, **kwargs):
            index = seen["lean"]
            seen["lean"] += 1
            return _lean() if index == lean_at else None

        with mock.patch.object(recent.cryptobull, "candidates",
                               return_value=candidates) as ranked, \
             mock.patch.object(recent.crypto, "try_chart", side_effect=fake_chart), \
             mock.patch.object(recent.onset_module, "onset",
                               side_effect=fake_onset), \
             mock.patch.object(recent.onset_module, "steady_lean",
                               side_effect=fake_lean):
            rows, stats = recent.crypto_rows()
        return rows, stats, ranked, asked

    def test_the_whole_ranking_is_walked_not_the_first_twenty_five(self):
        candidates = [_candidate(i, change=0.0) for i in range(40)]
        rows, stats, ranked, asked = self._run(candidates)
        # Every candidate was asked for, and the ask carried the ranking's own
        # full depth rather than the leaning list's twenty-five.
        self.assertEqual(len(asked), 40)
        self.assertEqual(ranked.call_args[0][0], recent.cryptobull.MAX_CANDIDATES)
        self.assertEqual(stats["universe"], 40)
        self.assertEqual(rows, [])

    def test_a_bullish_coin_past_the_old_cut_is_a_row(self):
        # The 2026-11-07 case: the day's only bullish coin ranked ~200th by
        # turnover. Index 30 stands in for it -- outside the old top-25 cut.
        candidates = [_candidate(i, change=0.0) for i in range(31)]
        rows, _, _, _ = self._run(candidates, bullish_at=30)
        self.assertEqual([row["ticker"] for row in rows], ["COIN30USDT"])
        self.assertEqual(rows[0]["direction"], "bullish")

    def test_a_coin_down_on_the_day_is_still_a_row(self):
        # The crypto table skipped a coin flat or down on the rolling day. This
        # table is the three-month verdict, so the day is not a filter.
        candidates = [_candidate(0, change=-8.0)]
        rows, _, _, _ = self._run(candidates, bullish_at=0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["direction"], "bullish")

    def test_the_day_change_is_not_carried_on_the_row(self):
        # Asked for by name: "i'm only interested in 3-month change bro".
        candidates = [_candidate(0, change=3.5)]
        rows, _, _, _ = self._run(candidates, bullish_at=0)
        self.assertNotIn("change", rows[0])

    def test_the_three_month_move_is_carried_on_the_row(self):
        candidates = [_candidate(0)]
        rows, _, _, _ = self._run(candidates, bullish_at=0)
        self.assertEqual(rows[0]["windowMove"], 1.0)

    def test_the_price_hint_travels_so_a_sub_cent_coin_does_not_print_zero(self):
        # BEAM printed "$0.00" in the table's default two decimals until the
        # chart's own hint rode the row; six here proves it is read, not fixed.
        candidates = [_candidate(0)]
        rows, _, _, _ = self._run(candidates, bullish_at=0, price_hint=6)
        self.assertEqual(rows[0]["priceHint"], 6)

    def test_a_leaning_coin_inside_the_first_twenty_five_still_leans(self):
        candidates = [_candidate(i) for i in range(30)]
        rows, _, _, _ = self._run(candidates, lean_at=3)
        self.assertEqual([row["ticker"] for row in rows], ["COIN3USDT"])
        self.assertEqual(rows[0]["lean"], "bullish")

    def test_a_leaning_coin_past_the_first_twenty_five_is_not_added(self):
        # The leaning table keeps exactly the rows it had before the merge.
        candidates = [_candidate(i) for i in range(30)]
        rows, _, _, _ = self._run(candidates, lean_at=recent.CRYPTO_LIMIT)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
