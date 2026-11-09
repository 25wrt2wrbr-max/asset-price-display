#!/usr/bin/env python3
"""Recently bullish assets across markets, each dated to the day it turned.

Why this module exists
----------------------
The page grew three tables that each answer a piece of this question and a
fourth that answers none of it:

* "Bullish Philippine stocks" -- every PSE name whose chart is bullish, dated.
* "Most traded crypto" -- the heaviest coins whose chart is bullish.
* "Most traded today" -- the busiest listings in two markets, with no verdict.

None of them spans markets, and none of them has anything to say about the
Philippine government bond yield -- which is read with the same algorithm as
everything else and wants the same thing said about it: when did it turn?

So this module is the one table that answers it in one place. One row per
instrument, one column for the market it belongs to, one column for the date
the current run began, and the rows ordered newest-turn first, so the reader
sees what turned most recently across every market at a glance.

The label is the badge's, not a lookalike
-----------------------------------------
"Bullish" here means what `trend.classify` says, on the window the chart
draws -- there is no second definition of bullish in this project and there is
none here. The date is `onset`'s -- the same walk the Philippine sweep walks,
moved into a shared module so that one question has one answer. See
`onset.py`.

Every instrument is judged on its own source, and the sources are named in
the payload so a reader can see them:

* **Ondo stocks and ETFs** -- every stock and ETF listed at app.ondo.finance
  (`ondolist.tickers`), judged on Yahoo's daily bars, which are the bars the
  page's own chart draws for a US ticker. The row and the chart its click
  opens are the same series. Since 2026-11-07 the shelf **is** the universe at
  the reader's request ("the limit is just what's available at
  app.ondo.finance -- no longer trading volume"), so a name outside it is not
  scanned however heavily it trades, and a name inside it is scanned however
  thinly it trades.
* **Ondo intelligent portfolios** -- the seven baskets the same shop sells
  (`mag7xon`, `blkgrwon`, ...), judged on the token's own daily price from
  DeFiLlama, which is the series the chart a click opens draws (`ondo.py`).
* **Philippine stocks** -- the rows of the Philippine sweep (`bullish.py`),
  read from the sweep the server already keeps warm. This module does not
  re-sweep the exchange: the sweep takes about half a minute, and doing it
  twice would make this table fresher than the sweep it is built from.
* **Crypto** -- the chartable USDT ranking (`cryptobull.candidates`), judged
  on Binance's daily bars, the same bars the crypto table and the crypto
  chart use.
* **US Treasuries** -- the seven Treasury futures on the curve, 2-year through
  ultra bond (`rates.py`), judged on the same Yahoo daily bars the chart route
  draws for them. A fixed list rather than a ranking: there is one thirty-year
  contract, not a market of them to be scanned by turnover. A Treasury future
  is a *price*, so unlike the Philippine yields below nothing is inverted.
* **Philippine bonds** -- the 2-year, 5-year and 10-year government bond
  yields from TradingView (`tv.py`).
* **Philippine funds** -- the forty-seven peso funds a Philippine investor
  actually holds: the BPI Wealth UITFs, the ALFM and Odyssey funds, the
  Philippine Stock Index Fund and the four PERA funds. They have no ticker
  and no exchange; each publishes one NAVPU a business day, and `phfunds.py`
  reads that series from the registry that publishes it. A NAVPU is a daily
  close, so it is judged exactly as any other price is.

The bond yield is the one row that reads the other way
------------------------------------------------------
The same classifier reads the yield series, but the displayed direction is
inverted to reflect the usual price movement of an existing fixed-rate bond:
a falling yield is "bullish (yield falling)" and is the only bond verdict this
table carries. The date is the start of the underlying yield run. This is an
inference from yields, not a price chart or a forecast.

The peso column
---------------
Each row carries its turnover twice: in the currency it was traded in
(`turnover`) and in pesos (`turnoverPhp`). The conversion is the leaderboards'
own `markets.php_per_usd` rate, so every table that shows a peso figure on this
page shows the same one. A yield has no traded volume and a futures contract's
volume is a count of contracts, not money, so those rows carry no peso figure
and the cell says so.

What is not in the table
------------------------
Nothing that is not bullish is in it. A bearish US stock is not a row, because
the table is a table of things that are going up, and the Philippine sweep
already stands as the place to read about a name that is not. The bond yields
follow the same rule, on the bond-price reading: a falling yield is a row, and
a rising or flat one is not -- the yield is still one instrument per tenor
rather than a candidate picked from a market, but the verdict decides whether
the row is there like every other market's.

How the history behind the date is fetched
------------------------------------------
The walk redraws a ninety-day window at every bar it tests, so it needs
history behind that window: a year of daily bars for each instrument, which
is what `WALK_SPAN` asks for. A price that is bullish over the last three
months but was falling a year ago has a run that starts inside the fetched
history, and a run that reaches back past it is reported as *censored* --
"bullish for at least this long" -- rather than dated to the oldest bar
fetched, which would be a date the data does not support.

The US leg's bars come from Yahoo, which the browser fetches for this project
because Yahoo answers plain HTTP clients with a 429. That fetch is injected
rather than imported: `scan` takes a `fetch_us_bars` callable, because the
browser lives in `server.py` and `server.py` imports this module. The same
injection keeps this module testable without a browser.

Standard library only, like the rest of the project. It imports `markets`,
`cryptobull`, `crypto`, `tv`, `pse`, `phfunds` and `onset`, and nothing imports
it but the server.
"""

from __future__ import annotations

import concurrent.futures
import time

import crypto
import cryptobull
import markets
import ondo
import ondolist
import onset as onset_module
import phfunds
import pse
import rates
import tv

# How many United States listings the **fallback** judges, when the Ondo shelf
# could not be read at all.
#
# The universe is normally the shelf (`ondolist.tickers`): every stock and ETF
# the shop lists, and nothing else, at the reader's request of 2026-11-07. A
# turnover ranking is still here for the one case it is the honest answer to --
# an unreadable shelf. With no shelf there is no universe, and an outage must
# not empty the table (invariant 3), so this leg falls back to the most-traded
# names the scanner can name and says in the note that it did. It is a
# fallback, not a limit: with a shelf in hand this number is never consulted.
#
# The cutoff used to be the product itself (50, then 130), and it cut real
# names off -- WMT ranked 57th by turnover and KO 124th. That is the defect the
# shelf replaces: neither ranking is what the reader can buy.
US_FALLBACK_LIMIT = 130

# How many of the heaviest coins are also read for **leaning** rows. The
# bullish rows are judged over the whole chartable ranking (`crypto_rows` says
# why); the leaning list is a curated side-table, and widening it would change a
# table the merge did not touch. Twenty-five is the depth that list has always
# had.
CRYPTO_LIMIT = 25

# The window a coin's chart draws, in **calendar months** -- the same rule the
# Yahoo chart is trimmed with, and now the same rule Binance's chart is trimmed
# with (`crypto.RANGE_MONTHS`). It is not 90 days: three months back from
# 2026-11-07 is 92 days, and a table that judged 90 while the chart drew 92 was
# measuring a different window from the one it opens. Asked for by name:
# "if there are 93 bars in yahoo, there should also be 93 data points from
# Binance not just 90 ... for uniformity and fairness".
CRYPTO_WINDOW_MONTHS = 3

# The smallest peso turnover a **Philippine stock** must show to stay on the
# table, and the only market that has a floor. Asked for by name, 2026-11-07:
# "there should still be a volume floor for philippines stocks. PHP1M".
#
# The live case it produces: PAL was bullish at +0.77 with a 14-bar run on
# ₱311,040 of turnover, so the sweep judges it and the table hides it -- and the
# note says how many it hid, so a name that is bullish on its own chart is never
# silently missing (the reader's own complaint, and the reason the count is
# printed rather than the filter being silent).
#
# Two markets are deliberately outside it:
#
# * the **Ondo** rows, because the reader's rule is that the shelf is the limit;
#   a volume floor on top of it would be a second limit they did not ask for;
# * the **crypto** rows, whose ranking already stops at `CRYPTO_LIMIT`.
#
# A row with no traded volume at all -- a bond yield, a fund, a portfolio -- is
# exempt from the test: it never had a peso figure to fail it with.
MIN_TURNOVER_PHP = 1_000_000
FLOOR_MARKETS = ("Philippines",)

