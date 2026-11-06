#!/usr/bin/env python3
"""Daily bars from TradingView, for the instruments Yahoo does not quote.

Why this module exists
----------------------
The page's newest row is a Philippine government bond yield, and no source it
already talks to quotes one. Yahoo has no Philippine yield series; the ECB
publishes currency fixes; Binance publishes coins. TradingView does quote the
Philippine 10-year, 5-year and 2-year government bond yields (`TVC:PH10Y`,
`TVC:PH05Y`, `TVC:PH02Y`), as Refinitiv-sourced daily closes in percent.

The project already trusts TradingView for two things -- the scanner that
answers "what are the most traded listings" (`markets.py`, `pse.py`) and the
Philippine bars themselves (`pse.py`) -- so a yield read from the same house is
one more answer from a source the page already depends on, not a new
dependency.

How the bars are fetched
------------------------
Through `pse.py`'s socket, over the same browser path the Philippine listings
use. That is a deliberate choice, and it was the second one tried.

The chart protocol is a websocket, and it can be driven by a plain TLS socket
with no browser at all -- which is how this module was first written, and the
code was correct: the handshake, the session, the symbol resolution, the
series request and the `timescale_update` frame all arrived. The problem was
that the protocol drops most of the sessions it accepts. A session is told to
load a series (`series_loading`) and then the series never comes; whether it
comes at all looked like a coin flip, and it was worse for the 5-year yield
than for the others. Retrying hard enough to win that coin flip took forty
seconds for three symbols, and the flakiness came in bursts, so a sweep that
worked could be followed by one that did not.

Driving the same protocol from the browser instead is reliable: the same three
yields come back, every time, in under a second -- and they come back with the
same values the plain socket produced when it did answer, so the switch cost
nothing but the flakiness. The browser is also not a new dependency: it is the
one Moli-backed path the whole project already runs on, and `pse.py` is its
socket client.

So this module is deliberately thin. It owns the *bond yields*: which symbols
are the Philippine curve, what they are called, and what a row of them means.
The socket is `pse.py`'s, which already knows how to speak to TradingView and
how to batch and retry without lying about what it fetched.

The chart, and the one direction it reverses
-------------------------------------------
Since 2026-10-31 this module also draws the chart behind a bond row. The bars are
exactly the ones the row was judged on -- the same disk copy, the same trim, the
same `trend.classify` call -- so a row and the chart its click opens are one
series, not two (invariant 1 in the project's notes). Only the *route* changed:
before, a bond row was not a link because the chart route drew what Yahoo draws
and Yahoo quotes no Philippine yield; now `server.chart_data` routes these three
symbols here before it builds a Yahoo URL.

The plotted line is the yield in percent -- that is the series, and inventing a
bond-price series out of it would be a fabrication. What is reversed is the
*label*: the classifier reads the yield's own numbers, which calls a falling
yield "bearish", and a reader thinking about a bond wants that said as a bond
price ("bullish: yield falling"). That reversal already existed on the table row;
`bond_price_call` applies the same one to the chart's badge, so the two cannot
disagree. The payload carries `yieldSeries` and `yieldTrend` (the classifier's
unreversed call) so the page can say which line it is drawing and what the yield
itself did.
"""

from __future__ import annotations

import time

import diskcache
import onset as onset_module
import pse
import trend

# The Philippine government bond yields, and what they are called. Two-year,
# five-year, ten-year: the short, the middle and the long of the curve, so the
# reader can see whether the whole curve is moving or only one end of it.
#
# TradingView's spelling is the only way to name a bond yield -- the ticker
# carries a zero (`PH02Y`, not `PH2Y`) because `PH5Y` is a different
# instrument, or no instrument at all.
BONDS = (
    ("TVC:PH02Y", "Philippines 2-year government bond yield"),
    ("TVC:PH05Y", "Philippines 5-year government bond yield"),
    ("TVC:PH10Y", "Philippines 10-year government bond yield"),
)

# The tenors on their own, so the curve can be named once and read two ways:
# `SYMBOLS` is the queue a caller hands the socket and `NAMES` is what a chart
# labels itself.
SYMBOLS = tuple(symbol for symbol, _name in BONDS)
NAMES = dict(BONDS)
_BY_TENOR = {symbol.split(":")[-1]: symbol for symbol in SYMBOLS}

# Bars to ask for. The walk behind a "since when" date needs history behind
# the ninety-day window, so a year of daily bars is the smallest useful
# request; three hundred is comfortable and still one series.
BARS = 300

# TradingView's spelling of a daily bar. The page's own charts use Yahoo's
# "1d", and the two are the same thing.
INTERVAL = "1D"
WEEKLY = "1W"

