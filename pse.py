#!/usr/bin/env python3
"""Price history for Philippine Stock Exchange stocks, which Yahoo does not carry.

Why this module exists
----------------------
Yahoo has no PSE equities at all. `TEL.PS`, `JFC.PS`, `ALI.PS`, `SM.PS`,
`BDO.PS` and the rest every return HTTP 404 "No data found, symbol may be
delisted", and searching for the company names turns up foreign and OTC shells
(AYAAF, BDOUY, PHI on the NYSE) rather than the Manila listing. The one
survivor is the index itself -- `PSEI.PS` charts fine -- which is what makes the
gap read as "the index is there, the stocks are not".

So PSE equities need a different source, and the shape of that source is forced
by what actually answers:

    search    scanner.tradingview.com/philippines/scan   plain HTTP, 263 rows
    bars      data.tradingview.com socket.io websocket   a real browser only

The split matters. Search has to be fast -- it backs a type-ahead box -- and the
scanner answers an ordinary HTTP client in half a second, so it never touches
the browser. History has no HTTP route: every candidate was tried and refused.
stooq 403s on `tel.ph` for both CSV and page, pse.com.ph is behind Cloudflare
(403, and it blocks the browser too), the old phisix appspot service is
discontinued (503; the surviving `phisix-api3` rehost has no history endpoint),
and investing.com is Cloudflare-gated. TradingView's websocket is the only one
that returns daily bars, so the bars go through Moli.

This is the same division of labour as `crypto.py` -- a plain-HTTP source for
the per-request work and an injected browser path for what needs one -- but for
the opposite reason: Binance answers plain HTTP and *can* serve bars, while
TradingView's scanner answers plain HTTP and *cannot*.

Why the `PSE:` prefix
---------------------
A PSE ticker is not globally unique: bare `TEL` is TE Connectivity on the NYSE,
which Yahoo charts happily and correctly. Prefixing the symbol with its venue
(`PSE:TEL`) means the two never collide, so Yahoo's answer for `TEL` still
stands and this module only claims the symbols it can actually serve. It also
routes before any fetch happens: `server.py` sees `PSE:` and goes straight here
instead of spending a Moli round trip on a URL that is certain to 404.

A `TEL.PS` typed by hand is accepted too -- `.PS` is the suffix Yahoo's own
conventions teach, and it names the venue, so the stem is already the PSE
ticker.

Why the universe is fetched whole
---------------------------------
The scanner's server-side `filter` uses a word-based `match` operator that
misses `pldt`, `globe`, `jollibee`, `metrobank` and `pse` outright, so it cannot
be trusted to answer a type-ahead query. One request returns all 263 securities;
ranking them locally is both faster and better, and it means an exact ticker can
be floated above everything else.

Standard library only, and keeps the server's "no dependencies" property.

Since 2026-11-18 the bars half lives in `pse_bars.py` (the socket scripts, the
batched history reader and the chart builders). This module keeps the universe,
search, the shared constants and the browser runners, and re-exports every name
`pse_bars.py` defines, so `pse.chart` and `patch.object(pse, ...)` still work.
"""

from __future__ import annotations

import labpath  # noqa: F401  (puts lab/ on sys.path)

import datetime
import json
import threading
import time
import urllib.request


SCANNER = "https://scanner.tradingview.com"
SCAN_URL = f"{SCANNER}/philippines/scan"
# Both the scanner and the socket want an Origin TradingView accepts. A page on
# scanner.tradingview.com is the one that lets the scanner POST through its
# preflight (www.tradingview.com does not); data.tradingview.com refuses to load
# as a page at all, so the socket is opened from the www origin instead, which it
# accepts. The www origin is served by `robots.txt`, not the home page: TradingView
# checks the origin, not the document, and the home page spends ~0.6 s rendering
# subresources the socket never needs -- while the whole-universe sweep and every
# PSE chart pay that tax once per call.
SCAN_PAGE = f"{SCANNER}/symbol?symbol=PSE%3ATEL"
SOCKET_PAGE = "https://www.tradingview.com/robots.txt"
SOCKET_URL = "wss://data.tradingview.com/socket.io/websocket"

