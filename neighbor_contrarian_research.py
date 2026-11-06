#!/usr/bin/env python3
"""Test a lagged market-direction gate on asset-specific neighbors.

This is a retrospective, post-selection experiment, not independent evidence
or a production forecast. All historical outcomes used must predate a signal.
"""
from __future__ import annotations

import json
from collections import defaultdict

import adaptive_forecast_research as adaptive
import asset_local_forecast_research as local
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts as model
import neighbor_forecast_research as neighbor
import regime_gate_forecast_research as regime
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "neighbor-contrarian-research.json"


def evaluate_samples(samples, direction, adaptive_folds, years=adaptive.YEARS):
    eligible = adaptive.add_local_features(samples, direction)
    by_symbol = defaultdict(list)
    for sample in samples:
        by_symbol[sample["symbol"]].append(sample)
    previous_folds = {f["year"]: f for f in adaptive_folds}
    annual = defaultdict(lambda: defaultdict(list))
    totals = defaultdict(list)
    gates = {}
    for s in eligible:
        day = s["date"]
        if day.year not in years:
            continue
        if day not in gates:
            gates[day] = regime.market_gate(samples, day, direction)
        gate = gates[day]
        score = neighbor.estimate(by_symbol[s["symbol"]], s, direction)
        neighbor_call = direction if score is not None and score >= neighbor.THRESHOLD else None
        own = direction if s["local_score"] >= local.CALL_THRESHOLD else None
        gate_passes = gate is not None and gate < regime.GATE_THRESHOLD
        fold = previous_folds.get(day.year, {})
        old_model, old_choice = fold.get("model"), fold.get("selected")
        old = direction if old_model and old_choice and model.score(old_model, s["features"][:10]) >= old_choice["threshold"] else None
        labels = {"neighbor_contrarian": neighbor_call if gate_passes else None,
                  "neighbor": neighbor_call,
                  "local_contrarian": own if gate_passes else None,
                  "asset_local": own, "adaptive": old}
        for name, label in labels.items():
            annual[day.year][name].append((s, label))
            totals[name].append((s, label))
    names = ("neighbor_contrarian", "neighbor", "local_contrarian", "asset_local", "adaptive")
    folds = []
    for year in years:
        fold = {"year": year, **{name: backtest.metrics(annual[year][name], direction) for name in names}}
        folds.append(fold)
        print(f"  {year}: gated neighbor {fold['neighbor_contrarian']['n']} / {fold['neighbor_contrarian']['hit_pct']}%; neighbor {fold['neighbor']['n']} / {fold['neighbor']['hit_pct']}%", flush=True)
    return {"test_n": len(totals["neighbor_contrarian"]),
            **{name: backtest.metrics(totals[name], direction) for name in names},
            "gate_unavailable_n": sum(1 for s, _ in totals["neighbor"] if gates[s["date"]] is None),
            "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    prior = json.loads((fv.ROOT / "research" / "adaptive-forecast-research.json").read_text(encoding="utf-8"))
    report = {"method": "Issue an asset-local nearest-neighbor call only when the market-wide target-direction rate from the prior 18 months, using only completed outcomes before the signal, is below 50%. A missing gate abstains. Replay prior local, neighbor, local-contrarian, and adaptive models on the same locally eligible observations; selected calls differ. Flat outcomes count as misses.",
              "limitations": ["This experiment was selected after inspecting the contrarian result on the same years, so results are exploratory, not an independent test or prospective validation. Confidence intervals do not account for repeated selection.",
                              "Overlapping signals and shared shocks limit independent information. Current selected listings largely omit delisted assets; eligible observations require asset-local history.",
                              "Yahoo crypto differs from the app's Binance feed; same-close execution, fees, taxes, dividends and slippage are not modeled. No app labels change."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        names = [symbol for symbol, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {symbol: raw["bars"][symbol] for symbol in names if symbol in raw["bars"]}
        print(f"Evaluating {market} {direction}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = targeted.observations(subset)
        result = evaluate_samples(samples, direction, prior["markets"][market]["folds"])
        result.update({"received": len(subset["bars"]), "requested": len(names),
                       "observation_n": len(samples), "skipped": skipped})
        report["markets"][market] = result
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({k: {key: v[key] for key in ("test_n", "neighbor_contrarian", "neighbor", "local_contrarian", "asset_local", "adaptive", "gate_unavailable_n")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
