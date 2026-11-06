#!/usr/bin/env python3
"""Weekend peso prices, from Coins.ph's USDC/PHP order book.

Why this module exists
----------------------
The peso pair does not trade at the weekend. Yahoo charts USD/PHP (`PHP=X`,
which is also spelled `USDPHP=X` -- one series, two spellings) on the FX week:
bars Monday to Friday, closing Friday evening Manila time, reopening Monday
morning. A reader who opens the chart on a Saturday or a Sunday therefore sees
Friday's close and nothing more.

Coins.ph's USDC/PHP book trades every day of the week, and USDC is a dollar
token, so its peso price is a peso-per-dollar reading on the days the
interbank market is shut. Measured 2026-11-01 against Yahoo's own series:

* 400 daily bars back to 2025-09-28, every calendar day present -- 57 of each
  weekday, Saturdays and Sundays included. `klines?limit=1000` reaches
  2024-02-06.
* Across 259 shared days the stablecoin ran a median 0.09 and a mean 0.13
  pesos *above* the interbank rate (sd 0.20, range -0.29 to +1.50). That head
  is a domestic premium, not a rate: it is why a weekend bar is spliced in at
  the stablecoin's own price and the chart says whose price it is, rather than
  being smoothed into Yahoo's Friday close.

What it is *not*
----------------
A USD/PHP rate. Across 51 measured weekends the stablecoin's Friday->Sunday
move had a 0.07 correlation with the interbank's Friday->Monday move (same
direction 27 times out of 51), and a 0.12% standard deviation against the
interbank's 0.52%. The weekend book is quiet and domestic; the offshore market
that reopens on Monday is where the peso actually moves. So the weekend bars
say what people were paying for a dollar in pesos on Coins.ph that day, and
nothing more -- they are drawn, and the badge scores them because the badge
scores the bars the chart draws, but they are not a forecast of the reopen.

Which days are the weekend
--------------------------
Manila's, because the reader's weekend is the one being filled. Every stamp is
read as the Manila calendar day it falls in (UTC+8), which is also what makes
Yahoo's series line up: its bars are stamped at 00:00 or 23:00 UTC of the
trading day, and the FX week's Sunday 21:00 GMT reopen is *Monday* 05:00 in
Manila -- so under this reading a year of Yahoo's bars hold 52 Mondays and 52
Fridays, no Sundays at all, and exactly one stray Saturday (a forming bar
carrying Friday's price, stamped at the moment Yahoo last refreshed).

A Saturday or Sunday Yahoo did print is *replaced*, not kept: that forming bar
holds Friday's close under a Saturday stamp, which is precisely the gap this
module exists to fill. A weekday is never touched.

Errors
------
`CoinsError` is an outage -- the wire failed -- and the caller keeps Yahoo's
bars and says nothing about it. There is no verdict error: this module only
ever *adds* to a chart, so nothing it does can turn a symbol into a 404.

Standard library only, plus this project's own `diskcache`, so it imports
nothing heavy and shares the durability rule every other source here follows.
"""

from __future__ import annotations

import datetime
import json
import threading
import time
import urllib.request

import diskcache

PAIR = "USDCPHP"

# The exchange's own kline endpoint, Coinbase-Pro shaped: rows of
# [openTime, open, high, low, close, volume, closeTime, ...]. Daily buckets open
# at 00:00 UTC, which is 08:00 in Manila -- so a bar's date is the same on both
# clocks, and the key this module files it under is the one it is drawn at.
KLINES = "https://api.pro.coins.ph/openapi/quote/v1/klines"

# Bars to ask for. 1000 is the endpoint's own ceiling and reaches a bit over two
# and a half years, so a five-year chart is filled back as far as the source
# goes and left as Yahoo drew it before that.
LIMIT = 1000

DAY = 86400

# Manila is the weekend being filled, so every stamp is bucketed by the Manila
# calendar day: a bar stamped 21:00 UTC Sunday is Monday 05:00 in Manila, the
# hour the FX week reopens, and belongs to Monday.
MANILA = 8 * 3600

# The Yahoo symbols this reading belongs to. `PHP=X` is the peso *per dollar*
# leg -- Yahoo's own spelling of USD/PHP, the same series `USDPHP=X` charts.
SYMBOLS = frozenset({"PHP=X", "USDPHP=X"})

CACHE_KEY = "coinsph:kline:" + PAIR

# The page re-reads a live chart every minute, and on a weekend the newest bar
# *is* the current price, so the copy is kept no longer than the chart's own
# minute. One fetch serves every span.
CACHE_TTL = 60

# A copy worth showing when the wire is down: a weekend close is a daily close,
# so a week-old one is still a fact about a weekend that has passed. Past that
# the chart reads as Yahoo drew it rather than as a stale crop.
CACHE_KEEP = 7 * DAY

HTTP_TIMEOUT = 20
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AssetPriceDisplay/1.0"

_lock = threading.Lock()
_cache: tuple[float, dict[int, float]] | None = None

# Set by the server so the module can fall back to the Moli browser path if a
# plain HTTP request is refused -- the same injection `ecb.py` uses, so neither
# module has to import the server back.
_fallback = None


class CoinsError(RuntimeError):
    """The Coins.ph book could not be read -- the wire, not the instrument."""


def set_http_fallback(fn) -> None:
    """Register a `fn(url) -> (status, body)` used if plain HTTP fails."""
    global _fallback
    _fallback = fn


