import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class LongTermTestKeptTest(unittest.TestCase):
    """Fails if the long-term holdout test is deleted. See docs/long-term-test.md."""

    def test_pieces_exist(self):
        for rel in ("docs/long-term-test.md", "lab/holdout_stability.py"):
            self.assertTrue((ROOT / rel).exists(), f"{rel} is the long-term holdout test; do not delete")

    def test_script_has_since_mode(self):
        self.assertIn("--since", (ROOT / "lab/holdout_stability.py").read_text())


if __name__ == "__main__":
    unittest.main()
