#!/usr/bin/env python3
"""Evaluate a conservative three-calendar-month price-direction candidate.

This is research, not the production classifier. The fixed candidate uses the
existing chart-window score only as a feature and calibrates bins using
outcomes available before each calendar-year evaluation. Each signal uses its
past and current close, not its future outcome, and training uses completed
outcomes only. See README for limitations.

    python3 forecast_validation.py
"""
from __future__ import annotations

import bisect
import calendar
import datetime as dt
import json
import math
import pathlib
import random
from collections import defaultdict
from zoneinfo import ZoneInfo

import onset
import trend_v1 as trend  # frozen: research models were fitted on its score scale

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "research" / "pse-history.json"
MARKET_DATA = ROOT / "research" / "market-history.json"
REPORT = ROOT / "research" / "forecast-validation.json"
MAX_DELAY = 10
MIN_WINDOW_BARS = 50
# Fixed before running this evaluation; these are feature bins, not forecasts.
EDGES = (-0.45, -0.25, -0.10, 0.10, 0.25, 0.45)
MIN_SAMPLES = 100
MIN_MONTHS = 24
MIN_SYMBOLS = 10
BOOTSTRAPS = 1000
BLOCK_MONTHS = 4  # consecutive monthly signals have overlapping 3m outcomes


def months_after(day, months):
    number = day.year * 12 + day.month - 1 + months
    year, month = divmod(number, 12)
    month += 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def score_bin(score):
    return bisect.bisect_right(EDGES, score)


def observations(data):
    """First available close each month; outcome close at/after 3 months.

    A missing or delayed exit is omitted, not treated as a loss. Data is
    assumed sorted and completed as in the saved PSE collection.
    """
    samples = []
    skipped = defaultdict(int)
    for symbol, rows in sorted(data["bars"].items()):
        zone = ZoneInfo(data.get("timezones", {}).get(symbol, "Asia/Manila"))
        stamps = [int(row[0]) for row in rows]
        closes = [float(row[2]) for row in rows]
        dates = [dt.datetime.fromtimestamp(t, zone).date() for t in stamps]
        seen = set()
        for i, day in enumerate(dates):
            month = day.year, day.month
            if month in seen:
                continue
            seen.add(month)
            indices = onset.window(stamps, i, stamps[i], months=data.get("window_months"))
            if len(indices) < MIN_WINDOW_BARS:
                skipped["short_window"] += 1
                continue
            target = months_after(day, 3)
            end = bisect.bisect_left(dates, target, lo=i + 1)
            if end >= len(dates) or (dates[end] - target).days > MAX_DELAY:
                skipped["missing_outcome"] += 1
                continue
            try:
                if not all(math.isfinite(closes[j]) and closes[j] > 0 for j in indices):
                    raise ValueError("invalid input price")
                score = trend.classify([closes[j] for j in indices])["score"]
                if not math.isfinite(closes[end]) or closes[end] <= 0:
                    raise ValueError("invalid outcome")
            except (ValueError, OverflowError):
                skipped["invalid_price"] += 1
                continue
            outcome = (closes[end] > closes[i]) - (closes[end] < closes[i])
            samples.append({"symbol": symbol, "date": day, "exit": dates[end],
                            "bin": score_bin(score), "outcome": outcome})
    return samples, dict(skipped)


def calibrate(samples, seed=20261030):
    """Fit bins with a one-sided, four-month block-bootstrap lower bound.

    Only declare a directional candidate where the lower bound on its hit
    rate exceeds 50%. Ties count as misses in both directions. The bootstrap
    resamples calendar months jointly across stocks, not individual trades.
    Empty calendar months remain in the time series.
    """
    by_bin = defaultdict(list)
    for sample in samples:
        by_bin[sample["bin"]].append(sample)
    result = {}
    for key in range(len(EDGES) + 1):
        group = by_bin[key]
        months = {s["date"].year * 12 + s["date"].month - 1 for s in group}
        symbols = {s["symbol"] for s in group}
        entry = {"n": len(group), "months": len(months), "symbols": len(symbols),
                 "direction": None, "lower_bound": None}
        if len(group) < MIN_SAMPLES or len(months) < MIN_MONTHS or len(symbols) < MIN_SYMBOLS:
            result[key] = entry
            continue
        total = sum(s["outcome"] == 1 for s in group)
        down = sum(s["outcome"] == -1 for s in group)
        direction = 1 if total > down else -1
        monthly = defaultdict(lambda: [0, 0])
        for sample in group:
            month = sample["date"].year * 12 + sample["date"].month - 1
            monthly[month][0] += sample["outcome"] == direction
            monthly[month][1] += 1
        first, last = min(months), max(months)
        series = [monthly[m] for m in range(first, last + 1)]
        rng = random.Random(seed + key)
        estimates = []
        for _ in range(BOOTSTRAPS):
            hits = count = 0
            drawn = 0
            while drawn < len(series):
                start = rng.randrange(len(series) - BLOCK_MONTHS + 1)
                for hit, n in series[start:start + min(BLOCK_MONTHS, len(series) - drawn)]:
                    hits += hit
                    count += n
                    drawn += 1
            if count:
                estimates.append(hits / count)
        estimates.sort()
        lower = estimates[int(0.05 * (len(estimates) - 1))]
        entry.update({"observed_hit_rate": round((total if direction == 1 else down) / len(group), 4),
                      "lower_bound": round(lower, 4),
                      "direction": ("bullish" if direction == 1 else "bearish") if lower > 0.5 else None})
        result[key] = entry
    return result


