#!/usr/bin/env python3
"""Explore nearest-neighbor forecasts gated by peer rank and market regime.

For the US, rebuild all inputs both with and without the influential PARA
series. This is post-selection research on previously inspected years, not
independent validation or production forecasting.
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
import regime_gate_forecast_research as regime
import relative_forecast_research as relative
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "peer-neighbor-regime-research.json"


def evaluate_samples(samples, direction, prepared, years=adaptive.YEARS):
    augmented = adaptive.add_local_features(samples, direction)
    by_symbol = defaultdict(list)
    for s in samples:
        by_symbol[s["symbol"]].append(s)
    peers, gates = {}, {}
    totals, annual = defaultdict(list), defaultdict(lambda: defaultdict(list))
    unavailable = 0
    names = ("neighbor_momentum_contrarian", "neighbor_reversal_contrarian",
             "neighbor_momentum", "neighbor_reversal", "neighbor_contrarian", "neighbor",
             "local_momentum_contrarian", "local_reversal_contrarian", "local_contrarian", "asset_local")
    for s in augmented:
        day = s["date"]
        if day.year not in years:
            continue
        if day not in peers:
            peers[day] = relative.peer_returns(prepared, day)
            gates[day] = regime.market_gate(samples, day, direction)
        features, gate = relative.relative_features(s, peers[day]), gates[day]
        unavailable += features is None or gate is None
        rank = features[1] if features is not None else None
        momentum = rank is not None and (rank >= .75 if direction == "bullish" else rank <= .25)
        reversal = rank is not None and (rank <= .25 if direction == "bullish" else rank >= .75)
        contrarian = gate is not None and gate < regime.GATE_THRESHOLD
        local_call = s["local_score"] >= local.CALL_THRESHOLD
        score = neighbor.estimate(by_symbol[s["symbol"]], s, direction)
        neighbor_call = score is not None and score >= neighbor.THRESHOLD
        flags = {"neighbor_momentum_contrarian": neighbor_call and momentum and contrarian,
                 "neighbor_reversal_contrarian": neighbor_call and reversal and contrarian,
                 "neighbor_momentum": neighbor_call and momentum, "neighbor_reversal": neighbor_call and reversal,
                 "neighbor_contrarian": neighbor_call and contrarian, "neighbor": neighbor_call,
                 "local_momentum_contrarian": local_call and momentum and contrarian,
                 "local_reversal_contrarian": local_call and reversal and contrarian,
                 "local_contrarian": local_call and contrarian, "asset_local": local_call}
        for name in names:
            pair = (s, direction if flags[name] else None)
            totals[name].append(pair)
            annual[day.year][name].append(pair)
    folds = []
    for year in years:
        fold = {"year": year, **{name: backtest.metrics(annual[year][name], direction) for name in names}}
        folds.append(fold)
        print(f"  {year}: neighbor momentum {fold['neighbor_momentum_contrarian']['n']} / {fold['neighbor_momentum_contrarian']['hit_pct']}%; reversal {fold['neighbor_reversal_contrarian']['n']} / {fold['neighbor_reversal_contrarian']['hit_pct']}%", flush=True)
    return {"test_n": len(totals["neighbor"]),
            **{name: backtest.metrics(totals[name], direction) for name in names},
            "input_unavailable_n": unavailable, "folds": folds}


def evaluate_market(raw, market, direction, exclude=frozenset()):
    names = [s for s, category in raw["universe"].items() if category == market and s not in exclude]
    subset = dict(raw)
    subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
    samples, skipped = targeted.observations(subset)
    prepared = relative.prepare_bars(subset["bars"], raw.get("timezones", {}))
    result = evaluate_samples(samples, direction, prepared)
    result.update({"received": len(subset["bars"]), "requested": len(names),
                   "observation_n": len(samples), "excluded": sorted(exclude), "skipped": skipped})
    return result


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    report = {"method": "Combine local nearest-neighbor calls with prior-local-date peer three-month momentum/reversal quartiles and the strictly prior completed-outcome market contrarian gate. Compare ungated and local counterparts on the same eligible observations; selected calls differ. Additionally rebuild the US universe, market gate and peer ranks without PARA, an exclusion selected after inspecting results. Flat outcomes are misses.",
              "limitations": ["Post-selection experiment after extensive examination of the same years; no independent or prospective validation and intervals do not adjust for model search.",
                              "Previous peer local dates do not prove information availability across time zones. Removing PARA is not verification of ticker identity, corporate-action treatment or other symbols.",
                              "Selected current listings omit delistings and require observed future outcomes; overlapping signals and market shocks limit independence. Yahoo crypto differs from Binance. No costs or executable same-close entry modeled; not deployed."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        print(f"Evaluating {market} {direction}", flush=True)
        report["markets"][market] = evaluate_market(raw, market, direction)
    if raw["universe"].get("PARA") != "us_equity" or "PARA" not in raw["bars"]:
        raise ValueError("Missing original PARA series; refusing false exclusion comparison")
    print("Rebuilding US equity without PARA", flush=True)
    report["us_without_para"] = evaluate_market(raw, "us_equity", "bearish", {"PARA"})
    expected = json.loads((fv.ROOT / "research" / "us-symbol-sensitivity-research.json").read_text(encoding="utf-8"))
    for name, existing in (("us_equity", expected["original"]), ("us_without_para", expected["without_symbol"])):
        actual = report["markets"][name] if name == "us_equity" else report[name]
        a, b = actual["local_momentum_contrarian"], existing["momentum_contrarian"]
        if (actual["test_n"], a["n"], a["correct"]) != (existing["test_n"], b["n"], b["correct"]):
            raise ValueError(f"{name}: local comparator replay differs from prior report")
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    keys = ("test_n", "neighbor_momentum_contrarian", "neighbor_reversal_contrarian", "local_momentum_contrarian", "local_reversal_contrarian", "neighbor")
    print(json.dumps({name: {key: result[key] for key in keys}
                      for name, result in {**report["markets"], "us_without_para": report["us_without_para"]}.items()}, indent=2))


if __name__ == "__main__":
    main()
