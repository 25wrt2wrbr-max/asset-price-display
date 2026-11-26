"""A fast price read for the chart on screen: `/api/quote?symbol=`.

The chart route is built for the three-month picture and is memoised for a
minute (`CACHE_TTL`), and the page re-reads it once a minute, so the hero
price could trail the market by up to two minutes. This asks Yahoo for today's
one-minute bars (extended hours included) and returns only the newest print,
kept for `QUOTE_TTL` seconds so several tabs share one browser run. It never
writes the chart cache, the classifier or the disk cache.

Fast path (2026-11-25): when the same symbol's default chart (`CHART_SPAN` /
`CHART_INTERVAL`, the page's `RANGE` / `INTERVAL`) sits in the memory memo,
is younger than `QUOTE_TTL`, and its newest bar is a live / pre / after print,
the quote is read from that bar and no browser is launched. It only reads the
memo; the label still comes from the chart route alone.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse

import faults
import ondo
import phfunds
import pse
import tv

import server as S

QUOTE_TTL = 25.0  # seconds; just under the page's 30 s poll, so tabs share a run
MEMO_MAX = 256  # symbols kept before stale ones are dropped
CHART_SPAN = "3mo"     # the page's default chart (static/core.js RANGE)
CHART_INTERVAL = "1d"  # ... and INTERVAL
LIVE_BASES = ("live", "pre", "after")

_lock = threading.Lock()
_memo: dict[str, tuple[float, dict]] = {}
_flight: dict[str, threading.Event] = {}


def is_yahoo_symbol(symbol: str) -> bool:
    s = symbol.strip().upper()
    return bool(s) and not (tv.is_bond_symbol(s) or pse.is_pse_symbol(s)
                            or s.startswith("EDGE:")
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


def from_chart(symbol: str) -> dict | None:
    """The quote read off the memoised default chart, or None.

    Only a fresh memory entry (younger than `QUOTE_TTL`, never a disk
    fallback) whose newest bar is a live / pre / after print answers; the
    basis is decided now, from the same functions the chart route uses
    (`live_point`, then `last_bar_basis`), so it matches the badge's wording.
    """
    raw = symbol.strip()
    for sym in dict.fromkeys((raw, raw.upper())):
        key = S.chart_key(sym, CHART_SPAN, CHART_INTERVAL)
        with S._cache_lock:
            hit = S._cache.get(key)
        if not hit:
            continue
        stored, data = hit
        if time.time() - stored >= QUOTE_TTL:
            return None
        if not isinstance(data, dict) or data.get("cached"):
            return None
        try:
            card = S.live_point(dict(data))
            basis = S.last_bar_basis(card)
            if basis not in LIVE_BASES:
                return None
            price = card["points"][-1]["c"]
        except (KeyError, IndexError, TypeError) as exc:
            faults.note("live_quote.from_chart", exc)
            return None
        if (not isinstance(price, (int, float)) or isinstance(price, bool)
                or price <= 0):
            return None
        # A live bar's print time is the session's last trade; an extended
        # print has no stamp of its own here, so it is dated to the read.
        printed = (card.get("session") or {}).get("lastPrint")
        stamp = printed if basis == "live" and isinstance(printed, int) else int(stored)
        return {"price": round(float(price), 6), "t": int(stamp),
                "symbol": data.get("symbol") or sym}
    return None


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
        got = from_chart(symbol) or _fetch(symbol.strip())
        with _lock:
            now = time.monotonic()
            if len(_memo) >= MEMO_MAX:  # every entry past QUOTE_TTL is dead weight
                for k in [k for k, (t, _) in _memo.items() if now - t > QUOTE_TTL]:
                    del _memo[k]
            _memo[key] = (now, got)
        return dict(got)
    finally:
        with _lock:
            _flight.pop(key).set()
