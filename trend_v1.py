#!/usr/bin/env python3
"""FROZEN -- version 1 of the classifier. Not the chart badge.

The badge is `trend.py` (version 2). This copy exists only because the
research models (`forecast_validation`, `market_forecasts`, `pse_backtest`,
`pse_bull_fund_bear_research`, `research_judgment`) were fitted on this
module's score scale, and re-scoring them with version 2 would silently
break their frozen bins. Do not edit it and do not use it for a label.

Classify a price series as bullish, bearish or neutral.

One blend at every series length: the backtested ensemble from
~/Documents/trend-algo, verbatim -- the same four signals, the same formulas,
the same weights -- so the badge on any chart IS the backtest's verdict, not a
lookalike of it. Volume is accepted for API compatibility but does not vote:
it was never in the backtest, and letting it vote would make the badge
something close to but not exactly the validated verdict. Short-window
performance and three-month persistence are unvalidated. The score is not a
probability or a promise of future returns.

    weight  signal      what it measures
    ------  ----------  -------------------------------------------------
    0.40    momentum    vol-normalized window return: the move divided by
                        the volatility it cost (`_vtsmom`)
    0.25    trend       OLS slope x R^2, normalized to a 30% window move
                        (`_regr2`)
    0.20    efficiency  Kaufman efficiency ratio: net move / path length
                        (`_effr`)
    0.15    range       where the last close sits in the window's range
                        (`_rng`)

A signal that cannot be computed over the bars there are is dropped and its
weight shared out over the ones that can, so a short series is judged on what
it actually supports rather than handed an invented reading. Below 50 bars
(`MIN_BARS`) the score is scaled back by sqrt(n / 50): a short window supports
a weaker conclusion, not a different one. One honesty note about that curve:
anchored at 50 it is nearly a no-op in the 40s (sqrt(49/50) = 0.99) and absent
from 50-62 bars, so a window in that band gets full confidence without having
reached the validated length. The backtest validated 63 bars; nothing below
that is validated at all.

What the backtest said
----------------------
The ensemble was fitted and checked out-of-sample on seven assets (SPY, QQQ,
AAPL, NVDA, GLD, TLT, BTC-USD; daily bars, 2021-2026; first 80% of each
timeline fit, last 20% out-of-sample). Findings that shaped this file:

* Vol-normalized momentum was the single strongest component, and
  normalizing made BEAR labels far more accurate out-of-sample (0.81 vs
  0.38-0.65 next-6-months accuracy for the raw-return variants). It is also
  what makes one shared threshold hold across everything this project scores:
  a +8% three-month move in a low-vol peso bond reads as strongly as a +30%
  move in a high-vol tech name, instead of the high-vol name reading
  "trendier" for the same information.
* At the 6-month forward horizon the ensemble's score vs future return
  Spearman rho was +0.127 in-sample, +0.070 OOS; BULL labels 65% accurate OOS,
  BEAR labels 81% OOS.
* This vol-normalized ensemble beat every raw variant tested at 6m OOS
  (tsmom+effr pair +0.064, raw tsmom alone +0.054, equal-weight-5 +0.046).

The horizon caveat travels with the port, because it is the backtest's most
practical finding: judged one month ahead the labels had NO edge (OOS rho
about -0.04 to -0.11 -- short-horizon reversal washes momentum out); judged
six months ahead they did (OOS rho +0.060 to +0.070). A three-month chart
classifies the NEXT 3-6 MONTHS. The bullish scanner and the badge read this
as a regime call, not a next-week timing signal.

Honest caveats, carried over from the backtest: bear labels on broad equity
indices mean-reverted at short horizons (deep 3-month drawdowns were usually
followed by bounces), so BEAR on an index is "regime danger", not "short
now"; the sample is one regime, 2021-2026 net-up, so the BEAR statistics rest
on few true down-markets; and all of it is historical.

The four signals are one signal, mostly
---------------------------------------
Measured over 3,000 63-bar random walks (2026-10-31), the components
correlate strongly: momentum vs efficiency +0.996, momentum vs trend +0.896,
momentum vs range +0.804. Efficiency is momentum with the denominator
changed; the blend is effectively one return-factor read three ways, with
`range` the only mildly orthogonal voice. That is fine -- the backtest
validated the blend as a unit, and re-weighting it by hand would un-match the
only evidence that exists -- but a label carried by all four is less
independent evidence than "four signals" suggests. `agreement` in the result
reports the count so a reader can see it.

The agreement field
-------------------
`agreement` is "how many components that express a direction point the way
the score does", as a string like "3/4". A bullish call carried 4/4 and one
carried 2/3 read the same label but not the same evidence, and the boundary
0.26 cases deserve an honest read. Components that sat out (None) or read
exactly 0.0 do not count. It is None when the score has no sign or no
component does. It is a reading of the same bars, reported beside the label
-- it never filters, never changes the label, the score or the date, the same
discipline `onset.turn`'s `manner` follows.

Why the regression is normalized by mean price
----------------------------------------------
The slope is read as a fraction of the mean price over the window --
`slope * (n-1) / mean(y)` is the straight-line move the fit implies, so +1.0
means "rose 30% linearly across the window". That is scale-free without
logs: one set of thresholds holds for a PHP 8 stock and a PHP 3,000 index.
(Earlier this module fit ln(Close) here; the raw-price form matches the
backtest exactly and is equally scale-free, so exactness won.)

Why R^2 is in the score
-----------------------
A steep slope means nothing if the price wandered far from the line. The
trend term is the slope multiplied by R^2 -- the backtest's damping, harsher
than the sqrt(R^2) used here before -- so a noisy chart cannot earn high
confidence on slope alone. R^2 is reported as `components.r2` too.

Every series gets a call
------------------------
There was a time when `classify` raised below 50 bars and the caller swallows
that into "no badge", which silently hid the verdict for thinly traded names
(PSE:MFC's 90-day window holds 49 bars) and fresh listings. The gate is gone
and stays gone: a shorter window is damped, never withheld. Only unusable
data -- an empty series, a non-positive price -- raises.

Standard library only -- no numpy, no pandas -- to keep the server dependency
free. The arrays are ~64 points, so the unvectorised loops cost nothing.

References:
  Moskowitz, Ooi, Pedersen (2012), J. Financial Economics 104(2) -- time-series momentum.
  Barroso, Santa-Clara (2015), J. Financial Economics 116(1) -- vol-managed momentum.
  Kaufman (2013), Trading Systems and Methods, 5th ed. -- efficiency ratio.
  Jegadeesh (1990), J. Finance 45(3) -- monthly reversal (why 1-month horizons are not used).
"""

