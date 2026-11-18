"""Exchange holidays: which weekdays the Philippine and New York markets are shut.

Used for one thing only: **how often the background sweeps re-read prices**.
A holiday is treated like a weekend, so the sweep drops to its closed-market
pace instead of re-reading a market that cannot move. Nothing here touches
bars, windows, the "since when" walk or a label.

Why it is safe to be wrong in one direction only
-------------------------------------------------
A holiday this module does not know reads as an open day: the sweep runs at
its normal pace, which is exactly what happened before this module existed.
A day wrongly called a holiday would slow the sweep while prices move, so the
callers keep their hourly re-read cap even on a holiday, and the two calendars
below only claim days they have a source for.

New York (NYSE)
---------------
Fixed rules (NYSE Rule 7.2 and the published calendar, read 2026-11-18 from
nyse.com/markets/hours-calendars for 2026-2028): New Year's Day, Martin Luther
King Jr. Day, Washington's Birthday, Good Friday, Memorial Day, Juneteenth
(from 2022), Independence Day, Labor Day, Thanksgiving and Christmas. A
holiday on a Sunday is observed the Monday after, on a Saturday the Friday
before -- except New Year's Day, which is then not observed at all (the
Friday is the last trading day of the year). One-off closures (a national
day of mourning) are not predictable and are not listed; they read as open.
Early-close days are full trading days here.

Philippines (PSE)
-----------------
The Philippine holidays are proclaimed year by year, and special non-working
days are often added late, so they are not hard-coded. TradingView's
`symbol_resolved` frame carries the exchange's own list
(`session_holidays`: comma-separated YYYYMMDD), and the PSE socket already
receives that frame on every read. `remember_pse` keeps the newest list on
disk (a plain record, never aged out); `pse_holiday` answers from it. Before the first read, or for a year
TradingView has not listed yet, every weekday reads as open.

Standard library only.
"""

from __future__ import annotations

import datetime as dt
import threading

import diskcache
import faults

PSE_KEY = "pse:holidays:v1"

_lock = threading.Lock()
_pse: frozenset | None = None      # None: not read from disk yet
_pse_raw: str | None = None


# -- New York ---------------------------------------------------------------------

def _easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (the anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """The n-th `weekday` (Mon=0) of a month; n=-1 is the last one."""
    if n > 0:
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: dt.date) -> dt.date:
    """Saturday -> the Friday before, Sunday -> the Monday after."""
    if day.weekday() == 5:
        return day - dt.timedelta(days=1)
    if day.weekday() == 6:
        return day + dt.timedelta(days=1)
    return day


def nyse_holidays(year: int) -> frozenset:
    """Every full-day NYSE closure in `year` that a fixed rule predicts."""
    days = set()
    new_year = dt.date(year, 1, 1)
    if new_year.weekday() == 6:
        days.add(new_year + dt.timedelta(days=1))
    elif new_year.weekday() != 5:          # Saturday: not observed at all
        days.add(new_year)
    days.add(_nth_weekday(year, 1, 0, 3))   # Martin Luther King Jr. Day
    days.add(_nth_weekday(year, 2, 0, 3))   # Washington's Birthday
    days.add(_easter(year) - dt.timedelta(days=2))   # Good Friday
    days.add(_nth_weekday(year, 5, 0, -1))  # Memorial Day
    if year >= 2022:
        days.add(_observed(dt.date(year, 6, 19)))   # Juneteenth
    days.add(_observed(dt.date(year, 7, 4)))        # Independence Day
    days.add(_nth_weekday(year, 9, 0, 1))   # Labor Day
    days.add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving
    days.add(_observed(dt.date(year, 12, 25)))      # Christmas
    return frozenset(days)


_nyse_memo: dict = {}


def nyse_holiday(day: dt.date) -> bool:
    """True when the NYSE is shut all day on `day` for a scheduled holiday."""
    year = day.year
    if year not in _nyse_memo:
        _nyse_memo[year] = nyse_holidays(year)
    return day in _nyse_memo[year]


def nyse_open_day(day: dt.date) -> bool:
    """A weekday that is not a scheduled NYSE holiday."""
    return day.weekday() < 5 and not nyse_holiday(day)


# -- Philippines --------------------------------------------------------------------

def parse_holidays(text) -> frozenset:
    """TradingView's `session_holidays` ("20260101,20260217,...") -> dates.

    Anything that is not an eight-digit date is skipped, so a malformed entry
    costs that entry, never the list.
    """
    out = set()
    for part in str(text or "").split(","):
        part = part.strip()
        if len(part) != 8 or not part.isdigit():
            continue
        try:
            out.add(dt.date(int(part[:4]), int(part[4:6]), int(part[6:])))
        except ValueError:
            continue
    return frozenset(out)


def _load_pse() -> frozenset:
    global _pse
    with _lock:
        if _pse is not None:
            return _pse
        days: frozenset = frozenset()
        try:
            days = parse_holidays(diskcache.load_plain(PSE_KEY))
        except Exception as exc:
            faults.note("PSE holiday list read", exc)
        _pse = days
        return _pse


def remember_pse(text) -> None:
    """Keep the exchange's holiday list from a `symbol_resolved` frame.

    Ignored when it parses to nothing (a frame without the field must not wipe
    a good list). Written to disk only when it changed.
    """
    global _pse, _pse_raw
    if not isinstance(text, str) or text == _pse_raw:
        return
    days = parse_holidays(text)
    if not days:
        return
    current = _load_pse()
    with _lock:
        _pse = days
        _pse_raw = text
    if days != current:
        try:
            diskcache.store_plain(PSE_KEY, text)
        except Exception as exc:
            faults.note("PSE holiday list write", exc)


def pse_holiday(day: dt.date) -> bool:
    """True when the Philippine exchange's own list names `day` a holiday."""
    return day in _load_pse()


def pse_open_day(day: dt.date) -> bool:
    """A weekday the Philippine exchange has not listed as a holiday."""
    return day.weekday() < 5 and not pse_holiday(day)


def reset() -> None:
    """Forget the in-memory PSE list (tests)."""
    global _pse, _pse_raw
    with _lock:
        _pse = None
        _pse_raw = None