def _get_json(url: str):
    """Fetch JSON, plain HTTP first, then the registered fallback."""
    last: Exception | None = None
    for via_plain in (True, False):
        try:
            if via_plain:
                req = urllib.request.Request(
                    url, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            if _fallback is None:
                break
            status, body = _fallback(url)
            if status >= 400:
                raise CoinsError(f"HTTP {status}")
            return json.loads(body)
        except CoinsError:
            raise
        except Exception as exc:  # urllib raises a wide net of errors
            last = exc
    raise CoinsError(f"Coins.ph unreachable ({url}): {last}")


def _parse(rows) -> dict[int, float]:
    """Kline rows -> {day: close}, keyed by the UTC midnight each bar opens at.

    The endpoint stamps its rows in *milliseconds* (`1793491200000` for
    2026-11-01), so the open time is scaled to epoch seconds before it becomes a
    day key -- a millisecond stamp read as seconds lands in the year 58,000 and
    every weekend would fall outside every window.
    """
    if not isinstance(rows, list):
        raise CoinsError("Coins.ph returned no kline rows")
    by_day: dict[int, float] = {}
    for row in rows:
        try:
            opened = int(int(row[0]) // 1000)      # milliseconds -> seconds
            close = float(row[4])
        except (IndexError, TypeError, ValueError):
            continue        # a shape this module does not understand
        if opened <= 0 or not close > 0:
            continue        # a bar with no trade behind it
        by_day[opened - opened % DAY] = round(close, 6)
    if not by_day:
        raise CoinsError("Coins.ph returned no usable USDC/PHP bars")
    return by_day


def _fetch() -> dict[int, float]:
    return _parse(_get_json(f"{KLINES}?symbol={PAIR}&interval=1d&limit={LIMIT}"))


def daily() -> tuple[dict[int, float], float, bool]:
    """USDC/PHP daily closes, the age of the reading, and whether it is a fallback.

    One fetch serves every chart and every span: the series is five hundred
    kilobytes of the same calendar, and a reader looking at a one-month and a
    one-year window is asking about the same weekends.

    * a copy inside `CACHE_TTL` is used without asking anyone;
    * otherwise the exchange is asked, and a good answer is kept;
    * when it does not answer, a copy up to `CACHE_KEEP` old is returned and the
      third element says so, so the page can print how old the weekend reading
      is instead of passing it off as this minute's.

    Raises `CoinsError` when the exchange did not answer and there is nothing
    worth showing.
    """
    global _cache
    now = time.time()
    with _lock:
        hit = _cache
    if hit and now - hit[0] <= CACHE_TTL:
        return hit[1], now - hit[0], False

    try:
        bars = _fetch()
    except CoinsError:
        with _lock:
            hit = _cache
        if hit and now - hit[0] <= CACHE_KEEP:
            return hit[1], now - hit[0], True
        saved = diskcache.load(CACHE_KEY)
        if saved is not None:
            fetched_at, stored = saved
            age = now - float(fetched_at)
            try:
                bars = {int(k): float(v) for k, v in stored.items()}
            except (AttributeError, TypeError, ValueError):
                bars = {}
            if bars and age <= CACHE_KEEP:
                with _lock:
                    _cache = (float(fetched_at), bars)
                return bars, age, True
        raise

    with _lock:
        _cache = (now, bars)
    try:
        diskcache.store(CACHE_KEY, {str(k): v for k, v in bars.items()})
    except Exception:
        pass                      # a cache that cannot be written costs a fetch
    return bars, 0.0, False


def is_usd_php(symbol: str) -> bool:
    """Whether a charted symbol is the peso pair -- Yahoo's two spellings of it."""
    return (symbol or "").strip().upper() in SYMBOLS


def manila_day(stamp: float) -> int:
    """The Manila calendar day a stamp falls in, as a UTC-midnight epoch second.

    The returned number is both the bar's day key and the stamp a filled bar is
    drawn at: 00:00 UTC is 08:00 in Manila, so it labels the same date on both
    clocks and sits in the chart's own daily rhythm.
    """
    return int(stamp + MANILA) // DAY * DAY


def is_weekend(day: int) -> bool:
    """Whether a Manila day key is a Saturday or a Sunday."""
    return datetime.datetime.fromtimestamp(
        day, datetime.timezone.utc).weekday() >= 5


def fill(points: list[dict], now: float | None = None) -> tuple[list[dict], list[int], float]:
    """Splice Coins.ph's Saturdays and Sundays into a USD/PHP series.

    Returns the series (sorted, weekdays untouched), the stamps of the bars the
    stablecoin supplied, and the age of that reading. A day Yahoo drew on a
    weekend is replaced by the stablecoin's close; a weekday never is.

    The fill runs to *today*, not to the last bar Yahoo drew: on a Monday
    morning before the FX week reopens -- 05:00 Manila -- Yahoo's series still
    ends on Friday, and a weekend that existed must not be missing from the
    chart because the other source has not caught up yet.

    Raises `CoinsError` from `daily` when the book cannot be read at all; the
    caller keeps Yahoo's bars and says nothing.
    """
    bars, age, _stale = daily()
    if not points:
        return list(points), [], age

    now = time.time() if now is None else now
    today = manila_day(now)
    first = manila_day(points[0]["t"])

    by_day: dict[int, dict] = {}
    for point in points:
        by_day[manila_day(point["t"])] = point

    proxy: list[int] = []
    for day, close in bars.items():
        if day < first or day > today or not is_weekend(day):
            continue
        by_day[day] = {"t": day, "c": close}
        proxy.append(day)
    if not proxy:
        return list(points), [], age
    return [by_day[key] for key in sorted(by_day)], sorted(proxy), age
