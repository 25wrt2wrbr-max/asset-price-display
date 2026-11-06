#!/usr/bin/env python3
"""Exploratory relative-strength and breadth forecasts, not production code.

Peer features are constructed from raw bars, never from outcome-filtered
observations. Peer closes must predate the signal's calendar date. Yearly
model fitting and threshold selection use only previously completed outcomes.
The evaluation years were already inspected: this is not an independent test.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
from zoneinfo import ZoneInfo

import adaptive_forecast_research as adaptive
import asset_local_forecast_research as local
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts as model
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "relative-forecast-research.json"
MAX_STALE_DAYS = 7
MIN_PEERS = 10


def prepare_bars(bars, timezones):
    """Index raw bars independently of future outcome availability."""
    prepared = {}
    for symbol, rows in bars.items():
        zone = ZoneInfo(timezones.get(symbol, "UTC"))
        dates = [dt.datetime.fromtimestamp(int(r[0]), zone).date() for r in rows]
        prepared[symbol] = (dates, [float(r[2]) for r in rows])
    return prepared


def peer_returns(prepared, day):
    """Return prior-date 20-bar and calendar-3-month returns per symbol."""
    result = {}
    for symbol, (dates, prices) in prepared.items():
        i = bisect.bisect_left(dates, day) - 1
        if i < 20 or (day - dates[i]).days > MAX_STALE_DAYS:
            continue
        target = fv.months_after(dates[i], -3)
        j = bisect.bisect_left(dates, target, 0, i + 1)
        if i - j + 1 < fv.MIN_WINDOW_BARS:
            continue
        a, b, c = prices[i], prices[i - 20], prices[j]
        if not all(math.isfinite(v) and v > 0 for v in (a, b, c)):
            continue
        result[symbol] = (math.log(a / b), math.log(a / c))
    return result


def relative_features(sample, peers):
    """Rank current asset against other assets' strictly prior-date returns."""
    others = [returns for symbol, returns in peers.items() if symbol != sample["symbol"]]
    if len(others) < MIN_PEERS:
        return None
    ret20, ret3 = sample["features"][2:4]
    n = len(others)
    return [sum(x[0] < ret20 for x in others) / n,
            sum(x[1] < ret3 for x in others) / n,
            sum(x[1] > 0 for x in others) / n]


def augment(samples, direction, prepared):
    local_samples = adaptive.add_local_features(samples, direction)
    cache, result = {}, []
    for s in local_samples:
        day = s["date"]
        if day not in cache:
            cache[day] = peer_returns(prepared, day)
        extra = relative_features(s, cache[day])
        if extra is not None:
            entry = dict(s)
            entry["features"] = s["features"] + extra
            result.append(entry)
    return result


def evaluate_samples(samples, direction, adaptive_folds, years=adaptive.YEARS):
    prior = {f["year"]: f for f in adaptive_folds}
    calls, local_calls, adaptive_calls, folds = [], [], [], []
    for year in years:
        start, end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        validation_start = dt.date(year - 2, 1, 1)
        fit_start = dt.date(year - 2 - adaptive.TRAIN_YEARS, 1, 1)
        fit = [s for s in samples if s["date"] >= fit_start and s["exit"] < validation_start]
        validation = [s for s in samples if validation_start <= s["date"] < start and s["exit"] < start]
        test = [s for s in samples if start <= s["date"] < end]
        trained = model.train(fit, direction)
        choice, diagnostics = adaptive.choose(trained, validation, direction)
        old = prior.get(year, {})
        old_model, old_choice = old.get("model"), old.get("selected")
        new = [(s, direction if choice and model.score(trained, s["features"]) >= choice["threshold"] else None) for s in test]
        own = [(s, direction if s["local_score"] >= local.CALL_THRESHOLD else None) for s in test]
        earlier = [(s, direction if old_model and old_choice and model.score(old_model, s["features"][:10]) >= old_choice["threshold"] else None) for s in test]
        calls.extend(new)
        local_calls.extend(own)
        adaptive_calls.extend(earlier)
        fold = {"year": year, "fit_n": len(fit), "validation_n": len(validation), "test_n": len(test),
                "last_fit_exit": max((s["exit"] for s in fit), default=None).isoformat() if fit else None,
                "last_validation_exit": max((s["exit"] for s in validation), default=None).isoformat() if validation else None,
                "model": trained, "selected": choice, "diagnostics": diagnostics,
                "relative": backtest.metrics(new, direction), "asset_local": backtest.metrics(own, direction),
                "adaptive": backtest.metrics(earlier, direction)}
        folds.append(fold)
        print(f"  {year}: relative {fold['relative']['n']} / {fold['relative']['hit_pct']}%; local {fold['asset_local']['n']} / {fold['asset_local']['hit_pct']}%", flush=True)
    return {"test_n": len(calls), "relative": backtest.metrics(calls, direction),
            "asset_local_same_eligible": backtest.metrics(local_calls, direction),
            "adaptive_same_eligible": backtest.metrics(adaptive_calls, direction), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    previous_report = json.loads((fv.ROOT / "research" / "adaptive-forecast-research.json").read_text(encoding="utf-8"))
    report = {"method": "For each market and direction, augment adaptive features with cross-sectional 20-bar and 3-month relative-strength ranks and peer 3-month positive-return breadth. Peer values use raw closes strictly before the signal date, at most 7 days stale, and exclude the current asset; require 10 peers. Fit and validation use only completed outcomes, with the same annual rolling procedure and threshold selection as adaptive_forecast_research.py. Replay prior models on identical eligible signals. Ties in future price are misses.",
              "limitations": ["Exploratory and repeatedly inspected historical years; not an independent or prospective test. The model and feature choice are subject to research selection, not reflected in uncertainty intervals.",
                              "Peer universe consists of selected current listings, not point-in-time historical constituents; delisted assets are mostly absent. Availability of enough peers and asset-local history determines eligibility.",
                              "Outcomes overlap and market shocks are correlated. Signal close may not be executable; fees, taxes, dividends, and slippage are excluded. Yahoo crypto differs from Binance; no live classifier changed."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {market} {direction}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = targeted.observations(subset)
        augmented = augment(samples, direction, prepare_bars(subset["bars"], raw.get("timezones", {})))
        result = evaluate_samples(augmented, direction, previous_report["markets"][market]["folds"])
        result.update({"received": len(subset["bars"]), "requested": len(names), "observation_n": len(samples),
                       "relative_and_local_eligible_n": len(augmented), "skipped": skipped})
        report["markets"][market] = result
    # Exclusive creation protects an existing report even if another run finishes first.
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({k: {key: v[key] for key in ("test_n", "relative", "asset_local_same_eligible", "adaptive_same_eligible")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