# How long a fetched series is worth skipping the fetch for, and how long it is
# still worth *showing* when the fetch failed. A yield is a daily close, so a
# copy six hours old has missed at most one bar; a copy a week old is a stale
# reading that still beats a gap in the curve, and it says how old it is.
#
# Two ages because they answer two questions, and both live here because the
# table row and the chart read the *same* disk copy -- `recent.py` imports these
# names rather than keeping a second set, and the two therefore cannot disagree
# about when a copy is fresh or about where it is filed.
BOND_CACHE_TTL = 6 * 3600
BOND_CACHE_KEEP = 7 * 24 * 3600
BOND_CACHE_PREFIX = "tv:bond:"


class TvError(RuntimeError):
    """The chart protocol refused, or never answered."""


class TvNotFound(LookupError):
    """The symbol is not one of the Philippine bond yields."""


def canonical(symbol: str) -> str | None:
    """TradingView's spelling of a yield this module knows, or None.

    Two spellings are accepted: the socket's own (`TVC:PH10Y`, which is what a
    row carries) and the bare tenor (`PH10Y`, which is what a reader or a URL
    is likely to type). Anything else is not a Philippine bond yield, and None
    says so rather than raising -- the usual caller is asking "is this mine?",
    which is a yes/no question.

    The bare tenor is matched only against the three in `BONDS`, so this can
    never claim an instrument it does not have a name for.
    """
    text = (symbol or "").strip().upper()
    if text in NAMES:
        return text
    if text.startswith("TVC:"):
        text = text[4:]
    return _BY_TENOR.get(text)


def is_bond_symbol(symbol: str) -> bool:
    """Whether `symbol` names one of the Philippine government bond yields."""
    return canonical(symbol) is not None


def cached_bars(symbol: str) -> tuple[list[dict] | None, float]:
    """The stored bars for a yield and how old they are; (None, 0) if none.

    Shared with `recent.py`, which reads the same copy for the table row: a bond
    chart and the row it was opened from must draw the same series, and two
    disk keys -- or two spellings of one key -- is how they stop doing that.

    The age is returned rather than judged, because there are two questions to
    ask of a copy: is it fresh enough to skip the fetch for (`BOND_CACHE_TTL`),
    and is it worth showing at all if the fetch failed (`BOND_CACHE_KEEP`).
    """
    saved = diskcache.load(BOND_CACHE_PREFIX + symbol)
    if saved is None:
        return None, 0.0
    fetched_at, bars = saved
    if not isinstance(bars, list) or not bars:
        return None, 0.0
    return bars, time.time() - float(fetched_at)


def store_bars(symbol: str, bars: list[dict]) -> None:
    """Keep a fetched series for the next read. A failed write is not a failure:
    a cache that could not be written costs the next fetch, not this answer."""
    try:
        diskcache.store(BOND_CACHE_PREFIX + symbol, bars)
    except Exception:
        pass


def bond_price_call(call: dict | None) -> dict | None:
    """The classifier's yield verdict, restated as the bond-price direction.

    A yield is not a price: `trend.classify` reads the yield's own numbers, so a
    falling yield is "bearish" to it, while a reader thinking about an existing
    fixed-rate bond means "bullish". The table has always made that reversal
    (`recent.bond_rows`); this is the same reversal, once, so the chart's badge
    and the row cannot say opposite things about one series.

    The classifier's own call is kept as `yieldLabel` / `yieldScore`, because
    the reversal is an inference and the page should be able to name what the
    yield itself did. Neutral stays neutral either way.
    """
    if not call:
        return None
    out = dict(call)
    out["yieldLabel"] = call.get("label")
    out["yieldScore"] = call.get("score")
    label = call.get("label")
    out["label"] = {"bullish": "bearish",
                    "bearish": "bullish"}.get(label, label)
    score = call.get("score")
    out["score"] = -score if isinstance(score, (int, float)) else score
    # The drift t reads in the badge's direction too, or a Bullish bond badge
    # would print a negative t beside it.
    sig = call.get("significance")
    out["significance"] = -sig if isinstance(sig, (int, float)) else sig
    lean = call.get("lean")
    out["lean"] = {"bullish": "bearish", "bearish": "bullish"}.get(lean, lean)
    return out


