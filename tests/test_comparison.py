"""Include the offline comparison UI checks in the normal test run."""

import pathlib
import subprocess
import unittest


class ComparisonTest(unittest.TestCase):
    def test_chart_and_request_lifecycle(self):
        subprocess.run(["node", pathlib.Path(__file__).with_suffix(".js")], check=True)
