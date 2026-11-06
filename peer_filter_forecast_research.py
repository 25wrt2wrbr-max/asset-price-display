#!/usr/bin/env python3
"""Exploratory cross-sectional strength filters on prior forecast calls.

Peers come from raw bars and use only prior-calendar-day closes. The chosen
rules follow repeated inspection of the same evaluation years and are not
independent or prospective validation, nor are they app classifiers.
"""
from __future__ import annotations

import json
from collections import defaultdict

import adaptive_forecast_research as adaptive
import asset_local_forecast_research as local
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import neighbor_forecast_research as neighbor
import relative_forecast_research as relative
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "peer-filter-forecast-research.json"


def evaluate_samples(samples, direction, prepared, years=adaptive.YEARS):
    augmented = adaptive.add_local_features(samples, direction)
    by_symbol = defaultdict(list)
    for s in samples:
        by_symbol[s["symbol"]].append(s)
    cache, annual, totals = {}, defaultdict(lambda: defaultdict(list)), defaultdict(list)
    unavailable = 0
    for s in augmented:
        day = s["date"]
        if day.year not in years:
            continue
        if day not in cache:
            cache[day] = relative.peer_returns(prepared, day)
        values = relative.relative_features(s, cache[day])
        unavailable += values is None
        own = s["local_score"] >= local.CALL_THRESHOLD
        value = neighbor.estimate(by_symbol[s["symbol"]], s, direction)
        nearest = value is not None and value >= neighbor.THRESHOLD
        # A fixed ex-ante direction-specific momentum filter, plus its inverse
        # as a diagnostic. Fixed ranks are not calibrated probabilities.
        rank = values[1] if values is not None else None
        momentum = rank is not None and (rank >= .75 if direction == "bullish" else rank <= .25)
        reversal = rank is not None and (rank <= .25 if direction == "bullish" else rank >= .75)
        labels = {"momentum_local": own and momentum, "momentum_neighbor": nearest and momentum,
                  "reversal_local": own and reversal, "reversal_neighbor": nearest and reversal,
                  "asset_local": own, "neighbor": nearest}
        for name, call in labels.items():
            pair = (s, direction if call else None)
            annual[day.year][name].append(pair)
            totals[name].append(pair)
    names = ("momentum_local", "momentum_neighbor", "reversal_local", "reversal_neighbor", "asset_local", "neighbor")
    folds = []
    for year in years:
        fold = {"year": year, **{name: backtest.metrics(annual[year][name], direction) for name in names}}
        folds.append(fold)
        print(f"  {year}: momentum local {fold['momentum_local']['n']} / {fold['momentum_local']['hit_pct']}%; reversal local {fold['reversal_local']['n']} / {fold['reversal_local']['hit_pct']}%", flush=True)
    return {"test_n": len(totals["asset_local"]),
            **{name: backtest.metrics(totals[name], direction) for name in names},
            "peer_unavailable_n": unavailable, "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    report = {"method": "Filter local and neighbor calls by the asset's 3-month return rank relative to peer returns from strictly earlier local calendar dates. For bullish signals, momentum is top quartile and reversal bottom quartile; for bearish signals, momentum is bottom quartile and reversal top quartile. Require at least ten other nonstale peers. Unfiltered comparators use the same eligible observations; calls differ. Flat outcomes are misses.",
              "limitations": ["Multiple filter variants and earlier experiments inspect the same years. These are exploratory, not independent or prospective tests; intervals do not adjust for model selection.",
                              "Previous local calendar dates do not guarantee availability across time zones. Peer universe uses present-day selected listings and omits many delisted assets. Peers are raw bars, not outcome-filtered observations.",
                              "Overlapping outcomes and correlated assets limit independent information. Yahoo crypto differs from Binance. Costs, taxes, dividends, slippage and executable same-close entry are not modeled; not deployed."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {market} {direction}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = targeted.observations(subset)
        prepared = relative.prepare_bars(subset["bars"], raw.get("timezones", {}))
        result = evaluate_samples(samples, direction, prepared)
        result.update({"received": len(subset["bars"]), "requested": len(names),
                       "observation_n": len(samples), "skipped": skipped})
        report["markets"][market] = result
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({market: {key: value[key] for key in ("test_n", "momentum_local", "momentum_neighbor", "reversal_local", "reversal_neighbor", "asset_local", "neighbor", "peer_unavailable_n")}
                      for market, value in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
