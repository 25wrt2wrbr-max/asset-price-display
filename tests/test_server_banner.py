"""Include the server-down banner checks in the normal test run."""

import pathlib
import subprocess
import unittest


class ServerBannerTest(unittest.TestCase):
    def test_two_misses_raise_one_answer_lowers(self):
        subprocess.run(["node", pathlib.Path(__file__).with_suffix(".js")], check=True)
