"""The table's trading-volume figure: a 5-session average of value traded.

The recent tables' "Trading volume" column and the Philippine peso floor
read one number per row: the mean of close x volume over the last
`SESSIONS` **finished** daily bars (user rule 2026-11-23, replacing the
single latest bar). A forming bar -- today's session still trading -- is
left out, because half a day would drag the average down.

Where today's forming bar starts, per market (`*_cutoff`, a timestamp:
bars stamped at or after it are not finished; None means every bar is):

* PSE: before 15:15 Manila + the closing print's delay, today's bar is the
  session so far (the same clock `pse.completed_trade` reads).
* Crypto (Binance daily bars open at 00:00 UTC): today's UTC day is forming.
* New York: today's bar is forming on an open day until 15 minutes after the
  16:00 close.

A bar with no volume field is skipped (silence, not a zero); a bar that
traded nothing counts as zero. A series with no volume at all (an index)
has no figure: None, never 0.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import market_days
import pse

SESSIONS = 5

_MANILA = ZoneInfo("Asia/Manila")
_NY = ZoneInfo("America/New_York")
NY_CLOSE = dt.time(16, 0)
NY_SETTLE = dt.timedelta(minutes=15)


def average(stamps, closes, volumes, cutoff: float | None = None,
            sessions: int = SESSIONS) -> float | None:
    """Mean close x volume over the last `sessions` finished bars."""
    picked: list[float] = []
    for i in range(min(len(stamps), len(closes)) - 1, -1, -1):
        if cutoff is not None and stamps[i] >= cutoff:
            continue
        volume = volumes[i] if volumes is not None and i < len(volumes) else None
        close = closes[i]
        if volume is None or close is None or not close > 0:
            continue
        picked.append(float(close) * float(volume))
        if len(picked) == sessions:
            break
    if not picked or not any(picked):
        return None
    return sum(picked) / len(picked)


def _midnight(now: float, zone) -> tuple[dt.datetime, float]:
    here = dt.datetime.fromtimestamp(now, zone)
    start = dt.datetime.combine(here.date(), dt.time(0, 0), tzinfo=zone)
    return here, start.timestamp()


def pse_cutoff(now: float) -> float | None:
    here, midnight = _midnight(now, _MANILA)
    close_at = dt.datetime.combine(here.date(), pse.SESSION_CLOSE,
                                   tzinfo=_MANILA) + pse.CLOSING_PRINT_DELAY
    return midnight if here < close_at else None


def crypto_cutoff(now: float) -> float | None:
    return _midnight(now, dt.timezone.utc)[1]


def ny_cutoff(now: float) -> float | None:
    here, midnight = _midnight(now, _NY)
    if not market_days.nyse_open_day(here.date()):
        return None
    settle = dt.datetime.combine(here.date(), NY_CLOSE, tzinfo=_NY) + NY_SETTLE
    return midnight if here < settle else None
