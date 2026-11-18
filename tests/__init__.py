"""Tests. `python3 run_tests.py` from the project root runs them all.

Importing this package also puts the project root and lab/ on sys.path, so
`python3 -m unittest tests.test_trend` works too.
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "lab"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
