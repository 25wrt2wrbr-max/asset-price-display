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
# The tests must never read or write the real cache folder or fire OS banners.
os.environ["APD_CACHE_DIR"] = tempfile.mkdtemp(prefix="apd-test-cache-")
os.environ.setdefault("APD_NOTIFY", "0")
atexit.register(shutil.rmtree, os.environ["APD_CACHE_DIR"], ignore_errors=True)
for p in (ROOT / "lab", ROOT):
    sys.path.insert(0, str(p))


# Node tests the full run also executes, in this order.
JS_TESTS = (
    "test_verdict_words.js", "test_watch_changes.js", "test_alarms.js",
    "test_desk.js", "test_spark_canvas.js", "test_etag_memo.js",
    "test_chart_quiet_sig.js",
    "test_psefees.js", "test_labelstrip.js", "test_peso.js", "test_benchmark.js",
    "test_comparison.js", "test_heatmap.js", "test_server_banner.js", "test_rates.js", "test_dividends.js",
    "test_deskextras.js", "test_desksuggest.js", "test_deskpack.js",
    "test_deskbackup.js", "test_friendly_ux.js", "test_glance.js",
)


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else "test_*.py"
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests"), pattern=pattern, top_level_dir=str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    ok = result.wasSuccessful()
    if len(sys.argv) == 1:  # the parity check belongs to the full run only
        parity = subprocess.run([sys.executable, str(ROOT / "export" / "verify_parity.py")])
        ok = ok and parity.returncode == 0
        for name in JS_TESTS:
            ok = subprocess.run(["node", str(ROOT / "tests" / name)]).returncode == 0 and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