# What the Philippine universe is made of, in the order the note prints it
# (2026-11-09). The reader asked why they should believe 262 listings were
# looked at rather than ten: the note now says how many of each kind, from the
# sweep's own `kinds` count. An index is scanned too, so it is named here --
# else "249 + 11 + 1 + 1" would not add up to the scanned figure beside it.
# `pse._kind` is the vocabulary: EQUITY, PREFERRED, ETF, CLOSEDEND, INDEX,
# MUTUALFUND, plus UNKNOWN for a shape it did not name.
PH_KIND_WORDS = (
    ("EQUITY", "common share", "common shares"),
    ("PREFERRED", "preferred share", "preferred shares"),
    ("ETF", "ETF", "ETFs"),
    ("CLOSEDEND", "closed-end fund", "closed-end funds"),
    ("INDEX", "index", "indexes"),
    ("MUTUALFUND", "fund", "funds"),
    ("UNKNOWN", "unclassified listing", "unclassified listings"),
)

# What the leaning table is allowed to show, at the reader's request
# (2026-11-06): only what can be bought at app.ondo.finance. A United States
# row must have an Ondo token (`ondolist`), and a leg whose instruments that
# shelf does not carry at all -- the Philippine funds -- keeps no leaning rows.
#
# Since 2026-11-07 the same shelf is the scan's **universe** for both tables,
# so for these two markets this filter can only ever confirm what the leg
# already did. It stays because it is also applied to a table read back from
# disk (`server.seed_recent`), where the universe that swept it may have been
# a different, wider one -- and because "is it for sale" and "was it scanned"
# are two questions that should not have to agree by luck.
ONDO_CHECKED_MARKETS = ("US", "Ondo portfolio")
ONDO_ABSENT_MARKETS = ("Philippine fund",)

# The Philippine government bond yields, and what they are called. Two-year,
# five-year, ten-year: the short, the middle and the long of the curve, so the
# reader can see whether the whole curve is moving or only one end of it.
#
# The list lives in `tv.py`, which now also owns the chart each of these rows
# opens. This is that tuple, not a copy of it: one tenor, one spelling, one
# name, so a symbol cannot exist in the table and be missing from the chart
# route (or the other way round).
BONDS = tv.BONDS

# The span fetched behind the ninety-day window the walk reads. A year of
# daily bars is four windows of history behind the latest bar, which is what
# a run that reaches the start of the fetched data needs to be reported as
# censored rather than dated to a bar that only happens to be the oldest one.
WALK_SPAN = "1y"
WALK_INTERVAL = "1d"

# How far behind the clock a daily series may be before it stops being a price.
#
# The case it exists for, measured 2026-11-07 so the standing is on the record:
# **ATKR** (Atkore Inc) was the first row of "Leaning bullish - not
# confirmed", priced $94.96, and its newest bar was **2026-10-16** -- three
# weeks dead, because the company had been taken over and the source had
# stopped printing. Nothing in the scan could tell: the series answered, the
# classifier read 51 bars of a frozen price, `onset.steady_lean` found the lean
# steady (held 5 of 5), and a stopped stock was put on the table as a near-miss
# to buy. The reader's words: "ATKR last price was October. wtf. don't show me
# this."
#
# A United States listing's newest daily bar is the last session's close, so on
# any evening it is hours old, across a weekend two or three days, and across a
# holiday weekend at most four. Five days is not a long weekend. It is also
# `crypto.STALE_BAR_DAYS`'s number for a pair Binance has stopped trading --
# the same idea at the same tolerance, and deliberately the same number, so
# "five days of silence" means one thing in this project. Measured that day:
# 473 of the shelf's 474 names answered with a bar 0.3 days old, and ATKR with
# one 21.3 days old. There was no middle ground to tune against.
#
# **What it is not applied to, and why.** The Philippine sweep, the funds and
# the bonds are read from sources whose markets close for long holidays -- the
# PSE shuts from 23 December to 4 January -- so a calendar gap there is a
# calendar fact, not a dead series. Crypto has its own test (`crypto.py`), and
# the Ondo tokens are priced by DeFiLlama at the moment of the request.
STALE_GAP_DAYS = 5

# The markets `drop_stale` re-filters in a table read back from disk: the leg
# this rule is written for, and the only one whose bars come from a market that
# never closes for more than a holiday weekend plus one day.
STALE_MARKETS = ("US",)


# How many coins are fetched at once. Binance is a public endpoint and this
# is a handful of plain HTTPS calls; eight at a time is well inside what it
# serves without a second thought.
CRYPTO_WORKERS = 8

# How long a fetched yield series is considered fresh, and how long it is kept
# as a fallback, and where it is kept.
#
# The yields come over TradingView's chart socket, which is the same socket the
# Philippine sweep uses and the same browser that fetches Yahoo -- so the read
# is quick and usually answers. "Usually" is the word that matters: the
# socket is shared with the sweep, and a sweep under load can come back short.
# So a fetch that succeeded is worth keeping, and a yield is a daily close, so
# a copy a few hours old has missed at most one bar.
#
# Two ages, because they answer two questions. `BOND_CACHE_TTL` is how long
# a copy is fresh enough to skip the fetch for: six hours, which is most of a
# trading day and most of the sweeps. `BOND_CACHE_KEEP` is how long a copy is
# still worth showing when the fetch failed: a week, because a row that says
# "the 10-year was 8.167% and rising" as of last Tuesday is more use than no
# row at all -- and the row says how old it is.
#
# Both ages belong to `tv.py` now, and so does the copy itself: the chart route
# reads the very same disk entry the row does, so the graph a click opens draws
# the bars the row was judged on, and neither side can age it by its own rule.
BOND_CACHE_TTL = tv.BOND_CACHE_TTL
BOND_CACHE_KEEP = tv.BOND_CACHE_KEEP


def _cached_bonds(symbol: str) -> tuple[list[dict] | None, float]:
    """The stored bars for a yield and how old they are. (None, 0) if there are none.

    The copy is `tv.cached_bars`'s, deliberately: the chart route reads through
    the same function, so the row and the chart are one series and one age.
    """
    return tv.cached_bars(symbol)


class RecentError(RuntimeError):
    """The table could not be assembled."""


def utc_day(stamp: int) -> str:
    """A bar's calendar date, as `YYYY-MM-DD`, in UTC.

    UTC because a daily US bar is stamped at the session's open -- 13:30 or
    14:30 UTC -- so the UTC date is the session's own date in every case that
    matters, and every other date this table prints is that shape.
    """
    return time.strftime("%Y-%m-%d", time.gmtime(int(stamp)))


def stale_gap(stamps, reference: float | None = None) -> float | None:
    """How many days the newest bar falls behind `reference`, if it is stale.

    `None` means "not stale", and it means two other things as well, on
    purpose: a series with no bars at all is not a stopped series -- that is
    `missing`, and it is counted there (invariant 3) -- and a series within
    `STALE_GAP_DAYS` of the reference is current.

    `reference` is what the series is read *against*, and the two callers want
    different things from it:

    * a **live read** -- the sweep, or one chart -- compares against the clock,
      because the question is "is this a price now?";
    * a **copy read back from disk** compares against the moment it was swept,
      because a table swept six days ago holds six-day-old bars that were
      current when they were fetched. Judged against today, such a copy would
      read as a table of dead series -- a fetch-age fact dressed up as a
      stock's.
    """
    if not stamps:
        return None
    try:
        newest = max(int(stamp) for stamp in stamps)
    except (TypeError, ValueError):
        return None
    now = time.time() if reference is None else float(reference)
    gap = (now - newest) / 86_400.0
    return gap if gap > STALE_GAP_DAYS else None


