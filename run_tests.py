#!/usr/bin/env python3
"""Run every test, then the JS/Python classifier parity check.

    python3 run_tests.py              # everything
    python3 run_tests.py "test_trend*.py"   # only files matching a pattern

Exit status is 0 only when every test and the parity check pass.
"""

import atexit
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
os.chdir(ROOT)  # several tests read files by relative path
# The tests must never read or write the real cache folder.
os.environ["APD_CACHE_DIR"] = tempfile.mkdtemp(prefix="apd-test-cache-")
atexit.register(shutil.rmtree, os.environ["APD_CACHE_DIR"], ignore_errors=True)
for p in (ROOT / "lab", ROOT):
    sys.path.insert(0, str(p))


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else "test_*.py"
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests"), pattern=pattern, top_level_dir=str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    ok = result.wasSuccessful()
    if len(sys.argv) == 1:  # the parity check belongs to the full run only
        parity = subprocess.run([sys.executable, str(ROOT / "export" / "verify_parity.py")])
        phrases = subprocess.run(["node", str(ROOT / "tests" / "test_verdict_words.js")])
        visits = subprocess.run(["node", str(ROOT / "tests" / "test_watch_changes.js")])
        alarms = subprocess.run(["node", str(ROOT / "tests" / "test_alarms.js")])
        ok = ok and parity.returncode == 0 and phrases.returncode == 0 and visits.returncode == 0 and alarms.returncode == 0
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