def summary(samples, predictions):
    if not samples:
        return {"n": 0}
    calls = [(s, predictions.get(s["bin"], {}).get("direction")) for s in samples]
    result = {"n": len(samples),
              "stocks": len({s["symbol"] for s in samples}),
              "months": len({(s["date"].year, s["date"].month) for s in samples}),
              "up_pct": round(100 * sum(s["outcome"] == 1 for s in samples) / len(samples), 2),
              "down_pct": round(100 * sum(s["outcome"] == -1 for s in samples) / len(samples), 2),
              "unchanged_pct": round(100 * sum(s["outcome"] == 0 for s in samples) / len(samples), 2)}
    for name, sign in (("bullish", 1), ("bearish", -1)):
        selected = [s for s, call in calls if call == name]
        result[name] = {"n": len(selected),
                        "months": len({(s["date"].year, s["date"].month) for s in selected}),
                        "stocks": len({s["symbol"] for s in selected}),
                        "hit_pct": round(100 * sum(s["outcome"] == sign for s in selected) / len(selected), 2) if selected else None}
    result["abstained"] = sum(call is None for _, call in calls)
    return result


def evaluate(data, years=range(2022, 2027)):
    samples, skipped = observations(data)
    folds = []
    for year in years:
        start, end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        # Strict cutoff prevents a training outcome overlapping the evaluation.
        training = [s for s in samples if s["exit"] < start]
        testing = [s for s in samples if start <= s["date"] < end]
        model = calibrate(training)
        folds.append({"year": year, "training_n": len(training),
                      "latest_training_exit": max((s["exit"] for s in training), default=None).isoformat() if training else None,
                      "bins": model, "evaluation": summary(testing, model)})
    return {"source": data.get("source"), "collected_at": data.get("collected_at"),
            "requested": len(data.get("universe", [])), "received": len(data["bars"]),
            "missing": data.get("missing"),
            "first_signal": min((s["date"] for s in samples), default=None).isoformat() if samples else None,
            "last_signal": max((s["date"] for s in samples), default=None).isoformat() if samples else None,
            "method": "First available close each month; compare to close on or after three calendar months, at most 10 days late. Chart-window score is binned; each yearly model uses only outcomes completed before that year. Ties are neither up nor down. Four-month moving-block bootstrap clusters months and stocks.",
            "limitations": ["Exploratory retrospective analysis, not an untouched prospective holdout; the same dataset has been studied before.",
                            "Currently listed PSE stocks only: delistings and survivorship bias are not addressed. Results do not validate other assets or markets.",
                            "Overlapping observations and common shocks reduce effective sample size; the block bootstrap is approximate and does not correct multiple bin selection.",
                            "Signal and entry use the same closing price, which may not be executable. No dividends, fees, taxes or slippage; price direction is not trading return.",
                            "The upstream close series may be revised for corporate actions; any unadjusted action can distort historical outcomes.",
                            "The window is 90 days for PSE and three calendar months for Yahoo. Samples with fewer than 50 bars are excluded; not all instruments are covered.",
                            "Only completed collected bars are studied; live quotes and stale series need separate handling."],
            "skipped": skipped, "folds": folds}


def main():
    pse_data = json.loads(DATA.read_text(encoding="utf-8"))
    report = {"PSE": evaluate(pse_data)}
    if MARKET_DATA.exists():
        market_data = json.loads(MARKET_DATA.read_text(encoding="utf-8"))
        for category in sorted(set(market_data["universe"].values())):
            symbols = [s for s, kind in market_data["universe"].items() if kind == category]
            subset = dict(market_data)
            subset["universe"] = symbols
            subset["bars"] = {s: market_data["bars"][s] for s in symbols if s in market_data["bars"]}
            subset["missing"] = {s: market_data["missing"][s] for s in symbols if s in market_data["missing"]}
            result = evaluate(subset)
            result["limitations"][1] = ("Small illustrative selection chosen today, not a historical point-in-time universe; delisted and failed instruments are missing. "
                                        "Results do not validate other assets or markets.")
            report[category] = result
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "markets": {
        key: [{"year": f["year"], **f["evaluation"]} for f in value["folds"]]
        for key, value in report.items()}}, indent=2))


if __name__ == "__main__":
    main()