def stale_entry(ticker: str, stamps, gap: float, symbol: str | None = None) -> dict:
    """The `stats` record of one series left off the table for having stopped."""
    try:
        newest = max(int(stamp) for stamp in stamps)
    except (TypeError, ValueError):
        newest = None
    entry = {
        "ticker": ticker,
        "chartSymbol": symbol or ticker,
        "lastBar": utc_day(newest) if newest is not None else None,
        "days": int(round(gap)),
    }
    return entry


def drop_stale(rows: list[dict],
               reference: float | None = None) -> tuple[list[dict], list[dict]]:
    """Split rows into the ones still worth showing and the ones that stopped.

    For a table read back from disk (`server.seed_recent`): a copy swept before
    this rule existed can hold a row whose series had already stopped, and a
    seed is on screen until the first sweep lands -- long enough for the reader
    who objected to ATKR to see it again after a restart. Only `STALE_MARKETS`
    is re-filtered; every other leg keeps its own freshness rules.

    The second answer is in `stats` shape (`stale_entry`), so the note can say
    what was dropped instead of the row simply disappearing.
    """
    kept: list[dict] = []
    stale: list[dict] = []
    for row in rows or []:
        if row.get("market") not in STALE_MARKETS:
            kept.append(row)
            continue
        last = row.get("last")
        gap = stale_gap([last] if last is not None else [], reference)
        if gap is None:
            kept.append(row)
        else:
            stale.append(stale_entry(row.get("ticker") or row.get("symbol"),
                                     [last], gap, row.get("chartSymbol")))
    return kept, stale


def _series(points: list, volumes: list | None = None) -> tuple[list[int], list[float], list]:
    """A chart payload's points -> (stamps, closes, volumes), aligned.

    The alignment is the point: a volume belongs to a bar or to nothing, and
    a bar with no volume must not borrow its neighbour's. A missing volume
    is zero, which `trend.classify` reads as "no volume to say" -- the same
    reading the Philippine sweep gives an index.
    """
    stamps: list[int] = []
    closes: list[float] = []
    vols: list[float] = []
    for i, point in enumerate(points or []):
        try:
            stamps.append(int(point["t"]))
            closes.append(float(point["c"]))
        except (KeyError, TypeError, ValueError):
            continue
        volume = None
        if volumes is not None and i < len(volumes):
            try:
                volume = float(volumes[i])
            except (TypeError, ValueError):
                volume = None
        vols.append(volume or 0.0)
    return stamps, closes, vols


def _window_move(row: dict) -> float | None:
    """The window's relative move: first drawn close to the newest.

    `onset` ships the pair as raw closes (`windowFirst`, `price`) because a
    price moves in per cent and a yield in percentage points; this is the
    price-side reading of it. The chart prints the same pair under the price
    ("+12.95% three-month move, since Jul 31"), so a row and its chart cannot
    disagree about how the window went.
    """
    first = row.get("windowFirst")
    last = row.get("price")
    if not first or last is None:
        return None
    try:
        return round(float(last) / float(first) - 1.0, 6)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _price_row(market: str, symbol: str, chart_symbol: str, ticker: str,
               name: str, kind: str, currency: str,
               call: dict, score=None) -> dict:
    """One bullish price, in the row shape the table draws."""
    return {
        "market": market,
        "symbol": symbol,
        "chartSymbol": chart_symbol,
        "ticker": ticker,
        "name": name,
        "kind": kind,
        "price": call["price"],
        "currency": currency,
        "direction": "bullish",
        "since": call["since"],
        "run": call["run"],
        "censored": call["censored"],
        "manner": call["manner"],
        "turnMove": call["turnMove"],
        "score": call["score"],
        "bars": call["bars"],
        "last": call["last"],
        "turnover": call["turnover"],
        # The three-month move the row prints: the window's first close to the
        # newest, the same pair the chart's hero delta uses.
        "windowMove": _window_move(call),
        "chartable": True,
    }


def _lean_row(market: str, symbol: str, chart_symbol: str, ticker: str,
              name: str, kind: str, currency: str, lean: dict) -> dict:
    """One leaning-bullish price: the badge reads Neutral, in the hold band.

    It carries `lean` instead of a run, because no label was ever given and
    there is no "since" to date. `scan` moves every row carrying `lean` out of
    the bullish table and into the payload's `leaning` list.
    """
    return {
        "market": market,
        "symbol": symbol,
        "chartSymbol": chart_symbol,
        "ticker": ticker,
        "name": name,
        "kind": kind,
        "price": lean["price"],
        "currency": currency,
        "direction": "neutral",
        "lean": "bullish",
        "score": lean["score"],
        "significance": lean["significance"],
        "progress": lean["progress"],
        "bars": lean["bars"],
        "last": lean["last"],
        "turnover": lean["turnover"],
        # How steady the lean is: the same call on the last `holdBars` bars, and
        # how many of them answered "leaning". Present on every row produced by
        # `onset.steady_lean`; None on anything that reached here another way.
        "held": lean.get("held"),
        "holdBars": lean.get("holdBars"),
        "chartable": True,
    }


def actionable(leaning: list[dict], shelf: dict | None) -> list[dict]:
    """The leaning rows a reader can act on at app.ondo.finance.

    Three answers, and the middle one is the point:

    * a United States row stays only when the shelf lists its ticker;
    * a leg the shelf cannot carry at all (`ONDO_ABSENT_MARKETS`) keeps no row;
    * every other market is untouched, because the request named the United
      States listings and the funds, not the peso stocks or the coins.

    `shelf` is None when the shelf could not be read and no copy was kept. That
    is not "nothing is listed" -- it is an outage, and an outage must not hide
    rows (invariant 3), so every row is kept and the payload says the filter
    did not run.
    """
    if not shelf:
        return list(leaning)
    kept: list[dict] = []
    for row in leaning:
        market = row.get("market")
        if market in ONDO_ABSENT_MARKETS:
            continue
        if market in ONDO_CHECKED_MARKETS and not ondolist.carries(
                row.get("ticker"), shelf):
            continue
        kept.append(row)
    return kept


def shelf_universe(shelf: dict | None) -> tuple[list[dict], bool]:
    """The Ondo shelf as bar-fetch records, and whether the shelf was readable.

    One record per stock and ETF the shop lists, in the shape `us_universe`
    rows have (`ticker`, `chartSymbol`, `name`, `kind`, `currency`) so the walk
    below never has to know where its universe came from. Two fields are
    placeholders: the shelf names a token, not a company, so `name` starts as
    the ticker and `kind` as a common stock, and Yahoo's own meta replaces both
    the moment the bars answer (`fetch_us_bars`).

    A shelf that could not be read answers the scanner's turnover ranking
    instead, with the flag set to False so the note can say the leg fell back.
    That is the only case a turnover limit still decides what is scanned.
    """
    if shelf:
        records = []
        seen: set[str] = set()
        for ticker in ondolist.tickers(shelf):
            symbol = markets.yahoo_symbol(ticker)
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            records.append({
                "ticker": ticker,
                "chartSymbol": symbol,
                "name": ticker,
                "kind": "Common stock",
                "currency": "USD",
            })
        return records, True

    universe = markets.us_universe(US_FALLBACK_LIMIT)
    records = []
    for row in universe:
        ticker = row.get("ticker")
        if ticker:
            records.append(row)
    return records, False


