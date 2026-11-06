#!/usr/bin/env python3
"""Explore asset-local three-month outcome models, without future leakage.

Evaluate monthly chronological forecasts using only the asset's older outcomes
completed before each signal. Fit simple 3-month price-feature regime groups,
shrink their win rates toward the asset's recent base rate and abstain when
there are too few historical observations or the estimate is below 55%.
This is retrospective exploratory research; do not treat rates as guarantees.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "asset-local-forecast-research.json"
YEARS = range(2020, 2027)
MIN_HISTORY = 24
MIN_REGIME = 6
PRIOR_STRENGTH = 8
DECAY_MONTHS = 60
CALL_THRESHOLD = .55


def regimes(values):
    """Fixed bins use only the existing chart window, with no symbol leakage."""
    trend, r5, r20, window_return, volatility, position, unchanged = values
    return (int(trend >= 0), int(r20 >= 0), int(position >= .5))


def estimate(history, current, direction):
    """Recency-weighted, regime-shrunk asset-local direction win frequency."""
    eligible = [s for s in history if s["exit"] < current["date"] and s["symbol"] == current["symbol"]]
    if len(eligible) < MIN_HISTORY:
        return None
    target = 1 if direction == "bullish" else -1
    current_regime = regimes(current["features"])
    total = wins = group_total = group_wins = 0.
    group_n = 0
    for s in eligible:
        months = (current["date"].year - s["date"].year) * 12 + current["date"].month - s["date"].month
        weight = 0.5 ** (months / DECAY_MONTHS)
        success = int(s["outcome"] == target)
        total += weight
        wins += weight * success
        if regimes(s["features"]) == current_regime:
            group_total += weight
            group_wins += weight * success
            group_n += 1
    if group_n < MIN_REGIME:
        return None
    base = wins / total
    return {"score": (group_wins + PRIOR_STRENGTH * base) / (group_total + PRIOR_STRENGTH),
            "history_n": len(eligible), "regime_n": group_n}


def evaluate_samples(samples, direction, baseline_folds, years=YEARS):
    test_start, test_end = dt.date(min(years), 1, 1), dt.date(max(years) + 1, 1, 1)
    by_symbol = defaultdict(list)
    for sample in samples:
        by_symbol[sample["symbol"]].append(sample)
    prior = {f["year"]: f.get("models", {}) for f in baseline_folds}
    new_calls, old_calls = [], []
    annual_new, annual_old = defaultdict(list), defaultdict(list)
    last_information = {}
    for current in samples:
        day = current["date"]
        if not test_start <= day < test_end or day.year not in years:
            continue
        eligible = [s for s in by_symbol[current["symbol"]] if s["exit"] < day]
        result = estimate(eligible, current, direction)
        label = direction if result and result["score"] >= CALL_THRESHOLD else None
        old = market_forecasts.predict(prior.get(day.year, {}), current["features"])
        new_calls.append((current, label))
        old_calls.append((current, old))
        annual_new[day.year].append((current, label))
        annual_old[day.year].append((current, old))
        if eligible:
            latest = max(s["exit"] for s in eligible)
            last_information[day.year] = max(last_information.get(day.year, latest), latest)
    folds = []
    for year in years:
        new = backtest.metrics(annual_new[year], direction)
        old = backtest.metrics(annual_old[year], direction)
        folds.append({"year": year, "new": new, "prior": old,
                      "latest_training_exit": last_information[year].isoformat() if year in last_information else None})
        print(f"  {year}: new {new['n']} / {new['hit_pct']}%; prior {old['n']} / {old['hit_pct']}%", flush=True)
    return {"test_n": len(new_calls), "new": backtest.metrics(new_calls, direction),
            "prior_same_eligible_samples": backtest.metrics(old_calls, direction),
            "abstained": sum(label is None for _, label in new_calls), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    baseline = json.loads(targeted.BASELINE.read_text(encoding="utf-8"))
    report = {"method": "Asset-specific, recency-weighted historical price-direction hit rates conditional on trend, 20-bar return and range position. A regime rate is shrunk toward the asset's recent base rate; require 24 completed historical outcomes and six regime examples, and forecast only if the estimated score is >=55%. Historical outcomes must complete strictly before the signal. No parameters are tuned on the test years. Compare with previous model on identical 2020-2026 eligible observations.",
              "limitations": ["Exploratory experiment after inspecting prior results; not untouched or prospective. Overlapping outcomes and common market shocks limit effective sample size; intervals do not account for research selection.",
                              "Uses current-listing historical data and excludes most delisted assets. Targeted observation builder requires six- and twelve-month references even though this rule uses only chart-window features.",
                              "Price direction is not trading return; no dividends, costs, taxes, slippage, or executable close assumed. Yahoo crypto differs from Binance; no live integration or current model fitting has been validated."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {market} {direction}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = targeted.observations(subset)
        result = evaluate_samples(samples, direction, baseline["markets"][market]["folds"])
        result.update({"received": len(subset["bars"]), "skipped": skipped})
        report["markets"][market] = result
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {key: v[key] for key in ("test_n", "new", "prior_same_eligible_samples", "abstained")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
