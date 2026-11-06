#!/usr/bin/env python3
"""Official daily reference rates from the European Central Bank.

Why this module exists
----------------------
Yahoo fabricates a history for currency crosses that have no dollar leg. Its
`EURPHP=X` daily series is not a market series at all: every week it prints a
"Sunday reopen" bar roughly three percent below the surrounding days (68.37 on
2026-10-04 against ~70.35 elsewhere), then recovers on Monday. The same
artifact shows on `EURJPY=X` and `EURGBP=X` in a milder form. The legs Yahoo
quotes (`EUR=X`, `PHP=X`) are honest; the cross it composes from them is not,
because the peso leg is illiquid and goes stale over the weekend while the
euro leg moves.

The ECB's daily reference fix is the authoritative answer. It publishes one
EUR-based rate per currency per *business day* -- no weekend bars exist, so
the phantom Sunday prints cannot appear. Frankfurter
(`api.frankfurter.dev`) serves the ECB dataset as JSON with no key, and it
triangulates any cross between the ~30 published currencies, so both
`EURPHP=X` and pairs like `EURJPY=X` can be charted honestly.

What this is *not*
------------------
A live quote. The ECB fix is one snapshot a day, fixed at ~16:00 Frankfurt
time, so the last bar is often yesterday's and today's fix does not exist
until late afternoon in Europe. The live price stays Yahoo's; this module
supplies only the *history*. Callers keep Yahoo's snapshot for the headline
and take these bars beneath it.

Why plain HTTP first
--------------------
Frankfurter answers plain HTTP clients (unlike Yahoo, which 429s them), so the
browser proxy is only a fallback, the same shape `crypto.py` uses for Binance.

Errors
------
`EcbError` is an outage -- the wire failed -- and the caller treats it as one
(disk rescue, warm skip). `LookupError` is a verdict -- the pair carries no
bars upstream -- and falls through to Yahoo the way "no such symbol" does.

Standard library only, so it imports only `trend` and shares the server's
"no dependencies" property.
"""

from __future__ import annotations

import calendar
import json
import re
import threading
import time
import urllib.request

import trend

API = "https://api.frankfurter.dev/v1"

# The currencies the ECB publishes. A pair outside this set (a `USDPHP=X` --
# that one Yahoo charts honestly anyway -- or a `TWDPHP=X`) is a verdict, not
# an outage: the caller falls back to Yahoo rather than spending a request to
# be told "no".
CURRENCIES = frozenset({
    "AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP", "HKD",
    "HUF", "IDR", "ILS", "INR", "ISK", "JPY", "KRW", "MXN", "MYR", "NOK",
    "NZD", "PHP", "PLN", "RON", "SEK", "SGD", "THB", "TRY", "USD", "ZAR",
})

# A six-letter pair, before the `=X` suffix the page's symbols carry.
FX_RE = re.compile(r"^[A-Z]{6}$")

# Bars to ask for, per range, at daily resolution -- the same table
# `crypto.py` keeps, so the range allowlist stays honest in one place.
RANGE_DAYS = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}

HTTP_TIMEOUT = 20
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AssetPriceDisplay/1.0"

# The daily fix is one snapshot a day, so a chart fetched at all today stays
# truthful until tomorrow's fix: a shorter TTL would re-fetch the same fixed
# bars without anything having changed underneath them. Six hours is what
# guarantees a refresh crosses the ~15:00 UTC publication moment: a chart
# fetched in the morning is re-fetched the same afternoon and gains the day's
# fix as its last bar.
DAY_TTL = 6 * 3600

# Hour of day every daily bar is stamped at: 15:00 UTC, the fix's own moment
# in winter and one hour behind it in summer. A calendar-time stamp keeps the
# *date* honest in every reader's timezone -- midnight UTC would render as the
# previous day for anyone west of Greenwich, and Yahoo's own 23:00-UTC FX
# stamps have that same off-by-one for them.
STAMP_HOUR = 15 * 3600

_lock = threading.Lock()
_history_cache: dict[str, tuple[float, dict]] = {}

# Set by the server so the module can fall back to the Moli browser path if a
# plain HTTP request is ever refused. Injected rather than imported to keep
# this module free of a cycle back into server.py.
_fallback = None


class EcbError(RuntimeError):
    """The ECB rates could not be fetched -- the wire, not the pair."""


def set_http_fallback(fn) -> None:
    """Register a `fn(url) -> (status, body)` used if plain HTTP fails."""
    global _fallback
    _fallback = fn


