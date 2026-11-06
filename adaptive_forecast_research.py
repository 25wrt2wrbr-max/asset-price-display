#!/usr/bin/env python3
"""Evaluate adaptive asset-specific 3-month price-direction candidates.

Research only. Nested, yearly chronological fit/validation/test, with a
time-varying feature based on each asset's completed past outcomes. Past
experiments have inspected the evaluation years: this is exploratory, not
an untouched holdout, and it does not change the live classifier.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

import asset_local_forecast_research as local
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts as model
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "adaptive-forecast-research.json"
YEARS = range(2020, 2027)
QUANTILES = (0.0, .25, .50, .75, .90)
MIN_VALIDATION = 100
MIN_MONTHS = 9
MIN_SYMBOLS = 10
TRAIN_YEARS = 8


def add_local_features(samples, direction):
    """Attach local score, using outcomes strictly completed before each date."""
    by_symbol = defaultdict(list)
    for s in samples:
        by_symbol[s["symbol"]].append(s)
    augmented = []
    for s in samples:
        estimate = local.estimate(by_symbol[s["symbol"]], s, direction)
        if estimate is None:
            continue
        entry = dict(s)
        entry["local_score"] = estimate["score"]
        entry["features"] = s["features"] + [estimate["score"],
            s["rules"]["six_month"], s["rules"]["year_momentum"]]
        augmented.append(entry)
    return augmented


def choose(trained, validation, direction):
    """Choose threshold using only validation outcomes; ties are misses."""
    if trained is None or not validation:
        return None, []
    scored = sorted((model.score(trained, s["features"]), i) for i, s in enumerate(validation))
    target = 1 if direction == "bullish" else -1
    base = sum(s["outcome"] == target for s in validation) / len(validation)
    results = []
    for quantile in QUANTILES:
        threshold = scored[min(len(scored) - 1, int(quantile * len(scored)))][0]
        selected = [validation[i] for score, i in scored if score >= threshold]
        n = len(selected)
        months = len({(s["date"].year, s["date"].month) for s in selected})
        symbols = len({s["symbol"] for s in selected})
        rate = sum(s["outcome"] == target for s in selected) / n if n else 0.
        eligible = n >= max(MIN_VALIDATION, len(validation) * .10) and months >= MIN_MONTHS and symbols >= MIN_SYMBOLS
        results.append({"quantile": quantile, "threshold": threshold, "n": n,
                        "months": months, "symbols": symbols,
                        "hit_pct": round(100 * rate, 2) if n else None,
                        "base_pct": round(100 * base, 2),
                        "qualifies": eligible and rate >= .52 and rate >= base + .01})
    passing = [entry for entry in results if entry["qualifies"]]
    return max(passing, key=lambda r: (r["hit_pct"], r["n"])) if passing else None, results


def evaluate_samples(samples, direction, baseline_folds, years=YEARS):
    samples = add_local_features(samples, direction)
    prior = {f["year"]: f.get("models", {}) for f in baseline_folds}
    calls, local_calls, prior_calls, folds = [], [], [], []
    for year in years:
        start, end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        validation_start = dt.date(year - 2, 1, 1)
        fit_start = dt.date(year - 2 - TRAIN_YEARS, 1, 1)
        fit = [s for s in samples if s["date"] >= fit_start and s["exit"] < validation_start]
        validation = [s for s in samples if validation_start <= s["date"] < start and s["exit"] < start]
        test = [s for s in samples if start <= s["date"] < end]
        trained = model.train(fit, direction)
        selected, diagnostics = choose(trained, validation, direction)
        annual = [(s, direction if selected and model.score(trained, s["features"]) >= selected["threshold"] else None) for s in test]
        local_annual = [(s, direction if s["local_score"] >= local.CALL_THRESHOLD else None) for s in test]
        # The saved earlier model expects the original seven input features.
        old_annual = [(s, market_forecasts_predict(prior.get(year, {}), s["features"][:7])) for s in test]
        calls.extend(annual)
        local_calls.extend(local_annual)
        prior_calls.extend(old_annual)
        fold = {"year": year, "fit_n": len(fit), "validation_n": len(validation), "test_n": len(test),
                "last_fit_exit": max((s["exit"] for s in fit), default=None).isoformat() if fit else None,
                "last_validation_exit": max((s["exit"] for s in validation), default=None).isoformat() if validation else None,
                "model": trained, "selected": selected, "diagnostics": diagnostics,
                "adaptive": backtest.metrics(annual, direction),
                "asset_local": backtest.metrics(local_annual, direction),
                "prior": backtest.metrics(old_annual, direction)}
        folds.append(fold)
        print(f"  {year}: adaptive {fold['adaptive']['n']} / {fold['adaptive']['hit_pct']}%; local {fold['asset_local']['n']} / {fold['asset_local']['hit_pct']}%", flush=True)
    return {"test_n": len(calls), "adaptive": backtest.metrics(calls, direction),
            "asset_local_same_eligible": backtest.metrics(local_calls, direction),
            "prior_same_eligible": backtest.metrics(prior_calls, direction),
            "abstained": sum(label is None for _, label in calls), "folds": folds}


def market_forecasts_predict(models, features):
    return model.predict(models, features)


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    baseline = json.loads(targeted.BASELINE.read_text(encoding="utf-8"))
    report = {"method": "Separate regularized models per market/direction use chart price features, 6/12-month historical returns and a lagged asset-local score trained only on already completed outcomes. Fit on at most eight preceding years, choose among five thresholds on a disjoint two-year validation period (>=52% and >=1 percentage point above validation baseline; minimum counts), and test each subsequent year. Replay previous and asset-local candidates on the identical eligible observations. Calendar-three-month close-to-close direction; ties are misses.",
              "limitations": ["Exploratory: previous experiments already inspected these years and development choices changed in response. This is not untouched out-of-sample or prospective evidence.",
                              "Overlapping signals and common shocks reduce effective sample size; approximate bootstrap intervals do not include model or threshold-selection uncertainty.",
                              "Current listings, mostly excluding delisted assets, create survivorship bias. Asset-local eligibility requires prior observed outcomes and additional six/twelve-month prices, excluding new and illiquid assets.",
                              "Yahoo crypto differs from Binance. The same-close signal may not be executable; no fees, taxes, slippage or dividends. Live, stale and intraday data have not been validated; models are not deployed."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        symbols = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in symbols if s in raw["bars"]}
        print(f"Evaluating {market} {direction}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = targeted.observations(subset)
        result = evaluate_samples(samples, direction, baseline["markets"][market]["folds"])
        result.update({"received": len(subset["bars"]), "requested": len(symbols), "skipped": skipped})
        report["markets"][market] = result
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {key: v[key] for key in ("test_n", "adaptive", "asset_local_same_eligible", "prior_same_eligible", "abstained")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