def _chart_payload(symbol: str, bars: list[dict], span: str,
                   interval: str, stale: int = 0) -> dict:
    """One tenor's bars -> the chart payload the page draws.

    `bars` may carry more history than the span asked for; the trim is
    `onset.window_now`, the same function the table row's walk asks, over the
    same 90-day (or 1-month, 1-year...) window the row is judged on. That is the
    project's rule for every source: a row's verdict must be computable from the
    window its chart draws.

    A weekly chart is not trimmed. A weekly bar spans seven days with its stamp
    on the week's first day, so comparing that stamp against a day boundary
    would amputate a bar that lies partly inside the window -- the same reason
    `server.slim_chart` leaves Yahoo's weekly payload alone.
    """
    ordered = sorted(bars, key=lambda bar: bar["t"])
    points = [{"t": int(bar["t"]), "c": round(float(bar["c"]), 6)}
              for bar in ordered]
    if not points:
        raise TvNotFound("No yield data for %s." % symbol)

    if interval == "1d":
        keep = onset_module.window_now([p["t"] for p in points],
                                       len(points) - 1,
                                       days=pse.RANGE_DAYS.get(
                                           span, pse.RANGE_DAYS["3mo"]))
        points = [points[i] for i in keep]
    if not points:
        raise TvNotFound("No yield data for %s in this window." % symbol)

    try:
        call = trend.classify([p["c"] for p in points])
    except ValueError:
        call = None   # a non-positive yield in the series; the chart still draws

    last = points[-1]["c"]
    return {
        "symbol": symbol,
        "name": NAMES.get(symbol) or symbol,
        "currency": "%",
        # The page's `formatPrice` reads a currency code; a yield is a
        # percentage, so it carries its unit here instead and the number is
        # printed with a trailing per-cent sign.
        "unit": "%",
        "exchange": "Philippine bond market",
        "type": "YIELD",
        "priceHint": 3,
        "previousClose": points[-2]["c"] if len(points) > 1 else None,
        "marketPrice": last,
        "points": points,
        # The page must be able to say what it is drawing and why the badge
        # reads the way it does -- see `bond_price_call`.
        "yieldSeries": True,
        "yieldTrend": call,
        "trend": bond_price_call(call),
        "source": "TradingView",
        # Seconds the reading predates the request, when the fetch failed and a
        # stored copy was served instead. Zero for a fresh fetch or a copy
        # inside `BOND_CACHE_TTL`.
        "stale": stale,
    }


def _mark_stale(payload: dict, age: float) -> dict:
    """Say a payload was built from a stored reading, in the shape a rescue speaks.

    A failed fetch that falls back to a copy older than `BOND_CACHE_TTL` is the
    same situation `diskcache`'s rescue describes: the answer is real, it just
    stopped arriving at `fetchedAt`. The payload therefore carries the same
    three stamps a rescue would add (`cached`, `fetchedAt`, `cacheError`), so
    the page dates the reading -- and, just as important, so a later read of a
    copy stored from this payload cannot pass it off as fresh.
    """
    payload["cached"] = True
    payload["fetchedAt"] = int(time.time() - age)
    payload["cacheError"] = "TradingView did not answer"
    return payload


