import unittest

import quality

DAY = 86_400
T0 = 1_700_000_000


def series(n=30, price=100.0):
    stamps = [T0 + i * DAY for i in range(n)]
    closes = [price + (i % 5) * 0.3 for i in range(n)]
    volumes = [1000 + i for i in range(n)]
    return stamps, closes, volumes


def codes(flags):
    return {f["code"] for f in flags}


class QualityTests(unittest.TestCase):
    def test_sound_series_has_no_flags(self):
        self.assertEqual(quality.check(*series()), [])

    def test_empty_series_has_no_flags(self):
        self.assertEqual(quality.check([], [], []), [])

    def test_bad_price(self):
        stamps, closes, volumes = series()
        closes[5] = 0
        self.assertIn("bad_price", codes(quality.check(stamps, closes, volumes)))
        closes[5] = float("nan")
        self.assertIn("bad_price", codes(quality.check(stamps, closes, volumes)))

    def test_repeated_or_backwards_dates(self):
        stamps, closes, volumes = series()
        stamps[7] = stamps[6]
        self.assertIn("unordered", codes(quality.check(stamps, closes, volumes)))
        stamps, closes, volumes = series()
        stamps[7], stamps[8] = stamps[8], stamps[7]
        self.assertIn("unordered", codes(quality.check(stamps, closes, volumes)))

    def test_gap_only_when_wider_than_holidays(self):
        stamps, closes, volumes = series()
        for i in range(10, len(stamps)):
            stamps[i] += 4 * DAY          # a long weekend: fine
        self.assertNotIn("gap", codes(quality.check(stamps, closes, volumes)))
        for i in range(10, len(stamps)):
            stamps[i] += 12 * DAY         # nearly three weeks of nothing
        flags = quality.check(stamps, closes, volumes)
        self.assertIn("gap", codes(flags))
        self.assertTrue(any("day gap" in f["text"] for f in flags))

    def test_jump(self):
        stamps, closes, volumes = series()
        closes[15:] = [c * 2.5 for c in closes[15:]]
        self.assertIn("jump", codes(quality.check(stamps, closes, volumes)))

    def test_frozen_run(self):
        stamps, closes, volumes = series()
        closes[-quality.FROZEN_RUN:] = [closes[-quality.FROZEN_RUN]] * quality.FROZEN_RUN
        self.assertIn("frozen", codes(quality.check(stamps, closes, volumes)))

    def test_no_volume_only_where_a_market_has_volume(self):
        stamps, closes, _ = series()
        zeros = [0.0] * len(closes)
        self.assertIn("no_volume", codes(quality.check(stamps, closes, zeros)))
        self.assertNotIn("no_volume", codes(quality.check(stamps, closes, zeros, volume=False)))
        self.assertNotIn("no_volume", codes(quality.check(stamps, closes, None)))

    def test_attach_marks_only_flagged_rows(self):
        rows = [{"chartSymbol": "A"}, {"chartSymbol": "B"}]
        quality.attach(rows, {"A": [{"code": "gap", "text": "x"}], "B": []})
        self.assertIn("quality", rows[0])
        self.assertNotIn("quality", rows[1])


if __name__ == "__main__":
    unittest.main()
