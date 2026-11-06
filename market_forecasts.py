#!/usr/bin/env python3
"""Experimental, market-specific three-calendar-month price forecasts.

Research only: models use only the displayed chart's 3-month close window.
Separate binary models are trained per market and target direction. Validation
uses earlier completed outcomes to pick an abstention threshold. No forecast
is returned when the validation period does not support a threshold.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

FEATURES = ("trend_score", "return_5", "return_20", "window_return",
            "volatility", "range_position", "unchanged_fraction")
THRESHOLDS = (.50, .55, .60, .65, .70, .75, .80)
MIN_FIT = 200
MIN_VALIDATION = 50
MIN_MONTHS = 6
MIN_SYMBOLS = 10
BLOCK = 4


def features(closes):
    """Features from the chart window alone; no future bars or volume."""
    import trend_v1 as trend  # frozen: fitted on its score scale
    prices = [float(c) for c in closes]
    if len(prices) < 50 or any(not math.isfinite(p) or p <= 0 for p in prices):
        raise ValueError("at least 50 finite positive closes are required")
    last = prices[-1]
    changes = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
    mean = sum(changes) / len(changes)
    volatility = math.sqrt(sum((x - mean) ** 2 for x in changes) / len(changes))
    low, high = min(prices), max(prices)
    return [trend.classify(prices)["score"],
            math.log(last / prices[-6]), math.log(last / prices[-21]),
            math.log(last / prices[0]), volatility,
            (last - low) / (high - low) if high > low else .5,
            sum(prices[i] == prices[i - 1] for i in range(1, len(prices))) / (len(prices) - 1)]


def _sigmoid(x):
    x = max(-30.0, min(30.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def train(samples, direction):
    """L2-regularized logistic model; ties are misses for either direction."""
    if direction not in ("bullish", "bearish"):
        raise ValueError("unknown direction")
    if len(samples) < MIN_FIT:
        return None
    columns = list(zip(*(s["features"] for s in samples)))
    means = [sum(c) / len(c) for c in columns]
    scales = [max(1e-9, math.sqrt(sum((v - m) ** 2 for v in col) / len(col)))
              for col, m in zip(columns, means)]
    xs = [[max(-5., min(5., (v - m) / scale)) for v, m, scale in zip(s["features"], means, scales)]
          for s in samples]
    target = 1 if direction == "bullish" else -1
    ys = [int(s["outcome"] == target) for s in samples]
    rate = max(.001, min(.999, sum(ys) / len(ys)))
    bias = math.log(rate / (1 - rate))
    weights = [0.] * len(means)
    for _ in range(90):
        grad = [0.] * len(weights)
        error_sum = 0.
        for row, y in zip(xs, ys):
            error = _sigmoid(bias + sum(w * x for w, x in zip(weights, row))) - y
            error_sum += error
            for j, x in enumerate(row):
                grad[j] += error * x
        bias -= .18 * error_sum / len(xs)
        for j in range(len(weights)):
            weights[j] -= .18 * (grad[j] / len(xs) + .04 * weights[j])
    return {"direction": direction, "means": means, "scales": scales,
            "bias": bias, "weights": weights, "fit_n": len(samples)}


def score(model, values):
    row = [max(-5., min(5., (v - m) / scale))
           for v, m, scale in zip(values, model["means"], model["scales"])]
    return _sigmoid(model["bias"] + sum(w * x for w, x in zip(model["weights"], row)))


def _lower_bound(selected, direction, seed=6151):
    months = defaultdict(lambda: [0, 0])
    target = 1 if direction == "bullish" else -1
    for s in selected:
        key = s["date"].year * 12 + s["date"].month - 1
        months[key][0] += s["outcome"] == target
        months[key][1] += 1
    series = [months[m] for m in range(min(months), max(months) + 1)]
    if len(series) < BLOCK:
        return 0.
    rng = random.Random(seed)
    values = []
    for _ in range(400):
        hits = count = drawn = 0
        while drawn < len(series):
            start = rng.randrange(len(series) - BLOCK + 1)
            for hit, n in series[start:start + min(BLOCK, len(series) - drawn)]:
                hits += hit
                count += n
                drawn += 1
        if count:
            values.append(hits / count)
    values.sort()
    return values[int(.05 * (len(values) - 1))] if values else 0.


def choose_threshold(model, validation):
    """Select greatest validation coverage whose block lower bound exceeds 51%."""
    if model is None:
        return None
    scored = [(s, score(model, s["features"])) for s in validation]
    for threshold in THRESHOLDS:
        selected = [s for s, value in scored if value >= threshold]
        months = {(s["date"].year, s["date"].month) for s in selected}
        symbols = {s["symbol"] for s in selected}
        if (len(selected) < MIN_VALIDATION or len(months) < MIN_MONTHS or
                len(symbols) < MIN_SYMBOLS):
            continue
        lower = _lower_bound(selected, model["direction"])
        if lower > .51:
            target = 1 if model["direction"] == "bullish" else -1
            return {"threshold": threshold, "n": len(selected), "months": len(months),
                    "symbols": len(symbols),
                    "hit_pct": round(100 * sum(s["outcome"] == target for s in selected) / len(selected), 2),
                    "lower_bound": round(lower, 4)}
    return None


def fit_direction(training, validation, direction):
    model = train(training, direction)
    choice = choose_threshold(model, validation)
    if model is None or choice is None:
        return None
    model["validation"] = choice
    return model


def predict(models, values):
    """Return one direction or None; conflicting directions abstain."""
    qualified = [direction for direction, model in models.items() if model and
                 score(model, values) >= model["validation"]["threshold"]]
    return qualified[0] if len(qualified) == 1 else None
