"""The past year of one asset's labels, bar by bar (`/api/labelhistory`).

Each bar's label is `trend.classify` over the three-month window the chart
would have drawn on that bar's day -- the walk `onset.py` already does to date
a run, kept there (`onset.history`) so the strip and the "since" date cannot
disagree. Nothing here judges anything new: it re-reads the one classifier on
past windows. It is history, worded as history, never as odds.

The bars are the one-year chart (`chart_data(symbol, "1y")`) plus the bars it
keeps behind its window (`historyTail`), so the first drawn bars have a full
three months behind them. A bond yield's labels are inverted the way its badge
is, so the strip says what the badge says.
"""

from __future__ import annotations

import nasdaq_bars
import onset
import pse
import tv

import server as S

SPAN = "1y"
WINDOW_SPAN = "3mo"
TTL = 3600  # seconds; a year of daily labels moves once a day

FLIP = {"bullish": "bearish", "bearish": "bullish"}


def build(symbol: str) -> dict:
    """The label history payload for `symbol`. Raises what `chart_data` raises."""
    data = S.chart_data(symbol, SPAN, "1d")
    points = [p for p in (data.get("points") or [])
              if isinstance(p, dict) and p.get("t") is not None and p.get("c") is not None]
    tail = [p for p in (data.get("historyTail") or [])
            if isinstance(p, dict) and p.get("t") is not None and p.get("c") is not None]
    full = tail + points
    stamps = [int(p["t"]) for p in full]
    closes = [float(p["c"]) for p in full]
    volumes = [p.get("v") or 0.0 for p in full]
    # The same window rule `chart_route` gives the badge for this source.
    months = (S.SPAN_MONTHS[WINDOW_SPAN]
              if data.get("source") in ("Yahoo", nasdaq_bars.SOURCE) else None)
    days = pse.RANGE_DAYS[WINDOW_SPAN]
    labels = onset.history(stamps, closes, volumes, first=len(tail),
                           days=days, months=months)
    inverted = tv.is_bond_symbol(symbol) or bool(data.get("yieldSeries"))
    if inverted:
        labels = [FLIP.get(x, x) for x in labels]
    return {
        "symbol": data.get("symbol") or symbol,
        "source": data.get("source"),
        "inverted": inverted,
        "t": stamps[len(tail):],
        "labels": labels,
        "summary": onset.history_summary(labels),
        # The zone the bars' dates are read in. A Philippine series (stock,
        # yield, fund) closes in Manila; stamped in UTC, a yield lands on the
        # day before.
        "timezone": data.get("timezone") or (
            "Asia/Manila" if (inverted or data.get("fundSeries")
                              or data.get("currency") == "PHP") else "UTC"),
        "cached": bool(data.get("cached")),
        "revalidate": bool(data.get("revalidate")),
        "fetchedAt": data.get("fetchedAt"),
    }


def history(symbol: str, fresh: bool = False) -> dict:
    """`build`, memoised for an hour under its own key. `fresh` drops the
    memo first: the page asks for that when its badge no longer matches the
    strip's newest label."""
    key = f"labelhistory:v1:{symbol.strip().upper()}"
    if fresh:
        with S._cache_lock:
            S._cache.pop(key, None)
    return S.cached(key, lambda: build(symbol), TTL)
