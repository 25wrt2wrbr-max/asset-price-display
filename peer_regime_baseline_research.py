#!/usr/bin/env python3
"""Explore peer/regime rules without requiring a local forecast to call.

The test population still requires local history for direct comparison. Rules
and years were already examined; this is not an independent test or app model.
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

REPORT = fv.ROOT / "research" / "peer-regime-baseline-research.json"


def evaluate_samples(samples, direction, prepared, years=adaptive.YEARS):
    eligible = adaptive.add_local_features(samples, direction)
    peers, gates = {}, {}
    annual, totals = defaultdict(lambda: defaultdict(list)), defaultdict(list)
    missing = 0
    names = ("momentum_contrarian", "reversal_contrarian", "momentum_standard",
             "reversal_standard", "momentum_local_contrarian", "reversal_local_contrarian", "asset_local")
    for s in eligible:
        day = s["date"]
        if day.year not in years:
            continue
        if day not in peers:
            peers[day] = relative.peer_returns(prepared, day)
            gates[day] = regime.market_gate(samples, day, direction)
        values, gate = relative.relative_features(s, peers[day]), gates[day]
        missing += values is None or gate is None
        rank = values[1] if values is not None else None
        momentum = rank is not None and (rank >= .75 if direction == "bullish" else rank <= .25)
        reversal = rank is not None and (rank <= .25 if direction == "bullish" else rank >= .75)
        contrary = gate is not None and gate < regime.GATE_THRESHOLD
        standard = gate is not None and gate >= regime.GATE_THRESHOLD
        own = s["local_score"] >= local.CALL_THRESHOLD
        flags = {"momentum_contrarian": momentum and contrary, "reversal_contrarian": reversal and contrary,
                 "momentum_standard": momentum and standard, "reversal_standard": reversal and standard,
                 "momentum_local_contrarian": momentum and contrary and own,
                 "reversal_local_contrarian": reversal and contrary and own, "asset_local": own}
        for name in names:
            pair = (s, direction if flags[name] else None)
            annual[day.year][name].append(pair)
            totals[name].append(pair)
    folds = []
    for year in years:
        fold = {"year": year, **{name: backtest.metrics(annual[year][name], direction) for name in names}}
        folds.append(fold)
        print(f"  {year}: momentum {fold['momentum_contrarian']['n']} / {fold['momentum_contrarian']['hit_pct']}%; reversal {fold['reversal_contrarian']['n']} / {fold['reversal_contrarian']['hit_pct']}%", flush=True)
    return {"test_n": len(totals["asset_local"]),
            **{name: backtest.metrics(totals[name], direction) for name in names},
            "input_unavailable_n": missing, "folds": folds}


def evaluate_market(raw, market, direction, exclude=frozenset()):
    names = [s for s, kind in raw["universe"].items() if kind == market and s not in exclude]
    subset = dict(raw)
    subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
    samples, skipped = targeted.observations(subset)
    prepared = relative.prepare_bars(subset["bars"], raw.get("timezones", {}))
    result = evaluate_samples(samples, direction, prepared)
    result.update({"requested": len(names), "received": len(subset["bars"]),
                   "observation_n": len(samples), "excluded": sorted(exclude), "skipped": skipped})
    return result


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    report = {"method": "Call using only three-month peer return quartile (momentum or reversal) and a market-wide historical direction rate gate (below 50% or at least 50%). Peers use strictly earlier local dates, market gate uses strictly completed earlier outcomes. Evaluate on the same local-history-eligible population as earlier tests; local score does not affect the new rule's calls. Rebuild US results without PARA in observations, market gate and peers. Unchanged outcomes are misses; selected calls differ.",
              "limitations": ["Multiple variants selected after inspecting the same data: exploratory and post-selection, not independent or prospective validation. Confidence intervals do not adjust for repeated selection.",
                              "Local-history eligibility and observed future outcomes still restrict the sample even though local scores do not gate the new call. Current-selected listing universe omits delisted instruments.",
                              "Prior peer local dates do not prove cross-timezone availability. PARA exclusion does not verify corporate actions or other ticker identities. Overlapping outcomes share shocks. Yahoo crypto differs from Binance; no costs or executable close assumed."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        print(f"Evaluating {market} {direction}", flush=True)
        report["markets"][market] = evaluate_market(raw, market, direction)
    if raw["universe"].get("PARA") != "us_equity" or "PARA" not in raw["bars"]:
        raise ValueError("Missing original PARA series")
    print("Rebuilding US equity without PARA", flush=True)
    report["us_without_para"] = evaluate_market(raw, "us_equity", "bearish", {"PARA"})
    reference = json.loads((fv.ROOT / "research" / "us-symbol-sensitivity-research.json").read_text(encoding="utf-8"))
    for name, saved in (("us_equity", reference["original"]), ("us_without_para", reference["without_symbol"])):
        current = report["markets"][name] if name == "us_equity" else report[name]
        a, b = current["momentum_local_contrarian"], saved["momentum_contrarian"]
        if (current["test_n"], a["n"], a["correct"]) != (saved["test_n"], b["n"], b["correct"]):
            raise ValueError(f"{name}: comparator does not match saved report")
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    keys = ("test_n", "momentum_contrarian", "reversal_contrarian", "momentum_standard", "reversal_standard", "momentum_local_contrarian", "reversal_local_contrarian")
    print(json.dumps({name: {key: data[key] for key in keys}
                      for name, data in {**report["markets"], "us_without_para": report["us_without_para"]}.items()}, indent=2))


if __name__ == "__main__":
    main()
