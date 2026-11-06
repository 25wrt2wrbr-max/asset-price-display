#!/usr/bin/env python3
"""Exploratory market-benchmark-aware directional forecasts, not deployed.

Daily benchmark bars are lagged to a prior calendar date, to avoid assuming
that a benchmark close was known at another instrument's signal time. Model
features, thresholds and annual tests are chronological; the historical test
period is nevertheless reused research, not an independent or prospective test.
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

REPORT = fv.ROOT / "research" / "benchmark-forecast-research.json"
ADAPTIVE_REPORT = fv.ROOT / "research" / "adaptive-forecast-research.json"
BENCHMARKS = {"currency": "EURUSD=X", "us_equity": "SPY", "crypto": "BTC-USD"}
MAX_STALE_DAYS = 7
MIN_BENCHMARK_BARS = 50


def benchmark_features(rows, timezone, day):
    """Prior completed date's ~3-month return, short return and volatility."""
    zone = ZoneInfo(timezone)
    dates = [dt.datetime.fromtimestamp(int(r[0]), zone).date() for r in rows]
    end = bisect.bisect_left(dates, day) - 1
    if end < 0 or (day - dates[end]).days > MAX_STALE_DAYS:
        return None
    start_day = fv.months_after(dates[end], -3)
    start = bisect.bisect_left(dates, start_day, 0, end + 1)
    prices = [float(row[2]) for row in rows[start:end + 1]]
    if len(prices) < MIN_BENCHMARK_BARS or any(not math.isfinite(x) or x <= 0 for x in prices):
        return None
    returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
    avg = sum(returns) / len(returns)
    return [math.log(prices[-1] / prices[0]), math.log(prices[-1] / prices[-21]),
            math.sqrt(sum((r - avg) ** 2 for r in returns) / len(returns))]


def augment(samples, direction, rows, timezone):
    local_samples = adaptive.add_local_features(samples, direction)
    cache = {}
    result = []
    for s in local_samples:
        day = s["date"]
        if day not in cache:
            cache[day] = benchmark_features(rows, timezone, day)
        extra = cache[day]
        if extra is None:
            continue
        entry = dict(s)
        entry["features"] = s["features"] + extra
        result.append(entry)
    return result


def evaluate_samples(samples, direction, prior_folds, adaptive_folds, years=adaptive.YEARS):
    old = {f["year"]: f.get("models", {}) for f in prior_folds}
    adapt = {f["year"]: f for f in adaptive_folds}
    new_calls, local_calls, old_calls, adaptive_calls, folds = [], [], [], [], []
    for year in years:
        start, end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        validation_start = dt.date(year - 2, 1, 1)
        fit_start = dt.date(year - 2 - adaptive.TRAIN_YEARS, 1, 1)
        fit = [s for s in samples if s["date"] >= fit_start and s["exit"] < validation_start]
        validation = [s for s in samples if validation_start <= s["date"] < start and s["exit"] < start]
        test = [s for s in samples if start <= s["date"] < end]
        trained = model.train(fit, direction)
        choice, diagnostics = adaptive.choose(trained, validation, direction)
        new = [(s, direction if choice and model.score(trained, s["features"]) >= choice["threshold"] else None) for s in test]
        local_run = [(s, direction if s["local_score"] >= local.CALL_THRESHOLD else None) for s in test]
        old_run = [(s, model.predict(old.get(year, {}), s["features"][:7])) for s in test]
        prior_adaptive = adapt.get(year, {})
        prior_choice, prior_model = prior_adaptive.get("selected"), prior_adaptive.get("model")
        adapt_run = [(s, direction if prior_choice and prior_model and model.score(prior_model, s["features"][:10]) >= prior_choice["threshold"] else None) for s in test]
        new_calls.extend(new)
        local_calls.extend(local_run)
        old_calls.extend(old_run)
        adaptive_calls.extend(adapt_run)
        fold = {"year": year, "fit_n": len(fit), "validation_n": len(validation), "test_n": len(test),
                "last_fit_exit": max((s["exit"] for s in fit), default=None).isoformat() if fit else None,
                "last_validation_exit": max((s["exit"] for s in validation), default=None).isoformat() if validation else None,
                "model": trained, "selected": choice, "diagnostics": diagnostics,
                "benchmark": backtest.metrics(new, direction),
                "asset_local": backtest.metrics(local_run, direction),
                "adaptive": backtest.metrics(adapt_run, direction),
                "prior": backtest.metrics(old_run, direction)}
        folds.append(fold)
        print(f"  {year}: benchmark {fold['benchmark']['n']} / {fold['benchmark']['hit_pct']}%; local {fold['asset_local']['n']} / {fold['asset_local']['hit_pct']}%", flush=True)
    return {"test_n": len(new_calls), "benchmark": backtest.metrics(new_calls, direction),
            "asset_local_same_eligible": backtest.metrics(local_calls, direction),
            "adaptive_same_eligible": backtest.metrics(adaptive_calls, direction),
            "prior_same_eligible": backtest.metrics(old_calls, direction),
            "abstained": sum(label is None for _, label in new_calls), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    prior = json.loads(targeted.BASELINE.read_text(encoding="utf-8"))
    adaptive_report = json.loads(ADAPTIVE_REPORT.read_text(encoding="utf-8"))
    report = {"method": "Same annual chronological fit/validation/test and thresholds as adaptive_forecast_research.py, with 3 additional benchmark features: previous-date benchmark 3-month and 20-bar returns and 3-month volatility. SPY, EURUSD=X and BTC-USD are proxies for US equities, currencies and crypto respectively; each benchmark close must be from a prior local calendar date and no more than 7 days old. Replay earlier models on the exact same eligible observations. A label forecasts close direction at 3 calendar months; unchanged prices are misses.",
              "limitations": ["Exploratory, repeatedly inspected retrospective test years: no independent or prospective holdout. Results cannot establish future accuracy and bootstrap intervals do not adjust for this research selection.",
                              "Benchmarks are coarse proxies, not causal features; cross-timezone timestamps may affect conservative daily alignment. Model excludes observations missing benchmark or local-history data and uses selected surviving listings.",
                              "Monthly observations overlap and assets share shocks; costs, dividends, taxes, slippage and same-close execution are not modeled. Yahoo crypto is not the Binance feed. Not deployed or validated for intraday/stale inputs."],
              "benchmarks": BENCHMARKS, "markets": {}}
    for market, direction in targeted.TASKS.items():
        symbol = BENCHMARKS[market]
        if symbol not in raw["bars"] or symbol not in raw["timezones"]:
            raise ValueError(f"Missing benchmark {symbol}; refusing to fabricate inputs")
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {market} {direction}, benchmark {symbol}", flush=True)
        samples, skipped = targeted.observations(subset)
        augmented = augment(samples, direction, raw["bars"][symbol], raw["timezones"][symbol])
        result = evaluate_samples(augmented, direction, prior["markets"][market]["folds"], adaptive_report["markets"][market]["folds"])
        result.update({"received": len(subset["bars"]), "observation_n": len(samples),
                       "benchmark_and_local_eligible_n": len(augmented), "skipped": skipped})
        report["markets"][market] = result
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {key: v[key] for key in ("test_n", "benchmark", "asset_local_same_eligible", "adaptive_same_eligible", "prior_same_eligible", "abstained")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
