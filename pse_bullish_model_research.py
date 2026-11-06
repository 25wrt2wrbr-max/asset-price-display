#!/usr/bin/env python3
"""Test a selective Philippine bullish forecast, separate from app labels.

The same history has been inspected repeatedly; results are exploratory, not
independent validation. No current-trend classifier is modified.
"""
from __future__ import annotations

import datetime as dt
import json

import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts as model
import pse_bull_fund_bear_research as previous

REPORT = fv.ROOT / "research" / "pse-bullish-model-research.json"
YEARS = range(2020, 2027)
QUANTILES = (0., .25, .5, .75, .9)
MIN_CASES = 30
MIN_MONTHS = 6
MIN_SYMBOLS = 8
MIN_RATE = .51
MIN_LIFT = .01


def features(values):
    """Chart-window features plus fixed nonlinear interactions, no future data."""
    score, r5, r20, ret, vol, position, unchanged = values
    return values + [score * score, r20 * r20, ret * ret,
                     score * vol, r20 * vol, ret * vol,
                     position * vol, unchanged * vol]


def choose(trained, validation):
    """Select a score threshold on a strictly earlier bullish-only population."""
    if trained is None or not validation:
        return None, []
    scored = sorted((model.score(trained, s["model_features"]), i)
                    for i, s in enumerate(validation))
    base = sum(s["outcome"] == 1 for s in validation) / len(validation)
    diagnostics = []
    for quantile in QUANTILES:
        threshold = scored[min(len(scored) - 1, int(quantile * len(scored)))][0]
        selected = [validation[i] for score, i in scored if score >= threshold]
        n = len(selected)
        correct = sum(s["outcome"] == 1 for s in selected)
        months = len({(s["date"].year, s["date"].month) for s in selected})
        symbols = len({s["symbol"] for s in selected})
        rate = correct / n if n else 0.
        qualifies = (n >= MIN_CASES and months >= MIN_MONTHS and symbols >= MIN_SYMBOLS
                     and rate >= MIN_RATE and rate >= base + MIN_LIFT)
        diagnostics.append({"quantile": quantile, "threshold": threshold, "n": n,
                            "correct": correct, "months": months, "symbols": symbols,
                            "hit_pct": round(rate * 100, 2) if n else None,
                            "baseline_pct": round(base * 100, 2), "qualifies": qualifies})
    passing = [d for d in diagnostics if d["qualifies"]]
    return (max(passing, key=lambda d: (d["correct"] / d["n"], d["n"])) if passing else None), diagnostics


def evaluate(samples, years=YEARS):
    rows = []
    for sample in samples:
        row = dict(sample)
        row["model_features"] = features(sample["features"])
        rows.append(row)
    candidate, baseline, baseline_active, folds = [], [], [], []
    for year in years:
        start, end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        validation_start = dt.date(year - 2, 1, 1)
        # All groups are actual app bullish labels. Training targets use only
        # outcomes completed before the validation period begins.
        fit = [s for s in rows if s["app_label"] == "bullish" and s["exit"] < validation_start]
        validation = [s for s in rows if s["app_label"] == "bullish" and validation_start <= s["date"] < start and s["exit"] < start]
        test = [s for s in rows if start <= s["date"] < end]
        fitted = model.train([dict(s, features=s["model_features"]) for s in fit], "bullish")
        winner, diagnostics = choose(fitted, validation)
        current, reference, active = [], [], []
        for s in test:
            bull = s["app_label"] == "bullish"
            passed = bull and winner is not None and model.score(fitted, s["model_features"]) >= winner["threshold"]
            current.append((s, "bullish" if passed else None))
            reference.append((s, "bullish" if bull else None))
            active.append((s, "bullish" if bull and winner is not None else None))
        candidate.extend(current)
        baseline.extend(reference)
        baseline_active.extend(active)
        fold = {"year": year, "fit_n": len(fit), "validation_n": len(validation),
                "latest_fit_exit": max((s["exit"] for s in fit), default=None).isoformat() if fit else None,
                "latest_validation_exit": max((s["exit"] for s in validation), default=None).isoformat() if validation else None,
                "model": fitted, "selected": winner, "validation_diagnostics": diagnostics,
                "candidate": backtest.metrics(current, "bullish"),
                "app_bullish": backtest.metrics(reference, "bullish")}
        folds.append(fold)
        print(f"{year}: {fold['candidate']['n']} calls, {fold['candidate']['hit_pct']}%", flush=True)
    return {"test_n": len(candidate), "candidate": backtest.metrics(candidate, "bullish"),
            "app_bullish": backtest.metrics(baseline, "bullish"),
            "app_bullish_active_years": backtest.metrics(baseline_active, "bullish"), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    data = json.loads(fv.DATA.read_text(encoding="utf-8"))
    samples, skipped = previous.pse_observations(data)
    result = evaluate(samples)
    result.update({"requested": len(data["universe"]), "received": len(data["bars"]), "skipped": skipped})
    report = {"method": "Select a subset of actual app bullish labels. For each year fit regularized logistic regression on prior bullish observations whose outcomes finish before the two-year validation period. Select among fixed score quantiles on bullish validation observations with outcomes completed before test year, requiring >=30 calls, >=6 months, >=8 stocks, >=51% accuracy and >=1 percentage point over the validation bullish baseline; otherwise abstain. Features use the 90-day chart window, including fixed interactions. Test on first monthly close to first close on or after three calendar months, at most ten days late; unchanged is incorrect. Minimum 50 chart-window bars. Compare 2020-2026 eligible population and active test years; calls selected differ.",
              "limitations": ["The same years have been repeatedly examined and this is exploratory, not an untouched or prospective holdout. Threshold selection and feature choices introduce selection bias not covered by bootstrap intervals.",
                              "Current listed stocks omit delistings, eligible samples require observable outcomes, and historical data may be revised; missing and pending outcomes are excluded.",
                              "Monthly overlapping horizons and shared shocks are correlated. Prices do not represent realizable same-close entry, dividends, transaction costs, slippage or taxes. The app remains unchanged."],
              "PSE": result}
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({k: result[k] for k in ("test_n", "candidate", "app_bullish", "app_bullish_active_years")}, indent=2))


if __name__ == "__main__":
    main()
