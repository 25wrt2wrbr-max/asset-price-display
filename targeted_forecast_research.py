#!/usr/bin/env python3
"""Research targeted 3-month price-direction rules with longer history.

This is not a live classifier. For each market and test year, learn fixed-rule
thresholds on older data, choose a candidate on a disjoint two-year validation
period, and test on the subsequent year. Prior experiments have inspected the
test years, so these are exploratory walk-forward results, not an untouched
holdout. Requires the saved market-history-extended.json and prior report.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
from collections import defaultdict
from zoneinfo import ZoneInfo

import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts
import onset

REPORT = fv.ROOT / "research" / "targeted-forecast-research.json"
BASELINE = fv.ROOT / "research" / "market-specific-exploratory.json"
TASKS = {"currency": "bearish", "us_equity": "bearish", "crypto": "bullish"}
YEARS = range(2020, 2027)
QUANTILES = (.50, .75, .90)
MIN_FIT = 200
MIN_VALIDATION = 100
MIN_MONTHS = 9
MIN_SYMBOLS = 10
# Scores are rank features, not calibrated probabilities. Fixed before testing.
RULES = ("momentum", "reversal", "short_momentum", "short_reversal",
         "six_month", "six_month_reversal", "year_momentum", "year_reversal",
         "low_volatility", "high_volatility", "trend_agreement", "trend_reversal")


def rule_values(window, six_return, year_return):
    """Compute dimensionless ranks using only information available at signal."""
    base = market_forecasts.features(window)
    score, ret5, ret20, ret3, vol, pos, _ = base
    return {"momentum": score, "reversal": -score,
            "short_momentum": ret20, "short_reversal": -ret20,
            "six_month": six_return, "six_month_reversal": -six_return,
            "year_momentum": year_return, "year_reversal": -year_return,
            "low_volatility": -vol, "high_volatility": vol,
            "trend_agreement": score + math.tanh(3 * six_return),
            "trend_reversal": -score - math.tanh(3 * six_return)}


def reference(dates, closes, index, months):
    target = fv.months_after(dates[index], -months)
    j = bisect.bisect_right(dates, target, 0, index) - 1
    if j < 0 or (target - dates[j]).days > fv.MAX_DELAY:
        return None
    if not math.isfinite(closes[j]) or closes[j] <= 0:
        return None
    return math.log(closes[index] / closes[j])


def observations(data):
    samples, skipped = [], defaultdict(int)
    for symbol, rows in sorted(data["bars"].items()):
        zone = ZoneInfo(data.get("timezones", {}).get(symbol, "UTC"))
        stamps = [int(r[0]) for r in rows]
        closes = [float(r[2]) for r in rows]
        dates = [dt.datetime.fromtimestamp(t, zone).date() for t in stamps]
        seen = set()
        for i, day in enumerate(dates):
            month = day.year, day.month
            if month in seen:
                continue
            seen.add(month)
            if day.year < 2010:
                continue
            target = fv.months_after(day, 3)
            end = bisect.bisect_left(dates, target, lo=i + 1)
            if end >= len(rows) or (dates[end] - target).days > fv.MAX_DELAY:
                skipped["missing_outcome"] += 1
                continue
            cutoff = onset.months_back(stamps[i], 3)
            start = bisect.bisect_left(stamps, cutoff, 0, i + 1)
            if i - start + 1 < fv.MIN_WINDOW_BARS:
                skipped["short_window"] += 1
                continue
            try:
                window = closes[start:i + 1]
                current = closes[i]
                if not math.isfinite(current) or current <= 0 or not math.isfinite(closes[end]) or closes[end] <= 0:
                    raise ValueError("invalid close")
                six = reference(dates, closes, i, 6)
                year = reference(dates, closes, i, 12)
                if six is None or year is None:
                    skipped["insufficient_long_history"] += 1
                    continue
                features = market_forecasts.features(window)
                values = rule_values(window, six, year)
            except (ValueError, OverflowError):
                skipped["invalid_price"] += 1
                continue
            samples.append({"symbol": symbol, "date": day, "exit": dates[end],
                            "features": features, "rules": values,
                            "outcome": (closes[end] > current) - (closes[end] < current)})
    return samples, dict(skipped)


def select(training, validation, direction):
    """Pick best validation precision among fixed historical-score quantiles.

    The minimum coverage and required improvement over the validation base rate
    apply before the later test. This gate is heuristic, not a confidence bound.
    """
    if len(training) < MIN_FIT or len(validation) < MIN_VALIDATION:
        return None, []
    target = 1 if direction == "bullish" else -1
    base = sum(s["outcome"] == target for s in validation) / len(validation)
    candidates = []
    for name in RULES:
        ordered = sorted(s["rules"][name] for s in training)
        for quantile in QUANTILES:
            threshold = ordered[min(len(ordered) - 1, int(quantile * len(ordered)))]
            chosen = [s for s in validation if s["rules"][name] >= threshold]
            n = len(chosen)
            months = len({(s["date"].year, s["date"].month) for s in chosen})
            symbols = len({s["symbol"] for s in chosen})
            hit_rate = sum(s["outcome"] == target for s in chosen) / n if n else 0.
            eligible = n >= max(MIN_VALIDATION, math.ceil(len(validation) * .10)) and months >= MIN_MONTHS and symbols >= MIN_SYMBOLS
            candidates.append({"rule": name, "quantile": quantile, "threshold": threshold,
                               "n": n, "months": months, "symbols": symbols,
                               "hit_pct": round(100 * hit_rate, 2) if n else None,
                               "base_pct": round(100 * base, 2),
                               "eligible": eligible,
                               "qualifies": eligible and hit_rate >= .53 and hit_rate >= base + .02})
    winners = [c for c in candidates if c["qualifies"]]
    # Maximizing across 36 rules/thresholds is vulnerable to selection bias;
    # all candidates are recorded and test performance is reported separately.
    return max(winners, key=lambda c: (c["hit_pct"], c["n"])) if winners else None, candidates


def baseline_predict(sample, models):
    return market_forecasts.predict(models, sample["features"])


def evaluate_samples(samples, market, direction, baseline_folds, years=YEARS):
    folds, calls, old_calls = [], [], []
    previous_by_year = {f["year"]: f for f in baseline_folds}
    for year in years:
        start, end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        validation_start = dt.date(year - 2, 1, 1)
        training = [s for s in samples if s["exit"] < validation_start]
        validation = [s for s in samples if validation_start <= s["date"] < start and s["exit"] < start]
        test = [s for s in samples if start <= s["date"] < end]
        winner, diagnostics = select(training, validation, direction)
        annual = [(s, direction if winner and s["rules"][winner["rule"]] >= winner["threshold"] else None) for s in test]
        old_models = previous_by_year.get(year, {}).get("models", {})
        old_annual = [(s, baseline_predict(s, old_models)) for s in test]
        calls.extend(annual)
        old_calls.extend(old_annual)
        folds.append({"year": year, "fit_n": len(training), "validation_n": len(validation), "test_n": len(test),
                      "last_fit_exit": max((s["exit"] for s in training), default=None).isoformat() if training else None,
                      "last_validation_exit": max((s["exit"] for s in validation), default=None).isoformat() if validation else None,
                      "selected": winner, "validation_candidates": diagnostics,
                      "new": backtest.metrics(annual, direction),
                      "prior": backtest.metrics(old_annual, direction)})
        print(f"  {year} {market}: new {folds[-1]['new']['n']} / {folds[-1]['new']['hit_pct']}%; prior {folds[-1]['prior']['n']} / {folds[-1]['prior']['hit_pct']}%", flush=True)
    return {"test_n": len(calls), "new": backtest.metrics(calls, direction),
            "prior_same_eligible_samples": backtest.metrics(old_calls, direction),
            "abstained": sum(label is None for _, label in calls), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    report = {"method": "Separate fixed rule families for each requested market and direction. Features use the same 3-month Yahoo chart window plus 6- and 12-month past reference prices. For each test year, derive rule thresholds from training outcomes completed before a disjoint two-year validation window. Select by validation hit rate, subject to >=53%, >=2 percentage points above its validation base rate, and minimum coverage. Test on the following year; later outcomes never affect that year's selected rule. Comparison replays the previous model on identical eligible observations. Target is close on or after 3 calendar months, up to 10 days late; ties are misses.",
              "limitations": ["Exploratory experiment; related research examined these years. 36 candidate rules/thresholds create substantial multiple-selection bias; results are not an independent holdout or prospective evidence.",
                              "Selected instruments are current listings, not a historical point-in-time universe; delistings are largely absent. Outcomes overlap and share market shocks. Approximate intervals do not correct for selection.",
                              "An extra year of history and up-to-date 6/12-month references are required; excluded data changes the evaluation population. Replayed prior metrics use the same eligible population and years but may differ from earlier published figures.",
                              "Yahoo crypto differs from the app's Binance data. No fees, dividends, taxes, slippage, or executable close are assumed. Live data, unfinished bars, and stale data are not validated. No app labels are changed."],
              "markets": {}}
    for market, direction in TASKS.items():
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {market} {direction}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = observations(subset)
        result = evaluate_samples(samples, market, direction, baseline["markets"][market]["folds"])
        result.update({"received": len(subset["bars"]), "requested": len(names), "skipped": skipped})
        report["markets"][market] = result
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {key: v[key] for key in ("test_n", "new", "prior_same_eligible_samples", "abstained")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
