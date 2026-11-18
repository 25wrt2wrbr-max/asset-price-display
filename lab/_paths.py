"""Puts the project root and lab/ on sys.path, so lab scripts run from anywhere."""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "lab"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
