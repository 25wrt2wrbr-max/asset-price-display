#!/usr/bin/env python3
"""Explore asset-local historical nearest neighbors; research only.

Every neighbor's outcome must have completed strictly before the signal.
Previously inspected evaluation years are not an independent holdout.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

import adaptive_forecast_research as adaptive
import asset_local_forecast_research as local
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts as model
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "neighbor-forecast-research.json"
LOOKBACK_MONTHS = 60
MIN_HISTORY = 24
NEIGHBORS = 12
THRESHOLD = .55
# Fixed dimension scales prevent future samples from defining the distance.
FEATURE_SCALES = (1., .05, .12, .20, .02, .5, .10)


def estimate(history, current, direction):
    if direction not in ("bullish", "bearish"):
        raise ValueError("unknown direction")
    day = current["date"]
    cutoff = fv.months_after(day, -LOOKBACK_MONTHS)
    eligible = [s for s in history if s["symbol"] == current["symbol"]
                and cutoff <= s["date"] < day and s["exit"] < day]
    if len(eligible) < MIN_HISTORY:
        return None
    def distance(s):
        return sum(((s["features"][i] - current["features"][i]) / scale) ** 2
                   for i, scale in enumerate(FEATURE_SCALES))
    nearest = sorted(eligible, key=lambda s: (distance(s), s["date"]))[:NEIGHBORS]
    target = 1 if direction == "bullish" else -1
    return sum(s["outcome"] == target for s in nearest) / len(nearest)


def evaluate_samples(samples, direction, adaptive_folds, years=adaptive.YEARS):
    augmented = adaptive.add_local_features(samples, direction)
    by_symbol = defaultdict(list)
    for s in samples:
        by_symbol[s["symbol"]].append(s)
    prior = {f["year"]: f for f in adaptive_folds}
    annual = defaultdict(lambda: defaultdict(list))
    calls, local_calls, adaptive_calls = [], [], []
    unavailable = 0
    for s in augmented:
        year = s["date"].year
        if year not in years:
            continue
        value = estimate(by_symbol[s["symbol"]], s, direction)
        unavailable += value is None
        new = direction if value is not None and value >= THRESHOLD else None
        own = direction if s["local_score"] >= local.CALL_THRESHOLD else None
        fold = prior.get(year, {})
        old_model, old_choice = fold.get("model"), fold.get("selected")
        old = direction if old_model and old_choice and model.score(old_model, s["features"][:10]) >= old_choice["threshold"] else None
        for name, label in (("neighbor", new), ("asset_local", own), ("adaptive", old)):
            annual[year][name].append((s, label))
        calls.append((s, new))
        local_calls.append((s, own))
        adaptive_calls.append((s, old))
    folds = []
    for year in years:
        fold = {"year": year, **{name: backtest.metrics(annual[year][name], direction)
                                 for name in ("neighbor", "asset_local", "adaptive")}}
        folds.append(fold)
        print(f"  {year}: neighbor {fold['neighbor']['n']} / {fold['neighbor']['hit_pct']}%; local {fold['asset_local']['n']} / {fold['asset_local']['hit_pct']}%", flush=True)
    return {"test_n": len(calls), "neighbor": backtest.metrics(calls, direction),
            "asset_local_same_eligible": backtest.metrics(local_calls, direction),
            "adaptive_same_eligible": backtest.metrics(adaptive_calls, direction),
            "neighbor_unavailable_n": unavailable, "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    prior = json.loads((fv.ROOT / "research" / "adaptive-forecast-research.json").read_text(encoding="utf-8"))
    report = {"method": "For each asset and direction, find the 12 nearest previous chart-feature observations in the past 60 months, using fixed feature scales. Require 24 historical observations with exits strictly before the signal and call when at least 55% of neighbors match the requested direction. Unchanged prices count as misses. Compare earlier candidates on the same local-history-eligible test observations, though their selected calls differ.",
              "limitations": ["Fixed experimental choices follow many tests on the same years. Results are exploratory, not independent validation; reported intervals do not account for research selection.",
                              "Overlapping outcomes and common market shocks mean calls and neighbors are not independent. Five-year lookback and local eligibility exclude short histories.",
                              "Current selected listings mostly omit delisted instruments. Yahoo crypto is not the Binance feed. No costs, dividends, slippage, or executable same-close entry; no production deployment."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {market} {direction}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = targeted.observations(subset)
        result = evaluate_samples(samples, direction, prior["markets"][market]["folds"])
        result.update({"received": len(subset["bars"]), "requested": len(names), "observation_n": len(samples), "skipped": skipped})
        report["markets"][market] = result
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({k: {key: v[key] for key in ("test_n", "neighbor", "asset_local_same_eligible", "adaptive_same_eligible", "neighbor_unavailable_n")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
