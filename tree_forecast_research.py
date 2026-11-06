#!/usr/bin/env python3
"""Exploratory shallow decision-tree forecasts; never used by the app.

Each market/direction gets its own yearly tree, fit only on completed past
outcomes. Its call threshold is picked on a later, disjoint validation period.
Previously examined evaluation years are exploratory, not an independent test.
"""
from __future__ import annotations

import datetime as dt
import json

import adaptive_forecast_research as adaptive
import asset_local_forecast_research as local
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts as model
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "tree-forecast-research.json"
MAX_DEPTH = 3
MIN_LEAF = 100
SPLIT_QUANTILES = (.25, .5, .75)


def train(samples, direction):
    """Fit a fixed-depth tree using binary squared-error split reduction."""
    if direction not in ("bullish", "bearish"):
        raise ValueError("unknown direction")
    if len(samples) < 2 * MIN_LEAF:
        return None
    width = len(samples[0]["features"])
    if any(len(s["features"]) != width for s in samples):
        raise ValueError("inconsistent feature lengths")
    target = 1 if direction == "bullish" else -1

    def grow(rows, depth):
        n = len(rows)
        wins = sum(s["outcome"] == target for s in rows)
        leaf = {"n": n, "wins": wins, "score": wins / n}
        if depth >= MAX_DEPTH or n < 2 * MIN_LEAF or wins in (0, n):
            return leaf
        parent = wins * (n - wins) / n
        best = None
        for feature in range(width):
            ordered = sorted(rows, key=lambda s: s["features"][feature])
            prefix = [0]
            for s in ordered:
                prefix.append(prefix[-1] + (s["outcome"] == target))
            for quantile in SPLIT_QUANTILES:
                i = int(n * quantile)
                if i < MIN_LEAF or n - i < MIN_LEAF:
                    continue
                left_value, right_value = ordered[i - 1]["features"][feature], ordered[i]["features"][feature]
                if left_value >= right_value:
                    continue
                lw, rw = prefix[i], wins - prefix[i]
                loss = lw * (i - lw) / i + rw * (n - i - rw) / (n - i)
                gain = parent - loss
                if gain > 1e-12 and (best is None or gain > best[0]):
                    best = (gain, feature, (left_value + right_value) / 2, ordered, i)
        if best is None:
            return leaf
        _, feature, threshold, ordered, i = best
        return {**leaf, "feature": feature, "threshold": threshold,
                "left": grow(ordered[:i], depth + 1), "right": grow(ordered[i:], depth + 1)}

    return grow(samples, 0)


def score(tree, features):
    while "feature" in tree:
        tree = tree["left"] if features[tree["feature"]] < tree["threshold"] else tree["right"]
    return tree["score"]


def choose(tree, validation, direction):
    """Use the same validation-only coverage and hit-rate gates as adaptive."""
    if tree is None or not validation:
        return None, []
    scored = sorted((score(tree, s["features"]), i) for i, s in enumerate(validation))
    target = 1 if direction == "bullish" else -1
    base = sum(s["outcome"] == target for s in validation) / len(validation)
    diagnostics = []
    for q in adaptive.QUANTILES:
        threshold = scored[min(len(scored) - 1, int(q * len(scored)))][0]
        selected = [validation[i] for value, i in scored if value >= threshold]
        n = len(selected)
        months = len({(s["date"].year, s["date"].month) for s in selected})
        symbols = len({s["symbol"] for s in selected})
        rate = sum(s["outcome"] == target for s in selected) / n
        eligible = n >= max(adaptive.MIN_VALIDATION, len(validation) * .10) and months >= adaptive.MIN_MONTHS and symbols >= adaptive.MIN_SYMBOLS
        diagnostics.append({"quantile": q, "threshold": threshold, "n": n,
                            "months": months, "symbols": symbols, "hit_pct": round(100 * rate, 2),
                            "base_pct": round(100 * base, 2),
                            "qualifies": eligible and rate >= .52 and rate >= base + .01})
    passing = [r for r in diagnostics if r["qualifies"]]
    return (max(passing, key=lambda r: (r["hit_pct"], r["n"])) if passing else None), diagnostics


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
        tree = train(fit, direction)
        choice, diagnostics = choose(tree, validation, direction)
        old = prior.get(year, {})
        old_model, old_choice = old.get("model"), old.get("selected")
        new = [(s, direction if choice and score(tree, s["features"]) >= choice["threshold"] else None) for s in test]
        own = [(s, direction if s["local_score"] >= local.CALL_THRESHOLD else None) for s in test]
        earlier = [(s, direction if old_model and old_choice and model.score(old_model, s["features"][:10]) >= old_choice["threshold"] else None) for s in test]
        calls.extend(new)
        local_calls.extend(own)
        adaptive_calls.extend(earlier)
        fold = {"year": year, "fit_n": len(fit), "validation_n": len(validation), "test_n": len(test),
                "last_fit_exit": max((s["exit"] for s in fit), default=None).isoformat() if fit else None,
                "last_validation_exit": max((s["exit"] for s in validation), default=None).isoformat() if validation else None,
                "tree": tree, "selected": choice, "diagnostics": diagnostics,
                "tree_result": backtest.metrics(new, direction), "asset_local": backtest.metrics(own, direction),
                "adaptive": backtest.metrics(earlier, direction)}
        folds.append(fold)
        print(f"  {year}: tree {fold['tree_result']['n']} / {fold['tree_result']['hit_pct']}%; local {fold['asset_local']['n']} / {fold['asset_local']['hit_pct']}%", flush=True)
    return {"test_n": len(calls), "tree": backtest.metrics(calls, direction),
            "asset_local_same_eligible": backtest.metrics(local_calls, direction),
            "adaptive_same_eligible": backtest.metrics(adaptive_calls, direction), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    prior = json.loads((fv.ROOT / "research" / "adaptive-forecast-research.json").read_text(encoding="utf-8"))
    report = {"method": "Separate depth-3 decision trees for currency bearish, US stock bearish and crypto bullish forecasts. Use adaptive chart features, lagged asset-local score and historical 6/12-month returns. Fit binary outcome splits on older data, minimum 100 samples per leaf; select a validation-only score threshold with adaptive's gates; test later year. Ties are misses. Replayed comparators share eligible observations, but select different calls.",
              "limitations": ["Repeatedly inspected historical data and research selection; this is not an independent or prospective test. Uncertainty intervals do not include model selection.",
                              "Overlapping outcomes and shared market shocks reduce independent information. Current listing universe mostly omits delisted assets; local history requirements narrow eligibility.",
                              "Yahoo crypto differs from Binance. No fees, taxes, dividends, slippage, or executable same-close entry; this model is not deployed."], "markets": {}}
    for market, direction in targeted.TASKS.items():
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {market} {direction}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = targeted.observations(subset)
        eligible = adaptive.add_local_features(samples, direction)
        result = evaluate_samples(eligible, direction, prior["markets"][market]["folds"])
        result.update({"received": len(subset["bars"]), "requested": len(names), "observation_n": len(samples),
                       "local_eligible_n": len(eligible), "skipped": skipped})
        report["markets"][market] = result
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({k: {key: v[key] for key in ("test_n", "tree", "asset_local_same_eligible", "adaptive_same_eligible")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