def us_rows(fetch_us_bars, shelf: dict | None = None) -> tuple[list[dict], dict]:
    """The bullish Ondo stocks and ETFs, and what the scan could not say.

    `fetch_us_bars` is called with the tickers to judge and answers
    `{ticker: (stamps, closes, volumes, meta)}` -- the bars the page's own
    chart draws for that ticker, plus Yahoo's name for it. It is injected
    because the fetch is a browser one and the browser lives in `server.py`.

    A ticker whose bars did not arrive is left out and counted in `missing`:
    the alternative, treating it as "not bullish", would put a fetch failure
    into the table as a fact about the stock.

    A ticker whose bars *did* arrive but stopped weeks ago is left out too, and
    counted in `stale` with the date of its last bar: a frozen price is not a
    price now, and a verdict read off it is a verdict about the month it
    stopped in (see `STALE_GAP_DAYS`, and ATKR as the case that made it
    visible). The note prints those names, so a row that is absent is never
    unexplained.

    The window is Yahoo's own three *calendar* months, not ninety days,
    because that is the window the chart route asks Yahoo for and so the
    window the chart draws. The two are a couple of trading sessions apart,
    which is nothing -- except that `trend.classify` changes regime at 63
    bars, so ninety days (62 bars for a US listing) and Yahoo's window (64
    bars) are judged by different weight tables and can answer differently.
    SPY was the proof: bullish here at +0.27, neutral on its own chart.

    The bars are asked for under the row's `chartSymbol`, which is the
    spelling the chart route draws -- a class share carries Yahoo's dash
    (`BRK-B`), not the shelf's dot (`brk.bon`, `BRK.B`). Judging the shelf's
    spelling would report the name as a fetch failure on every sweep, which is
    a wrong fact about a stock that answers perfectly well under its own name.
    """
    records, from_shelf = shelf_universe(shelf)
    symbols = [record.get("chartSymbol") or record.get("ticker")
               for record in records]
    symbols = [symbol for symbol in symbols if symbol]
    if not symbols:
        raise RecentError("the Ondo shelf is empty")

    by_symbol: dict[str, dict] = {}
    for record in records:
        by_symbol.setdefault(record.get("chartSymbol") or record.get("ticker"),
                             record)

    try:
        bars = fetch_us_bars(symbols) or {}
    except Exception as exc:
        raise RecentError("the US bars could not be fetched: %s" % exc)

    rows: list[dict] = []
    missing: list[str] = []
    stale: list[dict] = []
    for symbol in symbols:
        record = by_symbol[symbol]
        ticker = record.get("ticker") or symbol
        series = bars.get(symbol)
        if not series:
            missing.append(ticker)
            continue
        stamps, closes, volumes = series[:3]
        meta = series[3] if len(series) > 3 and isinstance(series[3], dict) else {}
        # A series the source stopped printing is not judged at all, in either
        # table: a verdict read off a frozen price is a verdict about the month
        # it stopped in, and the row would carry that month's price as though it
        # were today's. Counted, not swallowed -- the note prints the names and
        # their last bar, because a name that vanished without a word is the
        # thing the reader objected to about the peso floor (see
        # `STALE_GAP_DAYS`).
        gap = stale_gap(stamps)
        if gap is not None:
            stale.append(stale_entry(ticker, stamps, gap, symbol))
            continue
        call = onset_module.onset(stamps, closes, volumes, want="bullish",
                                  months=onset_module.WINDOW_MONTHS)
        name = meta.get("name") or record.get("name") or ticker
        kind = meta.get("kind") or record.get("kind") or "Common stock"
        currency = meta.get("currency") or record.get("currency") or "USD"
        if call is None:
            lean = onset_module.steady_lean(
                stamps, closes, volumes, months=onset_module.WINDOW_MONTHS)
            if lean is not None:
                rows.append(_lean_row(
                    "US", ticker, symbol, ticker, name, kind, currency, lean))
            continue
        rows.append(_price_row(
            "US", ticker, symbol, ticker, name, kind, currency, call))
    return rows, {"universe": len(records), "missing": sorted(missing),
                  "stale": stale, "shelf": from_shelf}


def ondo_portfolio_rows(shelf: dict | None = None) -> tuple[list[dict], dict]:
    """The bullish Ondo intelligent portfolios, and what the scan could not say.

    The seven baskets are tokens on the same shelf, so they belong in the same
    two tables -- asked for by name, 2026-11-07: "include all stocks & ETFs,
    and intelligent portfolios". Their bars are the token's own daily price
    from DeFiLlama (`ondo.bars_for`), which is exactly what the chart a click
    opens draws, so a row and its chart are one series as everywhere else.

    The window is the chart's: `ondo` trims to ninety calendar days for `3mo`
    (`RANGE_DAYS`), so this walk asks for the default ninety-day window rather
    than Yahoo's calendar-month one. They are different shops with different
    trims, and the rule is that a row is the verdict its own chart shows.

    A portfolio that did not answer is counted in `missing`, never judged: a
    token six weeks old has 43 bars, and an empty fetch is an outage, not a
    neutral basket.

    Two things are deliberately plain:

    * **No turnover.** A portfolio token is bought and redeemed, not traded on
      an exchange, so its bars carry no volume and the row carries none either
      -- the peso floor does not apply, and the column says so.
    * **A fixed list, and the shelf decides which of it is on sale.** The
      tokens live in `ondo.py` (a chart needs an identity); the shelf says
      which are still listed, and `actionable` filters the leaning half.
    """
    tokens = ondo.portfolio_tokens()
    listed = set(ondolist.portfolios(shelf)) if shelf else None
    rows: list[dict] = []
    missing: list[str] = []
    judged = 0
    for token in tokens:
        ticker = token["ticker"]
        if listed is not None and ticker not in listed:
            # No longer on sale. Not a fetch failure and not a verdict, so it
            # is not counted as either: the shop stopped listing it.
            continue
        try:
            bars = ondo.bars_for(token, WALK_SPAN)
        except ondo.OndoError:
            missing.append(ticker)
            continue
        judged += 1
        stamps, closes, volumes = _series(bars)
        call = onset_module.onset(stamps, closes, volumes, want="bullish")
        symbol = ondo.symbol_for(ticker)
        hint = ondo.price_hint(bars)
        if call is None:
            lean = onset_module.steady_lean(stamps, closes, volumes)
            if lean is not None:
                row = _lean_row("Ondo portfolio", symbol, symbol, ticker,
                                token["name"], token.get("kind"), "USD", lean)
                row.update({"turnover": None, "turnoverPhp": None,
                            "priceHint": hint})
                rows.append(row)
            continue
        row = _price_row("Ondo portfolio", symbol, symbol, ticker,
                         token["name"], token.get("kind"), "USD", call)
        row.update({"turnover": None, "turnoverPhp": None, "priceHint": hint})
        rows.append(row)
    return rows, {"universe": judged + len(missing), "missing": sorted(missing)}


