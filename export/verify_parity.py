#!/usr/bin/env python3
"""Check export/trend.js against the Python original (trend.py / onset.py).

Generates a spread of series -- long and short, trending, flat, tie-heavy,
volume-less -- runs both implementations on them, and reports any mismatch.

    python3 export/verify_parity.py
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import trend  # noqa: E402
import onset  # noqa: E402


def make_series(rng: random.Random, n: int) -> tuple[list[float], list[float]]:
    """A series and its volumes, in one of a few shapes."""
    shape = rng.choice(["up", "down", "flat", "chop", "ties", "spike"])
    base = rng.choice([1.0, 8.0, 3000.0, 0.5])
    step = rng.uniform(-0.02, 0.02)
    closes, volumes = [], []
    price = base
    for _ in range(n):
        if shape == "up":
            price *= 1 + step + rng.uniform(-0.004, 0.004)
        elif shape == "down":
            price *= 1 - abs(step) + rng.uniform(-0.004, 0.004)
        elif shape == "flat":
            price = base
        elif shape == "chop":
            price *= 1 + rng.uniform(-0.02, 0.02)
        elif shape == "ties":
            price = base * rng.choice([1.0, 1.0, 1.0, 1.01])
        else:
            price *= 1 + (0.08 if rng.random() < 0.05 else rng.uniform(-0.01, 0.01))
        closes.append(round(max(0.01, price), 4))
        volumes.append(0.0 if rng.random() < 0.3 else float(rng.randint(1000, 900000)))
    return closes, volumes


def main() -> int:
    rng = random.Random(20261029)
    cases = []
    for _ in range(400):
        n = rng.choice([1, 2, 3, 4, 5, 8, 10, 20, 35, 49, 50, 55, 62, 63, 64,
                        80, 92, 120, 250])
        closes, volumes = make_series(rng, n)
        cases.append({"closes": closes, "volumes": volumes})

    # A few hand-built edge cases.
    cases.append({"closes": [10.0] * 80, "volumes": [100.0] * 80})
    cases.append({"closes": [10.0 + i * 0.01 for i in range(70)], "volumes": None})
    cases.append({"closes": [10.0] * 5, "volumes": None})
    # A perfectly steady payer and faller: no variance, but no doubt either.
    cases.append({"closes": [10.0 * 1.001 ** i for i in range(40)], "volumes": None})
    cases.append({"closes": [10.0 * 0.999 ** i for i in range(40)], "volumes": None})
    # A strong rise that fades into the hold band.
    cases.append({"closes": [10.0 * 1.01 ** i for i in range(50)]
                  + [10.0 * 1.01 ** 49 * 0.995 ** i for i in range(1, 8)],
                  "volumes": None})

    cases_path = os.path.join(HERE, ".cases.json")
    js_out_path = os.path.join(HERE, ".js_out.json")
    with open(cases_path, "w") as fh:
        json.dump(cases, fh)

    proc = subprocess.run(
        ["node", "-e", """
const fs = require('fs');
const T = require(process.argv[1]);
const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = cases.map(c => {
  let v = null, o = null;
  try { v = T.classify(c.closes, c.volumes); } catch (e) { v = {error: e.message}; }
  return v;
});
fs.writeFileSync(process.argv[3], JSON.stringify(out));
""", os.path.join(HERE, "trend.js"),
         cases_path,
         js_out_path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr)
        return 1

    with open(js_out_path) as fh:
        js_out = json.load(fh)

    bad = 0
    for case, js in zip(cases, js_out):
        try:
            py = trend.classify(case["closes"], case["volumes"])
        except ValueError as exc:
            py = {"error": str(exc)}
        if py.get("label") != js.get("label"):
            print("LABEL MISMATCH", py, js)
            bad += 1
            continue
        if "error" in py:
            continue
        if abs(py["score"] - js["score"]) > 1e-9 or py["confidence"] != js["confidence"] \
                or py["bars"] != js["bars"] or py["agreement"] != js["agreement"] \
                or py["held"] != js["held"] \
                or py["lean"] != js.get("lean") \
                or abs(py["progress"] - js["progress"]) > 1e-9 \
                or (py["significance"] is None) != (js["significance"] is None) \
                or (py["significance"] is not None
                    and abs(py["significance"] - js["significance"]) > 1e-9):
            print("MISMATCH", py, js)
            bad += 1
            continue
        for k, v in py["components"].items():
            jv = js["components"].get(k)
            if (v is None) != (jv is None) or (v is not None and abs(v - jv) > 1e-9):
                print("COMPONENT MISMATCH", k, v, jv, py)
                bad += 1
                break

    # Onset parity on the same cases (timestamps spread one day apart).
    stamp_cases = []
    base_ts = 1700000000
    for i, case in enumerate(cases):
        if len(case["closes"]) < 3:
            continue
        stamps = [base_ts + 86400 * j for j in range(len(case["closes"]))]
        stamp_cases.append({"stamps": stamps, "closes": case["closes"],
                            "volumes": case["volumes"] or [0.0] * len(case["closes"])})

    stamp_cases_path = os.path.join(HERE, ".cases2.json")
    js_onsets_path = os.path.join(HERE, ".js_out2.json")
    with open(stamp_cases_path, "w") as fh:
        json.dump(stamp_cases, fh)

    proc = subprocess.run(
        ["node", "-e", """
