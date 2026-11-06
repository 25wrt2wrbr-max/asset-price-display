#!/usr/bin/env python3
"""Experimental refinement of the prior bearish US stock candidate.

Historical years were repeatedly examined. This is not a live forecast or
independent validation and does not modify the app's trend classifier.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

import asset_local_forecast_research as local
import bearish_forecast_research as prior
import forecast_extended_validation as extended
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts as model
import relative_forecast_research as relative
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "us-bearish-refinement-research.json"
YEARS = range(2020, 2027)
QUANTILES = (0., .25, .5, .75)
MIN_CASES = 20
MIN_MONTHS = 6
MIN_SYMBOLS = 5


def features(sample, local_score):
    score, r5, r20, ret, vol, position, unchanged = sample["features"]
    six, year = sample["rules"]["six_month"], sample["rules"]["year_momentum"]
    return [score, r5, r20, ret, vol, position, unchanged, local_score, six, year,
            score * score, r20 * r20, ret * ret, vol * score,
            local_score * ret, six * vol, year * vol]


def prepare(samples, prepared):
    """Rebuild prior calls and signal-time features from the PARA-free inputs."""
    by_symbol = defaultdict(list)
    for s in samples:
        by_symbol[s["symbol"]].append(s)
    rows = []
    for sample in prior.signal_flags(samples, prepared):
        if not sample["local_available"]:
            continue
        estimate = local.estimate(by_symbol[sample["symbol"]], sample, "bearish")
        row = dict(sample)
        row["model_features"] = features(sample, estimate["score"])
        rows.append(row)
    return rows


def select(fitted, validation):
    """Threshold only on historical calls from the previous bearish rule."""
    if fitted is None or not validation:
        return None, []
    scores = sorted((model.score(fitted, s["model_features"]), i) for i, s in enumerate(validation))
    base = sum(s["outcome"] == -1 for s in validation) / len(validation)
    diagnostics = []
    for quantile in QUANTILES:
        threshold = scores[min(len(scores) - 1, int(quantile * len(scores)))][0]
        chosen = [validation[i] for score, i in scores if score >= threshold]
        n = len(chosen)
        correct = sum(s["outcome"] == -1 for s in chosen)
        months = len({(s["date"].year, s["date"].month) for s in chosen})
        symbols = len({s["symbol"] for s in chosen})
        rate = correct / n if n else 0.
        qualified = (n >= MIN_CASES and months >= MIN_MONTHS and symbols >= MIN_SYMBOLS
                     and rate >= .51 and rate >= base + .01)
        diagnostics.append({"quantile": quantile, "threshold": threshold, "n": n,
                            "correct": correct, "months": months, "symbols": symbols,
                            "hit_pct": round(rate * 100, 2) if n else None,
                            "baseline_pct": round(base * 100, 2), "qualifies": qualified})
    passing = [d for d in diagnostics if d["qualifies"]]
    return (max(passing, key=lambda d: (d["correct"] / d["n"], d["n"])) if passing else None), diagnostics


def evaluate(rows, years=YEARS):
    candidates, previous, active, folds = [], [], [], []
    for year in years:
        start, end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
        validation_start = dt.date(year - 2, 1, 1)
        fit = [s for s in rows if s["exit"] < validation_start]
        validation = [s for s in rows if validation_start <= s["date"] < start
                      and s["exit"] < start and s["flags"]["momentum_contrarian"]]
        test = [s for s in rows if start <= s["date"] < end]
        fitted = model.train([dict(s, features=s["model_features"]) for s in fit], "bearish")
        choice, diagnostics = select(fitted, validation)
        new_calls, old_calls, active_calls = [], [], []
        for s in test:
            old = s["flags"]["momentum_contrarian"]
            selected = old and choice is not None and model.score(fitted, s["model_features"]) >= choice["threshold"]
            new_calls.append((s, "bearish" if selected else None))
            old_calls.append((s, "bearish" if old else None))
            active_calls.append((s, "bearish" if old and choice else None))
        candidates.extend(new_calls)
        previous.extend(old_calls)
        active.extend(active_calls)
        fold = {"year": year, "fit_n": len(fit), "validation_n": len(validation),
                "latest_fit_exit": max((s["exit"] for s in fit), default=None).isoformat() if fit else None,
                "latest_validation_exit": max((s["exit"] for s in validation), default=None).isoformat() if validation else None,
                "model": fitted, "choice": choice, "validation_diagnostics": diagnostics,
                "candidate": backtest.metrics(new_calls, "bearish"),
                "previous": backtest.metrics(old_calls, "bearish")}
        folds.append(fold)
        print(f"{year}: {fold['candidate']['n']} calls, {fold['candidate']['hit_pct']}%", flush=True)
    return {"test_n": len(candidates), "candidate": backtest.metrics(candidates, "bearish"),
            "previous": backtest.metrics(previous, "bearish"),
            "previous_active_years": backtest.metrics(active, "bearish"), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(extended.DATA.read_text(encoding="utf-8"))
    names = [s for s, category in raw["universe"].items() if category == "us_equity" and s != "PARA"]
    subset = dict(raw)
    subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
    samples, skipped = targeted.observations(subset)
    prepared = relative.prepare_bars(subset["bars"], raw.get("timezones", {}))
    result = evaluate(prepare(samples, prepared))
    saved = json.loads((fv.ROOT / "research" / "us-symbol-sensitivity-research.json").read_text(encoding="utf-8"))["without_symbol"]
    old = saved["momentum_contrarian"]
    if (result["test_n"], result["previous"]["n"], result["previous"]["correct"]) != (saved["test_n"], old["n"], old["correct"]):
        raise ValueError("Prior US candidate replay differs from saved PARA-free result")
    result.update({"requested": len(names), "received": len(subset["bars"]), "skipped": skipped})
    report = {"method": "A regularized logistic model fits prior completed US observations using chart features, stock-local historical score, longer returns and fixed interactions. Each year select among score thresholds using only previous-rule bearish calls in the prior two years whose exits completed before test year; require 20 calls, 6 months, 5 symbols, >=51% hit and >=1 percentage point improvement over previous-rule validation calls, otherwise abstain. Test calls must also pass the previous momentum/contrarian local rule. Model fit outcomes end strictly before validation starts. Same 2020-2026 eligible sample and replay as prior US rule; PARA excluded from observations, market gate, and peer ranks. First monthly close versus first close on or after 3 calendar months, at most 10 days late; ties are misses.",
              "limitations": ["Exploratory after extensive repeated inspection, not an untouched or prospective test; model and threshold search create selection bias not included in intervals.",
                              "Selected current listings omit many delisted stocks; history may be revised or have ticker identity/corporate action errors. PARA exclusion was chosen after inspection. Pending and missing outcomes are excluded.",
                              "Peer previous local dates do not guarantee availability at the signal time. Overlapping calls and shared shocks are correlated; no costs, dividends, taxes, slippage or executable same-close entry. No app deployment."],
              "US": result}
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({k: result[k] for k in ("test_n", "candidate", "previous", "previous_active_years")}, indent=2))


if __name__ == "__main__":
    main()
