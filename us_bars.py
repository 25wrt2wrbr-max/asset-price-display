"""The stored year of United States daily bars behind the recent table.

The recent sweep judges every shelf name on a year of daily bars, and it used to
download that whole year for every name on every sweep. Old daily bars do not
change, so the year is kept here and a sweep asks Yahoo only for the last month
(`TAIL_SPAN`), which is laid over the stored year (`merge`).

What keeps the result the same series a full download would give:

* The stored thing is **bars, never rows or verdicts**. The window and the
  stale check read the clock, so the walk re-runs on every sweep.
* The fresh month **replaces** every stored bar it covers, the stored newest
  bar included (that one may carry the extended-hours price).
* Before the two are joined, the closes they share are compared. Any
  difference (a split, a restated close), any missing day, or too little
  overlap refuses the join, and the caller downloads the full year instead.
* The full year is downloaded again once a day regardless (`FULL_EVERY`).

It also answers "can this name have changed since it was last read?"
(`settled`): outside New York's 04:00-20:00 trading on weekdays that are not
NYSE holidays, a name read after
that close is read again only once an hour (`CLOSED_REREAD`) instead of on
every sweep. Futures trade almost round the clock and are never slowed.

Standard library only. No network here: `sweeps.fetch_us_bars` does the asking.
"""

from __future__ import annotations

import bisect
import datetime as dt
import threading
import time
from zoneinfo import ZoneInfo

import diskcache
import faults
import market_days

KEY = "recent:usbars:v1"

# What a sweep asks Yahoo for once the year is stored. A month is about 22
# bars: far more overlap than the check needs, and still a seventh of the year.
TAIL_SPAN = "1mo"

# The whole year is downloaded again this often, whatever the overlap says --
# the bars older than the tail are only ever checked by this.
FULL_EVERY = 24 * 3600

# Stored bars the fresh tail must confirm (the stored newest is not counted:
# it may be the extended-hours price, which is allowed to differ).
MIN_OVERLAP = 3

# New York's trading day as Yahoo prices it: pre-market opens 04:00 and
# after-hours ends 20:00, and the newest bar carries those prices.
NEW_YORK = "America/New_York"
_NY = ZoneInfo(NEW_YORK)
EXT_OPEN = dt.time(4, 0)
EXT_CLOSE = dt.time(20, 0)
# A read this long after the close has the day's last price in it.
SETTLE = 15 * 60
# While closed, a settled name is still re-read this often rather than never.
CLOSED_REREAD = 3600

_lock = threading.Lock()
_base: dict[str, dict] | None = None    # None: not read from disk yet
_saved_at = 0.0


def closed_since(now: float) -> float | None:
    """When New York's current closed stretch began, or None while it trades.

    A scheduled NYSE holiday (`market_days.nyse_holiday`) is closed like a
    weekend, so a Monday holiday is closed since Friday's 20:00. A closure no
    rule predicts reads as an open day, which costs the fetches it would have
    cost anyway and never serves an old bar as current.
    """
    here = dt.datetime.fromtimestamp(now, _NY)
    today = here.date()
    if (market_days.nyse_open_day(today)
            and EXT_OPEN <= here.time() < EXT_CLOSE):
        return None
    day = today
    if not market_days.nyse_open_day(today) or here.time() < EXT_OPEN:
        day -= dt.timedelta(days=1)
    for _ in range(14):              # bounded: weekends plus holidays
        if market_days.nyse_open_day(day):
            break
        day -= dt.timedelta(days=1)
    return dt.datetime.combine(day, EXT_CLOSE, tzinfo=_NY).timestamp()


def settled(record: dict, symbol: str, now: float) -> bool:
    """True when `symbol` cannot have moved since it was last read.

    Only a New York listing, only while New York is closed, only when the last
    read landed after that close had settled -- and only for an hour.
    """
    if str(symbol).upper().endswith("=F") or record.get("tz") != NEW_YORK:
        return False
    closed = closed_since(now)
    if closed is None:
        return False
    read_at = float(record.get("readAt") or 0)
    return read_at >= closed + SETTLE and now - read_at < CLOSED_REREAD


