#!/usr/bin/env python3
"""Explore agreement between asset-local and nearest-neighbor forecasts.

No future outcomes enter either constituent score. Reused evaluation years
are exploratory and model selection is not corrected; this is not deployed.
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

REPORT = fv.ROOT / "research" / "consensus-forecast-research.json"


def evaluate_samples(samples, direction, adaptive_folds, years=adaptive.YEARS):
    augmented = adaptive.add_local_features(samples, direction)
    by_symbol = defaultdict(list)
    for s in samples:
        by_symbol[s["symbol"]].append(s)
    prior = {f["year"]: f for f in adaptive_folds}
    annual = defaultdict(lambda: defaultdict(list))
    all_calls = defaultdict(list)
    gate_cache = {}
    for s in augmented:
        year, day = s["date"].year, s["date"]
        if year not in years:
            continue
        neighbor_value = neighbor.estimate(by_symbol[s["symbol"]], s, direction)
        own = direction if s["local_score"] >= local.CALL_THRESHOLD else None
        nearest = direction if neighbor_value is not None and neighbor_value >= neighbor.THRESHOLD else None
        consensus = direction if own and nearest else None
        if day not in gate_cache:
            gate_cache[day] = regime.market_gate(samples, day, direction)
        gate = gate_cache[day]
        gated = own if gate is not None and gate >= regime.GATE_THRESHOLD else None
        fold = prior.get(year, {})
        old_model, old_choice = fold.get("model"), fold.get("selected")
        old = direction if old_model and old_choice and model.score(old_model, s["features"][:10]) >= old_choice["threshold"] else None
        labels = {"consensus": consensus, "asset_local": own, "neighbor": nearest,
                  "regime_gate": gated, "adaptive": old}
        for name, label in labels.items():
            annual[year][name].append((s, label))
            all_calls[name].append((s, label))
    folds = []
    for year in years:
        result = {"year": year, **{name: backtest.metrics(annual[year][name], direction)
                                    for name in ("consensus", "asset_local", "neighbor", "regime_gate", "adaptive")}}
        folds.append(result)
        print(f"  {year}: consensus {result['consensus']['n']} / {result['consensus']['hit_pct']}%; local {result['asset_local']['n']} / {result['asset_local']['hit_pct']}%", flush=True)
    return {"test_n": len(all_calls["consensus"]),
            **{name: backtest.metrics(all_calls[name], direction)
               for name in ("consensus", "asset_local", "neighbor", "regime_gate", "adaptive")},
            "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    prior = json.loads((fv.ROOT / "research" / "adaptive-forecast-research.json").read_text(encoding="utf-8"))
    report = {"method": "Call the requested direction only when both the prior asset-local model and the prior nearest-neighbor model call that direction. Their scores use only outcomes completed strictly before the signal. Replay asset-local, nearest-neighbor, market-regime gate, and adaptive comparators on the same eligible observations; models select different calls. Ties count as misses.",
              "limitations": ["Consensus was proposed after examining results for both components and all test years. This is exploratory, not independent or prospective validation; intervals ignore research selection.",
                              "Overlapping outcomes and correlated assets mean sample counts overstate independent information. Narrower coverage may make observed accuracy less representative.",
                              "Current selected listings omit many delisted assets. Yahoo crypto differs from Binance. No costs, dividends, slippage, or executable same-close entry assumed; not a production model."],
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
    print(json.dumps({k: {key: v[key] for key in ("test_n", "consensus", "asset_local", "neighbor", "regime_gate", "adaptive")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
