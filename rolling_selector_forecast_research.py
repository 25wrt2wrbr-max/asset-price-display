#!/usr/bin/env python3
"""Select directional forecast rules using only their completed past calls.

This is exploratory: years, candidate rules and selector were previously
inspected. It is not an independent validation or an app classifier.
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
import neighbor_forecast_research as neighbor
import regime_gate_forecast_research as regime
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "rolling-selector-forecast-research.json"
CANDIDATES = ("local", "neighbor", "local_contrarian", "neighbor_contrarian")
LOOKBACK_MONTHS = 24
MIN_CALLS = 60
MIN_MONTHS = 9
MIN_SYMBOLS = 10
MIN_RATE = .50


def select(history, day, direction):
    """Select by past hit rate, breaking ties in fixed candidate order."""
    cutoff = fv.months_after(day, -LOOKBACK_MONTHS)
    target = 1 if direction == "bullish" else -1
    best_name, best_rate = None, -1.
    for name in CANDIDATES:
        rows = [s for s in history.get(name, ()) if cutoff <= s["date"] < day and s["exit"] < day]
        if (len(rows) < MIN_CALLS or len({(s["date"].year, s["date"].month) for s in rows}) < MIN_MONTHS
                or len({s["symbol"] for s in rows}) < MIN_SYMBOLS):
            continue
        rate = sum(s["outcome"] == target for s in rows) / len(rows)
        if rate >= MIN_RATE and rate > best_rate:
            best_name, best_rate = name, rate
    return best_name


def evaluate_samples(samples, direction, years=adaptive.YEARS):
    augmented = adaptive.add_local_features(samples, direction)
    by_symbol, by_day = defaultdict(list), defaultdict(list)
    for s in samples:
        by_symbol[s["symbol"]].append(s)
    for s in augmented:
        by_day[s["date"]].append(s)
    # Queue only reconstructed calls. Calls whose exits equal a signal day are
    # deliberately withheld, regardless of possible intraday execution time.
    completed, pending = defaultdict(list), defaultdict(list)
    totals, annual = defaultdict(list), defaultdict(lambda: defaultdict(list))
    chosen_counts = defaultdict(int)
    for day, group in sorted(by_day.items()):
        for name in CANDIDATES:
            ordered = pending[name]
            ordered.sort(key=lambda s: s["exit"])
            split = bisect.bisect_left([s["exit"] for s in ordered], day)
            completed[name].extend(ordered[:split])
            pending[name] = ordered[split:]
        chosen = select(completed, day, direction)
        market_rate = regime.market_gate(samples, day, direction)
        for s in group:
            own = s["local_score"] >= local.CALL_THRESHOLD
            value = neighbor.estimate(by_symbol[s["symbol"]], s, direction)
            near = value is not None and value >= neighbor.THRESHOLD
            contra = market_rate is not None and market_rate < regime.GATE_THRESHOLD
            flags = {"local": own, "neighbor": near,
                     "local_contrarian": own and contra,
                     "neighbor_contrarian": near and contra}
            for name in CANDIDATES:
                if flags[name]:
                    pending[name].append(s)
            if day.year not in years:
                continue
            chosen_counts[chosen or "unavailable"] += 1
            labels = {name: direction if flags[name] else None for name in CANDIDATES}
            labels["selector"] = direction if chosen and flags[chosen] else None
            for name, label in labels.items():
                totals[name].append((s, label))
                annual[day.year][name].append((s, label))
    names = ("selector",) + CANDIDATES
    folds = []
    for year in years:
        fold = {"year": year, **{name: backtest.metrics(annual[year][name], direction) for name in names}}
        folds.append(fold)
        print(f"  {year}: selector {fold['selector']['n']} / {fold['selector']['hit_pct']}%; local {fold['local']['n']} / {fold['local']['hit_pct']}%", flush=True)
    return {"test_n": len(totals["selector"]),
            **{name: backtest.metrics(totals[name], direction) for name in names},
            "selection_counts": dict(chosen_counts), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    report = {"method": "Reconstruct four candidate forecasts (local, neighbor, and each with the prior market contrarian gate) at each signal date. From each candidate's calls in the past 24 months whose outcomes finished strictly before this signal, select the highest historical hit rate if at least 50%, 60 calls, nine signal months and ten symbols. Ties use fixed candidate order. Emit only when the selected candidate itself calls. Outcomes of simultaneously pending forecasts never enter selection. Compare all candidates on identical eligible observations, not necessarily identical selected calls. Ties in prices are misses.",
              "limitations": ["Selector and candidates follow repeated inspection of the same years. This is exploratory, not an untouched holdout or prospective test; bootstrap intervals omit research selection.",
                              "Monthly windows overlap, assets share shocks and selection rates are not calibrated probabilities. Selected current listings omit many delisted assets; local-history eligibility restricts coverage.",
                              "Yahoo crypto differs from Binance. No fees, taxes, dividends, slippage or executable same-close entry modeled. No production deployment."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {market} {direction}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = targeted.observations(subset)
        result = evaluate_samples(samples, direction)
        result.update({"received": len(subset["bars"]), "requested": len(names),
                       "observation_n": len(samples), "skipped": skipped})
        report["markets"][market] = result
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({market: {key: value[key] for key in ("test_n", "selector", *CANDIDATES, "selection_counts")}
                      for market, value in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
