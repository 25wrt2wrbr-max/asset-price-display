#!/usr/bin/env python3
"""Explore a lagged market-outcome gate for asset-local forecasts.

No outcomes completing on or after the signal date enter the market gate.
Retrospective evaluation years were previously inspected and are not an
independent test. This script does not change the app.
"""
from __future__ import annotations

import bisect
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

REPORT = fv.ROOT / "research" / "regime-gate-forecast-research.json"
LOOKBACK_MONTHS = 18
MIN_CASES = 100
MIN_MONTHS = 9
MIN_SYMBOLS = 10
GATE_THRESHOLD = .50


def market_gate(history, day, direction):
    """Target rate over recent signals with outcomes finished before day."""
    target = 1 if direction == "bullish" else -1
    cutoff = fv.months_after(day, -LOOKBACK_MONTHS)
    eligible = [s for s in history if cutoff <= s["date"] < day and s["exit"] < day]
    months = {(s["date"].year, s["date"].month) for s in eligible}
    symbols = {s["symbol"] for s in eligible}
    if len(eligible) < MIN_CASES or len(months) < MIN_MONTHS or len(symbols) < MIN_SYMBOLS:
        return None
    return sum(s["outcome"] == target for s in eligible) / len(eligible)


def evaluate_samples(samples, direction, adaptive_folds, years=adaptive.YEARS):
    augmented = adaptive.add_local_features(samples, direction)
    by_day = defaultdict(list)
    for s in augmented:
        if s["date"].year in years:
            by_day[s["date"]].append(s)
    ordered = sorted(samples, key=lambda s: s["exit"])
    exits = [s["exit"] for s in ordered]
    prior = {f["year"]: f for f in adaptive_folds}
    annual = defaultdict(lambda: defaultdict(list))
    calls, local_calls, adaptive_calls = [], [], []
    gate_unavailable = 0
    for day, group in sorted(by_day.items()):
        end = bisect.bisect_left(exits, day)
        gate = market_gate(ordered[:end], day, direction)
        if gate is None:
            gate_unavailable += len(group)
        fold = prior.get(day.year, {})
        old_model, old_choice = fold.get("model"), fold.get("selected")
        for s in group:
            own = direction if s["local_score"] >= local.CALL_THRESHOLD else None
            gated = own if gate is not None and gate >= GATE_THRESHOLD else None
            old = direction if old_model and old_choice and model.score(old_model, s["features"][:10]) >= old_choice["threshold"] else None
            for name, label in (("gated", gated), ("asset_local", own), ("adaptive", old)):
                annual[day.year][name].append((s, label))
            calls.append((s, gated))
            local_calls.append((s, own))
            adaptive_calls.append((s, old))
    folds = []
    for year in years:
        fold = {"year": year, **{name: backtest.metrics(annual[year][name], direction)
                                 for name in ("gated", "asset_local", "adaptive")}}
        folds.append(fold)
        print(f"  {year}: gated {fold['gated']['n']} / {fold['gated']['hit_pct']}%; local {fold['asset_local']['n']} / {fold['asset_local']['hit_pct']}%", flush=True)
    return {"test_n": len(calls), "gated": backtest.metrics(calls, direction),
            "asset_local_same_eligible": backtest.metrics(local_calls, direction),
            "adaptive_same_eligible": backtest.metrics(adaptive_calls, direction),
            "gate_unavailable_n": gate_unavailable, "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    prior = json.loads((fv.ROOT / "research" / "adaptive-forecast-research.json").read_text(encoding="utf-8"))
    report = {"method": "Gate the asset-local forecast using the target direction's rolling market-wide hit rate: only make a call when at least half of historical outcomes hit the target. Use signals within 18 calendar months whose outcomes finished strictly before the signal, with at least 100 outcomes, 9 signal months, and 10 assets; otherwise abstain. Evaluate on the same locally eligible signals as the adaptive and asset-local comparators; models select different calls. Unchanged future prices are misses.",
              "limitations": ["A research-driven fixed rule tested on previously inspected years is not an untouched or prospective test. Multiple research iterations bias results; intervals do not correct for selection.",
                              "The historical rates use overlapping outcomes and highly correlated assets, not independent trials. The market gate is lagging and is not a calibrated probability.",
                              "Current selected listings mostly omit delisted assets; local and market history requirements limit coverage. Yahoo crypto differs from Binance. No costs, dividends, slippage or executable same-close entry assumed. No live integration."],
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
    print(json.dumps({k: {key: v[key] for key in ("test_n", "gated", "asset_local_same_eligible", "adaptive_same_eligible", "gate_unavailable_n")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
