#!/usr/bin/env python3
"""Experiment: rolling pooled and asset-local outcome forecasts.

For each observation use only outcomes whose exits predate its signal and
whose signal falls in the prior 36 months. Smooth each asset's regime history
toward the corresponding market regime, then forecast only when the smoothed
hit rate is at least 55%. The fixed research method is tested retrospectively
on years previously inspected, so this is not independent validation.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
from collections import defaultdict

import asset_local_forecast_research as local
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecast_backtest as backtest
import market_forecasts as model
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "pooled-forecast-research.json"
YEARS = range(2020, 2027)
LOOKBACK_MONTHS = 36
MIN_MARKET_CASES = 200
MIN_MARKET_MONTHS = 18
MIN_MARKET_SYMBOLS = 10
MIN_ASSET_CASES = 8
MIN_GROUP_CASES = 3
MARKET_PRIOR = 25
ASSET_PRIOR = 8
THRESHOLD = .55


def _add(bucket, sample, target):
    bucket[0] += sample["outcome"] == target
    bucket[1] += 1


def build_state(history, direction):
    """Aggregate a pre-filtered point-in-time training set into sufficient statistics."""
    target = 1 if direction == "bullish" else -1
    market = [0, 0]
    regimes = defaultdict(lambda: [0, 0])
    assets = defaultdict(lambda: [0, 0])
    asset_regimes = defaultdict(lambda: [0, 0])
    months, symbols = set(), set()
    for s in history:
        key = local.regimes(s["features"][:7])
        months.add((s["date"].year, s["date"].month))
        symbols.add(s["symbol"])
        _add(market, s, target)
        _add(regimes[key], s, target)
        _add(assets[s["symbol"]], s, target)
        _add(asset_regimes[(s["symbol"], key)], s, target)
    return {"market": market, "regimes": regimes, "assets": assets,
            "asset_regimes": asset_regimes, "months": len(months), "symbols": len(symbols)}


def estimate(state, sample):
    """Return the shrunken hit score or None if history is too sparse."""
    market_wins, market_n = state["market"]
    if (market_n < MIN_MARKET_CASES or state["months"] < MIN_MARKET_MONTHS or
            state["symbols"] < MIN_MARKET_SYMBOLS):
        return None
    key, symbol = local.regimes(sample["features"][:7]), sample["symbol"]
    group_wins, group_n = state["regimes"].get(key, (0, 0))
    asset_wins, asset_n = state["assets"].get(symbol, (0, 0))
    own_wins, own_n = state["asset_regimes"].get((symbol, key), (0, 0))
    if asset_n < MIN_ASSET_CASES or own_n < MIN_GROUP_CASES:
        return None
    market_base = market_wins / market_n
    market_group = (group_wins + MARKET_PRIOR * market_base) / (group_n + MARKET_PRIOR)
    asset_base = (asset_wins + ASSET_PRIOR * market_base) / (asset_n + ASSET_PRIOR)
    pooled_prior = (market_group + asset_base) / 2
    return (own_wins + ASSET_PRIOR * pooled_prior) / (own_n + ASSET_PRIOR)


def evaluate_samples(samples, direction, prior_folds, adaptive_folds, years=YEARS):
    """Replay all comparators on identical local-history-eligible observations."""
    import adaptive_forecast_research as adaptive
    augmented = adaptive.add_local_features(samples, direction)
    old = {f["year"]: f.get("models", {}) for f in prior_folds}
    adapt = {f["year"]: f for f in adaptive_folds}
    # Rebuild every signal date: markets with different local signal dates must
    # not see an exit that happens later in the same month.
    by_date = defaultdict(list)
    for s in augmented:
        if s["date"].year in years:
            by_date[s["date"]].append(s)
    ordered = sorted(samples, key=lambda s: s["exit"])
    exits = [s["exit"] for s in ordered]
    calls, local_calls, adaptive_calls, old_calls = [], [], [], []
    annual = defaultdict(lambda: defaultdict(list))
    for day, group in sorted(by_date.items()):
        cutoff = fv.months_after(day, -LOOKBACK_MONTHS)
        end = bisect.bisect_left(exits, day)
        # Exclude same-day outcomes; no assumption on intraday close timing.
        history = [s for s in ordered[:end] if s["date"] >= cutoff]
        state = build_state(history, direction)
        afold = adapt.get(day.year, {})
        amodel, achoice = afold.get("model"), afold.get("selected")
        for s in group:
            value = estimate(state, s)
            labels = {"pooled": direction if value is not None and value >= THRESHOLD else None,
                      "asset_local": direction if s["local_score"] >= local.CALL_THRESHOLD else None,
                      "adaptive": direction if achoice and amodel and model.score(amodel, s["features"]) >= achoice["threshold"] else None,
                      "prior": model.predict(old.get(day.year, {}), s["features"][:7])}
            for name, label in labels.items():
                annual[day.year][name].append((s, label))
            calls.append((s, labels["pooled"]))
            local_calls.append((s, labels["asset_local"]))
            adaptive_calls.append((s, labels["adaptive"]))
            old_calls.append((s, labels["prior"]))
    folds = []
    for year in years:
        item = {"year": year, **{key: backtest.metrics(annual[year][key], direction)
                                 for key in ("pooled", "asset_local", "adaptive", "prior")}}
        folds.append(item)
        print(f"  {year}: pooled {item['pooled']['n']} / {item['pooled']['hit_pct']}%; local {item['asset_local']['n']} / {item['asset_local']['hit_pct']}%", flush=True)
    return {"test_n": len(calls), "pooled": backtest.metrics(calls, direction),
            "asset_local_same_eligible": backtest.metrics(local_calls, direction),
            "adaptive_same_eligible": backtest.metrics(adaptive_calls, direction),
            "prior_same_eligible": backtest.metrics(old_calls, direction),
            "abstained": sum(label is None for _, label in calls), "folds": folds}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    baseline = json.loads(targeted.BASELINE.read_text(encoding="utf-8"))
    adaptive_report = json.loads((fv.ROOT / "research" / "adaptive-forecast-research.json").read_text(encoding="utf-8"))
    report = {"method": "Per market/direction, a rolling 36-month asset/regime hit frequency shrunk toward market and asset base rates. Use strictly prior completed outcomes, fixed >=55% score and minimum market/asset/regime observations. Compare prior asset-local, adaptive and original models on identical eligible 2020–2026 signals. Target is close-to-close direction three calendar months ahead; unchanged prices count as misses.",
              "limitations": ["Repeatedly inspected historical years and research iteration: not independent, untouched, or prospective evidence. Bootstrap intervals do not correct for research selection.",
                              "Current selected instruments omit many delisted assets. Short histories, missing references and local-history-ineligible observations are excluded; crypto source is Yahoo rather than Binance.",
                              "Outcome windows overlap and share market shocks. Same-close entry may not be executable; no dividends, fees, taxes or slippage. Not deployed or validated on live/stale/partial bars."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        names = [s for s, category in raw["universe"].items() if category == market]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Evaluating {market} {direction}: {len(subset['bars'])} histories", flush=True)
        samples, skipped = targeted.observations(subset)
        result = evaluate_samples(samples, direction, baseline["markets"][market]["folds"], adaptive_report["markets"][market]["folds"])
        result.update({"received": len(subset["bars"]), "requested": len(names), "skipped": skipped})
        report["markets"][market] = result
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}; archive it manually first")
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {key: v[key] for key in ("test_n", "pooled", "asset_local_same_eligible", "adaptive_same_eligible", "prior_same_eligible", "abstained")}
                      for k, v in report["markets"].items()}, indent=2))


if __name__ == "__main__":
    main()