def rate_rows(fetch_us_bars) -> tuple[list[dict], dict]:
    """The bullish United States Treasury futures, and what the scan could not say.

    The curve is a fixed list (`rates.CONTRACTS`), not a ranking: the
    United States leg above judges the most *traded* listings, and a futures
    contract has no place in that -- the TradingView scanner cannot even name
    one -- so every rate was outside this table whatever its chart said. Seven
    contracts, one per curve point, judged exactly like a stock: Yahoo's daily
    bars, which are the bars the chart a click opens draws (the chart route
    sends `ZB=F` to Yahoo, and `fetch_us_bars` asks for the same URL shape), and
    the same `onset` walk over them.

    The window is Yahoo's own three *calendar* months, as it is for the United
    States leg, because that is the window the chart draws.

    Two things are deliberately not the Philippine bond leg:

    * **Nothing is inverted.** A Treasury future is a price, so the
      classifier's own label is the row's -- a higher quote is a higher bond
      price is bullish. `tv.BONDS` inverts because it reads a yield; there is
      no yield here to read.
    * **No turnover.** A contract's volume counts contracts, and close times
      contracts is not a traded value in any currency, so the row carries
      `turnover: None` -- a dash, the way a bond yield and a fund print one.
      The price carries its own
      precision (`rates.price_hint`), because a Treasury quote's fraction is a
      32nd and two decimals would round it away.

    `fetch_us_bars` is the server's browser fetch, injected for the reason
    `us_rows` gives. It is called a second time rather than being merged into
    the United States leg's call: one leg failing must not take the other with
    it, and six symbols are one browser run (~2 s) inside a sweep that already
    spends most of a minute.

    A contract whose bars did not arrive is counted in `missing` and left out,
    never judged bearish (invariant 3).
    """
    contracts = rates.CONTRACTS
    symbols = [contract["symbol"] for contract in contracts]
    try:
        bars = fetch_us_bars(symbols) or {}
    except Exception as exc:
        raise RecentError("the Treasury futures' bars could not be fetched: %s"
                          % exc)

    rows: list[dict] = []
    missing: list[str] = []
    for contract in contracts:
        series = bars.get(contract["symbol"])
        if not series:
            missing.append(contract["ticker"])
            continue
        stamps, closes, volumes = series[:3]
        call = onset_module.onset(stamps, closes, volumes, want="bullish",
                                  months=onset_module.WINDOW_MONTHS)
        hint = rates.price_hint(closes)
        if call is None:
            lean = onset_module.steady_lean(
                stamps, closes, volumes, months=onset_module.WINDOW_MONTHS)
            if lean is not None:
                row = _lean_row(
                    "US Treasury", contract["symbol"], contract["symbol"],
                    contract["ticker"], contract["name"], "Treasury future",
                    "USD", lean)
                row.update({"turnover": None, "turnoverPhp": None,
                            "priceHint": hint})
                rows.append(row)
            continue
        row = _price_row(
            "US Treasury", contract["symbol"], contract["symbol"],
            contract["ticker"], contract["name"], "Treasury future", "USD",
            call)
        row.update({"turnover": None, "turnoverPhp": None, "priceHint": hint})
        rows.append(row)
    return rows, {"universe": len(contracts),
                  "count": sum(1 for row in rows if not row.get("lean")),
                  "missing": sorted(missing)}


def crypto_rows() -> tuple[list[dict], dict]:
    """The bullish coins of the chartable USDT ranking.

    The ranking is the one the crypto table walked -- the chartable coins,
    heaviest twenty-four-hour turnover first -- and the bars are Binance's,
    the same ones the crypto chart draws. A coin whose bars did not arrive
    is counted in `missing` rather than judged bearish.

    The walk reads the **whole** ranking, not a top slice: every other market
    on this table is judged exhaustively (the Ondo shelf, the PSE universe, all
    47 funds), and a coin that is bullish on its own chart is a row however
    thinly it trades. A top-25 cut used to be enough when the crypto table sat
    below this one with its own deeper walk; with that table merged in, the cut
    would silently lose rows it was showing -- measured 2026-11-07, the one
    bullish coin of the day (BEAMUSDT, $0.74M traded) ranked around 200th.

    The day condition the crypto table kept is **not** applied. That table was
    a list of what was heavy *and* up today, and a red row under its heading
    read as a fault; this table is the three-month verdict, and the reader asked
    for the three-month reading only -- so the rolling day is not a filter and
    not a figure on the row either.

    Leaning rows are still read only from the first `CRYPTO_LIMIT` candidates,
    so the leaning table is exactly what it was.
    """
    ranked = cryptobull.candidates(cryptobull.MAX_CANDIDATES)
    rows: list[dict] = []
    missing: list[str] = []
    scanned = 0

    def probe(candidate):
        return crypto.try_chart(candidate["symbol"], WALK_SPAN, WALK_INTERVAL)

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(CRYPTO_WORKERS, max(1, len(ranked)))) as pool:
        charts = list(pool.map(probe, ranked))

    for index, (candidate, chart) in enumerate(zip(ranked, charts)):
        scanned += 1
        if chart is None:
            missing.append(candidate["symbol"])
            continue
        stamps, closes, volumes = _series(chart.get("points"),
                                          chart.get("volumes"))
        call = onset_module.onset(stamps, closes, volumes, want="bullish",
                                  months=CRYPTO_WINDOW_MONTHS)
        if call is not None:
            row = _price_row(
                "Crypto", chart["symbol"], chart["symbol"],
                candidate["ticker"], candidate["name"], "Coin", "USD", call,
            )
            # The rolling day's change is not carried: this table reports the
            # three-month verdict and the window's own figures, and the reader
            # asked for the three-month reading only (2026-11-07).
            # Decimals the price is drawn at, by magnitude: at the table's
            # default two, a sub-cent coin prints "$0.00", which is a figure
            # that says nothing. The chart's own readout uses the same hint.
            row["priceHint"] = chart.get("priceHint")
            rows.append(row)
            continue
        if index >= CRYPTO_LIMIT:
            continue
        lean = onset_module.steady_lean(stamps, closes, volumes,
                                        months=CRYPTO_WINDOW_MONTHS)
        if lean is not None:
            rows.append(_lean_row(
                "Crypto", chart["symbol"], chart["symbol"],
                candidate["ticker"], candidate["name"], "Coin", "USD",
                lean))
    return rows, {"universe": len(ranked), "scanned": scanned,
                  "missing": sorted(missing)}