from __future__ import annotations

import math

# Bars at which the score counts in full. Below it a series is still scored --
# every series gets a call -- but the verdict is scaled back by sqrt(n / MIN_BARS),
# because a 20-bar sample supports a weaker conclusion than a 60-bar one. This is
# a confidence knob, not a gate: it never withholds the label.
MIN_BARS = 50

# The window the backtest validated, in daily bars: 90 calendar days is ~63
# trading bars. The blend reads the trailing min(63, n) bars at every length.
RETURN_WINDOW = 63

# A vol-normalized return over fewer than this many log returns is noise, not
# a measurement; the term drops out and its weight is shared out.
MIN_RETURNS = 10

# The backtest ensemble, verbatim. Do not adjust these by hand -- every change
# here un-matches the backtested classifier this module exists to agree with.
WEIGHTS = {
    "momentum": 0.40,
    "trend": 0.25,
    "efficiency": 0.20,
    "range": 0.15,
}

# |score| at or above this is a directional call; below it, the chart is
# genuinely unresolved and we say so rather than guess. Same threshold the
# backtest validated (stable between 0.20 and 0.30 in its checks).
CALL_THRESHOLD = 0.25

# Confidence tiers, reported alongside the label so a 0.26 boundary case and a
# 0.70 run do not read the same. Same breakpoints the backtest classifier used.
STRONG_THRESHOLD = 0.45


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