# The universe moves at the speed of IPOs and delistings. An hour is plenty and
# keeps a failed refresh from being retried on every keystroke.
INDEX_TTL = 3600
HTTP_TIMEOUT = 20
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AssetPriceDisplay/1.0"

# Calendar days per range, used to trim the series to an exact window. These are
# the same numbers the crypto path uses.
RANGE_DAYS = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}

# Bars to *ask* TradingView for, which is a different unit: its bars are trading
# days (~250 a year), not calendar days. Asking for `days` bars for a 90-calendar-
# day range would return four and a half months, so we ask for a little more than
# the window needs and trim to the window below. The 5-year count is the most
# TradingView will give in one call, and covers 5.2 years -- enough to trim back
# to 5.
BAR_COUNT = {"1mo": 30, "3mo": 70, "6mo": 130, "1y": 270, "2y": 560, "5y": 1300}
MAX_BARS = 1300
# Fetch enough hidden history for the calendar-year context and 252-bar gate.
OUTLOOK_BARS = 400

# Type ids the socket accepts. "1w" hangs; "1W" works.
TIMEFRAME_DAILY = "1D"
TIMEFRAME_WEEKLY = "1W"

# The exchange's own clock, used by exactly one rule: is today's bar finished?
# pse.com.ph's published schedule (read 2026-11-04) runs 9:00 pre-open, 9:30
# open, 12:00-13:00 recess, 14:45 pre-close, 15:00 closing VWAP session and
# **15:15 market close**. That is the only moment a day's volume stops growing,
# so it is what `completed_trade` asks. A couple of minutes past the bell are
# allowed for the closing print to land in the daily bar.
#
# No holiday calendar lives here on purpose: on a holiday there is no bar dated
# today, so `completed_trade` falls through to the last session that traded
# without needing to know the exchange was shut.
SESSION_CLOSE = datetime.time(15, 15)
CLOSING_PRINT_DELAY = datetime.timedelta(minutes=2)
# When today's bar can be moving at all: the opening bell to the close. The
# same published schedule decides this, and `chart()` ships the window so the
# page can say the newest point is the price trading now rather than a close.
SESSION_OPEN = datetime.time(9, 30)

# In-page deadline. The socket answers in 2-3s; past this nothing useful is
# coming, and a bounded wait keeps the whole request inside SUBPROCESS_TIMEOUT
# so the failure is ours to report rather than a killed subprocess.
DEADLINE_MS = 12_000
# How long the stream must be quiet before the bar set is treated as complete.
# The first `timescale_update` can be partial, so we wait for silence instead of
# assuming one frame is the whole series.
SETTLE_MS = 700

# -- the whole-universe sweep -------------------------------------------------
# One socket can carry many chart sessions at once, so the universe is fetched in
# chunks rather than a symbol at a time. The ceiling is soft and comes from the
# server: >40 concurrent sessions intermittently drops every message on the
# socket, while <=40 has been reliable in every run. A chunk that comes back
# short is retried rather than accepted, because a partial answer is
# indistinguishable from a quiet symbol except by what is missing from it.
BATCH_SYMBOLS = 40
BATCH_WORKERS = 4
BATCH_ATTEMPTS = 3
# The deadline is per chunk, not for the sweep. The per-symbol path answers in
# 2-3s and a 40-symbol chunk takes about 10s, so this has room for the several
# frames a hundred times the payload arrives in.
BATCH_DEADLINE_MS = 50_000
# Longer than SETTLE_MS: with forty sessions in flight the frames interleave, so
# a gap in one symbol's stream is not evidence that its series is finished.
BATCH_SETTLE_MS = 6_000
# Bars per symbol. This is BAR_COUNT["1y"], which is what the labeling walk
# needs: it must be able to redraw a 90-calendar-day window (~63 trading bars) at
# each bar it steps back to, and 270 bars is four such windows of history behind
# the latest bar.
BATCH_BARS = 270