def _days(stamps, zone_name: str):
    try:
        zone = ZoneInfo(zone_name or "UTC")
        return [dt.datetime.fromtimestamp(stamp, zone).date() for stamp in stamps]
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None


def _same(a, b) -> bool:
    return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a)))


def merge(base, tail, zone_name: str):
    """`base` with `tail` laid over its end, or None when they do not fit.

    Both are `(stamps, closes, volumes)`. Bars are matched by the exchange's
    calendar day, not the raw stamp, because a bar still forming can be stamped
    at its last trade instead of the session's open. None means "download the
    whole year": the caller must never guess.
    """
    b_stamps, b_closes, b_volumes = base
    t_stamps, t_closes, t_volumes = tail
    if not b_stamps or not t_stamps:
        return None
    b_days = _days(b_stamps, zone_name)
    t_days = _days(t_stamps, zone_name)
    if b_days is None or t_days is None:
        return None
    for days in (b_days, t_days):
        # In order, one bar a day -- except the newest day, which Yahoo may
        # print twice while it is still trading (the bar and the live print).
        if any(later < earlier or (later == earlier and later != days[-1])
               for earlier, later in zip(days, days[1:])):
            return None
    keep = bisect.bisect_left(b_days, t_days[0])
    at = {day: index for index, day in enumerate(t_days)}
    if b_days[-1] not in at:
        return None
    # Every stored bar the tail covers, the stored newest day left out.
    overlap = range(keep, bisect.bisect_left(b_days, b_days[-1]))
    # A series that stopped weeks ago has a month with only a bar or two in
    # it; all of those must be confirmed, and that is all that can be.
    if len(overlap) < min(MIN_OVERLAP, len(set(t_days)) - 1):
        return None
    for index in overlap:
        match = at.get(b_days[index])
        if match is None or not _same(b_closes[index], t_closes[match]):
            return None             # a day the tail lacks, or a changed close
    stored = set(b_days[keep:])
    if any(day <= b_days[-1] and day not in stored for day in t_days):
        return None                 # a day the stored year lacks
    return (list(b_stamps[:keep]) + list(t_stamps),
            list(b_closes[:keep]) + list(t_closes),
            list(b_volumes[:keep]) + list(t_volumes))


def _load() -> dict[str, dict]:
    global _base
    with _lock:
        if _base is None:
            saved = diskcache.load(KEY)
            value = saved[1] if saved else None
            _base = value if isinstance(value, dict) else {}
        return _base


def reset() -> None:
    """Forget everything, and do not read the disk copy (for tests)."""
    global _base, _saved_at
    with _lock:
        _base = {}
        _saved_at = 0.0


def get(symbol: str) -> dict | None:
    record = _load().get(symbol)
    if not isinstance(record, dict):
        return None
    try:
        if not (len(record["s"]) == len(record["c"]) == len(record["v"]) > 0):
            return None
    except (KeyError, TypeError):
        return None
    return record


def series(record: dict) -> tuple:
    """`(stamps, closes, volumes, meta)` as copies a caller may keep."""
    return (list(record["s"]), list(record["c"]), list(record["v"]),
            dict(record.get("meta") or {}))


def put(symbol: str, bars, meta: dict, zone_name: str, now: float,
        full: bool) -> None:
    """Remember `bars` for `symbol`. `full` says a whole year was downloaded."""
    store = _load()
    stamps, closes, volumes = bars
    with _lock:
        previous = store.get(symbol) or {}
        store[symbol] = {
            "s": list(stamps), "c": list(closes), "v": list(volumes),
            "meta": dict(meta or {}), "tz": zone_name or "",
            "fullAt": now if full else float(previous.get("fullAt") or 0),
            "readAt": now,
        }


def drop(symbol: str) -> None:
    store = _load()
    with _lock:
        store.pop(symbol, None)


def save(now: float | None = None) -> None:
    """File the whole store on disk as one record, so a restart starts warm."""
    global _saved_at
    store = _load()
    with _lock:
        snapshot = dict(store)
        _saved_at = time.time() if now is None else now
    try:
        diskcache.store(KEY, snapshot)
    except Exception as exc:     # best effort, like every other disk write
        faults.note("US bars store", exc)


def saved_at() -> float:
    return _saved_at
