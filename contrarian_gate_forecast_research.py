#!/usr/bin/env python3
"""Explore a contrary market-regime filter; not an independently validated model.

Only outcomes strictly completed before each signal are used. The filter was
chosen after seeing related experiments on the same years, so its reported
performance is exploratory and is not suitable for deployment.
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
import regime_gate_forecast_research as regime
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "contrarian-gate-forecast-research.json"


def evaluate_samples(samples, direction, adaptive_folds, years=adaptive.YEARS):
    augmented = adaptive.add_local_features(samples, direction)
    prior = {f["year"]: f for f in adaptive_folds}
    annual = defaultdict(lambda: defaultdict(list))
    all_calls = defaultdict(list)
    gate_cache = {}
    unavailable = 0
    for s in augmented:
        day, year = s["date"], s["date"].year
        if year not in years:
            continue
        if day not in gate_cache:
            gate_cache[day] = regime.market_gate(samples, day, direction)
        value = gate_cache[day]
        unavailable += value is None
        own = direction if s["local_score"] >= local.CALL_THRESHOLD else None
        contrarian = own if value is not None and value < regime.GATE_THRESHOLD else None
        standard = own if value is not None and value >= regime.GATE_THRESHOLD else None
        fold = prior.get(year, {})
        old_model, old_choice = fold.get("model"), fold.get("selected")
        old = direction if old_model and old_choice and model.score(old_model, s["features"][:10]) >= old_choice["threshold"] else None
        for name, label in (("contrarian", contrarian), ("asset_local", own),
                            ("regime_gate", standard), ("adaptive", old)):
            annual[year][name].append((s, label))
            all_calls[name].append((s, label))
    folds = []
    for year in years:
        fold = {"year": year, **{name: backtest.metrics(annual[year][name], direction)
                                 for name in ("contrarian", "asset_local", "regime_gate", "adaptive")}}
        folds.append(fold)
        print(f"  {year}: contrarian {fold['contrarian']['n']} / {fold['contrarian']['hit_pct']}%; local {fold['asset_local']['n']} / {fold['asset_local']['hit_pct']}%", flush=True)
    return {"test_n": len(all_calls["contrarian"]),
            **{name: backtest.metrics(all_calls[name], direction)
               for name in ("contrarian", "asset_local", "regime_gate", "adaptive")},
            "gate_unavailable_n": unavailable, "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    prior = json.loads((fv.ROOT / "research" / "adaptive-forecast-research.json").read_text(encoding="utf-8"))
    report = {"method": "Permit the asset-local call only when the earlier regime gate's market-wide target-direction rate is strictly below 50%; unavailable gate abstains. The 18-month gate uses only outcomes strictly completed before the signal, requiring 100 cases, nine months and ten assets. Replay the earlier regime-gated, adaptive and asset-local methods on the same eligible observations, although their calls differ. Flat outcomes are misses.",
              "limitations": ["This inverse rule was proposed after inspecting earlier test outcomes. Test years are reused, not a holdout; multiple research selection is not included in intervals.",
                              "Overlapping outcomes and correlated assets reduce independent information; a lagged hit rate is not a calibrated probability. The model may rarely call.",
                              "Current selected listings omit many delisted assets. Yahoo crypto differs from Binance; costs, dividends, slippage and executable close are not modeled. Not deployed."],
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
    print(json.dumps({k: {key: v[key] for key in ("test_n", "contrarian", "asset_local", "regime_gate", "adaptive", "gate_unavailable_n")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
