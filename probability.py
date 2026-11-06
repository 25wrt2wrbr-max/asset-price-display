"""Chart-only estimate of a positive three-month return after assumed costs.

Fit daily log-return mean and sample variance to the bars actually drawn. Under
an independent, stationary normal-log-return model, project the mean H sessions
forward. Predictive variance is s²(H + H²/n): future price noise plus uncertainty
in the estimated mean. The normal approximation does not include regime changes,
fat tails, or all uncertainty in estimated variance; this is a model estimate,
not an empirically calibrated success rate. No class historical up-rate or badge
score is used. Asset classes supply only session calendars and assumed costs.
"""

from __future__ import annotations

import calendar
import datetime as dt
import math
import statistics

CLASSES = {
    "us_equity": {"cost": 0.0025, "label": "US stock"},
    "pse": {"cost": 0.0120, "label": "PSE stock"},
    "crypto": {"cost": 0.0020, "label": "crypto"},
    "currency": {"cost": 0.0005, "label": "currency pair"},
    "fund": {"cost": 0.0050, "label": "fund"},
    "future": {"cost": 0.0020, "label": "futures contract"},
    "token": {"cost": 0.0020, "label": "tokenized fund"},
}

# Classes whose series trades every calendar day, so three months is ~92
# sessions rather than the ~65 weekdays an exchange keeps.
CALENDAR_DAY_CLASSES = frozenset({"crypto", "token"})

MIN_RETURNS = 20


def norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def asset_class(payload: dict) -> str | None:
    """The instrument's calendar/cost category, not a return prior."""
    ptype = (payload.get("type") or "").strip()
    source = (payload.get("source") or "").strip()
    if payload.get("yieldSeries"):
        return None
    if ptype == "FUTURE":
        return "future"
    if payload.get("fundSeries") or ptype in ("Net asset value", "MUTUALFUND"):
        return "fund"
    if ptype == "Tokenized fund":
        # A token that tracks a fund's per-token value: it trades around the
        # clock on chain, so it keeps a calendar week, and it is swapped rather
        # than subscribed, so the crypto round trip is the closer cost.
        return "token"
    if ptype == "CRYPTOCURRENCY" or source == "Binance":
        return "crypto"
    if ptype == "CURRENCY":
        return "currency"
    if source == "TradingView":
        return "pse"
    if ptype in ("EQUITY", "ETF", "INDEX"):
        return "us_equity"
    return None


def estimate(payload: dict) -> dict | None:
    """Estimate P(three-month simple return > assumed round-trip cost).

    Require a continuous usable series rather than silently bridging invalid
    bars. Daily session gaps (weekends/holidays) are normal; weekly returns are
    not daily returns and are deliberately unsupported. Flat/constant-return
    series have no estimated stochastic scale, so receive no invented certainty.
    """
    name = asset_class(payload)
    if name is None or payload.get("interval", "1d") != "1d":
        return None
    points = payload.get("points") or []
    if len(points) < MIN_RETURNS + 1:
        return None
    closes, stamps = [], []
    for point in points:
        if not isinstance(point, dict):
            return None
        c, t = point.get("c"), point.get("t")
        if (not isinstance(c, (int, float)) or isinstance(c, bool)
                or not math.isfinite(c) or c <= 0
                or not isinstance(t, (int, float)) or isinstance(t, bool)
                or not math.isfinite(t)):
            return None
        closes.append(c)
        stamps.append(t)
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    if any(g <= 0 or g > 7 * 86400 for g in gaps):
        return None
    if statistics.median(gaps) > 2 * 86400:
        return None
    returns = [math.log(b) - math.log(a) for a, b in zip(closes, closes[1:])]
    n = len(returns)
    mean = statistics.mean(returns)
    sd = statistics.stdev(returns)
    if sd <= 1e-9:
        return None
    try:
        last = dt.datetime.fromtimestamp(stamps[-1], dt.timezone.utc).date()
        year, month = divmod(last.year * 12 + last.month - 1 + 3, 12)
        month += 1
        end = dt.date(year, month, min(last.day, calendar.monthrange(year, month)[1]))
    except (ValueError, OverflowError, OSError):
        return None
    # Crypto and on-chain tokens have a session every day; the other supported
    # series have weekday sessions. Exclude exchange holidays only when an
    # exchange calendar exists.
    calendar_days = (end - last).days
    horizon = (calendar_days if name in CALENDAR_DAY_CLASSES else sum(
        (last + dt.timedelta(days=i)).weekday() < 5
        for i in range(1, calendar_days + 1)))
    cost = CLASSES[name]["cost"]
    projected = horizon * mean
    predictive_sd = sd * math.sqrt(horizon + horizon * horizon / n)
    p = norm_cdf((projected - math.log1p(cost)) / predictive_sd)
    return {
        "probability": round(min(max(p, 0.01), 0.99), 4),
        "class": name,
        "label": CLASSES[name]["label"],
        "cost": cost,
        "method": "chart-log-return-normal",
        "observations": n,
        "horizonBars": horizon,
        "dailyMean": mean,
        "dailySigma": sd,
        "predictiveSigma": predictive_sd,
    }