def bond_rows() -> tuple[list[dict], dict]:
    """The Philippine government bond yields, and how each is trending.

    The same classifier reads the yield; the displayed bond-price direction
    and score are inverted. The run remains the underlying yield's run.

    Only a **falling** yield is a row: that is the one yield movement that
    reads as a bond price going up. A rising yield reads as a falling bond
    price, and a flat one has no run to date at all -- neither is something
    that turned bullish, so neither belongs in this table (changed
    2026-10-31, at the reader's request; the three tenors used to be shown
    whatever their verdict). The tenors that were judged and dropped are
    counted in the leg's stats, so the note above the table still says how
    many of the curve's three points were read.

    The three tenors are fetched together -- one browser run, one socket, three
    sessions on it -- and each is kept for `BOND_CACHE_TTL` afterwards, so a
    sweep fifteen minutes after the last one does not pay for the fetch again.
    """
    rows: list[dict] = []
    missing: list[str] = []

    wanted = [symbol for symbol, _ in BONDS]
    series: dict[str, list[dict]] = {}
    ages: dict[str, float] = {}
    # The copies that had to be served past their TTL because the fetch did
    # not answer. A copy inside its TTL is an ordinary cache hit and is not
    # flagged; a copy past it is a fallback, and the reader is told.
    fallbacks: set[str] = set()

    # Fresh copies are used as they are, and the network is only asked for
    # the ones that have none.
    for symbol in wanted:
        bars, age = _cached_bonds(symbol)
        if bars is not None and age <= BOND_CACHE_TTL:
            series[symbol] = bars
            ages[symbol] = age

    if len(series) < len(wanted):
        stale = [symbol for symbol in wanted if symbol not in series]
        fresh = tv.histories(stale)
        for symbol, bars in fresh.items():
            series[symbol] = bars
            ages[symbol] = 0.0
            try:
                diskcache.store(BOND_CACHE_PREFIX + symbol, bars)
            except Exception:
                pass

    # What the network could not answer is served from an older copy if one
    # exists: a row that says "as of three days ago" is more use than a gap
    # in the curve, and the row says which it is.
    for symbol in wanted:
        if symbol in series:
            continue
        bars, age = _cached_bonds(symbol)
        if bars is not None and age <= BOND_CACHE_KEEP:
            series[symbol] = bars
            ages[symbol] = age
            fallbacks.add(symbol)

    for symbol, name in BONDS:
        bars = series.get(symbol)
        if not bars:
            missing.append(symbol)
            continue
        age = ages.get(symbol, 0.0)
        stamps = [bar["t"] for bar in bars]
        closes = [bar["c"] for bar in bars]
        volumes = [0.0] * len(closes)
        call = onset_module.current(stamps, closes, volumes)
        if call is None:
            missing.append(symbol)
            continue

        label = call["label"]
        # A falling yield is the only one kept: read as a bond price it is the
        # one direction this table is about. A rising yield would be a bearish
        # row and a flat one has no run to date, so both are dropped here
        # rather than filtered later by the reader.
        if label != "bearish":
            # A yield in the falling side's hold band is a bond price leaning
            # bullish: same window, same reversal as the row below.
            lean = (onset_module.steady_lean(stamps, closes, volumes,
                                             want="bearish")
                    if label == "neutral" else None)
            if lean is not None:
                row = _lean_row("Philippine bond", symbol, symbol,
                                symbol.split(":")[-1], name,
                                "Government bond yield", "%", lean)
                row.update({
                    "note": "yield falling",
                    "score": -lean["score"],
                    "significance": (-lean["significance"]
                                     if lean["significance"] is not None
                                     else None),
                    "turnover": None,
                    "tz": "Asia/Manila",
                    "stale": int(age) if symbol in fallbacks else 0,
                })
                rows.append(row)
            continue

        # The run of the direction the yield is actually in, which is the one
        # just checked: bearish, so a falling yield.
        run = onset_module.onset(stamps, closes, volumes, want="bearish")
        if run is None:
            # The badge and the walk disagreed on the latest bar; a row with no
            # date cannot say "since when", so it is counted rather than shown.
            missing.append(symbol)
            continue

        rows.append({
            "market": "Philippine bond",
            "symbol": symbol,
            # The row's chart is drawn from the same TradingView series the row
            # was judged on (see `tv.chart`), so the row is a link like any
            # other and a click opens exactly these bars. Before 2026-10-31 it
            # carried nothing here, because the chart route drew what Yahoo
            # draws and Yahoo quotes no Philippine yield.
            "chartSymbol": symbol,
            "ticker": symbol.split(":")[-1],
            "name": name,
            "kind": "Government bond yield",
            "price": closes[-1],
            "currency": "%",
            "direction": "bullish",
            "note": "yield falling",
            "since": run["since"],
            "run": run["run"],
            "censored": run["censored"],
            "manner": run["manner"],
            "turnMove": run["turnMove"],
            "score": -call["score"],
            "bars": call["bars"],
            "last": stamps[-1],
            "turnover": None,
            # No three-month move: for a yield the level is the figure, and the
            # direction beside it already says how a bond price read the move.
            # A points change over the window is a figure about a figure, so
            # the table prints none for a yield (asked for by name, 2026-11-07:
            # "for bonds, the most important thing is yield. changes don't mean
            # shit. + the bearish or bullish judgment").
            "windowMove": None,
            "chartable": True,
            # The bars are stamped at the close of the Manila session -- five
            # in the morning, which is 21:00 the day before in UTC. So the
            # date of a bar is read in Manila, and the row says which
            # timezone to read it in rather than leaving the front end to
            # guess. Every other row's bars are stamped inside their own
            # session's own day in UTC, so this one carries the field and the
            # rest do not.
            "tz": "Asia/Manila",
            # How old this reading is, in seconds, when it was served as a
            # fallback -- that is, when the fetch did not answer and a copy
            # past its TTL was used instead. Zero for a fresh fetch and zero
            # for an ordinary cache hit inside its TTL. The table shows it,
            # because a yield row that is three days old should not look like
            # one from today.
            "stale": int(age) if symbol in fallbacks else 0,
        })
    return rows, {"universe": len(BONDS),
                  "count": sum(1 for row in rows if not row.get("lean")),
                  "missing": missing}


def fund_rows() -> tuple[list[dict], dict]:
    """The bullish Philippine funds, judged on the NAVPU series they publish.

    A fund has no ticker, no exchange and no volume: what it has is one net
    asset value per unit, struck once a business day by its manager. `phfunds`
    reads that series from whichever registry publishes the fund, keeps the
    business days, and hands back the same bars a click on the row will plot --
    so this leg, like every other, is the chart's own window and the chart's
    own classifier (invariant 1).

    Three things are worth knowing about what comes out:

    * **No turnover.** A fund is not traded, so the row carries `turnover:
      None`, and the volume column prints a dash rather than a zero.
    * **A money market fund is always bullish.** Its NAVPU accrues interest
      every day and never marks to a loss, so the three-month window on one is
      essentially always "bullish", and its run is always *censored* ("at least
      this long"). That is a true statement about a cash fund; it is not a
      signal about the market.
    * **A fund that did not answer is missing, not bearish.** Its publisher may
      be down; either way it is counted in `missing` and left out, because a
      fetch failure must never appear as a verdict about a fund (invariant 3).

    The series itself is cached for `phfunds.CACHE_TTL`, so a sweep fifteen
    minutes after the last one reads its funds from disk: a NAVPU is published
    once a business day, and re-reading it four times an hour would buy nothing
    but traffic.
    """
    codes = [entry[0] for entry in phfunds.FUNDS]
    answers = phfunds.refresh(codes)
    rows: list[dict] = []
    missing: list[str] = []
    for code in codes:
        answer = answers.get(code)
        if not isinstance(answer, dict) or not answer.get("bars"):
            missing.append(code)
            continue
        bars = answer["bars"]
        stamps = [bar["t"] for bar in bars]
        closes = [bar["c"] for bar in bars]
        # A fund publishes no volume, so there is nothing for a volume signal
        # to read: zeros are "no volume to say", which is what the classifier
        # expects of a series that has none (the same value the Philippine
        # sweep gives an index).
        volumes = [0.0] * len(closes)
        call = onset_module.onset(stamps, closes, volumes, want="bullish")
        if call is None:
            lean = onset_module.steady_lean(stamps, closes, volumes)
            if lean is not None:
                fund = phfunds.record(code)
                row = _lean_row(
                    "Philippine fund", phfunds.symbol_for(code),
                    phfunds.symbol_for(code), code, fund["name"],
                    {"Equity": "Equity fund", "Bond": "Bond fund",
                     "Balanced": "Balanced fund",
                     "PERA": "PERA fund"}.get(fund["category"], "Fund"),
                    fund["currency"], lean)
                row.update({
                    "turnover": None,
                    "turnoverPhp": None,
                    "priceHint": phfunds.price_hint(bars),
                    "stale": int(answer["age"]) if answer.get("stale") else 0,
                })
                rows.append(row)
            continue
        fund = phfunds.record(code)
        rows.append({
            "market": "Philippine fund",
            # The row is a link: `FUND:<CODE>` is what the chart route reads,
            # and it draws exactly these bars through `phfunds.chart`.
            "symbol": phfunds.symbol_for(code),
            "chartSymbol": phfunds.symbol_for(code),
            "ticker": code,
            "name": fund["name"],
            "kind": {"Equity": "Equity fund", "Bond": "Bond fund",
                     "Balanced": "Balanced fund",
                     "PERA": "PERA fund"}.get(fund["category"], "Fund"),
            "category": fund["category"],
            "price": call["price"],
            "currency": fund["currency"],
            "direction": "bullish",
            "since": call["since"],
            "run": call["run"],
            "censored": call["censored"],
            "manner": call["manner"],
            "turnMove": call["turnMove"],
            "score": call["score"],
            "bars": call["bars"],
            "last": call["last"],
            "turnover": None,
            "turnoverPhp": None,
            # The window's move, like every other price row's.
            "windowMove": _window_move(call),
            # A four-decimal NAVPU printed at two would round away the only
            # digits that moved this month, so the row carries its own
            # precision for the table to honour.
            "priceHint": phfunds.price_hint(bars),
            "chartable": True,
            # Seconds the reading predates this sweep, when the publisher did
            # not answer and a stored copy was shown instead. Zero for a fresh
            # fetch or a copy inside its TTL.
            "stale": int(answer["age"]) if answer.get("stale") else 0,
        })
    return rows, {"universe": len(codes), "scanned": len(codes),
                  "missing": sorted(missing)}


