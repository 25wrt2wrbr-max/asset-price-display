#!/usr/bin/env python3
"""Combine prior peer-strength and market-outcome gates for exploration.

This combination was chosen after inspecting component results on the same
years; it is not independent validation and is not used by the app.
"""
from __future__ import annotations

import json
from collections import defaultdict

import adaptive_forecast_research as adaptive
import asset_local_forecast_research as local
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import regime_gate_forecast_research as regime
import relative_forecast_research as relative
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "peer-regime-forecast-research.json"


def evaluate_samples(samples, direction, prepared, years=adaptive.YEARS):
    augmented = adaptive.add_local_features(samples, direction)
    peers, gates = {}, {}
    totals, annual = defaultdict(list), defaultdict(lambda: defaultdict(list))
    unavailable = 0
    for s in augmented:
        day = s["date"]
        if day.year not in years:
            continue
        if day not in peers:
            peers[day] = relative.peer_returns(prepared, day)
            gates[day] = regime.market_gate(samples, day, direction)
        values = relative.relative_features(s, peers[day])
        gate = gates[day]
        unavailable += values is None or gate is None
        own = s["local_score"] >= local.CALL_THRESHOLD
        rank = values[1] if values is not None else None
        momentum = rank is not None and (rank >= .75 if direction == "bullish" else rank <= .25)
        reversal = rank is not None and (rank <= .25 if direction == "bullish" else rank >= .75)
        contrarian = gate is not None and gate < regime.GATE_THRESHOLD
        standard = gate is not None and gate >= regime.GATE_THRESHOLD
        flags = {"momentum_contrarian": own and momentum and contrarian,
                 "momentum_standard": own and momentum and standard,
                 "reversal_contrarian": own and reversal and contrarian,
                 "reversal_standard": own and reversal and standard,
                 "momentum_local": own and momentum,
                 "reversal_local": own and reversal,
                 "local_contrarian": own and contrarian,
                 "asset_local": own}
        for name, flag in flags.items():
            pair = (s, direction if flag else None)
            totals[name].append(pair)
            annual[day.year][name].append(pair)
    names = ("momentum_contrarian", "momentum_standard", "reversal_contrarian", "reversal_standard",
             "momentum_local", "reversal_local", "local_contrarian", "asset_local")
    folds = []
    for year in years:
        fold = {"year": year, **{name: backtest.metrics(annual[year][name], direction) for name in names}}
        folds.append(fold)
        print(f"  {year}: momentum/contrarian {fold['momentum_contrarian']['n']} / {fold['momentum_contrarian']['hit_pct']}%; momentum/standard {fold['momentum_standard']['n']} / {fold['momentum_standard']['hit_pct']}%", flush=True)
    return {"test_n": len(totals["asset_local"]),
            **{name: backtest.metrics(totals[name], direction) for name in names},
            "input_unavailable_n": unavailable, "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    report = {"method": "Filter asset-local calls by both peer three-month relative-strength quartile (momentum or reversal) and the market-wide target-direction rate (below 50% contrarian or at least 50% standard). Compute peers from prior local calendar dates and market rates from strictly completed prior outcomes. Missing inputs abstain. Compare components on the same eligible observations; selected calls differ. Unchanged outcomes count as misses.",
              "limitations": ["Combination and four alternatives were chosen after examining historical component results, so this is exploratory rather than independent or prospective validation. Bootstrap intervals do not account for model search.",
                              "Previous peer local dates do not guarantee cross-timezone availability. Current selected listings omit many delisted instruments. Overlapping outcomes and market shocks reduce independent information.",
                              "Coverage can be very small. Yahoo crypto differs from Binance; no costs, taxes, dividends, slippage or executable same-close entry. Not deployed."],
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
    keys = ("test_n", "momentum_contrarian", "momentum_standard", "reversal_contrarian", "reversal_standard", "momentum_local", "reversal_local", "local_contrarian", "asset_local", "input_unavailable_n")
    print(json.dumps({market: {key: value[key] for key in keys} for market, value in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
