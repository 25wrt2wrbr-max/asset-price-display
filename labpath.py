"""Puts lab/ on sys.path so the app can import the research modules kept there."""

import pathlib
import sys

_LAB = str(pathlib.Path(__file__).resolve().parent / "lab")
if _LAB not in sys.path:
    sys.path.append(_LAB)