def _get_json(url: str) -> dict:
    """Fetch JSON, plain HTTP first, then the registered fallback."""
    last: Exception | None = None
    for via_plain in (True, False):
        try:
            if via_plain:
                req = urllib.request.Request(
                    url, headers={"User-Agent": UA, "Accept": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            if _fallback is None:
                break
            status, body = _fallback(url)
            if status >= 400:
                raise EcbError(f"HTTP {status}")
            return json.loads(body)
        except EcbError:
            raise
        except Exception as exc:  # urllib raises a wide net of OSErrors
            last = exc
    raise EcbError(f"ECB source unreachable ({url}): {last}")


def _history(base: str) -> dict:
    """Daily rates for `base`, fetched once per six hours and sliced per call.

    One wire call covers the longest range this server allows (`5y`), so every
    range a reader picks is served from the same fetch rather than re-fetched
    per span. Frankfurter's shape is
    `{"rates": {"2026-09-01": {"PHP": 72.355}, ...}}` with the base already
    applied.
    """
    with _lock:
        hit = _history_cache.get(base)
        if hit and time.time() - hit[0] < DAY_TTL:
            return hit[1]
    start = time.strftime(
        "%Y-%m-%d", time.gmtime(time.time() - RANGE_DAYS["5y"] * 86400))
    data = _get_json(f"{API}/{start}..?base={base}")
    rates = data.get("rates")
    if not isinstance(rates, dict) or not rates:
        raise EcbError("ECB source returned no rates")
    with _lock:
        _history_cache[base] = (time.time(), rates)
    return rates


def chartable(symbol: str) -> bool:
    """Whether this cross is fully inside the ECB's currency set.

    Accepts either spelling a caller might hold -- the page's `EURPHP=X` or
    the bare pair `EURPHP` -- because the route hands over the page's.
    """
    pair = symbol.upper()
    if pair.endswith("=X"):
        pair = pair[:-2]
    if not FX_RE.fullmatch(pair):
        return False
    return pair[:3] in CURRENCIES and pair[3:6] in CURRENCIES


def chart(symbol: str, span: str, interval: str) -> dict:
    """Daily/weekly bars for a cross, in the server's payload shape.

    Raises EcbError when the fetch fails (an outage, the caller's rescue) and
    LookupError when the pair is outside the ECB set or carries no bars (a
    verdict, the caller's fall back to Yahoo).

    A weekly interval folds the daily fixes into seven-day buckets and keeps
    each bucket's last fix at its own stamp -- the way a weekly bar's close is
    its Friday, dated the day it was fixed rather than the bucket boundary,
    which the epoch's Thursday start would mislabel by up to five days.
    """
    pair = symbol.upper()
    if pair.endswith("=X"):
        pair = pair[:-2]
    base, quote = pair[:3], pair[3:6]
    if base not in CURRENCIES or quote not in CURRENCIES:
        raise LookupError(f"{symbol} is outside the ECB currency set")

    rates = _history(base)
    days = sorted(d for d in rates if quote in rates.get(d, {}))
    try:
        points = [{"t": calendar.timegm(time.strptime(d, "%Y-%m-%d")) + STAMP_HOUR,
                   "c": round(float(rates[d][quote]), 6)}
                  for d in days]
    except (KeyError, TypeError, ValueError):
        raise LookupError(f"Malformed ECB rates for {symbol}") from None

    if not points:
        raise LookupError(f"No price data for {symbol}.")
    cutoff = time.time() - RANGE_DAYS.get(span, RANGE_DAYS["3mo"]) * 86400
    points = [p for p in points if p["t"] >= cutoff]
    if not points:
        raise LookupError(f"No price data for {symbol} in {span}.")

    if interval == "1wk":
        buckets: dict[int, tuple[int, float]] = {}
        for p in points:
            slot = buckets.get(p["t"] // (7 * 86400))
            if slot is None or p["t"] >= slot[0]:
                buckets[p["t"] // (7 * 86400)] = (p["t"], p["c"])
        points = [{"t": t, "c": c} for t, c in buckets.values()]

    # Same contract as the Yahoo path: every series is scored, however short,
    # and only unusable data (a non-positive price) leaves the badge off.
    trend_call = None
    try:
        trend_call = trend.classify([p["c"] for p in points])
    except ValueError:
        pass

    last = points[-1]["c"]
    previous = points[-2]["c"] if len(points) > 1 else None
    return {
        "symbol": symbol.upper(),
        "name": f"{base}/{quote}",
        "currency": quote,
        "exchange": "ECB",
        "type": "CURRENCY",
        "priceHint": 4,
        "previousClose": previous,
        "marketPrice": last,
        "points": points,
        "trend": trend_call,
        "source": "ECB reference rates",
    }