# Queries that name the market rather than a security. Few PSE company names
# contain these words (only the exchange's own stock contains "PSE"), so without
# this a search for "philippines" finds almost nothing.
MARKET_ALIASES = {
    "pse", "psei", "philippines", "philippine", "ph",
    "pse index", "psei index", "philippine stock exchange", "philippines stocks",
    "philippine stocks", "manila", "ph stocks",
}

# What people type vs what the exchange calls the company. These are the names
# the listings themselves do not contain: "Metrobank" is listed as
# "Metropolitan Bank & Trust Co." and "Meralco" as "Manila Electric Co.", so no
# amount of substring matching on the official name can find them. Keyed by the
# words a user would actually type, valued by ticker.
SYNONYMS = {
    "metrobank": "MBT", "metro bank": "MBT",
    "meralco": "MER", "meralco electric": "MER",
    "icb": "ICT", "ictsi": "ICT", "container terminal": "ICT",
    "unionbank": "UBP", "union bank": "UBP",
    "china bank": "CBC", "chinabank": "CBC",
    "petron": "PCOR", "purefoods": "PF", "san miguel food": "FB",
    "sm prime": "SMPH", "smph": "SMPH", "megawide": "MWIDE",
    "converge": "CNVRG", "monde": "MONDE", "nlex": "NLEX",
    "philippine national bank": "PNB", "security bank": "SECB",
    "robinsons bank": "RLC", "manila water": "MWC", "aboitiz power": "AP",
    "first gen": "FGEN", "emperor": "EMP", "century pacific": "CPG",
}

# The index is not in the scanner's universe (it lists securities, not indices),
# but the socket resolves it and there is no other way to chart it. Registered by
# hand so it can be searched and shown alongside the stocks it tracks.
INDEX_ENTRY = {
    "symbol": "PSE:PSEI",
    "ticker": "PSEI",
    "name": "PSEi Index",
    "kind": "INDEX",
    "cap": None,
}

_lock = threading.Lock()
_index_cache: tuple[float, dict | None] = (0.0, None)

# Injected by the server, exactly as `crypto.set_http_fallback` is: this module
# must not import server.py, and only the server knows where Moli lives.
_eval_runner = None

# The batch runner is the same browser path with a longer budget. A whole-universe
# chunk is a deliberately long-lived socket -- it has to outlive the several
# seconds a hundred-odd frames take to arrive -- so it cannot share the per-chart
# timeout without one of the two being wrong. Falls back to `_eval_runner`, so the
# batch entry point still works for a caller that registers only one runner.
_batch_runner = None


class PseError(RuntimeError):
    """The PSE source could not be reached, or returned something unusable."""


class PseNotFound(PseError):
    """TradingView has no such symbol. A verdict about the symbol, not an outage.

    Kept distinct from PseError so a typo reads as "no such symbol" (HTTP 404)
    rather than as a 502 that blames the upstream.
    """


def set_eval_runner(fn) -> None:
    """Register `fn(page, script) -> stdout` used to drive the browser."""
    global _eval_runner
    _eval_runner = fn


def set_batch_runner(fn) -> None:
    """Register the longer-budget browser runner the sweep needs (see `_batch_runner`)."""
    global _batch_runner
    _batch_runner = fn


def _run(page: str, script: str) -> str:
    """Run `script` in the browser on `page`, returning its stdout."""
    if _eval_runner is None:
        raise PseError("no browser runner registered")
    try:
        return _eval_runner(page, script)
    except Exception as exc:  # UpstreamError and friends, re-labelled for callers
        raise PseError(f"browser path unavailable ({exc})")


def _run_batch(page: str, script: str) -> str:
    """`_run`, on the batch runner when one is registered (see `_batch_runner`)."""
    runner = _batch_runner or _eval_runner
    if runner is None:
        raise PseError("no browser runner registered")
    try:
        return runner(page, script)
    except Exception as exc:
        raise PseError(f"browser path unavailable ({exc})")