const fs = require('fs');
const T = require(process.argv[1]);
const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = cases.map(c => {
  const r = T.onset(c.stamps, c.closes, c.volumes, 'bullish');
  return r === null ? null : {since: r.since, run: r.run, censored: r.censored,
                              anchored: r.anchored, manner: r.manner,
                              turnMove: r.turnMove, score: r.score, window: r.window};
});
fs.writeFileSync(process.argv[3], JSON.stringify(out));
""", os.path.join(HERE, "trend.js"),
         stamp_cases_path,
         js_onsets_path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr)
        return 1

    with open(js_onsets_path) as fh:
        js_onsets = json.load(fh)

    for case, js in zip(stamp_cases, js_onsets):
        py = onset.onset(case["stamps"], case["closes"], case["volumes"], "bullish")
        if (py is None) != (js is None):
            print("ONSET PRESENCE MISMATCH", py, js)
            bad += 1
            continue
        if py is None:
            continue
        for k in ("since", "run", "censored", "anchored", "manner", "turnMove", "window"):
            if py[k] != js[k]:
                print("ONSET MISMATCH", k, py[k], js[k])
                bad += 1
                break

    # The same walk over Yahoo's calendar-months window -- the one a US
    # listing is judged on, because that is the window Yahoo's own chart
    # draws. The stamps here are real calendar days, so the month arithmetic
    # has something to bite on.
    month_cases = []
    month_base = 1750000000
    for i, case in enumerate(cases):
        if len(case["closes"]) < 3:
            continue
        stamps = [month_base + 86400 * j for j in range(len(case["closes"]))]
        month_cases.append({"stamps": stamps, "closes": case["closes"],
                            "volumes": case["volumes"] or [0.0] * len(case["closes"])})

    month_cases_path = os.path.join(HERE, ".cases3.json")
    js_months_path = os.path.join(HERE, ".js_out3.json")
    with open(month_cases_path, "w") as fh:
        json.dump(month_cases, fh)

    proc = subprocess.run(
        ["node", "-e", """
const fs = require('fs');
const T = require(process.argv[1]);
const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = cases.map(c => {
  const r = T.onset(c.stamps, c.closes, c.volumes, 'bullish', undefined, 3);
  return r === null ? null : {since: r.since, run: r.run, censored: r.censored,
                              anchored: r.anchored, manner: r.manner,
                              turnMove: r.turnMove, score: r.score, window: r.window};
});
fs.writeFileSync(process.argv[3], JSON.stringify(out));
""", os.path.join(HERE, "trend.js"),
         month_cases_path,
         js_months_path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr)
        return 1

    with open(js_months_path) as fh:
        js_months = json.load(fh)

    for case, js in zip(month_cases, js_months):
        py = onset.onset(case["stamps"], case["closes"], case["volumes"],
                         "bullish", months=3)
        if (py is None) != (js is None):
            print("MONTH ONSET PRESENCE MISMATCH", py, js)
            bad += 1
            continue
        if py is None:
            continue
        for k in ("since", "run", "censored", "anchored", "manner", "turnMove", "window"):
            if py[k] != js[k]:
                print("MONTH ONSET MISMATCH", k, py[k], js[k])
                bad += 1
                break

    print(f"{len(cases)} classify cases, {len(stamp_cases)} onset cases, "
          f"{len(month_cases)} calendar-month onset cases, {bad} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
