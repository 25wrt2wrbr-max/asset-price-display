"""Peso cash rates: the BSP policy rate and short government bill yields.

What it shows, and why from here
--------------------------------
The rates strip on the morning desk is the yardstick every peso holding is
measured against: what cash earns. Two numbers answer that:

* the **BSP policy rate** (target reverse repurchase rate), and
* the **yields on short government bills** -- 1 month, 3 months, 6 months,
  1 year.

The central bank's own site (bsp.gov.ph) answers scripts and the Moli browser
with "Access Denied", and treasury.gov.ph sits behind a bot wall, so neither
can be read (checked 2026-11-26). TradingView carries both, on the same chart
socket the page already uses for the 2/5/10-year bond yields:
`ECONOMICS:PHINTR` (one bar per policy change -- 5.50% from 2026-10-22, which
matches the Monetary Board's announcement that day) and `TVC:PH01MY`,
`TVC:PH03MY`, `TVC:PH06MY`, `TVC:PH01Y` (daily).

The bill numbers are **market yields**, what the bills trade at -- not the
Treasury's auction results. The strip says so in words.

Nothing here touches `trend.classify`, and nothing is labelled bullish or
bearish: these are levels, shown as levels. The symbols are deliberately not
in `tv.BONDS`, so they never become rows in the recent table.

A tenor that did not arrive is left out (never printed as 0); if nothing
arrived at all the fetch raises `pse.PseError`, an outage, and `S.cached`
serves the last saved copy stamped as such.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pse

import server as S

POLICY = "ECONOMICS:PHINTR"
BILLS = (
    ("TVC:PH01MY", "1 month"),
    ("TVC:PH03MY", "3 months"),
    ("TVC:PH06MY", "6 months"),
    ("TVC:PH01Y", "1 year"),
)
SYMBOLS = (POLICY,) + tuple(symbol for symbol, _tenor in BILLS)

KEY = "phrates:v2"          # v2 added cashHistory
TTL = 3600               # bills move once a day; the policy rate a few times a year
BARS = 130               # ~6 months of daily bills (the beat-cash line looks
                         # up the yield on a chart's first day); years of policy
CASH = "TVC:PH03MY"      # the bill the "against cash" line compares with
CHANGE_BARS = 5          # "this week": the yield 5 trading days back
STILL_BARS = 3           # a yield unchanged this many bars says when it last moved

_MANILA = ZoneInfo("Asia/Manila")


def _day(stamp) -> str:
    """A bar stamp as its Manila date. Daily bills are stamped 22:00 UTC (6 am
    Manila, the trading day they belong to); policy bars 00:00 UTC on the day."""
    return dt.datetime.fromtimestamp(int(stamp), _MANILA).date().isoformat()


def _round(value: float) -> float:
    return round(float(value), 3)


def _since(rows: list) -> int:
    """Index of the first bar of the trailing run of equal closes."""
    i = len(rows) - 1
    while i > 0 and rows[i - 1][4] == rows[-1][4]:
        i -= 1
    return i


def policy_row(rows: list) -> dict | None:
    """{rate, since, previous} from the policy series, or None if empty."""
    rows = [r for r in rows or [] if len(r) >= 5 and r[4] is not None]
    if not rows:
        return None
    start = _since(rows)
    return {
        "rate": _round(rows[-1][4]),
        "since": _day(rows[start][0]),
        "previous": _round(rows[start - 1][4]) if start > 0 else None,
    }


def bill_row(symbol: str, tenor: str, rows: list) -> dict | None:
    """{symbol, tenor, yield, asOf, unchangedSince, changeWeek} or None."""
    rows = [r for r in rows or [] if len(r) >= 5 and r[4] is not None]
    if not rows:
        return None
    start = _since(rows)
    still = len(rows) - start            # bars the yield has sat at this level
    back = rows[-1 - CHANGE_BARS] if len(rows) > CHANGE_BARS else None
    return {
        "symbol": symbol,
        "tenor": tenor,
        "yield": _round(rows[-1][4]),
        "asOf": _day(rows[-1][0]),
        # A thin tenor can be carried forward for days with the same print;
        # then the honest date is when it last moved, not today.
        "unchangedSince": _day(rows[start][0]) if still >= STILL_BARS and start > 0 else None,
        "changeWeek": _round(rows[-1][4] - back[4]) if back else None,
    }


def build(bars: dict) -> dict:
    """The strip's payload from `{symbol: rows}` (rows `[t, o, h, l, c, ...]`).
    Raises `pse.PseError` when no series arrived at all -- an outage."""
    policy = policy_row(bars.get(POLICY) or [])
    bills = [row for row in (bill_row(symbol, tenor, bars.get(symbol) or [])
                             for symbol, tenor in BILLS) if row]
    if policy is None and not bills:
        raise pse.PseError("no peso rate series arrived from TradingView")
    return {
        "policy": policy,
        "bills": bills,
        # [day, yield] for the 3-month bill, oldest first: what cash earned
        # from any start day, for the chart's "against cash" line.
        "cashHistory": [[_day(r[0]), _round(r[4])] for r in bars.get(CASH) or []
                        if len(r) >= 5 and r[4] is not None],
        "missing": [symbol for symbol in SYMBOLS if not bars.get(symbol)],
        "source": "TradingView",
        "fetchedAt": int(dt.datetime.now(dt.timezone.utc).timestamp()),
    }


def produce() -> dict:
    return build(pse.history_many(list(SYMBOLS), count=BARS))


def snapshot() -> dict:
    """The rates, at most hourly from the network, a saved copy in an outage."""
    return S.cached(KEY, produce, TTL)


def saved() -> dict | None:
    """The last saved snapshot from disk, without any network call."""
    stored = S.diskcache.load(KEY)
    return stored[1] if stored and isinstance(stored[1], dict) else None
