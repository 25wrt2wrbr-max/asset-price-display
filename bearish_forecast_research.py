#!/usr/bin/env python3
"""Exploratory three-month bearish forecasts for PSE, US stocks and funds.

This is not the application's trend classifier. Candidate choice in each
annual fold uses only earlier completed outcomes, but the history has been
repeatedly inspected and is not an independent or prospective validation.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

import asset_local_forecast_research as local
import forecast_extended_validation as extended
import forecast_validation as fv
import market_forecast_backtest as backtest
import regime_gate_forecast_research as regime
import relative_forecast_research as relative
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "bearish-forecast-research-comparable.json"
YEARS = range(2020, 2027)
# The ordered list also fixes the tie-breaker for validation selection.
CANDIDATES = ("local", "local_momentum", "local_reversal",
              "momentum_contrarian", "reversal_contrarian",
              "weak_trend", "strong_trend")
MIN_CALLS = 60
MIN_MONTHS = 6
MIN_SYMBOLS = 10
MIN_ACCURACY = .51
MIN_LIFT = .01


def flags(sample, local_score, peer_rank, market_rate):
    """Produce candidates from signal-time inputs; unavailable inputs abstain."""
    own = local_score is not None and local_score >= local.CALL_THRESHOLD
    momentum = peer_rank is not None and peer_rank <= .25
    reversal = peer_rank is not None and peer_rank >= .75
    contra = market_rate is not None and market_rate < regime.GATE_THRESHOLD
    trend_score = sample["features"][0]
    return {"local": own, "local_momentum": own and momentum,
            "local_reversal": own and reversal,
            "momentum_contrarian": own and momentum and contra,
            "reversal_contrarian": own and reversal and contra,
            "weak_trend": trend_score <= -.25,
            "strong_trend": trend_score >= .25}


def choose(validation):
    """Choose a rule using only a separately supplied completed validation set."""
    if not validation:
        return None, []
    baseline = sum(s["outcome"] == -1 for s in validation) / len(validation)
    diagnostics = []
    for name in CANDIDATES:
        chosen = [s for s in validation if s["flags"][name]]
        n = len(chosen)
        months = len({(s["date"].year, s["date"].month) for s in chosen})
        symbols = len({s["symbol"] for s in chosen})
        rate = sum(s["outcome"] == -1 for s in chosen) / n if n else None
        qualifies = (n >= MIN_CALLS and months >= MIN_MONTHS and symbols >= MIN_SYMBOLS
                     and rate >= MIN_ACCURACY and rate >= baseline + MIN_LIFT)
        diagnostics.append({"rule": name, "n": n, "months": months,
                            "symbols": symbols, "hit_pct": round(rate * 100, 2) if rate is not None else None,
                            "baseline_pct": round(baseline * 100, 2), "qualifies": qualifies})
    passing = [item for item in diagnostics if item["qualifies"]]
    # Use exact counts, not rounded percentages, to rank close candidates.
    winner = max(passing, key=lambda item: (
        sum(s["outcome"] == -1 for s in validation if s["flags"][item["rule"]]) / item["n"],
        item["n"])) if passing else None
    return winner, diagnostics


def signal_flags(samples, prepared):
    """Reconstruct each signal without using its own future outcome as input."""
    by_symbol = defaultdict(list)
    for s in samples:
        by_symbol[s["symbol"]].append(s)
    peer_cache, gate_cache = {}, {}
    result = []
    for s in samples:
        day = s["date"]
        if day not in peer_cache:
            peer_cache[day] = relative.peer_returns(prepared, day)
            gate_cache[day] = regime.market_gate(samples, day, "bearish")
        estimate = local.estimate(by_symbol[s["symbol"]], s, "bearish")
        features = relative.relative_features(s, peer_cache[day])
        rank = features[1] if features is not None else None
        entry = dict(s)
        entry["local_available"] = estimate is not None
        entry["flags"] = flags(s, estimate["score"] if estimate else None, rank, gate_cache[day])
        result.append(entry)
    return result


def evaluate_samples(samples, prepared, years=YEARS, require_local=False):
    rows = signal_flags(samples, prepared)
    if require_local:
        rows = [s for s in rows if s["local_available"]]
    total, prior, always, folds = [], [], [], []
    for year in years:
        start, end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        validation_start = dt.date(year - 2, 1, 1)
        validation = [s for s in rows if validation_start <= s["date"] < start and s["exit"] < start]
        test = [s for s in rows if start <= s["date"] < end]
        winner, diagnostics = choose(validation)
        selected = [(s, "bearish" if winner and s["flags"][winner["rule"]] else None) for s in test]
        earlier = [(s, "bearish" if s["flags"]["momentum_contrarian"] else None) for s in test]
        base = [(s, "bearish") for s in test]
        total.extend(selected)
        prior.extend(earlier)
        always.extend(base)
        folds.append({"year": year, "validation_n": len(validation),
                      "latest_validation_exit": max((s["exit"] for s in validation), default=None).isoformat() if validation else None,
                      "selected_rule": winner, "validation_diagnostics": diagnostics,
                      "candidate": backtest.metrics(selected, "bearish"),
                      "previous_us_rule": backtest.metrics(earlier, "bearish"),
                      "always_down": backtest.metrics(base, "bearish")})
        print(f"  {year}: {winner['rule'] if winner else 'abstain'}; {folds[-1]['candidate']['n']} calls", flush=True)
    return {"test_n": len(total), "candidate": backtest.metrics(total, "bearish"),
            "previous_us_rule": backtest.metrics(prior, "bearish"),
            "always_down": backtest.metrics(always, "bearish"), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(extended.DATA.read_text(encoding="utf-8"))
    pse = json.loads(fv.DATA.read_text(encoding="utf-8"))
    report = {"method": "For each market, reconstruct seven candidate rules using chart-window trend, asset-local completed outcomes, prior-date peer ranks and completed market outcomes. Select the highest validation accuracy over the previous two years among rules with >=60 calls, >=6 months, >=10 symbols, >=51% accuracy and >=1 percentage point above always-down in that validation population. Otherwise abstain. Validation outcomes must finish strictly before the test year; local and market outcomes must finish strictly before each signal. First monthly close versus first close on or after three calendar months, at most ten days late; unchanged is incorrect. US and funds require 6- and 12-month history; the US population additionally requires an available asset-local score, to match the earlier US candidate. PSE uses its 90-day chart window; Yahoo uses three calendar months. All peer returns use three calendar months.",
              "limitations": ["Exploratory research after repeated inspection of these years, not untouched or prospective validation; selection and approximate bootstrap intervals do not account for multiple testing.",
                              "Today-selected listings omit most delistings. Eligible observations require known outcomes; missing and pending outcomes are omitted, not losses. Local history is also reconstructed from outcome-available samples.",
                              "Prior local-date peer closes do not prove cross-timezone availability. Corporate actions, ticker identity and other histories remain unverified; PARA is excluded from every US input after inspection.",
                              "Calls overlap and share shocks; counts are not independent. No dividends, trading costs, taxes, slippage, or executable same-close entry are assumed. Fund universe includes exchange-traded products beyond conventional ETFs. Not deployed."],
              "markets": {}}
    for market in ("PSE", "us_equity", "fund"):
        if market == "PSE":
            subset = pse
            samples, skipped = backtest.observations(subset)
            zones = {symbol: subset.get("timezones", {}).get(symbol, "Asia/Manila") for symbol in subset["bars"]}
            requested = len(subset["universe"])
        else:
            names = [symbol for symbol, category in raw["universe"].items()
                     if category == market and not (market == "us_equity" and symbol == "PARA")]
            subset = dict(raw)
            subset["bars"] = {symbol: raw["bars"][symbol] for symbol in names if symbol in raw["bars"]}
            samples, skipped = targeted.observations(subset)
            zones = raw.get("timezones", {})
            requested = len(names)
        print(f"Evaluating {market}: {len(subset['bars'])} histories", flush=True)
        prepared = relative.prepare_bars(subset["bars"], zones)
        result = evaluate_samples(samples, prepared, require_local=market == "us_equity")
        result.update({"requested": requested, "received": len(subset["bars"]),
                       "observation_n": len(samples), "skipped": skipped})
        report["markets"][market] = result
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({market: {key: value[key] for key in ("test_n", "candidate", "previous_us_rule", "always_down")}
                      for market, value in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
