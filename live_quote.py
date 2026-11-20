"""A fast price read for the chart on screen: `/api/quote?symbol=`.

The chart route is built for the three-month picture and is memoised for a
minute (`CACHE_TTL`), and the page re-reads it once a minute, so the hero
price could trail the market by up to two minutes. This asks Yahoo for today's
one-minute bars (extended hours included) and returns only the newest print,
kept for `QUOTE_TTL` seconds so several tabs share one browser run. It never
touches the chart cache, the classifier or the disk cache.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse

import ondo
import phfunds
import pse
import tv

import server as S

QUOTE_TTL = 1.0  # seconds; one Moli run is ~1 s

_lock = threading.Lock()
_memo: dict[str, tuple[float, dict]] = {}
_flight: dict[str, threading.Event] = {}


def is_yahoo_symbol(symbol: str) -> bool:
    s = symbol.strip().upper()
    return bool(s) and not (tv.is_bond_symbol(s) or pse.is_pse_symbol(s)
                            or phfunds.is_fund_symbol(s) or ondo.is_ondo_symbol(s)
                            or s.startswith(phfunds.PREFIX) or s.startswith(ondo.PREFIX))


def newest_print(payload: dict) -> dict | None:
    """`{price, t}` of the newest usable print in a Yahoo 1m chart answer."""
    try:
        res = payload["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        return None
    meta = res.get("meta") or {}
    stamps = res.get("timestamp") or []
    closes = (((res.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    for t, c in zip(reversed(stamps), reversed(closes)):
        if isinstance(c, (int, float)) and not isinstance(c, bool) and c > 0:
            price, stamp = float(c), int(t)
            break
    else:
        price = meta.get("fulldayPrice") or meta.get("regularMarketPrice")
        stamp = meta.get("regularMarketTime")
        if not isinstance(price, (int, float)) or price <= 0:
            return None
        price = float(price)
    # The meta price is the session's own print and can be newer than the
    # last finished minute bar.
    mt = meta.get("regularMarketTime")
    mp = meta.get("fulldayPrice") or meta.get("regularMarketPrice")
    if (isinstance(mt, int) and isinstance(mp, (int, float)) and mp > 0
            and (stamp is None or mt >= stamp)):
        price, stamp = float(mp), mt
    return {"price": round(price, 6), "t": int(stamp or time.time())}


def _fetch(symbol: str) -> dict:
    url = ("https://%s/v8/finance/chart/%s?range=1d&interval=1m&includePrePost=true"
           % (S.CHART_HOST, urllib.parse.quote(symbol, safe="")))
    status, body = S.moli_get(url)
    if status >= 500:
        raise S.UpstreamError("Upstream HTTP %s" % status)
    try:
        payload = json.loads(body)
    except ValueError:
        raise S.UpstreamError("Upstream returned non-JSON (HTTP %s)" % status)
    got = newest_print(payload)
    if got is None:
        raise LookupError("no live price for %r" % symbol)
    got["symbol"] = ((payload.get("chart", {}).get("result") or [{}])[0]
                     .get("meta", {}).get("symbol")) or symbol
    return got


def quote(symbol: str) -> dict:
    """The newest print for `symbol`, at most `QUOTE_TTL` seconds old."""
    key = symbol.strip().upper()
    while True:
        with _lock:
            hit = _memo.get(key)
            if hit and time.monotonic() - hit[0] <= QUOTE_TTL:
                return dict(hit[1])
            wait = _flight.get(key)
            if wait is None:
                _flight[key] = threading.Event()
                break
        wait.wait(15)
    try:
        got = _fetch(symbol.strip())
        with _lock:
            _memo[key] = (time.monotonic(), got)
        return dict(got)
    finally:
        with _lock:
            _flight.pop(key).set()
