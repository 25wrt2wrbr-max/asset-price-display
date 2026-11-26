"""Rows carry the window's volumes beside its closes, for the volume tag."""

import time
import unittest

import onset


def _bars(volume):
    end = time.time() - 60
    stamps = [int(end - (69 - i) * 86_400) for i in range(70)]
    closes = [100.0 + i for i in range(70)]
    return stamps, closes, [volume] * 70


class SparkVolumeTests(unittest.TestCase):
    def test_volumes_match_the_spark_window(self):
        call = onset.onset(*_bars(1_234_567.0))
        self.assertIsNotNone(call)
        self.assertEqual(len(call["sparkVol"]), len(call["spark"]))
        self.assertEqual(call["sparkVol"][-1], 1_235_000.0)   # four digits

    def test_no_volume_is_none(self):
        self.assertIsNone(onset.onset(*_bars(0.0))["sparkVol"])

    def test_helper_handles_missing_values(self):
        self.assertIsNone(onset.spark_volumes([None, None], [0, 1]))
        self.assertEqual(onset.spark_volumes([None, 5.0], [0, 1]), [0.0, 5.0])


if __name__ == "__main__":
    unittest.main()