def chart(symbol: str, span: str = "3mo", interval: str = "1d") -> dict:
    """The chart payload for one bond yield, from disk or the socket.

    A fresh copy is used without a browser run; otherwise the socket is asked,
    and a fetch that fails falls back to a copy up to `BOND_CACHE_KEEP` old and
    says how old it is. Only when there is nothing worth showing does this
    raise, and it raises `TvError` -- an outage, which the caller rescues from
    the chart cache like any other transport failure.
    """
    canonical_symbol = canonical(symbol)
    if canonical_symbol is None:
        raise TvNotFound("%r is not a Philippine bond yield." % symbol)

    days = pse.RANGE_DAYS.get(span, pse.RANGE_DAYS["3mo"])
    weekly = interval == "1wk"
    count = max(60, days // 7 + 8) if weekly else BARS

    bars, age = cached_bars(canonical_symbol)
    stale = 0
    if not weekly and bars is not None and age <= BOND_CACHE_TTL:
        pass                                   # fresh enough: no fetch at all
    else:
        try:
            bars = history(canonical_symbol, count=count,
                           interval=WEEKLY if weekly else INTERVAL)
            if not weekly:
                store_bars(canonical_symbol, bars)
        except TvError:
            if bars is None or age > BOND_CACHE_KEEP:
                raise
            # The wire did not answer and a stored copy is still worth
            # showing. The payload reports its age rather than passing it off
            # as today's reading.
            stale = int(age)
    payload = _chart_payload(canonical_symbol, bars, span, interval, stale)
    return _mark_stale(payload, age) if stale else payload


def charts_many(symbols: list[str], span: str = "3mo",
                interval: str = "1d") -> dict[str, dict | Exception]:
    """`chart()` for several tenors from as few socket runs as possible.

    The row warmer's leg: three sessions on one socket cost a single browser
    run, where three `chart()` calls would pay for three. Results are keyed by
    the spelling the caller asked with, and a symbol that could not be built
    maps to its exception -- `TvNotFound` for "not ours", `TvError` for an
    outage -- so the warmer can tell a verdict from a broken wire the way the
    PSE leg does.
    """
    asked: dict[str, str] = {}      # canonical -> spelling asked
    out: dict[str, dict | Exception] = {}
    for spelling in symbols:
        canonical_symbol = canonical(spelling)
        if canonical_symbol is None:
            out[spelling] = TvNotFound(
                "%r is not a Philippine bond yield." % spelling)
        else:
            asked[canonical_symbol] = spelling

    if not asked:
        return out

    days = pse.RANGE_DAYS.get(span, pse.RANGE_DAYS["3mo"])
    weekly = interval == "1wk"
    count = max(60, days // 7 + 8) if weekly else BARS

    series: dict[str, list[dict]] = {}
    ages: dict[str, float] = {}
    need: list[str] = []
    for canonical_symbol in asked:
        bars, age = cached_bars(canonical_symbol)
        if not weekly and bars is not None and age <= BOND_CACHE_TTL:
            series[canonical_symbol] = bars
        else:
            need.append(canonical_symbol)

    if need:
        fetched = histories(need, count=count,
                            interval=WEEKLY if weekly else INTERVAL)
        for canonical_symbol in need:
            bars = fetched.get(canonical_symbol)
            if bars:
                series[canonical_symbol] = bars
                if not weekly:
                    store_bars(canonical_symbol, bars)
                continue
            bars, age = cached_bars(canonical_symbol)
            if bars is not None and age <= BOND_CACHE_KEEP:
                series[canonical_symbol] = bars
                ages[canonical_symbol] = age

    for canonical_symbol, spelling in asked.items():
        bars = series.get(canonical_symbol)
        if not bars:
            out[spelling] = TvError(
                "TradingView did not answer for %s" % canonical_symbol)
            continue
        stale = int(ages.get(canonical_symbol, 0.0))
        try:
            payload = _chart_payload(canonical_symbol, bars, span,
                                     interval, stale)
        except Exception as exc:      # a malformed series is this row's problem
            out[spelling] = exc
        else:
            out[spelling] = (_mark_stale(payload, ages[canonical_symbol])
                             if stale else payload)
    return out


def _bars(rows: list) -> list[dict]:
    """TradingView's raw rows -> this project's bar shape.

    A row is `[time, open, high, low, close]` and, where there is one, a
    volume. A bond yield has no volume, so its rows stop at five -- and a
    missing volume is not a malformed row, it just means there is nothing to
    say about liquidity.
    """
    bars: list[dict] = []
    for row in rows or []:
        try:
            stamp = int(row[0])
            close = float(row[4])
        except (IndexError, TypeError, ValueError):
            continue
        if not close > 0:
            continue
        bar = {"t": stamp, "c": close}
        try:
            bar["v"] = float(row[5])
        except (IndexError, TypeError, ValueError):
            bar["v"] = 0.0
        bars.append(bar)
    return bars


def history(symbol: str, count: int = BARS,
            interval: str = INTERVAL) -> list[dict]:
    """Daily bars for `symbol`, oldest first.

    `symbol` is TradingView's own spelling -- "TVC:PH10Y" -- because there is
    no other way to name a bond yield.

    Raises `TvError` when the symbol could not be read. A refusal is a verdict
    about the symbol and an outage is a verdict about the wire; the caller
    decides what to do with each, and neither is worth a bar series.
    """
    try:
        rows = pse.history_many([symbol], count=count, timeframe=interval)
    except Exception as exc:
        raise TvError("TradingView did not answer for %s (%s)" % (symbol, exc))
    series = rows.get(symbol) or []
    if not series:
        raise TvError("TradingView sent no bars for %s" % symbol)
    return _bars(series)


def histories(symbols: list[str], count: int = BARS,
              interval: str = INTERVAL) -> dict[str, list[dict]]:
    """Daily bars for several symbols, read together.

    The bonds are three tenors of one curve and the page reads them as one
    thing, so they are asked for together: one browser run, one socket, three
    sessions on it. The socket handles the batching and the retry -- `pse.py`
    already does both, and does them without reporting a symbol it did not
    fetch as a symbol with no bars.

    A symbol that never answered is absent from the answer rather than an
    empty list, so the caller can tell "no bars" from "not asked".
    """
    symbols = [s for s in symbols if s]
    if not symbols:
        return {}
    try:
        rows = pse.history_many(symbols, count=count, timeframe=interval)
    except Exception:
        return {}
    out: dict[str, list[dict]] = {}
    for symbol, series in (rows or {}).items():
        bars = _bars(series)
        if bars:
            out[symbol] = bars
    return out
