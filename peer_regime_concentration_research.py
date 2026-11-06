#!/usr/bin/env python3
"""Audit concentration of selected peer/regime calls, not a fresh backtest.

Calls are reconstructed from previously inspected data and selected rules.
Leave-one-group-out summaries are descriptive diagnostics using future
outcomes; they must never be used as live signal filters.
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

REPORT = fv.ROOT / "research" / "peer-regime-concentration-research.json"


def selected_calls(samples, direction, market, prepared, years=adaptive.YEARS):
    augmented = adaptive.add_local_features(samples, direction)
    peers, gates, calls = {}, {}, []
    for s in augmented:
        day = s["date"]
        if day.year not in years:
            continue
        if day not in peers:
            peers[day] = relative.peer_returns(prepared, day)
            gates[day] = regime.market_gate(samples, day, direction)
        features = relative.relative_features(s, peers[day])
        if features is None or gates[day] is None:
            continue
        rank = features[1]
        peer_pass = (rank >= .75 if market == "currency" or direction == "bullish" else rank <= .25)
        if (s["local_score"] >= local.CALL_THRESHOLD and peer_pass and
                gates[day] < regime.GATE_THRESHOLD):
            calls.append((s, direction))
    return calls


def group_stats(calls, direction, key):
    groups = defaultdict(list)
    for sample, label in calls:
        groups[key(sample)].append((sample, label))
    target = 1 if direction == "bullish" else -1
    total_wins = sum(s["outcome"] == target for s, _ in calls)
    result = []
    for name, group in sorted(groups.items()):
        n = len(group)
        wins = sum(s["outcome"] == target for s, _ in group)
        others = len(calls) - n
        result.append({"group": name, "calls": n, "correct": wins,
                       "hit_pct": round(100 * wins / n, 2),
                       "share_pct": round(100 * n / len(calls), 2),
                       "other_calls": others,
                       "without_group_hit_pct": round(100 * (total_wins - wins) / others, 2) if others else None})
    return result


def analyze(calls, direction):
    summary = backtest.metrics(calls, direction)
    summary.pop("coverage_pct", None)  # denominator is the already-selected calls
    return {"selected_only": summary,
            "years": group_stats(calls, direction, lambda s: str(s["date"].year)),
            "months": group_stats(calls, direction, lambda s: s["date"].strftime("%Y-%m")),
            "symbols": group_stats(calls, direction, lambda s: s["symbol"])}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    expected = json.loads((fv.ROOT / "research" / "peer-regime-forecast-research.json").read_text(encoding="utf-8"))
    report = {"method": "Replay original selected local+peer+contrarian calls; verify their count and correct count match the previously saved combined experiment, then summarize call shares and accuracy by signal year, month and symbol and report accuracy with each group excluded. Flat outcomes count as misses. Exclusion is a hindsight diagnostic, not a signal or independent validation.",
              "limitations": ["Post-selection audit of already inspected data: exclusion statistics and bootstrap intervals are not corrected for search or multiple comparisons.",
                              "Calendar groups and symbols remain correlated; no group count represents independent trials. Prior local-date peers do not establish cross-timezone availability.",
                              "Outcomes must be observable to enter the sample; current listings omit many delisted assets. Yahoo crypto differs from Binance. Same-close execution, fees and dividends are unmodeled."],
              "markets": {}}
    keys = {"currency": "reversal_contrarian", "us_equity": "momentum_contrarian", "crypto": "momentum_contrarian"}
    for market, direction in targeted.TASKS.items():
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Auditing {market} {direction}", flush=True)
        samples, skipped = targeted.observations(subset)
        prepared = relative.prepare_bars(subset["bars"], raw.get("timezones", {}))
        calls = selected_calls(samples, direction, market, prepared)
        result = analyze(calls, direction)
        prior = expected["markets"][market][keys[market]]
        if (result["selected_only"]["n"], result["selected_only"]["correct"]) != (prior["n"], prior["correct"]):
            raise ValueError(f"{market}: replay did not match original report")
        result.update({"matched_original_report": True, "received": len(subset["bars"]),
                       "requested": len(names), "skipped": skipped})
        report["markets"][market] = result
        print(f"  {len(calls)} calls; {len(result['years'])} years, {len(result['months'])} months, {len(result['symbols'])} symbols", flush=True)
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    for market, result in report["markets"].items():
        print(json.dumps({"market": market, "summary": result["selected_only"], "years": result["years"],
                          "largest_symbol_groups": sorted(result["symbols"], key=lambda g: -g["calls"])[:5]}, indent=2))


if __name__ == "__main__":
    main()