# ---------------------------------------------------------------- components
# The four components below are exact ports of trend_classifier.py's
# vtsmom / regr2 / effr / rng: same formulas, same saturation points, same
# edge cases. A component that cannot be measured returns None and is dropped
# from the blend with its weight renormalized -- the same convention the
# backtest classifier uses for its NaN components.

def _vtsmom(closes):
    """Vol-normalized window return, saturated at +/-3 window-sigmas.

    z = (P_end/P_start - 1) / (sigma_daily * sqrt(n - 1)), scored as z / 3.
    Dividing by realized volatility (Barroso & Santa-Clara 2015) is what makes
    one 0.25 threshold hold across the whole project, and what took the
    backtest's BEAR labels from unreliable to usable out-of-sample.

    Needs at least MIN_RETURNS log returns to say anything. sigma <= 0 -- a
    perfectly flat or perfectly linear series -- is "no measurement" rather
    than an invented extreme, so the term is dropped and its weight shared
    out. The check is a floor (1e-9), not `<= 0`: accumulated float noise
    gives a perfectly uniform series a variance around 1e-16, which would
    otherwise squeak past a zero test and send z into the clamp -- a steady
    payer would read "momentum: 1.0" off rounding noise. 1e-9 in daily
    log-return units sits far below the quietest real asset (~1e-4) and far
    above that noise.
    """
    window = _window_tail(closes)
    n = len(window)
    logret = [math.log(window[i] / window[i - 1]) for i in range(1, n)]
    if len(logret) < MIN_RETURNS:
        return None
    m = sum(logret) / len(logret)
    var = sum((r - m) ** 2 for r in logret) / len(logret)
    sigma = math.sqrt(var)
    if sigma <= 1e-9:
        return None
    ret = window[-1] / window[0] - 1.0
    z = ret / (sigma * math.sqrt(n - 1))
    return _clamp(z / 3.0)


def _regr2(closes):
    """OLS slope on raw price, normalized to the window move, times R^2.

    Returns (score, r2); (None, None) when the fit is degenerate (a flat
    window has no variance to explain). See "Why the regression is normalized
    by mean price" in the module docstring for the scaling.
    """
    window = _window_tail(closes)
    n = len(window)
    mean_x = (n - 1) / 2.0
    mean_y = sum(window) / n
    sxx = sxy = syy = 0.0
    for x, y in enumerate(window):
        dx, dy = x - mean_x, y - mean_y
        sxx += dx * dx
        sxy += dx * dy
        syy += dy * dy
    if sxx <= 0 or syy <= 0:
        return None, None
    r2 = (sxy * sxy) / (sxx * syy)
    slope = sxy / sxx
    z = _clamp((slope * (n - 1)) / mean_y / 0.30)
    return z * r2, r2


def _effr(closes):
    """Kaufman Efficiency Ratio over the trailing window: net move / path length.

    How directly price traveled: 1.0 is sixty-three straight up-closes, near 0
    is chop that went nowhere. A return alone cannot tell those apart -- a
    +10% window made of two gap days and a +10% grind earn the same momentum
    -- but only the grind is a trend worth the badge. A zero-path series
    (dead flat) drops the term, as in the backtest classifier.
    """
    window = _window_tail(closes)
    net = window[-1] - window[0]
    path = sum(abs(window[i] - window[i - 1]) for i in range(1, len(window)))
    if path <= 0:
        return None
    return _clamp(net / path)


def _rng(closes):
    """Last close's position in the trailing window's [low, high], as [-1, +1].

    Captures "grinding higher and making window highs" that a return can
    miss: after a V-shaped window the net return is small while the close
    sitting at the top of the range still says the buyers own it.

    A dead-flat window has no [low, high] to sit in -- "mid-range" would
    misreport "no measurement" as a measured neutral -- so it returns None
    and its weight is shared out, like the other components that sat out.
    """
    window = _window_tail(closes)
    lo, hi = min(window), max(window)
    if hi <= lo:
        return None
    return ((window[-1] - lo) / (hi - lo) - 0.5) * 2.0


def _window_tail(closes):
    """The trailing `RETURN_WINDOW` bars every signal reads."""
    return closes[-RETURN_WINDOW:]


