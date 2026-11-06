#!/usr/bin/env python3
"""Classify a price series as bullish, bearish or neutral.

The badge on a chart is this module's verdict over exactly the bars the chart
draws -- all of them, however many there are (a crypto chart's 92 daily bars,
a thin PSE name's 38, a fund's 65). Volume is accepted for API compatibility
but does not vote. The score is not a probability and the label is not a
forecast: it says whether the drawn window holds a trend that noise is
unlikely to have produced, and nothing about the next three months.

Version 2 (2026-10-31). Four measured defects of version 1 are fixed here;
version 1 is kept, frozen, as `trend_v1.py`, only because the research
models in `research/` were fitted on its score scale.

    weight  signal      what it measures
    ------  ----------  -------------------------------------------------
    0.40    momentum    the window's drift as a t-statistic: weighted mean
                        log return over its standard error (`_stats`)
    0.25    trend       weighted log-price regression slope x R^2,
                        normalized to a 30% window move (`_regr2`)
    0.20    efficiency  weighted net move / weighted path length (`_effr`)
    0.15    range       where the last close sits in the window's range
                        (`_rng`)

Fix 1 -- a label needs evidence, not just a score
-------------------------------------------------
Version 1 labelled 49% of driftless random walks Bullish or Bearish: its 0.25
threshold sat at roughly a 0.75-sigma move, which chance produces constantly.
A directional label now needs BOTH a score past `ENTER_SCORE` and a drift
t-statistic past `ENTER_T` (1.96). Measured on 63-bar driftless walks: 7-10%
labelled, against 49% before.

Fix 4 -- a label holds, it does not flicker
-------------------------------------------
Version 1 changed label ~8 times per 100 bars and 52-61% of changes reversed
within five bars; nudging only the newest close by one ordinary day's move
flipped it 9% of the time. There is now an entry band and a hold band:

    enter   score >= ENTER_SCORE (0.25) and t >= ENTER_T (1.96)
    hold    score >= HOLD_SCORE  (0.15) and t >= HOLD_T  (1.00)

A bar in the hold band keeps a label only if an unbroken run of same-side
bars leads back, within `HOLD_BARS` (10) bars, to one that entered. The
history is read from the same drawn series -- its prefixes ending 0..10 bars
ago -- so the call stays a pure function of the bars on screen. Measured over
the saved history (74 instruments, ~37,000 windows): 1.0 label changes per
100 bars (was 7.7), 19-27% reversing within five bars (was 58%), and a
one-sigma nudge to the newest close changes the label 0.3-0.9% of the time
(was 9.2%).

Fix 5 -- the oldest bar no longer decides
-----------------------------------------
Version 1's momentum and efficiency compared against the window's first bar,
so the bar leaving the window could flip the label with the price standing
still (3.3% of windows). Every return is now weighted by `_ramp`: the oldest
`FADE_IN` (25%) of the window phases in linearly, the rest counts in full,
so a bar leaving the window carries almost no weight. Dropping the oldest
bar now changes the label in 0.6% of windows.

Fix 7 -- every drawn bar counts, and a short window demands more evidence
------------------------------------------------------------------------
Version 1 read only the trailing 63 bars (a crypto chart draws 92, so the
badge ignored its first month) and damped short windows by an arbitrary
sqrt(n/50) that was a no-op from 49 bars up. Now the whole series given is
the window, and the small-sample penalty is the honest one: the drift's t
is measured against the Student-t critical value for the bars there are
(`_tcrit`), so 8 bars need t ~2.3 to count as 1.96 does at 63, and 4 bars
need ~3.2. Positive serial correlation -- stale prints on a thinly traded
name trending bar to bar -- inflates the standard error by (1 + 2 rho1), so
autocorrelated chop cannot pass for a trend; negative correlation is never
rewarded. Fewer than `MIN_RETURNS_T` (3) returns cannot carry a t at all and
read neutral, which is a call ("no evidence"), not a withheld one.

Real time
---------
The newest bar can be a live or extended-hours print (`server.full_day_close`).
That used to be dangerous: one thin print could flip the badge. With the hold
band a single print cannot undo a label unless it pushes the window out of
the hold band entirely, so the page can refresh the badge as often as the
price without it flickering.

What the four signals are
-------------------------
They correlate strongly (momentum vs efficiency ~+0.99 on random walks);
`agreement` reports how many point the score's way, beside the label, and
never filters.

Standard library only. The arrays are ~60-260 points and the hold band costs
`HOLD_BARS + 1` evaluations; one call is well under a millisecond.

References:
  Moskowitz, Ooi, Pedersen (2012), J. Financial Economics 104(2) -- time-series momentum.
  Newey, West (1987), Econometrica 55(3) -- autocorrelation-consistent variance.
  Kaufman (2013), Trading Systems and Methods, 5th ed. -- efficiency ratio.
"""

