#!/usr/bin/env python3
"""Explore forecasts conditional on a prior benchmark drawdown.

The benchmark comes from raw bars, never outcome-filtered observations. Its
close must be from a previous local date. This post-selection backtest uses
already-inspected years and is not independent or prospective validation.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
from collections import defaultdict
from zoneinfo import ZoneInfo

import adaptive_forecast_research as adaptive
import asset_local_forecast_research as local
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import neighbor_forecast_research as neighbor
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "shock-filter-forecast-research.json"
BENCHMARKS = {"currency": "EURUSD=X", "us_equity": "SPY", "crypto": "BTC-USD"}
MAX_STALE_DAYS = 7


def prepare_benchmark(rows, timezone):
    zone = ZoneInfo(timezone)
    return ([dt.datetime.fromtimestamp(int(r[0]), zone).date() for r in rows],
            [float(r[2]) for r in rows])


def prior_benchmark_return(prepared, day):
    """Use a prior-date 20-bar close-to-close return, or abstain."""
    dates, prices = prepared
    i = bisect.bisect_left(dates, day) - 1
    if i < 20 or (day - dates[i]).days > MAX_STALE_DAYS:
        return None
    current, start = prices[i], prices[i - 20]
    if not all(math.isfinite(p) and p > 0 for p in (current, start)):
        return None
    return math.log(current / start)


def evaluate_samples(samples, direction, prepared, years=adaptive.YEARS):
    eligible = adaptive.add_local_features(samples, direction)
    by_symbol = defaultdict(list)
    for s in samples:
        by_symbol[s["symbol"]].append(s)
    cache, annual, totals = {}, defaultdict(lambda: defaultdict(list)), defaultdict(list)
    missing = 0
    for s in eligible:
        day = s["date"]
        if day.year not in years:
            continue
        if day not in cache:
            cache[day] = prior_benchmark_return(prepared, day)
        benchmark = cache[day]
        missing += benchmark is None
        own = s["local_score"] >= local.CALL_THRESHOLD
        value = neighbor.estimate(by_symbol[s["symbol"]], s, direction)
        nearest = value is not None and value >= neighbor.THRESHOLD
        shock = benchmark is not None and benchmark < 0
        labels = {"shock_local": own and shock, "shock_neighbor": nearest and shock,
                  "asset_local": own, "neighbor": nearest}
        for name, call in labels.items():
            pair = (s, direction if call else None)
            annual[day.year][name].append(pair)
            totals[name].append(pair)
    names = ("shock_local", "shock_neighbor", "asset_local", "neighbor")
    folds = []
    for year in years:
        fold = {"year": year, **{name: backtest.metrics(annual[year][name], direction) for name in names}}
        folds.append(fold)
        print(f"  {year}: shock local {fold['shock_local']['n']} / {fold['shock_local']['hit_pct']}%; shock neighbor {fold['shock_neighbor']['n']} / {fold['shock_neighbor']['hit_pct']}%", flush=True)
    return {"test_n": len(totals["shock_local"]),
            **{name: backtest.metrics(totals[name], direction) for name in names},
            "missing_benchmark_n": missing, "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    report = {"method": "For each direction, issue an asset-local or neighbor call only when the benchmark's 20-bar return is negative. Benchmarks are SPY, EURUSD=X and BTC-USD. The latest benchmark close must be from a previous local calendar date, no more than seven days stale; missing data abstains. Replay ungated methods on the same eligible observations; calls differ. Flat outcomes are misses.",
              "limitations": ["This filter was developed after repeatedly inspecting these years; it is exploratory, not an independent holdout or prospective validation. Confidence intervals do not adjust for model selection.",
                              "Previous local calendar date does not prove cross-timezone availability in every case. EUR/USD is a coarse proxy for currencies, including inverse crosses. Current listings omit many delisted instruments.",
                              "Overlapping outcomes and shared market shocks reduce independent information. Yahoo crypto differs from Binance. No costs, taxes, dividends, slippage or executable same-close entry; not deployed."],
              "benchmarks": BENCHMARKS, "markets": {}}
    for market, direction in targeted.TASKS.items():
        symbol = BENCHMARKS[market]
        if symbol not in raw["bars"] or symbol not in raw["timezones"]:
            raise ValueError(f"Missing benchmark {symbol}")
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {market} {direction}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = targeted.observations(subset)
        result = evaluate_samples(samples, direction, prepare_benchmark(raw["bars"][symbol], raw["timezones"][symbol]))
        result.update({"received": len(subset["bars"]), "requested": len(names),
                       "observation_n": len(samples), "skipped": skipped})
        report["markets"][market] = result
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({market: {key: result[key] for key in ("test_n", "shock_local", "shock_neighbor", "asset_local", "neighbor", "missing_benchmark_n")}
                      for market, result in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
