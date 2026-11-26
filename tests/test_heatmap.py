"""Include the offline heatmap checks in the normal test run."""

import pathlib
import subprocess
import unittest


class HeatmapTest(unittest.TestCase):
    def test_moves_groups_and_depth(self):
        subprocess.run(["node", pathlib.Path(__file__).with_suffix(".js")], check=True)
