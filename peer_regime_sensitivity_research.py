#!/usr/bin/env python3
"""Sensitivity checks for selected peer/regime research rules, not validation.

Compares the original prior-local-date peer rule with a three-calendar-day
additional delay, and reports a greedy non-overlapping-per-asset subset. The
rules and evaluation years were already selected and inspected retrospectively.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

import adaptive_forecast_research as adaptive
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import regime_gate_forecast_research as regime
import relative_forecast_research as relative
import targeted_forecast_research as targeted
import asset_local_forecast_research as local

REPORT = fv.ROOT / "research" / "peer-regime-sensitivity-research.json"
DELAY_DAYS = 3
YEARS = adaptive.YEARS


def evaluate_samples(samples, direction, market, prepared, years=YEARS):
    """Replay selected rule with original vs additionally delayed peers."""
    augmented = adaptive.add_local_features(samples, direction)
    cache, gates = {}, {}
    calls = {"original": [], "delayed": []}
    unavailable = defaultdict(int)
    # Currency uses reversal; US equity and crypto use momentum. This choice
    # was made after observing the original results, not before that test.
    def passes(rank):
        if market == "currency":
            return rank >= .75
        return rank <= .25 if direction == "bearish" else rank >= .75

    for s in augmented:
        day = s["date"]
        if day.year not in years:
            continue
        if day not in gates:
            gates[day] = regime.market_gate(samples, day, direction)
        for name, delay in (("original", 0), ("delayed", DELAY_DAYS)):
            key = (day, delay)
            if key not in cache:
                cache[key] = relative.peer_returns(prepared, day - dt.timedelta(days=delay))
            peer = relative.relative_features(s, cache[key])
            gate = gates[day]
            unavailable[name] += peer is None or gate is None
            flag = (s["local_score"] >= local.CALL_THRESHOLD and peer is not None and
                    passes(peer[1]) and gate is not None and gate < regime.GATE_THRESHOLD)
            calls[name].append((s, direction if flag else None))

    def nonoverlapping(series):
        """Retain earliest signal per asset until its prior selected exit."""
        retained, last_exit = [], {}
        for sample, label in sorted(series, key=lambda row: (row[0]["date"], row[0]["symbol"])):
            if label is not None and (sample["symbol"] not in last_exit or sample["date"] > last_exit[sample["symbol"]]):
                retained.append((sample, label))
                last_exit[sample["symbol"]] = sample["exit"]
        return retained

    result = {"test_n": len(calls["original"]), "input_unavailable_n": dict(unavailable)}
    for name, series in calls.items():
        result[name] = backtest.metrics(series, direction)
        # Coverage for this diagnostic is intentionally omitted: its denominator
        # would otherwise be the retained calls, not the eligible population.
        result[name + "_nonoverlap_calls"] = backtest.metrics(nonoverlapping(series), direction)
        result[name + "_nonoverlap_calls"].pop("coverage_pct", None)
        result[name + "_annual"] = {str(year): backtest.metrics([p for p in series if p[0]["date"].year == year], direction)
                                     for year in years}
    return result


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    report = {"method": "Replay selected local+peer+contrarian variants on identical eligible observations with original prior-local-date peers and with peer dates strictly before signal date minus three calendar days. For each version also greedily retain a call only if that asset's previous retained call exited strictly before the new signal. Ties in outcomes are misses. Nonoverlap summaries do not report coverage; calls are selected using outcomes' exit dates for scheduling only.",
              "limitations": ["This is a post-selection sensitivity test on the same inspected historical data, not independent or prospective validation. Confidence intervals omit all prior model selection.",
                              "Longer delay mitigates but does not establish actual timestamp availability or execution. Peer ranking mixes current asset return with delayed peer returns. Outcome data, benchmark dates and local-time signal assumptions remain unverified point-in-time.",
                              "Non-overlap per asset does not remove cross-asset and market-shock dependence, and changes the selected call set. Current-selected universe omits many delisted instruments and filters for observed future outcomes. Yahoo crypto differs from Binance; no execution costs modeled."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {market} {direction}", flush=True)
        samples, skipped = targeted.observations(subset)
        prepared = relative.prepare_bars(subset["bars"], raw.get("timezones", {}))
        result = evaluate_samples(samples, direction, market, prepared)
        result.update({"received": len(subset["bars"]), "requested": len(names), "skipped": skipped})
        report["markets"][market] = result
        print(f"  original {result['original']['n']} / {result['original']['hit_pct']}%; delayed {result['delayed']['n']} / {result['delayed']['hit_pct']}%", flush=True)
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    keys = ("test_n", "original", "delayed", "original_nonoverlap_calls", "delayed_nonoverlap_calls", "input_unavailable_n")
    print(json.dumps({market: {key: result[key] for key in keys} for market, result in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