def ph_rows(sweep_rows: list[dict]) -> list[dict]:
    """The Philippine sweep's rows, in this table's row shape.

    The sweep already dated every name it found and already decided which
    names are bullish; this only restates them. A row that is missing its
    date is left out rather than shown undated: a "since" column that is
    blank on a row that has one everywhere else reads as a rendering fault.
    """
    rows = []
    for row in sweep_rows or []:
        if not row.get("since"):
            continue
        rows.append({
            "market": "Philippines",
            "symbol": row.get("symbol"),
            "chartSymbol": row.get("chartSymbol") or row.get("symbol"),
            "ticker": row.get("ticker"),
            "name": row.get("name"),
            "kind": row.get("kind"),
            "price": row.get("price"),
            "currency": row.get("currency") or "PHP",
            "direction": "bullish",
            "since": row.get("since"),
            "run": row.get("run"),
            "censored": row.get("censored"),
            "manner": row.get("manner"),
            "turnMove": row.get("turnMove"),
            "score": row.get("score"),
            "bars": row.get("bars"),
            "last": row.get("last"),
            "turnover": row.get("turnover"),
            "windowMove": _window_move(row),
            "chartable": True,
        })
    return rows


def ph_lean_rows(sweep_leaning: list[dict]) -> list[dict]:
    """The Philippine sweep's leaning names, in this table's lean-row shape."""
    rows = []
    for row in sweep_leaning or []:
        rows.append({
            "market": "Philippines",
            "symbol": row.get("symbol"),
            "chartSymbol": row.get("chartSymbol") or row.get("symbol"),
            "ticker": row.get("ticker"),
            "name": row.get("name"),
            "kind": row.get("kind"),
            "price": row.get("price"),
            "currency": row.get("currency") or "PHP",
            "direction": "neutral",
            "lean": "bullish",
            "score": row.get("score"),
            "significance": row.get("significance"),
            "progress": row.get("progress"),
            "bars": row.get("bars"),
            "last": row.get("last"),
            "turnover": row.get("turnover"),
            "held": row.get("held"),
            "holdBars": row.get("holdBars"),
            "chartable": True,
        })
    return rows


def scan(ph_sweep_rows: list[dict] | None = None,
         fetch_us_bars=None, ph_sweep_leaning: list[dict] | None = None,
         ondo_shelf: dict | None = None,
         ph_sweep_stats: dict | None = None) -> dict:
    """The whole table: every bullish instrument, the falling bond yields, the
    United States Treasury futures, and the funds.

    `ph_sweep_rows` are the rows of the Philippine sweep the server already
    keeps warm, and `ph_sweep_stats` is that sweep's own account of what it
    looked at (`universe`, `kinds`, `missing`) -- so the note can say "263
    scanned (249 common shares, 11 preferred shares, ...)" instead of only
    counting the rows that came out bullish. `fetch_us_bars` fetches the
    United States bars (see `us_rows`), and the Treasury futures leg pays it a
    second call for the curve's seven symbols. Both are arguments because the
    server owns both. The fund leg needs nothing injected: its sources answer
    plain HTTPS, so `phfunds.py` fetches them itself.

    `ondo_shelf` is the list of assets app.ondo.finance carries (see
    `ondolist.shelf`), or None when it could not be read. It does two jobs
    now: it is the **universe** of the United States leg and of the Ondo
    portfolio leg (a stock, an ETF or a basket the shop does not list is not
    scanned at all), and it filters the leaning list through `actionable`.
    With no shelf the United States leg falls back to the turnover ranking and
    says so in the note -- an outage must not empty the table.

    Raises `RecentError` when the table could not be assembled at all. One
    leg failing does not lose the others: a leg that failed is reported in
    the payload's `errors` and the rest of the table stands, because a page
    that already has four markets' worth of rows should not lose them to
    one market's outage.
    """
    rows: list[dict] = []
    errors: dict[str, str] = {}
    stats: dict[str, dict] = {}

    ph = ph_rows(ph_sweep_rows or [])
    rows.extend(ph)
    rows.extend(ph_lean_rows(ph_sweep_leaning or []))
    stats["Philippines"] = {"count": len(ph)}
    if isinstance(ph_sweep_stats, dict):
        # The universe the sweep actually read, with its makeup. Carried onto
        # the stats, which travel in the payload, so both notes and the seeded
        # copy describe the same scan.
        if ph_sweep_stats.get("universe"):
            stats["Philippines"]["universe"] = int(ph_sweep_stats["universe"])
        if ph_sweep_stats.get("kinds"):
            stats["Philippines"]["kinds"] = dict(ph_sweep_stats["kinds"])
        if ph_sweep_stats.get("missing"):
            stats["Philippines"]["missing"] = list(ph_sweep_stats["missing"])

    if fetch_us_bars is not None:
        # The two Yahoo legs, each with its own error: a browser leg that
        # answers one market's symbols and not the other's must not take both
        # down, and the note names whichever failed. The Ondo stocks and ETFs
        # are drawn from the shelf when it was read (see `shelf_universe`).
        for market, leg in (("US", us_rows), ("US Treasury", rate_rows)):
            try:
                if market == "US":
                    found, leg_stats = leg(fetch_us_bars, ondo_shelf)
                else:
                    found, leg_stats = leg(fetch_us_bars)
                rows.extend(found)
                stats[market] = leg_stats
            except Exception as exc:
                errors[market] = str(exc)
    else:
        errors["US"] = "no bar fetcher was given"
        errors["US Treasury"] = "no bar fetcher was given"

    # The Ondo intelligent portfolios: plain HTTPS to DeFiLlama, so unlike the
    # two legs above this one needs nothing injected and fails alone.
    try:
        baskets, basket_stats = ondo_portfolio_rows(ondo_shelf)
        rows.extend(baskets)
        stats["Ondo portfolio"] = basket_stats
    except Exception as exc:
        errors["Ondo portfolio"] = str(exc)

    try:
        coins, coin_stats = crypto_rows()
        rows.extend(coins)
        stats["Crypto"] = coin_stats
    except Exception as exc:
        errors["Crypto"] = str(exc)

    try:
        bonds, bond_stats = bond_rows()
        rows.extend(bonds)
        stats["Philippine bond"] = bond_stats
    except Exception as exc:
        errors["Philippine bond"] = str(exc)

    try:
        funds, fund_stats = fund_rows()
        rows.extend(funds)
        stats["Philippine fund"] = fund_stats
    except Exception as exc:
        errors["Philippine fund"] = str(exc)

    if not rows:
        raise RecentError("no rows could be assembled: %s" % (
            "; ".join("%s: %s" % item for item in errors.items()) or "nothing"))

    # Newest turn first -- the table's own claim is that it shows what
    # turned most recently. A row that somehow carries no date sorts last,
    # because one that never turned cannot claim to have turned recently.
    rows.sort(key=lambda row: (-(row.get("since") or 0),
                                -(row.get("turnover") or 0.0),
                                row.get("ticker") or ""))

    # The peso column: every row's turnover in pesos, whatever currency it was
    # traded in. A Philippine stock is already in pesos; a US stock or a coin
    # converts at the leaderboards' own rate (`markets.php_per_usd`, the
    # scanner's FX_IDC:USDPHP quote -- the same rate the "most traded" tables
    # annotate with, not a second rate invented here). A yield has no turnover
    # to convert and stays None. An unavailable rate costs the column, not the
    # table -- the same contract the other tables' peso figures keep -- and
    # the payload says so, so the note can too.
    try:
        fx = markets.php_per_usd()
        fx_error = None
    except (markets.MarketError, pse.PseError) as exc:
        fx, fx_error = None, str(exc)
    rate = fx["phpPerUsd"] if fx else None
    for row in rows:
        native = row.get("turnover")
        currency = (row.get("currency") or "").upper()
        if currency == "PHP":
            row["turnoverPhp"] = native
        elif currency == "USD" and native is not None and rate:
            row["turnoverPhp"] = native * rate
        else:
            row["turnoverPhp"] = None

    # The volume floor, applied to the converted figure and only to the
    # markets that have one (`FLOOR_MARKETS`): a Philippine stock under
    # ₱1,000,000 of turnover is not a row. A row with no peso figure at all
    # (a bond yield, a fund, a portfolio) is kept -- the floor tests traded
    # volume, and none is not "too little".
    #
    # What it hides is counted, not swallowed: the reader found PAL missing from
    # this table with nothing on screen to explain it, so `stats` carries the
    # number and the note prints it. The judged count keeps saying what was
    # looked at.
    dropped = [row for row in rows
               if row.get("market") in FLOOR_MARKETS
               and row.get("turnoverPhp") is not None
               and row["turnoverPhp"] < MIN_TURNOVER_PHP]
    if dropped:
        # By identity, not equality: two different rows can hold equal fields,
        # and dropping the wrong one would hide a name twice over.
        hidden_ids = {id(row) for row in dropped}
        rows[:] = [row for row in rows if id(row) not in hidden_ids]
        ph_stats = stats.setdefault("Philippines", {})
        if isinstance(ph_stats, dict):
            ph_stats["hidden"] = len(dropped)

    # The near-misses leave the bullish table here, into a list of their own:
    # neutral on their own charts, in the bullish hold band, closest to the
    # entry bar first.
    leaning = sorted((row for row in rows if row.get("lean")),
                     key=lambda row: (-(row.get("progress") or 0.0),
                                      row.get("ticker") or ""))
    rows[:] = [row for row in rows if not row.get("lean")]

    # ... and then out of the table entirely, unless the reader can act on it:
    # a United States listing must be on the Ondo shelf, and the funds are not
    # (see `actionable`). `ondoShelf` travels with the payload so the page can
    # say which shelf it read, and when, instead of implying it is current.
    leaning = actionable(leaning, ondo_shelf)

    return {
        "label": "Recently bullish assets",
        "rows": rows,
        "leaning": leaning,
        "ondoShelf": None if ondo_shelf is None else {
            "count": ondo_shelf.get("count"),
            "fetchedAt": int(ondo_shelf.get("fetchedAt") or 0),
            "cached": bool(ondo_shelf.get("cached")),
        },
        "stats": stats,
        # The Philippine scan, spelled out once, in the same words both notes
        # print. The page appends it under "Leaning bullish"; `summarize` puts
        # it under "Recently bullish assets". One string, so the two cannot
        # describe the same sweep differently.
        "phScan": ph_scan_line(stats.get("Philippines") or {}),
        "fx": fx,
        "fxError": fx_error,
        "errors": errors,
        "checkedAt": None,
        "error": None,
    }


