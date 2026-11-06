#!/usr/bin/env python3
"""Fit and evaluate experimental market/direction-specific forecasts.

    python3 market_forecast_backtest.py

Yearly rolling-origin folds: two years prior to the test year are reserved for
threshold validation; fit outcomes must finish before that validation starts,
and validation outcomes must finish before the test year. No test observations
influence that year's fit, thresholds or scaling. This is exploratory research,
not an untouched holdout: related historical data has been inspected before.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
from collections import defaultdict
from zoneinfo import ZoneInfo

import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecasts as model
import onset

REPORT = fv.ROOT / "research" / "market-specific-forecast.json"
YEARS = range(2016, 2027)
TASKS = {"us_equity": ("bearish",), "PSE": ("bullish",),
         "currency": ("bullish", "bearish"), "crypto": ("bullish", "bearish")}


def observations(data):
    result = []
    skipped = defaultdict(int)
    for symbol, rows in sorted(data["bars"].items()):
        zone = ZoneInfo(data.get("timezones", {}).get(symbol, "Asia/Manila"))
        stamps = [int(r[0]) for r in rows]
        closes = [float(r[2]) for r in rows]
        dates = [dt.datetime.fromtimestamp(t, zone).date() for t in stamps]
        seen = set()
        for i, day in enumerate(dates):
            month = (day.year, day.month)
            if month in seen:
                continue
            seen.add(month)
            window = onset.window(stamps, i, stamps[i], months=data.get("window_months"))
            # Exclude stale windows and incomplete or unobserved outcomes.
            if len(window) < fv.MIN_WINDOW_BARS:
                skipped["short_window"] += 1
                continue
            target = fv.months_after(day, 3)
            end = bisect.bisect_left(dates, target, lo=i + 1)
            if end >= len(rows) or (dates[end] - target).days > fv.MAX_DELAY:
                skipped["missing_outcome"] += 1
                continue
            try:
                values = model.features([closes[j] for j in window])
                if not math.isfinite(closes[end]) or closes[end] <= 0:
                    raise ValueError("invalid outcome")
            except (ValueError, OverflowError):
                skipped["invalid_price"] += 1
                continue
            result.append({"symbol": symbol, "date": day, "exit": dates[end],
                           "features": values,
                           "outcome": (closes[end] > closes[i]) - (closes[end] < closes[i])})
    return result, dict(skipped)


def metrics(calls, direction):
    result = previous.direction_metrics(calls, direction)
    selected = [s for s, label in calls if label == direction]
    if selected:
        result["same_cases_always_up_pct"] = round(100 * sum(s["outcome"] == 1 for s in selected) / len(selected), 2)
        result["same_cases_always_down_pct"] = round(100 * sum(s["outcome"] == -1 for s in selected) / len(selected), 2)
    return result


def evaluate(data, directions, years=YEARS):
    samples, skipped = observations(data)
    all_calls, folds = [], []
    for year in years:
        test_start, test_end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        validation_start = dt.date(year - 2, 1, 1)
        fit = [s for s in samples if s["exit"] < validation_start]
        validation = [s for s in samples if validation_start <= s["date"] < test_start and s["exit"] < test_start]
        test = [s for s in samples if test_start <= s["date"] < test_end]
        fitted = {direction: model.fit_direction(fit, validation, direction) for direction in directions}
        calls = [(s, model.predict(fitted, s["features"])) for s in test]
        all_calls.extend(calls)
        folds.append({"year": year, "fit_n": len(fit), "validation_n": len(validation),
                      "test_n": len(test),
                      "last_fit_exit": max((s["exit"] for s in fit), default=None).isoformat() if fit else None,
                      "last_validation_exit": max((s["exit"] for s in validation), default=None).isoformat() if validation else None,
                      "models": fitted, "directions": {d: metrics(calls, d) for d in directions},
                      "abstained": sum(label is None for _, label in calls)})
    return {"requested": len(data.get("universe", [])), "received": len(data["bars"]),
            "skipped": skipped, "test_n": len(all_calls),
            "directions": {d: metrics(all_calls, d) for d in directions},
            "abstained": sum(label is None for _, label in all_calls), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    report = {"method": "Market- and direction-specific regularized logistic models, fit to preceding three-month chart-window features. For each test year, coefficients are fitted using outcomes completed before the preceding two-year validation period; thresholds are chosen on that validation period, with outcomes completed before the test year. Calls in both directions conflict and are withheld. Monthly signal close versus first close on or after three calendar months, no more than ten days late. Ties are misses. Strictly chronological, but not a new untouched holdout.",
              "features": model.FEATURES, "years": list(YEARS),
              "limitations": ["Exploratory historical data, overlapping outcomes and correlated market shocks; bootstrap intervals are approximate and not corrected for model/threshold search.",
                              "Present-day selected universe omits many delisted assets. Outcome data may contain corporate-action distortions, and a same-close entry may not be executable.",
                              "No dividends, fees, taxes or slippage; a price-direction forecast is not a trading return. Crypto validation is Yahoo, not the app's Binance feed.",
                              "Short or missing windows and delayed exits are excluded, not negative observations. No bond yields or funds are evaluated.",
                              "Live partial daily bars, staleness, market identification, and chart/table parity have not been validated; models are not deployed."],
              "markets": {}}
    for category, directions in TASKS.items():
        if category == "PSE":
            subset = json.loads(fv.DATA.read_text(encoding="utf-8"))
        else:
            symbols = [s for s, kind in raw["universe"].items() if kind == category]
            subset = dict(raw)
            subset["universe"] = symbols
            subset["bars"] = {s: raw["bars"][s] for s in symbols if s in raw["bars"]}
        print(f"Evaluating {category}: {len(subset['bars'])} histories", flush=True)
        report["markets"][category] = evaluate(subset, directions)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {key: v[key] for key in ("received", "test_n", "directions", "abstained")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