# ------------------------------------------------------------------- classify

def classify(closes, volumes=None):
    """Score a daily close series.

    `closes` is oldest-first. `volumes` is accepted for compatibility but
    does not vote. The same four signals and weights apply at every length.

    Always returns a verdict: {"label", "score", "confidence", "bars",
    "agreement", "components"} where label is "bullish", "bearish" or
    "neutral" and confidence is how far the score sits past the call threshold
    ("strong", "moderate", "weak", "flat"). `agreement` is how many of the
    components that express a direction point the way the score does ("3/4"),
    or None -- see "The agreement field" in the module docstring; it is
    reported, never filtered on. A signal that cannot be computed is dropped
    from the blend and its weight is shared out over the ones that can.
    Raises ValueError only for unusable input -- an empty series, or a
    non-positive price.
    """
    closes = [float(c) for c in closes]
    n = len(closes)

    if not n:
        raise ValueError("No closes to classify.")
    # ln(price) is undefined at zero, and a non-positive price means bad data.
    # Bad data is not a judgement call, so this one still raises.
    if any(not c > 0 for c in closes):
        raise ValueError("Prices must be positive.")

    # The four return-shaped signals, over the trailing min(63, n) bars.
    momentum = _vtsmom(closes)
    trend, r2 = _regr2(closes)
    efficiency = _effr(closes)
    rng = _rng(closes)
    raw = {
        "momentum": momentum,
        "trend": trend,
        "efficiency": efficiency,
        "range": rng,
    }

    # Only signals with an answer vote, and their weights are renormalised so
    # the score keeps its [-1, 1] meaning however many of them there are.
    present = {k: v for k, v in raw.items() if v is not None}
    total_weight = sum(WEIGHTS[k] for k in present)
    score = (sum(WEIGHTS[k] * v for k, v in present.items()) / total_weight
             if total_weight else 0.0)
    # A shorter window supports a weaker conclusion, so the verdict is scaled
    # back toward neutral by sqrt(n / MIN_BARS) rather than being withheld.
    score *= math.sqrt(n / MIN_BARS) if n < MIN_BARS else 1.0
    score = max(-1.0, min(1.0, score))

    # -- call ---------------------------------------------------------------
    if score >= CALL_THRESHOLD:
        label = "bullish"
    elif score <= -CALL_THRESHOLD:
        label = "bearish"
    else:
        label = "neutral"

    # How much conviction sits behind the label: a 0.26 boundary case and a
    # 0.70 run both say "bullish", but they should not read the same. The
    # breakpoints are the backtest classifier's, and the short-series damping
    # above flows through honestly -- a 20-bar series that scores like a
    # moderate call reads "weak", because that is what it is.
    mag = abs(score)
    if mag >= STRONG_THRESHOLD:
        confidence = "strong"
    elif mag >= CALL_THRESHOLD:
        confidence = "moderate"
    elif mag >= 0.10:
        confidence = "weak"
    else:
        confidence = "flat"

    # -- agreement ----------------------------------------------------------
    # How many of the components that express a direction point the way the
    # score does. A reading of the same bars, reported beside the label --
    # never a second classifier: it must not change the label, the score or
    # the call, the way `onset.turn`'s manner never does.
    direction = 1 if score > 0 else -1 if score < 0 else 0
    voting = [v for v in present.values() if v != 0.0]
    if direction and voting:
        agree = sum(1 for v in voting if (v > 0) == (direction > 0))
        agreement = f"{agree}/{len(voting)}"
    else:
        agreement = None

    # Every signal is reported, including the ones that sat this one out: a
    # missing component is a fact about the data, and 0.0 would misreport
    # "unknown" as "measured neutral".
    components = {k: (round(float(v), 4) if v is not None else None)
                  for k, v in raw.items()}
    if r2 is not None:
        components["r2"] = round(float(r2), 4)

    return {
        "label": label,
        "score": round(score, 4),
        "confidence": confidence,
        "bars": n,
        "agreement": agreement,
        "components": components,
    }
