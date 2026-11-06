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

Standard library only, so it imports only `crypto` (for a price-hint fallback)
and `trend`, and keeps the server's "no dependencies" property.
"""

from __future__ import annotations

import datetime
import json
import math
import threading
import time
import urllib.request

import crypto
import pse_outlook
import trend

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


# The socket protocol, in one script. Every frame is `~m~<len>~m~<json>`; the
# length is authoritative, so frames are drained on it -- the resolved-symbol
# frame carries a session_holidays string of several kilobytes and slicing on
# braces loses the socket's place. Heartbeats (`~h~` frames) must be echoed or
# the server drops a multi-thousand-bar dump mid-flight.
#
# The sends must be in this order, and the symbol descriptor must begin with
# `=`: without it the reply to `resolve_symbol` is `symbol_error` and no bars
# ever arrive.
WS_SCRIPT = """(async () => {
  const bars = new Map();
  const out = { kind: null, error: null, meta: null, bars: null };
  return await new Promise((resolve) => {
    let ws, settled = false, gotSeries = false, quiet = null;
    const finish = (kind, error) => {
      if (settled) return;
      settled = true;
      clearTimeout(hard); clearTimeout(quiet);
      try { ws.close(); } catch (e) {}
      out.kind = kind || "error";
      if (error) out.error = error;
      out.bars = [...bars.values()].sort((a, b) => a[0] - b[0]);
      resolve(JSON.stringify(out));
    };
    const hard = setTimeout(() => finish("timeout", "no data before the deadline"), %(deadline)d);
    try {
      const day = new Date().toISOString().slice(0, 10);
      ws = new WebSocket(%(socket)s + "?from=chart%%2F&date=" + day);
    } catch (e) {
      out.kind = "error"; out.error = "socket could not be opened"; out.bars = [];
      return resolve(JSON.stringify(out));
    }
    const pack = (m, p) => { const s = JSON.stringify({ m, p }); return "~m~" + s.length + "~m~" + s; };
    ws.onopen = () => {
      const rnd = "cs" + Math.random().toString(36).slice(2, 8);
      ws.send(pack("set_auth_token", ["unauthorized_user_token"]));
      ws.send(pack("chart_create_session", [rnd, ""]));
      ws.send(pack("resolve_symbol", [rnd, "sds_sym_1",
        "={\\"adjustment\\":\\"splits\\",\\"symbol\\":\\"" + %(symbol)s + "\\"}"]));
      ws.send(pack("create_series", [rnd, "sds_1", "s1", "sds_sym_1", %(tf)s, %(count)d, ""]));
    };
    ws.onerror = () => finish("error", "socket error");
    ws.onclose = () => { if (!settled) finish("error", "socket closed before any data"); };
    ws.onmessage = (e) => {
      const text = String(e.data);
      const re = /~m~(\\d+)~m~/g;
      let m;
      while ((m = re.exec(text)) !== null) {
        const len = parseInt(m[1], 10);
        const whole = text.substr(m.index, m[0].length + len);
        const body = text.substr(m.index + m[0].length, len);
        if (body.indexOf("~h~") === 0) { try { ws.send(whole); } catch (err) {} continue; }
        let j;
        try { j = JSON.parse(body); } catch (err) { continue; }
        const name = j.m || j.p;
        if (name === "symbol_error") return finish("notfound", "symbol_error");
        if (name === "critical_error" || name === "protocol_error") return finish("error", String(name));
        if (name === "symbol_resolved") {
          const src = j.p[2] || {};
          out.meta = {
            name: src.description || src.short_description || null,
            currency: src.currency_code || null,
            exchange: (src.source2 && src.source2.description) || src.exchange || null,
            type: src.type || null,
            pricescale: src.pricescale || null
          };
        }
        if (name === "timescale_update" || name === "du") {
          const node = (j.p && j.p[1] && j.p[1].sds_1) || {};
          for (const x of (node.s || [])) {
            if (x && Array.isArray(x.v) && typeof x.v[0] === "number") bars.set(x.i, x.v);
          }
          if (name === "timescale_update" || gotSeries) {
            gotSeries = true;
            clearTimeout(quiet);
            quiet = setTimeout(() => finish("ok"), %(settle)d);
          }
        }
        if (name === "series_completed" && gotSeries) {
          clearTimeout(quiet);
          quiet = setTimeout(() => finish("ok"), 300);
        }
      }
    };
  });
})()"""


# The same protocol as WS_SCRIPT, widened to a chunk. Two differences that matter:
#
# * One `chart_create_session` **per symbol**. The free token refuses a second
#   `create_series` in an existing session -- `critical_error: exceed limit of
#   series in the session` -- so batching is many sessions on one socket, not one
#   session with many series. Therefore the series name is always `sds_1`: it is
#   only ambiguous within a session, and there is one series in each.
# * Completion is tracked per symbol, and the result is not trusted until every
#   session has reported `series_completed`. Otherwise the settle timer fires on
#   the first quiet moment and the chunk comes back with whatever had arrived --
#   which is how a 60-symbol chunk returned nothing at all.
BATCH_SCRIPT = """(async () => {
  const SYMS = %(symbols)s;
  // `meta` is keyed by symbol the way `bars` is: the `symbol_resolved` frame
  // arrives on the session that asked for it, and `sidOf` maps that session
  // back to the symbol. WS_SCRIPT captures the same fields for one symbol;
  // this is the same capture, widened to a chunk, so a batched chart can name
  // and price-scale its instrument exactly as the single-symbol one does.
  const out = { kind: "error", error: null, bars: {}, meta: {} };
  return await new Promise((resolve) => {
    const store = {}; const sessOf = {}; const done = {};
    let ws = null, settled = false, quiet = null;
    const finish = (kind, error) => {
      if (settled) return;
      settled = true;
      clearTimeout(hard); clearTimeout(quiet);
      try { ws.close(); } catch (e) {}
      out.kind = kind || "error";
      if (error) out.error = error;
      for (const s of SYMS) {
        const m = store[s];
        out.bars[s] = m ? [...m.values()].sort((a, b) => a[0] - b[0]) : [];
      }
      resolve(JSON.stringify(out));
    };
    // Every session must report before the answer is trusted -- see the header.
    const maybeDone = () => {
      if (Object.keys(done).length >= SYMS.length) finish("ok", null);
    };
    const hard = setTimeout(() => finish("timeout", "deadline"), %(deadline)d);
    const touch = () => {
      clearTimeout(quiet);
      quiet = setTimeout(() => finish("partial", "settled early"), %(settle)d);
    };
    try {
      const day = new Date().toISOString().slice(0, 10);
      ws = new WebSocket(%(socket)s + "?from=chart%%2F&date=" + day);
    } catch (e) {
      out.error = "socket could not be opened";
      return resolve(JSON.stringify(out));
    }
    const pack = (m, p) => { const s = JSON.stringify({ m, p }); return "~m~" + s.length + "~m~" + s; };
    const sidOf = {};
    ws.onopen = () => {
      ws.send(pack("set_auth_token", ["unauthorized_user_token"]));
      SYMS.forEach((s, i) => {
        const rnd = "cs" + i + Math.random().toString(36).slice(2, 6);
        sidOf[rnd] = s;
        ws.send(pack("chart_create_session", [rnd, ""]));
        ws.send(pack("resolve_symbol", [rnd, "sds_sym_1",
          "={\\"adjustment\\":\\"splits\\",\\"symbol\\":\\"" + s + "\\"}"]));
        ws.send(pack("create_series", [rnd, "sds_1", "s1", "sds_sym_1", %(tf)s, %(count)d, ""]));
      });
    };
    ws.onerror = () => finish("error", "socket error");
    ws.onclose = () => { if (!settled) finish("error", "closed before data"); };
    ws.onmessage = (e) => {
      const text = String(e.data);
      const re = /~m~(\\d+)~m~/g;
      let m;
      while ((m = re.exec(text)) !== null) {
        const len = parseInt(m[1], 10);
        const whole = text.substr(m.index, m[0].length + len);
        const body = text.substr(m.index + m[0].length, len);
        if (body.indexOf("~h~") === 0) { try { ws.send(whole); } catch (err) {} continue; }
        let j;
        try { j = JSON.parse(body); } catch (err) { continue; }
        const name = j.m || j.p;
        const sid = (j.p && typeof j.p[0] === "string") ? j.p[0] : null;
        const sym = sid ? sidOf[sid] : null;
        // A symbol the venue does not know still counts as answered, or the
        // chunk would wait out its deadline for a name that was never coming.
        if (name === "symbol_error") { if (sym) done[sym] = 1; maybeDone(); continue; }
        if (name === "symbol_resolved") {
          if (!sym) continue;
          const src = (j.p && j.p[2]) || {};
          out.meta[sym] = {
            name: src.description || src.short_description || null,
            currency: src.currency_code || null,
            exchange: (src.source2 && src.source2.description) || src.exchange || null,
            type: src.type || null,
            pricescale: src.pricescale || null
          };
          continue;
        }
        if (name === "critical_error" || name === "protocol_error") {
          return finish("error", String(name));
        }
        if (name === "timescale_update" || name === "du") {
          if (!sym) continue;
          const node = (j.p && j.p[1]) || {};
          const sds = node["sds_1"] || {};
          if (!store[sym]) { store[sym] = new Map(); sessOf[sym] = sid; }
          for (const x of (sds.s || [])) {
            if (x && Array.isArray(x.v) && typeof x.v[0] === "number") store[sym].set(x.i, x.v);
          }
          touch();
        }
        if (name === "series_completed" && sym) { done[sym] = 1; maybeDone(); }
      }
    };
  });
})()"""


def history_many(symbols, count=BATCH_BARS, timeframe=TIMEFRAME_DAILY,
                 chunk=BATCH_SYMBOLS, workers=BATCH_WORKERS,
                 attempts=BATCH_ATTEMPTS) -> dict[str, list]:
    """Daily bars for many symbols at once -> {symbol: rows}.

    A symbol is present only if its series arrived; a symbol missing from the
    result is one the sweep could not get, not one without bars. The caller
    decides what a missing name means.

    Why not one socket per symbol
    -----------------------------
    A browser costs about a second to start, so 263 separate `_history` calls
    would spend almost five minutes waiting on Chrome and almost none of it
    waiting on data. Many chart sessions can share one socket -- each needs its
    own `chart_create_session`, because the free token rejects a second
    `create_series` in the same session -- so a chunk of forty resolves in about
    ten seconds: a 30x saving, and the difference between a sweep that can be
    refreshed in the background and one that cannot.

    Chunking and retry
    ------------------
    Forty sessions per socket is the reliable ceiling; above it the server
    intermittently stops delivering, which shows up as an empty chunk rather
    than an error. Even at forty a chunk occasionally comes back short, so a
    short chunk is retried rather than tolerated: a missing symbol would
    otherwise be reported as "not bullish" when it is really "not fetched", and
    the table would silently lie by omission.
    """
    pending = [str(s) for s in symbols]
    if not pending:
        return {}

    out: dict[str, list] = {}
    for attempt in range(1, max(1, attempts) + 1):
        if not pending:
            break
        chunks = [pending[i:i + chunk] for i in range(0, len(pending), chunk)]
        with _pool(workers) as pool:
            results = list(pool.map(
                lambda c: (c, _fetch_chunk(c, timeframe, count)), chunks))
        pending = []
        for wanted, got in results:
            out.update(got)
            pending.extend(s for s in wanted if s not in got)
    return out


def _pool(workers: int):
    """A thread pool sized for `workers` Moli subprocesses.

    Threads rather than processes because the work is almost entirely waiting on
    a subprocess; the socket frames are parsed in the browser, and the Python
    side only ever reads the finished JSON.
    """
    from concurrent.futures import ThreadPoolExecutor
    return ThreadPoolExecutor(max_workers=max(1, workers))


def _fetch_chunk(symbols: list[str], timeframe: str, count: int) -> dict[str, list]:
    """One socket, one chart session per symbol. Missing symbols are simply absent.

    A chunk that fails outright returns `{}` rather than raising, so one bad
    chunk costs its own symbols and not the sweep -- the retry pass picks them up.
    """
    bars, _meta = _fetch_chunk_raw(symbols, timeframe, count)
    return bars


def _fetch_chunk_raw(symbols: list[str], timeframe: str,
                     count: int) -> tuple[dict[str, list], dict[str, dict]]:
    """`_fetch_chunk`, plus the `symbol_resolved` meta it now captures.

    The sweep only wants bars, but a batched *chart* also needs each
    instrument's name, currency and tick size, and those arrive on the same
    frames the bars do -- re-running the socket to collect them would double
    the browser spend for data that was already in the room. Returns
    `(bars, meta)`; both carry only the symbols that answered.
    """
    script = BATCH_SCRIPT % {
        "symbols": json.dumps([str(s) for s in symbols]),
        "tf": json.dumps(timeframe),
        "count": int(count),
        "deadline": BATCH_DEADLINE_MS,
        "settle": BATCH_SETTLE_MS,
        "socket": json.dumps(SOCKET_URL),
    }
    try:
        raw = _run_batch(SOCKET_PAGE, script)
        envelope = json.loads(raw)
    except (PseError, ValueError):
        return {}, {}
    if envelope.get("kind") != "ok":
        return {}, {}
    bars = envelope.get("bars") or {}
    out: dict[str, list] = {}
    for symbol, rows in bars.items():
        # An empty list is the socket's way of saying "this session produced
        # nothing", which is a failure to fetch rather than a verdict.
        if rows:
            out[str(symbol)] = rows
    meta = {str(k): v for k, v in (envelope.get("meta") or {}).items()
            if isinstance(v, dict)}
    return out, meta


def _history(symbol: str, timeframe: str, count: int) -> dict:
    """Drive one websocket call and return the parsed envelope."""
    script = WS_SCRIPT % {
        # The venue prefix is part of the symbol, not our own encoding of it:
        # TradingView resolves the bare "TEL" to TE Connectivity on another
        # exchange, and only "PSE:TEL" is the Manila listing.
        "symbol": json.dumps(symbol),
        "tf": json.dumps(timeframe),
        "count": int(count),
        "deadline": DEADLINE_MS,
        "settle": SETTLE_MS,
        "socket": json.dumps(SOCKET_URL),
    }
    raw = _run(SOCKET_PAGE, script)
    try:
        envelope = json.loads(raw)
    except ValueError:
        raise PseError(f"unusable socket reply: {str(raw)[:200]}")
    kind = envelope.get("kind")
    if kind == "notfound":
        raise PseNotFound(f"TradingView has no symbol {symbol!r}.")
    if kind != "ok":
        raise PseError(f"socket {kind}: {envelope.get('error') or 'no detail'}")
    return envelope


def price_hint(pricescale, price: float) -> int:
    """Decimals to show, taken from the instrument's own tick size.

    PSE quotes to the tick, so `pricescale` is a better answer than magnitude:
    a ₱0.31 stock ticks at 1/1000 (0.310), which a magnitude rule would round to
    0.3100. The floor of two decimals is the exchange's own convention -- the
    scale for a large-cap like PLDT is 1, but it is quoted in centavos, and
    `₱1,119` reads as a rounded price where `₱1,119.00` does not. Falls back to
    the crypto path's magnitude rule when the scale is missing.
    """
    try:
        scale = float(pricescale)
        if scale > 0:
            return max(2, min(6, int(round(math.log10(scale)))))
    except (TypeError, ValueError):
        pass
    return max(2, crypto.price_hint(price))


def completed_trade(points: list[dict], volumes: list, now: float | None = None
                    ) -> tuple[int | None, float | None, float | None]:
    """The newest **finished** session's (stamp, traded shares, traded value).

    "How much money moved through this name" is `close * volume` on a bar -- the
    same product `bullish.py` and `onset.py` rank the tables on, so a chart
    readout and a table row describe one session the same way.

    Why today's bar waits for the bell
    -----------------------------------
    The reader asked for the last **completed** trading day, and the provider
    gives no way to tell a finished bar from a forming one: TradingView's daily
    payload carries today's candle from the opening bell, and nothing in the
    frame says whether it has stopped moving (the same gap `pse_outlook` works
    around by discarding today's candle outright). So the clock does the work
    instead, from the exchange's own published schedule:

        pse.com.ph, trading hours (read 2026-11-04)
        9:00 pre-open / 9:30 open / 12:00-13:00 recess / 14:45 pre-close
        15:00 closing VWAP session / **15:15 market close**

    A bar dated today is therefore the session **so far** until `SESSION_CLOSE`,
    and today's finished session from `CLOSING_PRINT_DELAY` past it (the closing
    print takes a moment to land in the daily bar). A bar dated tomorrow is
    always refused -- that is a clock disagreement, not a session.

    No holiday calendar is needed and none is invented: on a holiday there is no
    bar dated today at all, so the walk falls through to the last day that
    actually traded. A suspension behaves the same way.

    Read at **read** time, not fetch time (`server.chart_data`), for the reason
    `lastBarBasis` is: a payload fetched at 10:30 and served at 16:00, or
    tomorrow from a disk copy, must not still be answering for the day it was
    fetched on. The rule is a pure function of the bars and the clock, so nothing
    outside the drawn series is invented.

    Two refusals, neither of them a zero:

    * **No volume at all.** The PSE index carries none, and a bar whose volume
      field did not survive parsing is silence rather than a session that
      traded nothing. `onset`'s own rule ("a missing volume is not a
      zero-volume session") applies.
    * **A zero-volume bar.** The same silence inside the series: a name that did
      not trade that day has no traded value to report, and PHP 0.00 beside a
      live price would read as a claim about demand rather than absence of
      prints.

    A weekly series is refused by the caller, not here: a week's volume times
    its close is not a trading *day*'s value.
    """
    if not points or not volumes:
        return None, None, None
    now = time.time() if now is None else now
    now_manila = datetime.datetime.fromtimestamp(now, pse_outlook.MANILA)
    today = now_manila.date()
    # Today's bar is a finished session only after the exchange's own close --
    # plus the moment the closing print needs to reach the daily bar. Before
    # that it is the session so far, and reporting it would print a partial day
    # as though it were complete.
    close_at = now_manila.replace(
        hour=SESSION_CLOSE.hour, minute=SESSION_CLOSE.minute,
        second=0, microsecond=0) + CLOSING_PRINT_DELAY
    today_is_final = now_manila >= close_at
    for i in range(len(points) - 1, -1, -1):
        try:
            stamp = int(points[i]["t"])
            close = float(points[i]["c"])
        except (KeyError, TypeError, ValueError):
            continue
        day = datetime.datetime.fromtimestamp(stamp, pse_outlook.MANILA).date()
        if day > today:
            continue                    # a stamp ahead of the clock: not a session
        if day == today and not today_is_final:
            continue                    # today, still trading
        volume = volumes[i] if i < len(volumes) else None
        if not volume or not close > 0:
            return None, None, None
        return stamp, float(volume), close * float(volume)
    return None, None, None


def chart(symbol: str, span: str, interval: str) -> dict:
    """Daily/weekly bars for a PSE security, in the server's payload shape.

    Raises PseNotFound for a symbol TradingView does not know and PseError for a
    transport failure, so the caller can tell a typo from an outage.
    """
    canonical = canonical_symbol(symbol)
    if canonical is None:
        raise PseNotFound(f"{symbol!r} is not a PSE symbol.")

    days = RANGE_DAYS.get(span, RANGE_DAYS["3mo"])
    if interval == "1wk":
        timeframe = TIMEFRAME_WEEKLY
        count = min(MAX_BARS, max(60, days // 7 + 8))
    else:
        timeframe = TIMEFRAME_DAILY
        count = max(OUTLOOK_BARS, BAR_COUNT.get(span, BAR_COUNT["3mo"]))

    envelope = _history(canonical, timeframe, count)
    meta = envelope.get("meta") or {}

    points: list[dict] = []
    volumes: list[float | None] = []
    seen: set[int] = set()
    for row in envelope.get("bars") or []:
        try:
            stamp = int(row[0])
            close = float(row[4])
        except (IndexError, TypeError, ValueError):
            continue  # tolerate a malformed row rather than lose the series
        if stamp in seen or not close > 0:
            continue
        # An index has no volume, so its bars carry only five fields. Absent
        # volume is not a malformed row -- it just means the ensemble's volume
        # signal has nothing to say.
        try:
            volume = float(row[5])
        except (IndexError, TypeError, ValueError):
            volume = None
        seen.add(stamp)
        points.append({"t": stamp, "c": round(close, 6)})
        volumes.append(volume)

    if not points:
        raise PseNotFound(f"No price data for {canonical}.")
    order = sorted(range(len(points)), key=lambda i: points[i]["t"])
    points = [points[i] for i in order]
    volumes = [volumes[i] for i in order]

    # Trim to the exact window. The bar count asked for is an over-estimate on
    # purpose (see BAR_COUNT); the timestamp is what makes the range honest
    # regardless of holidays. If a symbol has gone quiet for longer than the
    # window, fall back to its last bars so the chart is not blank.
    cutoff = time.time() - days * 86400
    start = next((i for i, p in enumerate(points) if p["t"] >= cutoff), None)
    if start is None or len(points) - start < 2:
        start = max(0, len(points) - max(2, trend.MIN_BARS))
    used = points[start:]
    used_volumes = volumes[start:]

    closes = [p["c"] for p in used]

    # Same contract as the Yahoo and crypto paths: every series is scored, so a
    # thinly traded PSE name -- whose 90-day window can hold only a few dozen
    # bars -- still gets its verdict, and only bad data leaves the badge off.
    trend_call = None
    try:
        trend_call = trend.classify(closes, used_volumes)
    except ValueError:
        pass

    last = used[-1]["c"]
    previous = used[-2]["c"] if len(used) > 1 else None

    # The board lot times the last close: the smallest cheque that buys this
    # stock, which the page shows under the price. Imported here rather than at
    # the top because `markets` imports this module -- for the scanner POST and
    # its browser fallback -- so a top-level import would be a cycle, and this is
    # the one place in it that needs the lot table. That table is the exchange's,
    # keyed on price, not the instrument's `pricescale`, which is the tick size.
    import markets
    lot, lot_cost = markets.minimum_investment(last)

    return {
        "symbol": canonical,
        "name": meta.get("name") or canonical,
        "currency": meta.get("currency") or "PHP",
        "exchange": meta.get("exchange") or "Philippine Stock Exchange",
        "type": meta.get("type") or "stock",
        "priceHint": price_hint(meta.get("pricescale"), last),
        "previousClose": previous,
        "marketPrice": last,
        "boardLot": lot,
        "minInvestment": lot_cost,
        "points": used,
        # Shares per bar, aligned with `points` (the shape `crypto.chart` ships),
        # so the last *completed* session's value can be read off at read time
        # instead of being frozen into this payload -- see `completed_trade`.
        "volumes": used_volumes,
        "longTermContext": pse_outlook.context(points) if interval == "1d" else None,
        "trend": trend_call,
        "source": "TradingView",
    }


def try_chart(symbol: str, span: str, interval: str) -> dict | None:
    """`chart()`, with "not ours" and "no bars" flattened to None."""
    try:
        return chart(symbol, span, interval)
    except PseNotFound:
        return None


def charts_many(symbols, span: str = "3mo", interval: str = "1d",
                chunk=BATCH_SYMBOLS, workers=BATCH_WORKERS,
                attempts=BATCH_ATTEMPTS) -> dict[str, dict | Exception]:
    """`chart()` for many PSE symbols at once, through the same batched socket.

    Returns `{canonical_symbol: payload}` for every symbol whose series
    arrived, and `{symbol: exception}` for the ones that did not. The split is
    the caller's whole interface to failure semantics: a bar-shaped entry is a
    finished chart, and an exception entry is either `PseNotFound` (a verdict
    about the symbol) or `PseError` (an outage about the wire) -- exactly the
    distinction `chart()` draws one symbol at a time, so a caller can treat
    them the same way it treats that one.

    Why this exists
    ---------------
    The row warmer used to warm each PSE row through `chart()` one browser run
    at a time: ~90 symbols, ~90 launches, ~90 single-symbol sockets. The sweep
    already proved that forty sessions share one socket (see `history_many`),
    so the warmer's pass can ride the same chunking -- the bars per symbol are
    identical, only the post-processing differs. That post-processing is lifted
    here verbatim from `chart()` (window trim, trend call, board-lot figure)
    rather than refactored out of it, on purpose: one copy per route is the
    price of the two routes not being able to drift, and this module already
    paid it once with `markets.minimum_investment`. A symbol whose series never
    arrives (the chunk came back short and the retry pass exhausted its
    attempts) gets a `PseError`, not silence -- "not fetched" is a transport
    verdict, not an answer about the symbol.

    The meta comes from the same socket run (`_fetch_chunk_raw`), so a batched
    chart names, scales and prices its instrument exactly as the single-symbol
    `chart()` does; a session whose `symbol_resolved` frame never arrived gets
    `chart()`'s own fallback defaults rather than a different spelling.
    """
    # Canonicalised up front, so the queue a caller built maps back to the
    # symbols the socket knows -- and so duplicates by spelling collapse.
    queue: dict[str, str] = {}
    for symbol in symbols:
        canonical = canonical_symbol(symbol)
        if canonical is None:
            raise PseNotFound(f"{symbol!r} is not a PSE symbol.")
        queue[canonical] = str(symbol)
    if not queue:
        return {}

    out: dict[str, dict | Exception] = {}
    pending = list(queue)
    for attempt in range(1, max(1, attempts) + 1):
        if not pending:
            break
        chunks = [pending[i:i + chunk] for i in range(0, len(pending), chunk)]
        with _pool(workers) as pool:
            results = list(pool.map(
                lambda c: _fetch_chunk_raw(c, _timeframe_for(span, interval),
                                           _bar_count_for(span, interval)),
                chunks))
        pending = []
        for wanted, (got, meta) in zip(chunks, results):
            for symbol in wanted:
                rows = got.get(symbol)
                if not rows:
                    pending.append(symbol)   # retry pass owns it
                    continue
                try:
                    out[symbol] = _build_chart(symbol, rows, meta.get(symbol) or {},
                                               span, interval)
                except PseNotFound as exc:
                    out[symbol] = exc        # bars arrived, none usable: verdict
                except PseError as exc:
                    out[symbol] = exc
                    # A broken series is transport, not absence: the retry
                    # pass has another go at it like any other miss.
                    pending.append(symbol)
    # Everything still pending after the last attempt is an outage wearing one
    # row per symbol -- same exception shape `_history` would have raised.
    for symbol in pending:
        out[symbol] = PseError(f"no series for {symbol!r} after {attempts} attempt(s)")
    return out


def _timeframe_for(span: str, interval: str) -> str:
    """The socket timeframe `chart()` picks for this window. Shared, so the
    batched path cannot disagree with the single one about `1wk`."""
    return (TIMEFRAME_WEEKLY if interval == "1wk" else TIMEFRAME_DAILY)


def _bar_count_for(span: str, interval: str) -> int:
    days = RANGE_DAYS.get(span, RANGE_DAYS["3mo"])
    if interval == "1wk":
        return min(MAX_BARS, max(60, days // 7 + 8))
    return max(OUTLOOK_BARS, BAR_COUNT.get(span, BAR_COUNT["3mo"]))


def _build_chart(symbol: str, rows, meta: dict, span: str, interval: str) -> dict:
    """One symbol's parsed bars -> the exact payload `chart()` returns.

    Lifted from `chart()`'s body (parse, dedupe, sort, trim, score, lot) with
    the socket run factored out in front. The trim, the trend and the lot
    arithmetic are the parts that must not drift between the two routes, and
    the comment trail inside `chart()` explains each -- read there.
    """
    days = RANGE_DAYS.get(span, RANGE_DAYS["3mo"])

    points: list[dict] = []
    volumes: list[float | None] = []
    seen: set[int] = set()
    for row in rows:
        try:
            stamp = int(row[0])
            close = float(row[4])
        except (IndexError, TypeError, ValueError):
            continue
        if stamp in seen or not close > 0:
            continue
        try:
            volume = float(row[5])
        except (IndexError, TypeError, ValueError):
            volume = None
        seen.add(stamp)
        points.append({"t": stamp, "c": round(close, 6)})
        volumes.append(volume)

    if not points:
        raise PseNotFound(f"No price data for {symbol}.")
    order = sorted(range(len(points)), key=lambda i: points[i]["t"])
    points = [points[i] for i in order]
    volumes = [volumes[i] for i in order]

    cutoff = time.time() - days * 86400
    start = next((i for i, p in enumerate(points) if p["t"] >= cutoff), None)
    if start is None or len(points) - start < 2:
        start = max(0, len(points) - max(2, trend.MIN_BARS))
    used = points[start:]
    used_volumes = volumes[start:]

    closes = [p["c"] for p in used]
    trend_call = None
    try:
        trend_call = trend.classify(closes, used_volumes)
    except ValueError:
        pass

    last = used[-1]["c"]
    previous = used[-2]["c"] if len(used) > 1 else None

    import markets
    lot, lot_cost = markets.minimum_investment(last)

    # `volumes` beside `points`, exactly as `chart()` ships them, so the
    # batched route a warmed row is stored through cannot omit what the
    # single-symbol route carries (see `completed_trade` for the read-time rule).
    return {
        "symbol": symbol,
        "name": meta.get("name") or symbol,
        "currency": meta.get("currency") or "PHP",
        "exchange": meta.get("exchange") or "Philippine Stock Exchange",
        "type": meta.get("type") or "stock",
        "priceHint": price_hint(meta.get("pricescale"), last),
        "previousClose": previous,
        "marketPrice": last,
        "boardLot": lot,
        "minInvestment": lot_cost,
        "points": used,
        "volumes": used_volumes,
        "longTermContext": pse_outlook.context(points) if interval == "1d" else None,
        "trend": trend_call,
        "source": "TradingView",
    }
