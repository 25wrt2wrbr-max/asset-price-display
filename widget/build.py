#!/usr/bin/env python3
"""Build the Trend Badge package.

    python3 widget/build.py          # build trend-widget.js and the demo prices
    python3 widget/build.py --zip    # also run the tests and make release/trend-badge-<ver>.zip

trend-widget.js = export/trend.js (the scorer, unchanged) + src/widget.js.
The demo prices are made up with a fixed seed, so no market data ships.
"""

import json
import math
import pathlib
import random
import re
import subprocess
import sys
import zipfile
from datetime import date, timedelta

HERE = pathlib.Path(__file__).resolve().parent
PROJECT = HERE.parent
SCORER = PROJECT / "export" / "trend.js"
WIDGET = HERE / "src" / "widget.js"
OUT = HERE / "trend-widget.js"
DATA = HERE / "demo-data"
SHIP = ["trend-widget.js", "demo.html", "README.md", "LICENSE.txt", "CHANGELOG.md",
        "demo-data/rising.json", "demo-data/falling.csv", "demo-data/sideways.json"]


def version() -> str:
    m = re.search(r'VERSION = "([^"]+)"', WIDGET.read_text())
    return m.group(1)


def build_js() -> None:
    ver = version()
    head = (f"/*! Trend Badge v{ver}. Commercial license: see LICENSE.txt.\n"
            " * The badge describes past prices. It is not a forecast. */\n")
    OUT.write_text(head + SCORER.read_text().rstrip() + "\n\n" + WIDGET.read_text())


def series(seed: int, drift: float, vol: float, start: float, n: int = 63):
    """Made-up business-day closes ending on a fixed date."""
    rng = random.Random(seed)
    days, d = [], date(2026, 11, 20)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    p, out = start, []
    for day in days:
        p *= math.exp(drift + vol * rng.gauss(0, 1))
        out.append((day.isoformat(), round(p, 2)))
    return out


def build_data() -> None:
    DATA.mkdir(exist_ok=True)
    rising = series(7, 0.0040, 0.009, 48.0)
    falling = series(11, -0.0045, 0.010, 120.0)
    sideways = series(16, 0.0, 0.010, 25.0)
    (DATA / "rising.json").write_text(json.dumps([{"date": d, "close": c} for d, c in rising], indent=0) + "\n")
    # Newest first on purpose: the widget turns it around.
    (DATA / "falling.csv").write_text("date,close\n" + "".join(f"{d},{c}\n" for d, c in reversed(falling)))
    (DATA / "sideways.json").write_text(json.dumps({"dates": [d for d, _ in sideways],
                                                    "closes": [c for _, c in sideways]}) + "\n")


def make_zip() -> pathlib.Path:
    for cmd in (["node", str(HERE / "test_widget.js")],
                [sys.executable, str(PROJECT / "export" / "verify_parity.py")]):
        if subprocess.run(cmd).returncode:
            sys.exit("tests failed; no zip made")
    rel = HERE / "release"
    rel.mkdir(exist_ok=True)
    name = f"trend-badge-{version()}"
    path = rel / f"{name}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in SHIP:
            z.write(HERE / f, f"{name}/{f}")
    return path


if __name__ == "__main__":
    build_js()
    build_data()
    print("built", OUT.name, "and demo-data/")
    if "--zip" in sys.argv:
        print("packaged", make_zip().relative_to(HERE))
