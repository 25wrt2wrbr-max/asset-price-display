#!/usr/bin/env python3
"""Explore filters on current PSE bullish labels and bearish fund calls.

All reported outcomes are historical and repeatedly inspected. These are not
live forecasts; the existing shared trend classifier is not changed.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
from collections import defaultdict
from zoneinfo import ZoneInfo

import asset_local_forecast_research as local
import forecast_extended_validation as extended
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts
import onset
import regime_gate_forecast_research as regime
import relative_forecast_research as relative
import targeted_forecast_research as targeted
import trend_v1 as trend  # frozen: research models were fitted on its score scale

REPORT = fv.ROOT / "research" / "pse-bull-fund-bear-research.json"
YEARS = range(2020, 2027)
PSE_RULES = ("bull", "bull_strong", "bull_local", "bull_peer_momentum",
             "bull_local_peer_momentum", "bull_low_volatility")
FUND_RULES = ("momentum_contrarian", "local", "local_momentum", "local_reversal",
              "reversal_contrarian", "weak_trend", "strong_trend")
MIN_CALLS = 50
MIN_MONTHS = 6
MIN_SYMBOLS = 10
MIN_RATE = .51
MIN_LIFT = .01


def pse_observations(data):
    """PSE window and exact app label, with completed 3-calendar-month outcome."""
    result, skipped = [], defaultdict(int)
    for symbol, rows in sorted(data["bars"].items()):
        zone = ZoneInfo(data.get("timezones", {}).get(symbol, "Asia/Manila"))
        stamps = [int(r[0]) for r in rows]
        closes = [float(r[2]) for r in rows]
        dates = [dt.datetime.fromtimestamp(t, zone).date() for t in stamps]
        seen = set()
        for i, day in enumerate(dates):
            month = day.year, day.month
            if month in seen:
                continue
            seen.add(month)
            indices = onset.window(stamps, i, stamps[i])
            if len(indices) < fv.MIN_WINDOW_BARS:
                skipped["short_window"] += 1
                continue
            target = fv.months_after(day, 3)
            end = bisect.bisect_left(dates, target, lo=i + 1)
            if end >= len(rows) or (dates[end] - target).days > fv.MAX_DELAY:
                skipped["missing_outcome"] += 1
                continue
            try:
                prices = [closes[j] for j in indices]
                if not all(math.isfinite(x) and x > 0 for x in prices + [closes[end]]):
                    raise ValueError("invalid price")
                features = market_forecasts.features(prices)
                call = trend.classify(prices)
            except (ValueError, OverflowError):
                skipped["invalid_price"] += 1
                continue
            result.append({"symbol": symbol, "date": day, "exit": dates[end],
                           "features": features, "app_label": call["label"],
                           "outcome": (closes[end] > closes[i]) - (closes[end] < closes[i])})
    return result, dict(skipped)


def make_flags(sample, direction, local_score, rank, gate):
    own = local_score is not None and local_score >= local.CALL_THRESHOLD
    score, _, _, _, vol, _, _ = sample["features"]
    if direction == "bullish":
        bull = sample["app_label"] == "bullish"
        strong = score >= trend.STRONG_THRESHOLD
        momentum = rank is not None and rank >= .75
        return {"bull": bull, "bull_strong": bull and strong,
                "bull_local": bull and own, "bull_peer_momentum": bull and momentum,
                "bull_local_peer_momentum": bull and own and momentum,
                "bull_low_volatility": bull and vol <= .015}
    momentum = rank is not None and rank <= .25
    reversal = rank is not None and rank >= .75
    contra = gate is not None and gate < regime.GATE_THRESHOLD
    return {"momentum_contrarian": own and momentum and contra,
            "local": own, "local_momentum": own and momentum,
            "local_reversal": own and reversal, "reversal_contrarian": own and reversal and contra,
            "weak_trend": score <= -.25, "strong_trend": score >= .25}


def reconstruct(samples, prepared, direction):
    by_symbol = defaultdict(list)
    for sample in samples:
        by_symbol[sample["symbol"]].append(sample)
    peers, gates, result = {}, {}, []
    for sample in samples:
        day = sample["date"]
        if day not in peers:
            peers[day] = relative.peer_returns(prepared, day)
            gates[day] = regime.market_gate(samples, day, direction) if direction == "bearish" else None
        estimate = local.estimate(by_symbol[sample["symbol"]], sample, direction)
        extra = relative.relative_features(sample, peers[day])
        rank = extra[1] if extra is not None else None
        entry = dict(sample)
        entry["flags"] = make_flags(sample, direction, estimate["score"] if estimate else None,
                                    rank, gates[day])
        result.append(entry)
    return result


def choose(validation, rules, direction):
    """Choose with earlier outcomes only; compare PSE filters to bullish labels."""
    target = 1 if direction == "bullish" else -1
    base = [s for s in validation if s["flags"]["bull"]] if direction == "bullish" else validation
    if not base:
        return None, []
    base_rate = sum(s["outcome"] == target for s in base) / len(base)
    diagnostics = []
    for name in rules:
        chosen = [s for s in validation if s["flags"][name]]
        n = len(chosen)
        successes = sum(s["outcome"] == target for s in chosen)
        months = len({(s["date"].year, s["date"].month) for s in chosen})
        symbols = len({s["symbol"] for s in chosen})
        rate = successes / n if n else 0.
        qualifies = (n >= MIN_CALLS and months >= MIN_MONTHS and symbols >= MIN_SYMBOLS
                     and rate >= MIN_RATE and rate >= base_rate + MIN_LIFT)
        diagnostics.append({"rule": name, "n": n, "correct": successes,
                            "months": months, "symbols": symbols,
                            "hit_pct": round(100 * rate, 2) if n else None,
                            "base_pct": round(100 * base_rate, 2), "qualifies": qualifies})
    passing = [item for item in diagnostics if item["qualifies"]]
    winner = max(passing, key=lambda x: (x["correct"] / x["n"], x["n"])) if passing else None
    return winner, diagnostics


def evaluate_rows(rows, direction, years=YEARS):
    rules = PSE_RULES if direction == "bullish" else FUND_RULES
    previous = "bull" if direction == "bullish" else "momentum_contrarian"
    new_calls, previous_calls, all_calls, folds = [], [], [], []
    for year in years:
        start, end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        validation_start = dt.date(year - 2, 1, 1)
        validation = [s for s in rows if validation_start <= s["date"] < start and s["exit"] < start]
        test = [s for s in rows if start <= s["date"] < end]
        winner, diagnostics = choose(validation, rules, direction)
        candidate = [(s, direction if winner and s["flags"][winner["rule"]] else None) for s in test]
        old = [(s, direction if s["flags"][previous] else None) for s in test]
        baseline = [(s, direction) for s in test]
        new_calls.extend(candidate)
        previous_calls.extend(old)
        all_calls.extend(baseline)
        fold = {"year": year, "validation_n": len(validation),
                "latest_validation_exit": max((s["exit"] for s in validation), default=None).isoformat() if validation else None,
                "choice": winner, "validation_diagnostics": diagnostics,
                "candidate": backtest.metrics(candidate, direction),
                "previous": backtest.metrics(old, direction),
                "always_direction": backtest.metrics(baseline, direction)}
        folds.append(fold)
        print(f"  {year}: {winner['rule'] if winner else 'abstain'}; {fold['candidate']['n']} calls", flush=True)
    return {"test_n": len(new_calls), "candidate": backtest.metrics(new_calls, direction),
            "previous": backtest.metrics(previous_calls, direction),
            "always_direction": backtest.metrics(all_calls, direction), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    pse = json.loads(fv.DATA.read_text(encoding="utf-8"))
    raw = json.loads(extended.DATA.read_text(encoding="utf-8"))
    names = [symbol for symbol, kind in raw["universe"].items() if kind == "fund"]
    funds = dict(raw)
    funds["bars"] = {symbol: raw["bars"][symbol] for symbol in names if symbol in raw["bars"]}
    report = {"method": "Reconstruct candidate filters using only signal-time chart features, prior completed outcomes, and previous-local-date peer bars. PSE candidate calls are always a subset of the actual existing bullish app label. Annual selection uses only validation signals in the preceding two years whose outcomes complete strictly before the test year, minimum 50 calls, six months, ten symbols, >=51% accuracy and >=1 point above validation baseline; otherwise abstain. Baseline for PSE is current bullish app labels, for funds always-down. Test 2020-2026, first monthly close to first close on or after three calendar months within 10 days; ties are incorrect. PSE >=50 bars; funds also require 6- and 12-month price references, matching the earlier bearish fund comparison. Previous fund rule is local score >=55%, bottom peer-return quartile, and market gate below 50%. Prior and new calls differ.",
              "limitations": ["Repeatedly inspected retrospective data; not an untouched or prospective holdout. Candidate and threshold search is not accounted for by bootstrap intervals.",
                              "Missing/pending outcomes are excluded, and samples were constructed using outcome availability. Current selected listings omit most delisted assets; corporate actions and ticker identity are unverified.",
                              "Previous-local-date peer bars do not guarantee actual cross-timezone availability. A signal-close entry may not be executable; returns exclude dividends, fees, slippage and tax.",
                              "Overlapping signals and common shocks are not independent. Funds include exchange-traded products beyond conventional ETFs. Research only; no deployment or change to current trend labels."],
              "markets": {}}
    for name, data, direction, builder in (("PSE", pse, "bullish", pse_observations),
                                          ("fund", funds, "bearish", targeted.observations)):
        print(f"Evaluating {name}: {len(data['bars'])} histories", flush=True)
        samples, skipped = builder(data)
        zones = data.get("timezones", {}) if name == "fund" else {s: data.get("timezones", {}).get(s, "Asia/Manila") for s in data["bars"]}
        rows = reconstruct(samples, relative.prepare_bars(data["bars"], zones), direction)
        result = evaluate_rows(rows, direction)
        result.update({"received": len(data["bars"]), "requested": len(data["universe"]) if name == "PSE" else len(names),
                       "observation_n": len(samples), "skipped": skipped})
        report["markets"][name] = result
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({m: {k: v[k] for k in ("test_n", "candidate", "previous", "always_direction")}
                      for m, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
