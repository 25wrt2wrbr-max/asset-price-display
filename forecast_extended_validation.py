#!/usr/bin/env python3
"""Walk-forward evaluation of the fixed binned candidate on expanded data.

The report is exploratory: earlier runs inspected portions of the time period,
the instruments were selected today, and no prospective data is available.
The classifier in the app remains unchanged.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import random
from collections import defaultdict

import forecast_validation as fv

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "research" / "market-history-extended.json"
REPORT = ROOT / "research" / "forecast-validation-extended.json"
YEARS = range(2011, 2027)
TARGET = 0.51


def direction_metrics(calls, name, seed=719):
    selected = [(s, predicted) for s, predicted in calls if predicted == name]
    sign = 1 if name == "bullish" else -1
    months = defaultdict(lambda: [0, 0])
    for s, _ in selected:
        month = s["date"].year * 12 + s["date"].month - 1
        months[month][0] += s["outcome"] == sign
        months[month][1] += 1
    n = len(selected)
    hits = sum(s["outcome"] == sign for s, _ in selected)
    result = {"n": n, "correct": hits, "hit_pct": round(100 * hits / n, 2) if n else None,
              "coverage_pct": round(100 * n / len(calls), 2) if calls else None,
              "months": len(months), "symbols": len({s["symbol"] for s, _ in selected}),
              "bootstrap_90_pct_interval": None,
              "meets_51_pct_observed": hits / n >= TARGET if n else None}
    if len(months) < 24:
        return result
    series = [months[m] for m in range(min(months), max(months) + 1)]
    rng = random.Random(seed)
    rates = []
    for _ in range(2000):
        hit = total = drawn = 0
        while drawn < len(series):
            start = rng.randrange(len(series) - fv.BLOCK_MONTHS + 1)
            for h, count in series[start:start + min(fv.BLOCK_MONTHS, len(series) - drawn)]:
                hit += h
                total += count
                drawn += 1
        if total:
            rates.append(hit / total)
    rates.sort()
    result["bootstrap_90_pct_interval"] = [round(100 * rates[int(p * (len(rates)-1))], 2)
                                             for p in (0.05, 0.95)]
    result["lower_bound_above_51_pct"] = rates[int(0.05 * (len(rates)-1))] > TARGET
    return result


def evaluate(data):
    samples, skipped = fv.observations(data)
    folds, calls = [], []
    for year in YEARS:
        start, end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        train = [s for s in samples if s["exit"] < start]
        test = [s for s in samples if start <= s["date"] < end]
        bins = fv.calibrate(train)
        annual_calls = [(s, bins.get(s["bin"], {}).get("direction")) for s in test]
        calls.extend(annual_calls)
        folds.append({"year": year, "training_n": len(train),
                      "latest_training_exit": max((s["exit"] for s in train), default=None).isoformat() if train else None,
                      "test": fv.summary(test, bins), "bins": bins})
    all_test = [s for s, _ in calls]
    base = fv.summary(all_test, {})
    directional = [(s, label) for s, label in calls if label is not None]
    correct = sum((label == "bullish" and s["outcome"] == 1) or
                  (label == "bearish" and s["outcome"] == -1)
                  for s, label in directional)
    selected_up = sum(s["outcome"] == 1 for s, _ in directional)
    selected_down = sum(s["outcome"] == -1 for s, _ in directional)
    return {"requested": len(data["universe"]), "received": len(data["bars"]),
            "missing": data["missing"], "skipped": skipped,
            "first_signal": min((s["date"] for s in samples), default=None).isoformat() if samples else None,
            "last_signal": max((s["date"] for s in samples), default=None).isoformat() if samples else None,
            "baseline": {k: base.get(k) for k in ("n", "up_pct", "down_pct", "unchanged_pct")},
            "bullish": direction_metrics(calls, "bullish"),
            "bearish": direction_metrics(calls, "bearish"),
            "combined": {"n": len(directional), "correct": correct,
                         "hit_pct": round(100 * correct / len(directional), 2) if directional else None,
                         "always_up_same_calls_pct": round(100 * selected_up / len(directional), 2) if directional else None,
                         "always_down_same_calls_pct": round(100 * selected_down / len(directional), 2) if directional else None,
                         "coverage_pct": round(100 * len(directional) / len(calls), 2) if calls else None},
            "abstained": sum(label is None for _, label in calls), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    data = json.loads(DATA.read_text(encoding="utf-8"))
    report = {"source": data["source"], "collected_at": data["collected_at"],
              "method": "Fixed score-bin candidate from forecast_validation.py; yearly expanding training on outcomes strictly completed before the test year. Signal on the first available close monthly, compare to close on or after three calendar months within 10 days. A tie is not correct for either direction. All folds are pooled by observation; months and symbols are correlated. 90% intervals are approximate four-month block bootstraps across all selected symbols, not individual confidence or a multiple-testing correction.",
              "limitations": ["Exploratory historical analysis: earlier research has inspected parts of these years; these are not an untouched or prospective holdout.",
                              "Current illustrative universe, generally excluding delisted securities; survivorship and selection biases remain.",
                              "Price close may be revised for corporate actions and is not dividend-adjusted. Same-close signal and entry may not be executable; no costs, taxes or dividends.",
                              "Daily outcomes overlap and share market shocks; raw observation counts are not independent.",
                              "Yahoo crypto data is not the Binance feed used by the application. This research does not establish accuracy for Philippine bonds or untested assets.",
                              "An observed score above 51% is not evidence that every year, individual asset, or future forecast will exceed 51%."],
              "markets": {}}
    for category in sorted(set(data["universe"].values())):
        symbols = [s for s, kind in data["universe"].items() if kind == category]
        subset = dict(data)
        subset["universe"] = symbols
        subset["bars"] = {s: data["bars"][s] for s in symbols if s in data["bars"]}
        subset["missing"] = {s: data["missing"][s] for s in symbols if s in data["missing"]}
        print(f"Evaluating {category}: {len(subset['bars'])} histories", flush=True)
        report["markets"][category] = evaluate(subset)
    pse = json.loads(fv.DATA.read_text(encoding="utf-8"))
    print(f"Evaluating PSE: {len(pse['bars'])} histories", flush=True)
    report["markets"]["PSE"] = evaluate(pse)
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "markets": {
        k: {key: v[key] for key in ("received", "baseline", "bullish", "bearish", "combined", "abstained")}
        for k, v in report["markets"].items()}}, indent=2))


if __name__ == "__main__":
    main()