def post_json(url: str, body: dict):
    """POST JSON, plain HTTP, then the browser path if it is refused.

    Public because a scanner POST is not PSE-specific: the same endpoint answers
    for the America and forex sections, and `markets.py` asks it about those.
    The browser fallback below loads `SCAN_PAGE`, a page on the scanner's own
    host, so the retry is same-origin for any section.
    """
    data = json.dumps(body).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=data,
            headers={"User-Agent": UA, "Content-Type": "application/json",
                     "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        last = exc
    # The same POST from inside a page on the scanner's own host, which is the
    # only origin whose preflight lets the content-type header through.
    script = """(async () => {
      const r = await fetch(%s, { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: %s });
      return JSON.stringify({ status: r.status, body: await r.text() });
    })()""" % (json.dumps(url), json.dumps(json.dumps(body)))
    try:
        outer = json.loads(_run(SCAN_PAGE, script))
        if int(outer.get("status", 0)) >= 400:
            raise PseError(f"scanner HTTP {outer['status']}")
        return json.loads(outer["body"])
    except PseError:
        raise
    except Exception as exc:
        raise PseError(f"scanner unreachable ({last}; browser: {exc})")


def _normalize(raw: dict) -> dict:
    """One scanner row -> our record. Unknown shapes are skipped by the caller."""
    symbol = str(raw.get("s") or "")
    cells = list(raw.get("d") or [])
    ticker, description, _close, _change, _volume, row_type, specs, _currency, cap, scale = (
        cells + [None] * 10
    )[:10]
    if not symbol.startswith("PSE:"):
        return {}
    if not ticker and not description:
        return {}
    return {
        "symbol": symbol,
        "ticker": str(ticker or symbol.split(":", 1)[1]).upper(),
        "name": str(description or ticker or symbol),
        "kind": _kind(row_type, specs),
        "cap": cap,
        "pricescale": scale,
    }


def _kind(row_type, specs) -> str:
    """TradingView's coarse `type` -> the instrument name the page shows.

    TradingView lumps ETFs, closed-end funds and preferred series all under
    `type: "stock"`/`"fund"`; `typespecs` is the finer-grained field, so an ETF
    is named as one rather than as a mutual fund, and a preferred series is not
    passed off as a common share.
    """
    if row_type == "index":
        return "INDEX"
    if isinstance(specs, list):
        if "etf" in specs:
            return "ETF"
        if "preferred" in specs:
            return "PREFERRED"
        if "closedend" in specs:
            return "CLOSEDEND"
    if row_type == "fund":
        return "MUTUALFUND"
    return "EQUITY"


def stocks_index() -> dict:
    """The PSE universe -> {"by_symbol", "ordered"}.

    Mirrors `crypto.identity_index`: cached for an hour, and on failure the last
    good copy is served rather than raising, so a scanner hiccup cannot blank
    the search box. Only a cold start with no cache at all raises.
    """
    now = time.time()
    global _index_cache
    with _lock:
        ts, cached = _index_cache
        if cached is not None and now - ts < INDEX_TTL:
            return cached

    body = {
        "filter": [],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "description", "close", "change", "volume",
                    "type", "typespecs", "currency", "market_cap_basic",
                    "pricescale"],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "range": [0, 400],
    }
    try:
        payload = post_json(SCAN_URL, body)
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise PseError("unexpected scanner payload")
    except PseError:
        with _lock:
            _, cached = _index_cache
        if cached is not None:
            return cached  # a hiccup upstream, not a broken universe
        raise

    ordered: list[dict] = []
    by_symbol: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = _normalize(row)
        if not record:
            continue
        ordered.append(record)
        by_symbol.setdefault(record["symbol"], record)

    # The index is not a security, so it is not in the scanner's list; add it so
    # "psei" resolves to the index rather than to the exchange's own stock.
    if INDEX_ENTRY["symbol"] not in by_symbol:
        ordered.append(dict(INDEX_ENTRY))
        by_symbol[INDEX_ENTRY["symbol"]] = dict(INDEX_ENTRY)

    value = {"by_symbol": by_symbol, "ordered": ordered}
    with _lock:
        _index_cache = (now, value)
    return value