def kinds_line(kinds: dict) -> str:
    """`{kind: count}` -> "249 common shares, 11 preferred shares, 1 ETF, ...".

    Fixed order and empty kinds dropped, so two sweeps that differ only in
    whether an ETF listed read as one sentence with one clause changed.
    """
    parts = []
    for kind, singular, plural in PH_KIND_WORDS:
        count = (kinds or {}).get(kind)
        if not count:
            continue
        parts.append(f"{count} {singular if count == 1 else plural}")
    # Anything the vocabulary above did not name is still counted: an
    # unlisted kind must not vanish from a figure whose whole job is honesty
    # about coverage.
    named = {kind for kind, _, _ in PH_KIND_WORDS}
    others = sum(count for kind, count in (kinds or {}).items()
                 if kind not in named)
    if others:
        parts.append(f"{others} other listing{'s' if others != 1 else ''}")
    return ", ".join(parts)


def ph_scan_line(detail: dict) -> str | None:
    """The Philippine scan as one sentence: "263 scanned (249 common shares...)".

    None when the sweep's own account of its universe did not travel (a table
    read from an older disk copy): a made-up count would be worse than the
    shorter line this note had before.
    """
    universe = detail.get("universe")
    if not universe:
        return None
    line = kinds_line(detail.get("kinds") or {})
    return f"Philippines: {universe} scanned" + (f" ({line})" if line else "")


def summarize(payload: dict) -> str:
    """One line for the card's note: what was judged, and what answered."""
    rows = len(payload.get("rows") or [])
    stats = payload.get("stats") or {}
    parts = [f"{rows} rows"]
    if payload.get("leaning") is not None:
        parts.append(f"{len(payload['leaning'])} leaning bullish")
        # The leaning list is filtered onto app.ondo.finance (see
        # `actionable`), so the note says so -- and says when it could not be,
        # rather than letting an outage read like a shelf that carries none.
        if payload.get("ondoShelf"):
            parts.append("United States rows are Ondo-listed only")
        elif payload["leaning"]:
            parts.append("Ondo list unavailable — leaning rows unfiltered")
    for market, detail in stats.items():
        count = detail.get("count")
        universe = detail.get("universe")
        missing = len(detail.get("missing") or [])
        stale = detail.get("stale") or []
        # The United States leg's universe is the Ondo shelf when it was read,
        # and the scanner's turnover ranking only when it was not. Which one it
        # was is a fact about the sweep, so the note says it instead of letting
        # "478 scanned" imply the shelf when it was a ranking.
        label = market
        if market == "US" and detail.get("shelf") is False:
            label = "US (turnover universe)"
        # The makeup of the Philippine universe, when the sweep sent it: the
        # leg's own line already says "263 scanned", and this says of what.
        breakdown = kinds_line(detail.get("kinds") or {})
        if count is not None and universe:
            # A leg that judged a fixed list and kept only the bullish ones --
            # the bond yields -- says both numbers, so a leg with no rows reads
            # as "nothing turned" and not as "nothing was looked at".
            parts.append(f"{label}: {universe} scanned"
                         + (f" ({breakdown})" if breakdown else "")
                         + ("" if count >= universe else f", {count} bullish"))
        elif count is not None:
            parts.append(f"{label}: {count}")
        elif universe:
            parts.append(f"{label}: {universe} scanned"
                         + (f" ({breakdown})" if breakdown else "")
                         + (f", {missing} did not answer" if missing else ""))
        hidden = detail.get("hidden")
        if hidden:
            # The floor hides rows, so the note says how many it hid --
            # across both tables, since it applies to a market and not to
            # one of them. A name that is bullish on its own chart and
            # absent from the table has to be explained on the page.
            parts.append(f"{hidden} below ₱{MIN_TURNOVER_PHP:,} volume hidden")
        if stale:
            # A series whose source stopped printing is not judged, so the note
            # names it and dates its last bar: the alternative is a name that
            # was in the table yesterday and is gone today with no word, which
            # is exactly what the reader objected to about the peso floor.
            # Three names at most -- this is a one-line note, and the count
            # carries the rest.
            named = ", ".join(
                "%s (last bar %s)" % (entry.get("ticker"), entry.get("lastBar"))
                for entry in stale[:3] if entry.get("ticker"))
            more = "" if len(stale) <= 3 else f" and {len(stale) - 3} more"
            parts.append(f"{len(stale)} stale series hidden: {named}{more}")
    errors = payload.get("errors") or {}
    for market, message in errors.items():
        parts.append(f"{market} unavailable")
    fx = payload.get("fx") or {}
    if fx.get("phpPerUsd"):
        parts.append(f"Converted at USDPHP {fx['phpPerUsd']}")
    elif payload.get("fxError"):
        parts.append("no peso-dollar rate — peso volume figures unavailable")
    return " · ".join(parts)
