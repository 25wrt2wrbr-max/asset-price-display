#!/usr/bin/env python3
"""Explore a gate based on previous completed asset-local forecast outcomes.

Forecasts and their outcomes are reconstructed point-in-time; a signal cannot
use a call that finishes on or after its date. Reused years are exploratory.
"""
from __future__ import annotations

import bisect
import json
from collections import defaultdict

import adaptive_forecast_research as adaptive
import asset_local_forecast_research as local
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts as model
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "calibration-gate-forecast-research.json"
LOOKBACK_MONTHS = 24
MIN_CALLS = 60
MIN_MONTHS = 9
MIN_SYMBOLS = 10
THRESHOLD = .50


def calibration_gate(completed_calls, day, direction):
    """Recent completed historical calls only, including ties as misses."""
    target = 1 if direction == "bullish" else -1
    cutoff = fv.months_after(day, -LOOKBACK_MONTHS)
    eligible = [s for s in completed_calls
                if cutoff <= s["date"] < day and s["exit"] < day]
    if (len(eligible) < MIN_CALLS or
            len({(s["date"].year, s["date"].month) for s in eligible}) < MIN_MONTHS or
            len({s["symbol"] for s in eligible}) < MIN_SYMBOLS):
        return None
    return sum(s["outcome"] == target for s in eligible) / len(eligible)


def evaluate_samples(samples, direction, adaptive_folds, years=adaptive.YEARS):
    augmented = adaptive.add_local_features(samples, direction)
    selected_history = sorted((s for s in augmented if s["local_score"] >= local.CALL_THRESHOLD),
                              key=lambda s: s["exit"])
    exits = [s["exit"] for s in selected_history]
    by_day = defaultdict(list)
    for s in augmented:
        if s["date"].year in years:
            by_day[s["date"]].append(s)
    prior = {f["year"]: f for f in adaptive_folds}
    annual = defaultdict(lambda: defaultdict(list))
    all_calls = defaultdict(list)
    gate_unavailable = 0
    for day, group in sorted(by_day.items()):
        end = bisect.bisect_left(exits, day)
        gate = calibration_gate(selected_history[:end], day, direction)
        if gate is None:
            gate_unavailable += len(group)
        fold = prior.get(day.year, {})
        old_model, old_choice = fold.get("model"), fold.get("selected")
        for s in group:
            own = direction if s["local_score"] >= local.CALL_THRESHOLD else None
            gated = own if gate is not None and gate >= THRESHOLD else None
            old = direction if old_model and old_choice and model.score(old_model, s["features"][:10]) >= old_choice["threshold"] else None
            for name, label in (("calibration_gate", gated), ("asset_local", own), ("adaptive", old)):
                annual[day.year][name].append((s, label))
                all_calls[name].append((s, label))
    folds = []
    for year in years:
        fold = {"year": year, **{name: backtest.metrics(annual[year][name], direction)
                                 for name in ("calibration_gate", "asset_local", "adaptive")}}
        folds.append(fold)
        print(f"  {year}: gated {fold['calibration_gate']['n']} / {fold['calibration_gate']['hit_pct']}%; local {fold['asset_local']['n']} / {fold['asset_local']['hit_pct']}%", flush=True)
    return {"test_n": len(all_calls["calibration_gate"]),
            **{name: backtest.metrics(all_calls[name], direction)
               for name in ("calibration_gate", "asset_local", "adaptive")},
            "gate_unavailable_n": gate_unavailable, "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    prior = json.loads((fv.ROOT / "research" / "adaptive-forecast-research.json").read_text(encoding="utf-8"))
    report = {"method": "Reconstruct historical asset-local calls as they would have appeared using only previously completed outcomes. Allow a new asset-local call only when at least 50% of the preceding 24 months' completed asset-local calls were correct; require 60 calls spanning 9 signal months and 10 symbols. Outcomes on the signal date are excluded. Replayed asset-local and adaptive comparators use the same eligible observations, but select different calls. Flat prices count as misses.",
              "limitations": ["This candidate follows repeated testing on the same years and is exploratory, not an untouched or prospective evaluation; intervals do not adjust for research selection.",
                              "Calls overlap and share market shocks; the gate's hit rate is not a calibrated probability. The gate can be unavailable and can reduce coverage dramatically.",
                              "Present-day selected listings omit many delisted assets. Yahoo crypto differs from Binance. Costs, dividends, slippage and executable same-close entry are not modeled. No app labels change."],
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
    print(json.dumps({k: {key: v[key] for key in ("test_n", "calibration_gate", "asset_local", "adaptive", "gate_unavailable_n")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