def canonical_symbol(symbol: str) -> str | None:
    """`PSE:TEL`, `tel.ps` -> `PSE:TEL`; None if the symbol is not a PSE one.

    The `.PS` form is accepted because that is the suffix Yahoo's own naming
    teaches; since the suffix names the venue, its stem is already the PSE
    ticker, so no ticker table is needed.
    """
    text = (symbol or "").strip().upper()
    if text.startswith("PSE:"):
        text = text[4:]
    elif text.endswith(".PS"):
        text = text[:-3]
    else:
        return None
    if not text or not text.replace("-", "").replace("&", "").isalnum():
        return None
    return "PSE:" + text


def is_pse_symbol(symbol: str) -> bool:
    return canonical_symbol(symbol) is not None


def market_query(query: str) -> bool:
    """Does `query` name the market itself rather than a security?

    Public because the caller needs it for ordering, not just for matching: PSE
    rows whose names contain neither "pse" nor "philippines" would otherwise rank
    below whatever Yahoo offers, and for "philippines" Yahoo's answer is an ETF
    basket and a wall of index codes that is not what was asked for.
    """
    return (query or "").strip().lower() in MARKET_ALIASES


def search_stocks(query: str, limit: int = 5) -> list[dict]:
    """PSE securities matching a search-box query, best match first.

    Never raises: a missing universe just means no additions. Two ranks are in
    play and they are not interchangeable. The first is how directly the match
    answers the query. The second is the ticker length -- PSE tickers are
    padded, so a short query hits them from the left even when the letters are
    meaningless: `SMC2P` starts with `sm`, and listing it as an "SM Investments"
    suggestion is wrong. An exact or prefix ticker hit therefore has to be
    shorter than the query plus a little slack, or it is demoted rather than
    shown. Market cap only separates instruments that tie on both.
    """
    needle = (query or "").strip().lower()
    if len(needle) < 2:
        return []
    try:
        index = stocks_index()
    except PseError:
        return []

    ordered = index["ordered"]
    if market_query(needle):
        # The words name the market, not a security, so the index leads and the
        # largest listings follow. No name test applies, hence the flat score.
        scored = []
        for record in ordered:
            if record["symbol"] == INDEX_ENTRY["symbol"]:
                scored.append((-1, 0, 0, record))       # always first
            elif record["kind"] == "EQUITY" and record.get("cap"):
                scored.append((4, 0, -(record["cap"] or 0), record))
        scored.sort(key=lambda item: item[:3])
        return [_row(record) for _, _, _, record in scored[:limit]]

    # A name the listings themselves do not use, resolved to the ticker it
    # means. Applied only when nothing matched on the name directly.
    synonym = SYNONYMS.get(needle)
    scored = []
    for record in ordered:
        ticker = record["ticker"].lower()
        name = record["name"].lower()
        if ticker == needle:
            rank, extra = 0, 0
        elif ticker.startswith(needle) and len(ticker) <= len(needle) + 3:
            rank, extra = 1, 0
        elif name.startswith(needle):
            rank, extra = 2, 0
        elif needle in name:
            rank, extra = 3, 0
        elif synonym and ticker == synonym.lower():
            # Ranked 0-adjacent: typing "metrobank" is as much a direct request
            # for MBT as typing "mbt" is, so it must not sit below name matches.
            rank, extra = 0, 1
        else:
            continue
        scored.append((rank, extra, -(record.get("cap") or 0), record))
    scored.sort(key=lambda item: item[:3])
    return [_row(record) for _, _, _, record in scored[:limit]]


def _row(record: dict) -> dict:
    """The search-result shape the page renders."""
    return {
        "symbol": record["symbol"],
        "name": record["name"],
        "exchange": "Philippine Stock Exchange",
        "type": record["kind"],
    }


# Split out on 2026-11-18: the chart socket, the batched history reader and the
# chart builders. Imported last so every name they reach through "pse" exists.
# Re-exported so "pse.<name>" and patch.object(pse, ...) keep working.
from pse_bars import (  # noqa: E402,F401
    BATCH_SCRIPT,
    WS_SCRIPT,
    _bar_count_for,
    _build_chart,
    _fetch_chunk,
    _fetch_chunk_raw,
    _history,
    _pool,
    _timeframe_for,
    chart,
    charts_many,
    completed_trade,
    history_many,
    price_hint,
    session_window,
    try_chart,
)
