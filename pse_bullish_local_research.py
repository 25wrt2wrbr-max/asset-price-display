#!/usr/bin/env python3
"""Evaluate fixed stock-local filters on existing PSE bullish labels only.

Research only, after repeated inspection of these years; not independently
validated and not a change to the application's trend classifier.
"""
from __future__ import annotations

import json
from collections import defaultdict

import asset_local_forecast_research as local
import forecast_validation as fv
import market_forecast_backtest as backtest
import neighbor_forecast_research as neighbor
import pse_bull_fund_bear_research as previous

REPORT = fv.ROOT / "research" / "pse-bullish-local-research.json"
YEARS = range(2020, 2027)
RULES = ("app_bullish", "local", "neighbor", "both")


def decide(sample, local_score, neighbor_score):
    bull = sample["app_label"] == "bullish"
    own = local_score is not None and local_score >= local.CALL_THRESHOLD
    near = neighbor_score is not None and neighbor_score >= neighbor.THRESHOLD
    return {"app_bullish": bull, "local": bull and own,
            "neighbor": bull and near, "both": bull and own and near}


def evaluate(samples, years=YEARS):
    by_symbol, annual, totals = defaultdict(list), defaultdict(lambda: defaultdict(list)), defaultdict(list)
    for s in samples:
        by_symbol[s["symbol"]].append(s)
    for s in samples:
        if s["date"].year not in years:
            continue
        history = by_symbol[s["symbol"]]
        own = local.estimate(history, s, "bullish")
        near = neighbor.estimate(history, s, "bullish")
        flags = decide(s, own["score"] if own else None, near)
        for name in RULES:
            pair = (s, "bullish" if flags[name] else None)
            totals[name].append(pair)
            annual[s["date"].year][name].append(pair)
    folds = [{"year": year, **{name: backtest.metrics(annual[year][name], "bullish") for name in RULES}}
             for year in years]
    return {"test_n": len(totals["app_bullish"]),
            **{name: backtest.metrics(totals[name], "bullish") for name in RULES}, "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    data = json.loads(fv.DATA.read_text(encoding="utf-8"))
    samples, skipped = previous.pse_observations(data)
    result = evaluate(samples)
    result.update({"requested": len(data["universe"]), "received": len(data["bars"]), "skipped": skipped})
    report = {"method": "Only existing app bullish labels may be selected. Compare local historical-regime score >=55%, 12-nearest historical chart-feature neighbors with >=55% positive outcomes, and their intersection. Neighbor rule requires 24 stock-local historical observations in the prior 60 months; local rule requires 24 completed outcomes and 6 regime examples. All historical exits must be strictly before the signal. Compare 2020-2026 first monthly close versus first close on or after three calendar months, within ten days; ties are incorrect. Chart window is 90 days and minimum 50 bars. Baseline and filters use the same eligible population but select different calls.",
              "limitations": ["Exploratory after repeated inspection; no independent or prospective holdout, and examining multiple candidates creates selection bias not reflected in intervals.",
                              "Outcomes overlap and stocks share shocks. Current listings omit most delistings; missing/pending outcomes are excluded and histories/corporate actions may be revised.",
                              "No trading costs, dividends or executable same-close entry assumed. No change to live trend classifier."], "PSE": result}
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({name: result[name] for name in RULES}, indent=2))


if __name__ == "__main__":
    main()