from __future__ import annotations

import math

# The bar count a chart falls back to when its window holds fewer than two
# bars (`onset.window`, `pse.chart`). Not a scoring threshold any more.
MIN_BARS = 50

# Below this many bars a walk's tested window is the data floor (`onset`'s
# censoring rule): too short to carry a judgement that is about the asset
# rather than about how little history there is.
MIN_RETURNS = 10

# The fewest log returns a drift t-statistic can be measured over.
MIN_RETURNS_T = 3

WEIGHTS = {
    "momentum": 0.40,
    "trend": 0.25,
    "efficiency": 0.20,
    "range": 0.15,
}

# The two bands (see "Fix 1" and "Fix 4").
ENTER_SCORE = 0.25
ENTER_T = 1.96
HOLD_SCORE = 0.15
HOLD_T = 1.00
HOLD_BARS = 10

# Kept under its old name: the score a directional call starts at.
CALL_THRESHOLD = ENTER_SCORE
STRONG_THRESHOLD = 0.45

# The share of the window, oldest first, that phases in (see "Fix 5").
FADE_IN = 0.25

# Normal quantiles the t correction is built on.
_Z95 = 1.6448536269514722
_Z975 = 1.959963984540054


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def _tcrit(df: int, z: float) -> float:
    """Student-t quantile for `df` degrees of freedom (Cornish-Fisher).

    Accurate to ~1e-3 from df=3 up, which is far finer than the bands. Used
    as the small-sample penalty: a t measured over few bars is scaled by
    z / t_df so it is read against the critical value it actually faces.
    """
    g1 = (z ** 3 + z) / 4.0
    g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96.0
    g3 = (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / 384.0
    return z + g1 / df + g2 / df ** 2 + g3 / df ** 3


def _ramp(m: int) -> list[float]:
    """Weights for `m` returns, oldest first: a linear fade-in, then 1.0."""
    k = max(1, int(round(m * FADE_IN)))
    return [min(1.0, (i + 1) / (k + 1)) for i in range(m)]


# ---------------------------------------------------------------- components

def _stats(closes):
    """Momentum component and drift t-statistic: (momentum, t).

    t is the ramp-weighted sum of log returns over its standard error,
    sigma * sqrt(sum w^2) * sqrt(1 + 2 max(rho1, 0)), then scaled by
    z95 / t_{m-1} for the bars there are. momentum is t / 3, clamped.

    A series whose returns do not vary (sigma under 1e-9 -- dead flat, or a
    perfectly steady payer) has no standard error to divide by: momentum
    sits out as no measurement, and t is +/-inf when every return points the
    same way (a steady rise is not in doubt) or 0.0 when the series is flat.
    """
    m = len(closes) - 1
    if m < MIN_RETURNS_T:
        return None, None
    lr = [math.log(closes[i] / closes[i - 1]) for i in range(1, m + 1)]
    w = _ramp(m)
    mu = sum(lr) / m
    var = sum((r - mu) ** 2 for r in lr) / (m - 1)
    sigma = math.sqrt(var)
    if sigma <= 1e-9:
        if all(r > 1e-12 for r in lr):
            return None, math.inf
        if all(r < -1e-12 for r in lr):
            return None, -math.inf
        return None, 0.0
    num = sum((r - mu) * (s - mu) for r, s in zip(lr[1:], lr[:-1]))
    rho = num / (var * (m - 1))
    inflate = math.sqrt(1.0 + 2.0 * max(0.0, rho))
    sw2 = math.sqrt(sum(x * x for x in w))
    z = sum(wi * r for wi, r in zip(w, lr)) / (sigma * sw2 * inflate)
    t = z * _Z95 / _tcrit(m - 1, _Z95)
    return _clamp(t / 3.0), t


def _regr2(closes):
    """Weighted log-price regression: (slope move x R^2, R^2).

    The implied window move exp(slope * (n-1)) - 1 is normalized to 30%,
    scale-free across a PHP 8 stock and a PHP 3,000 index. Point weights are
    the return ramp, the first point taking half the first return's weight,
    so the oldest bars barely tilt the fit. (None, None) for a flat window.
    """
    n = len(closes)
    if n < 3:
        return None, None
    w = _ramp(n - 1)
    pw = [w[0] * 0.5] + w
    y = [math.log(c) for c in closes]
    tw = sum(pw)
    mx = sum(p * i for i, p in enumerate(pw)) / tw
    my = sum(p * v for p, v in zip(pw, y)) / tw
    sxx = sxy = syy = 0.0
    for i, (p, v) in enumerate(zip(pw, y)):
        dx, dy = i - mx, v - my
        sxx += p * dx * dx
        sxy += p * dx * dy
        syy += p * dy * dy
    if sxx <= 0 or syy <= 1e-18:
        return None, None
    r2 = (sxy * sxy) / (sxx * syy)
    slope = sxy / sxx
    move = math.exp(_clamp(slope * (n - 1), -5.0, 5.0)) - 1.0
    return _clamp(move / 0.30) * r2, r2


def _effr(closes):
    """Weighted efficiency ratio: weighted net log move / weighted path."""
    m = len(closes) - 1
    if m < 1:
        return None
    w = _ramp(m)
    lr = [math.log(closes[i] / closes[i - 1]) for i in range(1, m + 1)]
    path = sum(wi * abs(r) for wi, r in zip(w, lr))
    if path <= 1e-12:
        return None
    return _clamp(sum(wi * r for wi, r in zip(w, lr)) / path)


def _rng(closes):
    """Last close's position in the window's [low, high], as [-1, +1].

    None for a dead-flat window, which has no range to sit in.
    """
    lo, hi = min(closes), max(closes)
    if hi <= lo:
        return None
    return ((closes[-1] - lo) / (hi - lo) - 0.5) * 2.0


# ------------------------------------------------------------------- scoring

def _evaluate(closes):
    """One window's components, score and drift t (no label, no history)."""
    momentum, t = _stats(closes)
    trend, r2 = _regr2(closes)
    efficiency = _effr(closes)
    rng = _rng(closes)
    raw = {"momentum": momentum, "trend": trend,
           "efficiency": efficiency, "range": rng}
    present = {k: v for k, v in raw.items() if v is not None}
    total = sum(WEIGHTS[k] for k in present)
    score = (sum(WEIGHTS[k] * v for k, v in present.items()) / total
             if total else 0.0)
    return _clamp(score), t, raw, r2


def _zone(score, t):
    """+2/-2 entry, +1/-1 hold band, 0 neither."""
    if t is None:
        return 0
    if score >= ENTER_SCORE and t >= ENTER_T:
        return 2
    if score <= -ENTER_SCORE and t <= -ENTER_T:
        return -2
    if score >= HOLD_SCORE and t >= HOLD_T:
        return 1
    if score <= -HOLD_SCORE and t <= -HOLD_T:
        return -1
    return 0


def progress(score, t) -> float:
    """How far a window has come toward entering a label, as a share of the bar.

    The smaller of score / ENTER_SCORE and |t| / ENTER_T, taken on the side the
    score points, so 1.0 means both halves of the entry bar are met. Used to
    rank leaning windows; it is not a probability.
    """
    if t is None or not score:
        return 0.0
    side = 1 if score > 0 else -1
    t_part = 1.0 if math.isinf(t) and t * side > 0 else max(0.0, t * side / ENTER_T)
    return round(min(score * side / ENTER_SCORE, t_part), 4)


def classify(closes, volumes=None):
    """Score a daily close series; the whole series is the window.

    `closes` is oldest-first. `volumes` is accepted for compatibility and
    never votes. Returns {"label", "score", "confidence", "bars",
    "agreement", "significance", "held", "components"}:

    * `label`        bullish / bearish / neutral (see the bands above).
    * `score`        the four-signal blend over the latest bar, [-1, 1].
    * `significance` the drift t-statistic after the small-sample and
                     serial-correlation corrections (None under 3 returns).
    * `held`         True when the label stands on the hold band: it entered
                     within the last `HOLD_BARS` bars and has not left it.
    * `confidence`   strong / moderate / holding for a label; weak / flat
                     for neutral.
    * `lean`         for a neutral window only: "bullish" / "bearish" when the
                     latest window sits in that side's hold band (it would
                     keep a label there but has not earned one), else None.
                     A reading of the same zone, never a label.
    * `progress`     the share of the entry bar met on the score's side
                     (see `progress`); 1.0 or more for an entered window.

    Raises ValueError only for unusable input -- an empty series or a
    non-positive price.
    """
    closes = [float(c) for c in closes]
    n = len(closes)
    if not n:
        raise ValueError("No closes to classify.")
    if any(not c > 0 for c in closes):
        raise ValueError("Prices must be positive.")

    score, t, raw, r2 = _evaluate(closes)
    zone_now = _zone(score, t)

    label_sign = 0
    held = False
    if abs(zone_now) == 2:
        label_sign = zone_now // 2
    elif zone_now != 0:
        # Walk back through the series as it stood 1..HOLD_BARS bars ago,
        # while every bar stays on this side, looking for one that entered.
        side = 1 if zone_now > 0 else -1
        for back in range(1, HOLD_BARS + 1):
            if n - back < 2:
                break
            s, tb, _, _ = _evaluate(closes[:n - back])
            z = _zone(s, tb)
            if z * side <= 0:
                break
            if abs(z) == 2:
                label_sign = side
                held = True
                break

    label = {1: "bullish", -1: "bearish"}.get(label_sign, "neutral")

    mag = abs(score)
    if label_sign:
        confidence = ("strong" if mag >= STRONG_THRESHOLD
                      else "moderate" if not held else "holding")
    else:
        confidence = "weak" if mag >= 0.10 else "flat"

    direction = 1 if score > 0 else -1 if score < 0 else 0
    voting = [v for v in raw.values() if v is not None and v != 0.0]
    if direction and voting:
        agree = sum(1 for v in voting if (v > 0) == (direction > 0))
        agreement = f"{agree}/{len(voting)}"
    else:
        agreement = None

    components = {k: (round(float(v), 4) if v is not None else None)
                  for k, v in raw.items()}
    if r2 is not None:
        components["r2"] = round(float(r2), 4)

    if t is None:
        significance = None
    elif math.isinf(t):
        significance = 99.0 if t > 0 else -99.0
    else:
        significance = round(t, 4)

    return {
        "label": label,
        "score": round(score, 4),
        "confidence": confidence,
        "bars": n,
        "agreement": agreement,
        "significance": significance,
        "held": held,
        "lean": ({1: "bullish", -1: "bearish"}.get(zone_now)
                 if not label_sign else None),
        "progress": progress(score, t),
        "components": components,
    }
