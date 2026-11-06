"""Longer-history context for PSE stocks, not a price forecast.

The displayed trend remains the single chart-window classifier. This separate
context reports the 6- and 12-calendar-month price comparisons evaluated in
pse_backtest.py, using only completed bars and withholding stale/missing data.
"""
from __future__ import annotations

import bisect
import calendar
import datetime as dt
import math
from zoneinfo import ZoneInfo

MANILA = ZoneInfo("Asia/Manila")
MAX_GAP_DAYS = 10
MIN_PRIOR_BARS = 252


def _months_back(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    month += 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def context(points, now=None):
    now = now or dt.datetime.now(MANILA)
    today = now.astimezone(MANILA).date()
    rows = []
    for p in points or []:
        try:
            stamp, price = int(p["t"]), float(p["c"])
            day = dt.datetime.fromtimestamp(stamp, MANILA).date()
            # Discard today's candle even after close: no exchange calendar or
            # finality flag exists in the provider payload.
            if day < today and math.isfinite(price) and price > 0:
                rows.append((day, price))
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
    rows.sort()
    result = {"status": "insufficient", "reason": "Insufficient completed price history"}
    if not rows:
        return result
    days = [r[0] for r in rows]
    last, price = rows[-1]
    result["asOf"] = last.isoformat()
    if (today - last).days > MAX_GAP_DAYS:
        result["reason"] = "Latest completed price is stale"
        return result
    if len(rows) <= MIN_PRIOR_BARS:
        return result
    comparisons = []
    for months in (6, 12):
        target = _months_back(last, months)
        index = bisect.bisect_right(days, target, hi=len(days) - 1) - 1
        if index < 0 or (target - days[index]).days > MAX_GAP_DAYS:
            return result
        comparisons.append({"months": months, "date": days[index].isoformat(),
                            "returnPct": round(100 * (price / rows[index][1] - 1), 2),
                            "above": price > rows[index][1]})
    return {"status": "available", "asOf": last.isoformat(),
            "comparisons": comparisons,
            "confirmed": all(c["above"] for c in comparisons)}
