#!/usr/bin/env python3
"""Explore lower-restriction market-specific forecast candidates.

Separate binary models for each market/direction use earlier fit outcomes,
then select a threshold on an earlier, disjoint validation period. This uses
point accuracy rather than a confidence-bound gate. The subsequent historical
test is exploratory and has already been inspected in related studies; do not
interpret its rates as prospective probabilities or deploy it automatically.
"""
from __future__ import annotations

import datetime as dt
import json

import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts as model

REPORT = fv.ROOT / "research" / "market-specific-exploratory.json"
YEARS = range(2016, 2027)
# Quantiles of validation scores, chosen before this experiment. No test data
# contributes to the thresholds. Cases tied at a threshold are all included.
QUANTILES = (0.0, 0.5, 0.75, 0.90, 0.95)
MIN_CASES = 50
MIN_MONTHS = 6
MIN_SYMBOLS = 10


def threshold_diagnostics(fitted, validation):
    """Find the widest validation-qualified group; retain rejected diagnostics."""
    if fitted is None or not validation:
        return None, []
    scored = sorted((model.score(fitted, s["features"]), index)
                    for index, s in enumerate(validation))
    target = 1 if fitted["direction"] == "bullish" else -1
    diagnostics = []
    winner = None
    for quantile in QUANTILES:
        threshold = scored[min(len(scored) - 1, int(quantile * len(scored)))][0]
        selected = [validation[index] for score, index in scored if score >= threshold]
        months = len({(s["date"].year, s["date"].month) for s in selected})
        symbols = len({s["symbol"] for s in selected})
        n = len(selected)
        hit_rate = sum(s["outcome"] == target for s in selected) / n
        eligible = n >= MIN_CASES and months >= MIN_MONTHS and symbols >= MIN_SYMBOLS
        item = {"quantile": quantile, "threshold": threshold, "n": n, "months": months,
                "symbols": symbols, "hit_pct": round(100 * hit_rate, 2),
                "eligible": eligible, "qualifies": eligible and hit_rate >= .51}
        diagnostics.append(item)
        if item["qualifies"] and winner is None:
            winner = item
    return winner, diagnostics


def evaluate_samples(samples, directions, years=YEARS):
    folds, calls = [], []
    for year in years:
        start = dt.date(year, 1, 1)
        end = dt.date(year + 1, 1, 1)
        validation_start = dt.date(year - 2, 1, 1)
        training = [s for s in samples if s["exit"] < validation_start]
        validation = [s for s in samples if validation_start <= s["date"] < start and s["exit"] < start]
        test = [s for s in samples if start <= s["date"] < end]
        fitted = {}
        diagnostics = {}
        for direction in directions:
            trained = model.train(training, direction)
            winner, choices = threshold_diagnostics(trained, validation)
            diagnostics[direction] = {"thresholds": choices, "selected": winner}
            if trained is not None and winner is not None:
                trained["validation"] = winner
                fitted[direction] = trained
            else:
                fitted[direction] = None
        annual = [(s, model.predict(fitted, s["features"])) for s in test]
        calls.extend(annual)
        folds.append({"year": year, "fit_n": len(training), "validation_n": len(validation),
                      "test_n": len(test),
                      "last_fit_exit": max((s["exit"] for s in training), default=None).isoformat() if training else None,
                      "last_validation_exit": max((s["exit"] for s in validation), default=None).isoformat() if validation else None,
                      "models": fitted, "diagnostics": diagnostics,
                      "directions": {d: backtest.metrics(annual, d) for d in directions},
                      "abstained": sum(label is None for _, label in annual)})
        print(f"  {year}: " + ", ".join(f"{d} {folds[-1]['directions'][d]['n']} calls" for d in directions), flush=True)
    return {"test_n": len(calls), "directions": {d: backtest.metrics(calls, d) for d in directions},
            "abstained": sum(label is None for _, label in calls), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    report = {"method": "Separate regularized logistic model per market and direction. In each year train on outcomes completed before a two-year validation period. Try fixed score quantiles on validation, select the highest-coverage candidate with >=51% point accuracy, >=50 observations, >=6 months, and >=10 instruments; then test the subsequent year with no tuning on its outcomes. Conflicting directions abstain. Signal is first monthly close; target is first close on or after three calendar months, at most 10 days late. Ties are failures.",
              "limitations": ["Exploratory retrospective experiment: related tests already inspected these years. Point-based selection and trying several thresholds introduce selection bias; there is no untouched holdout.",
                              "A 51% validation point estimate is not evidence of >51% future accuracy. Bootstrap intervals on test data are approximate, overlapping observations share shocks, and model selection is not accounted for.",
                              "Today-selected symbols generally omit delisted assets, causing survivorship bias. Price histories can be revised; no dividends, fees, tax, slippage or executable entry assumed.",
                              "Crypto uses Yahoo, not the app's Binance bars. No funds or bond yields are covered. Live stale or unfinished daily bars are untested. The app is unchanged."],
              "markets": {}}
    for category, directions in backtest.TASKS.items():
        if category == "PSE":
            subset = json.loads(fv.DATA.read_text(encoding="utf-8"))
        else:
            names = [s for s, kind in raw["universe"].items() if kind == category]
            subset = dict(raw)
            subset["universe"] = names
            subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {category}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = backtest.observations(subset)
        result = evaluate_samples(samples, directions)
        result.update({"received": len(subset["bars"]), "requested": len(subset["universe"]), "skipped": skipped})
        report["markets"][category] = result
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: {k: v[k] for k in ("received", "test_n", "directions", "abstained")}
                      for key, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
