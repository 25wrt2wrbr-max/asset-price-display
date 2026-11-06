#!/usr/bin/env python3
"""Explore rolling, past-outcome selection of narrower forecast filters.

This is research, not a change to the app's descriptive trend classifier.
The inspected years are not an independent or prospective test.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

import asset_local_forecast_research as local
import forecast_extended_validation as extended
import forecast_validation as fv
import market_forecast_backtest as backtest
import pse_bull_fund_bear_research as prior
import regime_gate_forecast_research as regime
import relative_forecast_research as relative
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "selective-bull-bear-research.json"
YEARS = range(2020, 2027)
LOOKBACK_MONTHS = 36
MIN_CALLS = 30
MIN_MONTHS = 6
MIN_SYMBOLS = 8
MIN_RATE = .51
MIN_LIFT = .01
PSE_RULES = ("bull_local", "bull_local_strong", "bull_local_weak",
             "bull_local_momentum", "bull_local_reversal", "bull_low_vol",
             "bull_peer_momentum", "bull_peer_reversal")
FUND_RULES = ("prior", "prior_strong_local", "prior_short_down", "prior_short_up",
              "prior_low_vol", "prior_high_vol", "prior_deep_trend")


def flags(sample, direction, local_score, rank, gate):
    score, _, r20, _, volatility, _, _ = sample["features"]
    own = local_score is not None and local_score >= local.CALL_THRESHOLD
    if direction == "bullish":
        bull = sample["app_label"] == "bullish"
        return {"baseline": bull, "bull_local": bull and own,
                "bull_local_strong": bull and own and score >= .45,
                "bull_local_weak": bull and own and score < .45,
                "bull_local_momentum": bull and own and rank is not None and rank >= .75,
                "bull_local_reversal": bull and own and rank is not None and rank <= .25,
                "bull_low_vol": bull and volatility <= .015,
                "bull_peer_momentum": bull and rank is not None and rank >= .75,
                "bull_peer_reversal": bull and rank is not None and rank <= .25}
    previous = own and rank is not None and rank <= .25 and gate is not None and gate < regime.GATE_THRESHOLD
    return {"baseline": previous, "prior": previous,
            "prior_strong_local": previous and local_score >= .60,
            "prior_short_down": previous and r20 < 0,
            "prior_short_up": previous and r20 >= 0,
            "prior_low_vol": previous and volatility <= .015,
            "prior_high_vol": previous and volatility > .015,
            "prior_deep_trend": previous and score <= -.25}


def reconstruct(samples, prepared, direction):
    by_symbol = defaultdict(list)
    for sample in samples:
        by_symbol[sample["symbol"]].append(sample)
    peers, gates, output = {}, {}, []
    for sample in samples:
        day = sample["date"]
        if day not in peers:
            peers[day] = relative.peer_returns(prepared, day)
            gates[day] = regime.market_gate(samples, day, direction) if direction == "bearish" else None
        estimate = local.estimate(by_symbol[sample["symbol"]], sample, direction)
        relative_values = relative.relative_features(sample, peers[day])
        rank = relative_values[1] if relative_values is not None else None
        entry = dict(sample)
        entry["flags"] = flags(sample, direction, estimate["score"] if estimate else None, rank, gates[day])
        output.append(entry)
    return output


def choose(history, day, direction):
    """Use only historical signals whose outcomes completed before this day."""
    cutoff = fv.months_after(day, -LOOKBACK_MONTHS)
    available = [s for s in history if cutoff <= s["date"] < day and s["exit"] < day]
    baseline = [s for s in available if s["flags"]["baseline"]]
    target = 1 if direction == "bullish" else -1
    if (len(baseline) < MIN_CALLS or
            len({(s["date"].year, s["date"].month) for s in baseline}) < MIN_MONTHS or
            len({s["symbol"] for s in baseline}) < MIN_SYMBOLS):
        return None
    base_rate = sum(s["outcome"] == target for s in baseline) / len(baseline)
    names = PSE_RULES if direction == "bullish" else FUND_RULES
    choices = []
    for name in names:
        group = [s for s in available if s["flags"][name]]
        n = len(group)
        if (n < MIN_CALLS or len({(s["date"].year, s["date"].month) for s in group}) < MIN_MONTHS or
                len({s["symbol"] for s in group}) < MIN_SYMBOLS):
            continue
        hit = sum(s["outcome"] == target for s in group)
        rate = hit / n
        if rate >= MIN_RATE and rate >= base_rate + MIN_LIFT:
            choices.append({"rule": name, "n": n, "correct": hit,
                            "base_n": len(baseline), "base_correct": sum(s["outcome"] == target for s in baseline),
                            "latest_exit": max(s["exit"] for s in group).isoformat()})
    return max(choices, key=lambda v: (v["correct"] / v["n"], v["n"])) if choices else None


def evaluate_rows(rows, direction, years=YEARS):
    days = defaultdict(list)
    for sample in rows:
        days[sample["date"]].append(sample)
    totals, annual = defaultdict(list), defaultdict(lambda: defaultdict(list))
    selections = defaultdict(int)
    selection_log = []
    for day, group in sorted(days.items()):
        if day.year not in years:
            continue
        choice = choose(rows, day, direction)
        selections[choice["rule"] if choice else "abstain"] += 1
        if choice:
            selection_log.append({"date": day.isoformat(), **choice})
        for sample in group:
            active = choice is not None
            output = {"candidate": active and sample["flags"][choice["rule"]],
                      "previous": sample["flags"]["baseline"],
                      "previous_active_dates": active and sample["flags"]["baseline"]}
            for name, selected in output.items():
                pair = (sample, direction if selected else None)
                totals[name].append(pair)
                annual[day.year][name].append(pair)
    names = ("candidate", "previous", "previous_active_dates")
    folds = [{"year": year, **{name: backtest.metrics(annual[year][name], direction) for name in names}}
             for year in years]
    return {"test_n": len(totals["candidate"]),
            **{name: backtest.metrics(totals[name], direction) for name in names},
            "selection_counts_by_signal_date": dict(selections), "selection_log": selection_log, "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    pse = json.loads(fv.DATA.read_text(encoding="utf-8"))
    raw = json.loads(extended.DATA.read_text(encoding="utf-8"))
    names = [symbol for symbol, kind in raw["universe"].items() if kind == "fund"]
    funds = dict(raw)
    funds["bars"] = {symbol: raw["bars"][symbol] for symbol in names if symbol in raw["bars"]}
    report = {"method": "On each signal date select among fixed subsets of the actual PSE bullish label or the previous bearish fund momentum/contrarian candidate, using the prior 36 months' reconstructed calls whose outcomes completed strictly before the signal. Require >=30 calls, >=6 months, >=8 symbols, >=51% correct and >=1 percentage point over that prior baseline's accuracy in the same historical window, otherwise abstain. Select highest historical hit rate, tie-break by coverage and fixed order. PSE label uses app classifier and 90-day window; funds use Yahoo 3-month window and require six- and twelve-month history. Peer returns use previous local dates. First monthly close to first close on or after three calendar months within ten days; ties are misses. Test 2020-2026. Comparisons use same eligible population; selected calls differ.",
              "limitations": ["Exploratory historical research after repeatedly examining these years. No untouched or prospective evaluation; multiple variants and research selection undermine naive confidence intervals.",
                              "Prior local-date peer closes may not have been available at signal time. Present-day listings and outcome-availability filtering cause survivorship and selection bias; missing and pending outcomes are not scored.",
                              "Overlapping horizons and market shocks make observations correlated. Raw prices may be revised; same-close execution, dividends, fees, taxes and slippage are not modeled. Funds include other ETPs. Not deployed."],
              "markets": {}}
    for name, data, direction, builder in (("PSE", pse, "bullish", prior.pse_observations),
                                          ("fund", funds, "bearish", targeted.observations)):
        print(f"Evaluating {name}: {len(data['bars'])} histories", flush=True)
        samples, skipped = builder(data)
        zones = data.get("timezones", {}) if name == "fund" else {s: data.get("timezones", {}).get(s, "Asia/Manila") for s in data["bars"]}
        rows = reconstruct(samples, relative.prepare_bars(data["bars"], zones), direction)
        result = evaluate_rows(rows, direction)
        result.update({"requested": len(data["universe"]) if name == "PSE" else len(names),
                       "received": len(data["bars"]), "skipped": skipped})
        report["markets"][name] = result
        print(json.dumps({key: result[key] for key in ("test_n", "candidate", "previous", "previous_active_dates")}), flush=True)
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
