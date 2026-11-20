#!/usr/bin/env python3
"""Local server for the asset price chart.

Serves the static page and proxies Yahoo Finance through Moli.

Why a proxy is needed
---------------------
Yahoo's chart API is not reachable the obvious ways:

* Plain HTTP clients get **HTTP 429**. `curl` and `urllib` both return
  "Too Many Requests", with or without a browser User-Agent.
* It also sends **no `Access-Control-Allow-Origin`** for an arbitrary origin, so
  a web page cannot call it directly even from a browser.
* Moli -- a real browser -- gets **HTTP 200**.

So the page asks this server, and this server asks Moli. Yahoo does allow CORS
from its *own* origins, so we load a cheap Yahoo page and call the API from
inside it, which also lets us keep the real status code.

Offline
-------
Every upstream answer is also kept on disk (`diskcache.py`, under `.cache/`),
so a request that cannot be re-fetched -- no internet, Moli broken, Yahoo or
TradingView down -- falls back to the last good copy instead of failing, and
that copy is dated: the payload carries `cached: true` and the `fetchedAt`
second it was actually retrieved, which the page shows as "data last retrieved
…". A "no such symbol" is an answer, not an outage, so it is never rescued
from disk; only transport errors are. Fresh copies carry no such stamp.

The fallback only helps if there is something to fall back to, so the charts
behind the tables are kept warm too: a background thread (`warm_rows_loop`)
retrieves the chart of every symbol the leaderboards, the bullish table and
the crypto table list, *and* every symbol the page has ever declared as its
watchlist (`POST
/api/watch`), at the range the page draws, whether or not anyone ever clicked
the row while the network was up. The watchlist lives in one browser's
localStorage and no source publishes it, so without the declaration the
warmer had never heard of the reader's own symbols — the one list that
matters most was the one nothing warmed. The server keeps the union of every
list ever declared, persisted as a plain disk record that never ages out, so
the machine (not a tab) remembers, through reboots and weekends. Offline, the
page can still name every top stock *and* draw its graph.

Those threads refresh on schedules, and a schedule is a poor way to notice the
internet coming back: a sweep that failed two minutes ago would still sleep its
full fifteen, and a row whose chart failed during the outage stays stamped — and
un-warmed — for a quarter-hour (`ROW_STALE_AFTER`). So a watch thread
(`net_watch_loop`) asks a
reachability question instead (a bare TCP connect; no browser, no page), and the
instant the answer flips from no to yes it expires every in-memory memo,
advances a reconnect epoch, wakes every sleeper, and re-warms the first paint.
The epoch is what makes the row warmer honest about a reconnection: each pass
re-consults disk, so a row whose chart *failed* during the outage is due again
at once, while a row whose chart *landed* re-adopts its fresh disk copy and
costs no browser run. The cache refills on the reconnection itself, with no one
having to open the page. (A row whose warm fetch is *rescued from disk* -- the
wire died mid-queue and the cache handed back the old copy as a success --
is treated as a failed attempt, not a landed one: its stamp is dropped, so the
next pass re-looks it at once. Otherwise the outage would be invisible exactly
where it hides best.) The console narrates it: the edge prints "back online:
re-fetching everything now" -- with a note first when no page has ever declared
a watchlist, because then "everything" holds no saved rows -- and once the
three refetching threads (first paint, bullish sweep, row charts) have each
finished their post-edge pass, the last one prints the closing line naming
what actually landed fresh: "back online: all refetches finished (Ns)", or
"refetch passes ended (Ns), but no fresh data for: <parts>" when the wire
refused. The same report closes startup: the boot's three first passes mark a
report opened before they start, and the last one prints "startup warm: all
refetches finished (Ns)" -- the same sentence, in the boot's tense, so the
console says when the first round of fetching is over without anyone opening
the page. An open page learns the same from `/api/health`'s `reconnections`
counter and re-reads its watchlist rows and active chart.

Usage
-----
    python3 server.py             # http://127.0.0.1:8000
    python3 server.py 8080        # custom port
    MOLI_BIN=/path/to/moli python3 server.py

Shutdown
--------
Ctrl-C (or SIGTERM) stops accepting connections, terminates any Moli fetch still
running, and releases the port, so a restart binds immediately. A second Ctrl-C
kills the process outright if something is wedged. If the port is already taken,
we say who holds it instead of dumping a traceback.
"""

from __future__ import annotations

import labpath  # noqa: F401  (puts lab/ on sys.path)

import datetime as dt
import errno
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

import faults
import bullish
import coinsph
import crypto
import cryptobull
import diskcache
import ecb
import markets
import nasdaq_bars
import ondo
import ondolist
import onset as onset_module
import phfunds
import probability
import quality
import pse
import rates
import recent
import research_judgment
import trend
import tv


if __name__ == "__main__":
    # Run as a script this module is "__main__"; the split-out modules say
    # "import server", and must get this same module, not a second copy.
    sys.modules.setdefault("server", sys.modules[__name__])

from moli_client import (  # noqa: E402,F401
    BATCH_EVAL_SCRIPT,
    BATCH_SUBPROCESS_TIMEOUT,
    BATCH_TIMEOUT_MS,
    EVAL_SCRIPT,
    HERE,
    MOLI,
    MOLI_TIMEOUT_MS,
    ORIGIN_PAGE,
    SUBPROCESS_TIMEOUT,
    UpstreamError,
    WARM_BATCH_SUBPROCESS_TIMEOUT,
    WARM_BATCH_TIMEOUT_MS,
    _running,
    _running_lock,
    moli_batch_get,
    moli_eval,
    moli_fallback,
    moli_get,
    moli_run,
    moli_sweep,
)
CHART_HOST = "query1.finance.yahoo.com"
SEARCH_HOST = "query2.finance.yahoo.com"

DEFAULT_PORT = 8000
CACHE_TTL = 60  # seconds

# The market tables are three upstream queries over data that moves only as
# trades print, and the page can ask for them repeatedly while a reader looks on.
# Longer than CACHE_TTL on purpose: a minute of latency on a leaderboard costs
# nothing a reader can perceive, whereas re-fetching on every poll costs three
# round trips to show the same numbers.
TOP_TTL = 300  # seconds

# The disk-cache key behind `/api/top`, named because `warm_routes` and
# `api_top` must read and write through the *same* key -- two spellings of one
# cache entry is how one of them stops being a fallback.
LEADERS_KEY = "markets:top"

# The disk-cache key behind `/api/cryptobull`, same reasoning: the prewarm
# pass, the row warmer and the route must all spell the crypto table's answer
# this one way.
# `:t2` -- scored by version 2 of the classifier (`trend.py`); a version-1
# table on disk must not be served as a current verdict.
CRYPTO_KEY = "crypto:bullish:v2:t2"

# The declared-record key (`diskcache.store_plain`) behind the browser's
# watchlist, same naming reasoning: the warmer, the route, and the startup
# adoption all read and write through this one spelling.
WATCHLIST_KEY = "client:watchlist"

# The chart window every table row answers to, in one spelling for both sides
# of the promise: `index.html`'s `RANGE`/`INTERVAL` constants say what a row
# click requests, `WARM_CHART` says what the first paint requests, and the row
# warmer below says what every *listed* symbol must already be cached at. If
# the page ever draws a different window, these two names and `WARM_CHART` are
# the lines that change together -- warmer and route must ask for the same
# window or the warm copy sits under one key while clicks read another.
WARM_SPAN, WARM_INTERVAL = "3mo", "1d"

# How old a row's disk copy may be before the warmer re-fetches it. Fifteen
# minutes is the promise the rest of this server already keeps -- the bullish
# sweep refreshes on `BULL_TTL` (900s), the tables re-read within `TOP_TTL`
# (300s) -- so the charts behind those rows are held to the same clock: after
# 900 seconds a row's disk copy is refreshed in the background whether or not
# anyone opened the page, so an outage that starts just after the wire dies
# finds the whole table at most a quarter-hour old. The page's own click
# still always fetches live (see `cached`); this is the *fallback* copy's age.
# `diskcache.MAX_AGE` is the outer bound -- past it the copy reads as absent
# offline anyway.
ROW_STALE_AFTER = 900  # seconds

# Pause after a chart batch fails to reach the network at all. One row's
# outage usually means the whole machine cannot, and the batches behind it
# would each spend a browser run to learn the same thing twice. The failed
# chunk's rows keep their attempt stamps (see the outcome comment above
# `_store_chart`), so they are not re-tried inside this epoch; the pause is
# what keeps a dead wire from being re-probed every idle poll instead of
# every couple of minutes. A reconnect (`_refresh_epoch`) expires the stamps
# outright, so the recovery pass starts the moment the watch says the wire
# is back -- never later than the backoff.
WARM_BACKOFF = 120  # seconds

# How long the warmer waits when its queue is empty before re-reading the
# tables for due rows. This is what keeps the machine warm with no browser
# open on it -- the sweep and the leaderboards refresh through the same
# `cached()` the routes call, and their rows are the work list.
WARM_IDLE_POLL = 60  # seconds

# Spacing between warmed *batches*, a floor rather than a throttle. The rows
# arrive in turnover order -- the most-traded names first -- so the head of
# each queue is what a reader is most likely to click, and the first batch
# (watchlist rows first) departs immediately, not lost behind the PSE tail.
# `cached()`'s single-flight lets a click overtake an in-flight warm of the
# same symbol without duplicating it. The batched warmer sleeps this long
# between chunks -- a handful of sleeps per pass, where the serial loop paid
# one per row -- so a pass that lands everything costs the browser runs plus
# a few seconds of spacing, not a hundred-odd seconds of Chrome.
WARM_PACING = 0.8  # seconds

# How many chart URLs one Moli run fetches for the warmer's Yahoo leg, and how
# long that run may take. The fixed cost of a browser launch amortises across
# the batch, so a bigger batch is strictly fewer launches -- but each URL's
# response body rides in one JSON envelope through Moli's stdout, and twenty
# three-month daily charts is a few hundred kilobytes: well inside what a
# subprocess pipe can carry, well under the wall timeout, and small enough
# that one slow URL in a giant batch would not hold a hundred others' bars
# hostage. Twenty means a ~40-symbol Yahoo queue is two runs, not forty.
WARM_BATCH = 20

# How many PSE symbols the warmer warms per socket chunk, and the pool depth.
# `pse.BATCH_SYMBOLS`/`BATCH_WORKERS` are the sweep's proven numbers (forty
# sessions per socket is the reliable ceiling) and the warmer borrows them
# rather than inventing its own: the chunk shape that survives the sweep
# survives a row pass, and the two share `_fetch_chunk_raw` underneath.
WARM_PSE_CHUNK = pse.BATCH_SYMBOLS
WARM_PSE_WORKERS = pse.BATCH_WORKERS

# The three bond tenors are one curve read off one socket, so their leg is a
# single batch of three: there is nothing to chunk and no reason to split it.
BOND_WARM_CHUNK = len(tv.SYMBOLS)

# Fund rows are read from public HTTPS documents rather than a browser, so a
# chunk here is a concurrency limit rather than a page budget: `phfunds`
# fetches what is missing in parallel and reads the rest off disk. Twelve keeps
# one pass's fund leg inside a few seconds once the series are cached, which is
# the normal case -- a NAVPU is published once a business day.
FUND_WARM_CHUNK = 12

# The bullish table is a different kind of request from everything above it: it
# reads 270 daily bars for each of ~260 PSE symbols over forty chart sessions per
# browser, and a cold run takes about 35 seconds. That is far too slow to do while
# a reader waits, and far too expensive to redo on every poll, so it is not
# fetched lazily at all -- one background thread keeps an answer warm (see
# `bullish_state`) and a request only ever reads what that thread last produced.
# The TTL is therefore the refresh interval, not a cache lifetime.
BULL_TTL = 900  # seconds

# Allowlist, so nothing a client sends can reshape the upstream URL.
ALLOWED_RANGES = {"1mo", "3mo", "6mo", "1y", "2y", "5y"}
ALLOWED_INTERVALS = {"1d", "1wk"}

# How many calendar months each range spans, in Yahoo's own reckoning: its
# `range=3mo` is three calendar months back from today, not ninety days. The
# chart trims to this and the recent table reads the same window, so a row and
# the chart its click opens read the same bars -- which matters more than it
# sounds, because the classifier changes regime at 63 bars and the two
# windows differ by a session or two.
SPAN_MONTHS = {"1mo": 1, "3mo": 3, "6mo": 6, "1y": 12, "2y": 24, "5y": 60}

# How far back Yahoo is actually asked, for a span the chart draws. One step
# wider, because the badge's steadiness reading needs the few bars *behind* the
# drawn window and a `range=3mo` payload starts at the cutoff (2026-11-07).
# `slim_chart` trims what is drawn back to the requested span, so the chart and
# its badge are unchanged; only the history behind them is available now.
#
# The last two entries are the edge: Yahoo's widest ranges are `10y` and `max`,
# so a 2-year chart is fetched as 5 years and a 5-year chart as 10. Nothing
# beyond 10 years is asked for -- a longer chart keeps its lean unfiltered,
# which is the honest answer to "not enough history to judge" rather than a
# guess.
FETCH_SPAN = {"1mo": "3mo", "3mo": "6mo", "6mo": "1y", "1y": "2y",
              "2y": "5y", "5y": "10y"}
KEEP_QUOTE_TYPES = {
    "EQUITY", "ETF", "CRYPTOCURRENCY", "CURRENCY",
    "INDEX", "FUTURE", "MUTUALFUND",
}

# Yahoo charts a currency pair only when one leg is USD: `JPYPHP=X` resolves in
# search and quotes a live market price, but its chart history is a single point
# -- a cross without a dollar leg simply has no series upstream. The two legs
# that compose it do, so the page's chart is synthesized from them (see
# `fx_cross_chart`). `=` terminates the pair and `X` the suffix, so a ticker
# like `JPY=X` itself can never match, and neither can a suffix-bearing equity.
FX_CROSS_RE = re.compile(r"^([A-Z]{6})=X$")
# Pairs whose market convention quotes them *against* the dollar rather than in
# it -- EUR, GBP, AUD and friends are `GBPUSD`, not `USDGBP`, and Yahoo's `X=X`
# tickers follow that convention. A leg in this set is inverted to per-USD
# before the cross is divided out; the rest are already per-USD.
USD_QUOTED_BASES = {"EUR", "GBP", "AUD", "NZD", "IEP", "ZMW"}

_cache: dict[str, tuple[float, object]] = {}

_cache_lock = threading.Lock()


_flights: dict[str, _Flight] = {}

# Where Yahoo and the coin's own venue disagree, Yahoo is charting a different
# instrument under the same ticker. A last close alone is not enough to tell:
# JUP-USD is a dead 2017 token at $0.00036 while the coin people mean is ~$0.34,
# four orders of magnitude apart, but BEAM-USD's two coins *converged* on
# 2026-11-11 (0.005319 on Yahoo vs 0.004457 on Kraken, 19.3% -- inside this
# gap) while their windows read -37.7% neutral and +225.8% bullish. So the
# whole shared series is compared too: one coin quoted at two venues holds a
# near-constant price ratio across the bars, two different coins do not. The
# crypto Yahoo gets right (BTC/ETH/SOL/XMR agree to a fraction of a percent,
# bar for bar) is left alone. No blocklist of tickers is needed.
REROUTE_GAP = 0.20

# How many shared bars make a shape reading. Fewer than this and the test falls
# back to the last close alone rather than judging a window from two points.
SERIES_BARS = 5


crypto.set_http_fallback(moli_fallback)
# Frankfurter answers plain HTTP clients, so this is a safety net the same way
# it is for `crypto.py` -- but the ECB route needs no browser in the first place.
ecb.set_http_fallback(moli_fallback)
# The coins.ph book answers plain HTTP too; the browser is the net, not the road.
coinsph.set_http_fallback(moli_fallback)
# DeFiLlama's coins API answers an ordinary HTTP client as well -- the Ondo
# tokens' price comes from it, and the browser is a net here, not the road.
ondo.set_http_fallback(moli_fallback)
# PSE bars come from a websocket, which no HTTP client can reach, so `pse.py`
# borrows the same browser path -- but raw, since it has its own protocol.
pse.set_eval_runner(moli_eval)
# The whole-universe sweep goes down that same path; it only needs more time.
pse.set_batch_runner(moli_sweep)


from memo import (  # noqa: E402,F401  (split out 2026-11-20)
    TRANSIENT_ERRORS,
    _Flight,
    _stamp_copy,
    cached,
    is_transient,
    tables_usable,
)


# -- noticing the internet come back ---------------------------------------------
#
# Everything above degrades gracefully when the wire is down, and every thread
# below refreshes on its schedule whether or not anyone is watching the page.
# What none of them can tell apart is "still offline" from "offline a minute
# ago, back now": the clocks an outage sets keep ticking after it ends, so a
# machine whose internet returned twenty seconds ago would sit on stamped
# outage memos, a sweeper's remaining fifteen minutes, and hour-old failed-row
# stamps, until those schedules happened to expire. This section closes the gap
# with one cheap question asked on a timer -- can we reach the internet right
# now -- and treats the *change* in the answer as the event. On the
# offline-to-online edge it expires every in-memory memo, advances a counter
# the warmer's freshness clock reads, wakes every sleeper, and re-warms the
# first paint: the sweep, the tables, the hero chart, and every *failed*
# row's chart refill on the reconnection itself, while landed rows re-adopt
# their disk copies and cost nothing. No page visit involved.

# The probe host is Binance's public market-data mirror -- the same one
# `crypto.py` charts coins from, chosen here because it is already vetted as
# reachable from places `api.binance.com` is not, and because a *bare TCP
# connect* to it answers the only question this watch has: is there a route to
# the internet. No HTTP, no browser, no page; the probe costs milliseconds and
# never queues behind the fetchers over Moli's profile lock. Any healthy host
# on port 443 does the same job, and one host suffices because they all sit
# behind the same wire. The flip side is recorded honestly: if this host were
# down while everything else were up, the watch would read the machine as
# offline -- but the retry clocks keep running anyway, so the only cost is that
# the edge arrives late, when the host answers again.
NET_PROBE = ("data-api.binance.vision", 443)
NET_PROBE_TIMEOUT = 2.0   # seconds the connect may take before it counts as a no
NET_PROBE_INTERVAL = 5.0  # seconds between questions while nothing has changed

# The reconnect counter, and the lock the background sleepers wait on. A lock
# of its own on purpose: `_cache_lock` guards the memos and this guards the
# waiting, and one lock for both would make every notifier-and-reader pair a
# lesson in lock ordering.
_refresh = threading.Condition()
_refresh_epoch = 0


def net_ok() -> bool:
    """Whether the internet answers right now: a TCP connect, nothing more.

    Deliberately not an HTTP request and certainly not a Moli run. Yahoo
    answers plain HTTP clients with 429 even when the connection is fine (see
    the module docstring), so "Yahoo said no" is no evidence about the wire --
    and a browser probe would serialize with the real fetches behind the
    profile lock, which is the opposite of watching. Whether port 443 of a
    well-connected host opens is the smallest question that separates "this
    machine is offline" from "this machine is online and someone upstream is
    having a problem".
    """
    try:
        with socket.create_connection(NET_PROBE, timeout=NET_PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def _sleep_or_wake(seconds: float, since: int | None = None) -> None:
    """Sleep `seconds`, shortened to the moment the watch sees the wire return.

    `time.sleep` cannot be interrupted, which would leave the reconnect edge to
    be noticed only after the interval ran out -- precisely the behavior this
    section exists to remove. Sleepers instead wait on `_refresh` and wake on
    the epoch change; either way they return into their caller's loop top,
    where the clocks and queues are re-read fresh, so waking early costs a
    little work and never costs correctness.

    `since` extends that promise to edges that landed *during the caller's
    pass* rather than during its sleep: pass the epoch you read when the pass
    began, and if the count has moved since then the wait is over before it
    starts. Without it, a sweep that lost its edge mid-flight would sleep a
    full interval and let the refetch -- and the completion report waiting on
    it -- trail the reconnection by minutes for no reason.
    """
    deadline = time.monotonic() + seconds
    with _refresh:
        epoch = _refresh_epoch if since is None else since
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or _refresh_epoch != epoch:
                return
            _refresh.wait(remaining)


def _expire_memos() -> None:
    """Empty the in-memory memo, so every key's next read reaches the network.

    `cached` fills its memo with the stamped fallback so waiters and the next
    caller share it without re-reading disk -- and re-stamps the TTL doing so,
    so after an outage the machine would keep serving that copy until the memo
    happened to expire. Clearing *everything*, not just the stamped entries,
    is the feature's whole point: a reconnection means "retrieve new data
    now," and an answer from before the wire dropped is not new data however
    recently it was fetched. Nothing is lost -- disk still holds every copy,
    so if the wire drops again mid-refill the same fallback is one read away
    -- and `cached`'s single-flight means a page request arriving during the
    refill shares the in-flight fetch instead of paying for a duplicate.
    """
    with _cache_lock:
        _cache.clear()


def net_reconnected() -> None:
    """The no-to-yes edge, everything in it. One call per reconnection.

    Order matters: the memos go and the epoch advances *before* the sleepers
    wake, so a thread that wakes finds the new world already in place -- an
    expired memo means its next read goes live, and a bumped epoch means
    `row_fresh` re-consults disk rather than trusting an outage-era stamp. The
    first paint is re-warmed *after* the notify, on a thread of its own, so
    none of this holds the watch loop against its five-second probe: the chart
    and tables refill through `warm_routes`, the same path startup takes, and
    the bullish sweep needs no help -- its sleeper just woke, and its next
    act is sweeping.

    The log line this writes is deliberately the *opening* sentence, not the
    summary: refilling everything takes minutes, and the three threads that do
    it each report done through `note_refetch_done`, which prints the closing
    line once the last one lands -- and that closing line only claims
    completion if every pass actually landed fresh data. Followed, when the
    union is still empty, by a note saying so before any of it starts.
    """
    global _refresh_epoch
    _expire_memos()
    with _refresh:
        _refresh_epoch += 1
        epoch = _refresh_epoch
        _refresh.notify_all()
    open_refetch_report(epoch)
    sys.stderr.write("  back online: re-fetching everything now\n")
    if not union_watchlist():
        # The one case where "everything" excludes a list a human keeps: a
        # server whose union is empty was never told (or booted before any
        # declaring page loaded), so the completion line below will land over
        # the tables and the hero chart and *not* over any watchlist row.
        # Say so at the edge, while it is still the interesting half of the
        # story -- a reader who saw stale saved rows after a "finished" log
        # deserves one sentence about why the queue was empty.
        sys.stderr.write(
            "  note: no watchlist declared yet -- saved rows will warm only"
            " once a page has loaded and told the server its list\n")
    threading.Thread(target=first_paint_pass, name="reheat", daemon=True).start()


# -- prewarming what the first paint always wants --------------------------------
#
# The page loads BTC-USD (a Yahoo chart) and the bullish stand-in. The first
# reader to arrive after `python3 server.py` would pay every cold cost at once:
# the chart (the chart and its watchlist row used to duplicate the work before
# `cached` learned single-flight, and one remains) and the CoinGecko/Binance
# identity lookups behind the crypto reroute test. The most-traded tables are
# not part of that paint.
#
# None of that is the reader's business to wait for. The bullish sweeper already
# embodies the pattern -- produce ahead, read what landed -- so the same trick
# covers the rest: one thread warms the caches the first paint reads, through the
# same `cached()` calls the routes make, so warming and serving are literally the
# same code path and cannot drift apart. It runs at startup and exits; the
# routes themselves keep the answers warm afterwards, and a warm-up that fails is
# simply a cold cache again -- the reader pays what they would have paid anyway.
# The connectivity watch runs it again on every reconnection (`first_paint_pass`),
# which is the same once-only warm-up in a second tense: the startup one fills a
# cold cache, the reheat one refills an expired one.
#
# The default chart symbol lives in `index.html` (RANGE/INTERVAL are the page's
# constants); keep them in step with `WARM_SPAN`/`WARM_INTERVAL` and
# `WARM_CHART` below.

WARM_CHART = ("USDPHP=X", WARM_SPAN, WARM_INTERVAL)


def warm_routes() -> bool:
    """Fill the caches the first paint reads, and report whether everything
    came off the wire *fresh*. Runs on the prewarm thread, and again on the
    reheat thread every time the watch sees the wire return (see
    `first_paint_pass`) -- at startup these are cold, and after a reconnection
    they are expired, which is the same problem in two tenses.

    The verdict counts a disk rescue as not-fresh, not just a raise: `cached`
    answers an outage with the stamped copy *as a success*, so a warm that
    "worked" while re-serving afternoon data is exactly the difference the
    reheat report is about (see `first_paint_pass`).
    """
    symbol, span, interval = WARM_CHART
    fresh = True
    for name, produce in (
        # Chart first: the heaviest answer and the one the page's hero waits on.
        # The most-traded tables and the 24-hour crypto list left the page on
        # 2026-11-07. Their routes still answer a direct request. Startup and
        # a reconnect do not fetch them.
        (f"chart:{symbol}", lambda: chart_data(symbol, span, interval)),
    ):
        try:
            value = produce()
        except Exception as exc:  # a warm miss is not a server failure
            sys.stderr.write(f"  warm {name}: {exc}\n")
            fresh = False
            continue
        if isinstance(value, dict) and value.get("cached"):
            fresh = False
    return fresh


def start_prewarm() -> None:
    """Warm the first-paint caches off the request path, once, at startup.

    Runs `first_paint_pass`, not bare `warm_routes`, so the pass marks the
    startup report -- that mark is the "first paint" part the closing line
    waits on; a warm that did not mark it would be a warm nobody reported.
    """
    thread = threading.Thread(target=first_paint_pass, name="prewarm", daemon=True)
    thread.start()


def tables_payload() -> dict:
    """The `/api/top` answer, lifted out of the route so the prewarm thread,
    the row warmer below, and a browser request all read the tables through
    one path -- the way `chart_data` keeps warming and serving from drifting
    apart.

    The tables are cached for TOP_TTL; the `checkedAt` stamp is not, or "checked
    at" would report the age of the cache entry rather than of the answer.
    `usable` guards the disk write: an all-error payload is an outage, not an
    answer, and must not overwrite the last good copy (see `cached` and
    `tables_usable`). But a disk-rescued copy must keep its *own* date: `cached`
    was stamped `fetchedAt` when it was retrieved, and adding a fresh
    `checkedAt` would let the page clock a month-old table as just checked. The
    `cached` flag already tells the page both stories.
    """
    payload = cached(LEADERS_KEY, markets.tables, TOP_TTL,
                     usable=tables_usable)
    if payload.get("cached"):
        return payload
    return {**payload, "checkedAt": int(time.time())}


def cryptobull_usable(payload) -> bool:
    """Whether a `cryptobull.scan` payload carries an answer at all.

    The scan reports failure by raising, so unlike the market tables it has no
    in-band error card to hide an outage behind -- but it can legitimately
    return *fewer* rows than asked for, and `short` is an answer, not an
    outage: a market where fewer than ten chartable coins are bullish has been
    measured, and disk must not trade that measurement for yesterday's longer
    table. What must never reach disk is a payload with an `error` set, or one
    whose rows are not a list -- a shape that would mean the scan broke halfway
    through building it. An empty row list with no error stands: "none of the
    pairs scanned is bullish" is a fact about the day, and a strong one.
    """
    if not isinstance(payload, dict) or payload.get("error"):
        return False
    return isinstance(payload.get("rows"), list)


def cryptobull_payload() -> dict:
    """The `/api/cryptobull` answer, through the same `cached` path the tables
    and every chart take -- the prewarm pass and the row warmer read this too,
    so warming and serving cannot drift apart.

    The scan is a handful of plain HTTPS calls to Binance and CoinGecko -- no
    browser -- so a cold fetch costs seconds, not the sweep's thirty-five; a
    request that lands on a miss simply waits out the one in flight. The
    `checkedAt` stamping follows `tables_payload` exactly: the cache entry is
    stamped when it was fetched, the answer when it was checked, and a
    disk-rescued copy keeps its own older date.
    """
    payload = cached(CRYPTO_KEY, cryptobull.scan, TOP_TTL,
                     usable=cryptobull_usable)
    if payload.get("cached"):
        return payload
    return {**payload, "checkedAt": int(time.time())}


# -- keeping every *listed* asset retrievable ------------------------------------
#
# The offline fallback is only as good as what was fetched while online, and
# until now that meant "whatever a reader happened to click". The tables land
# on disk on their own (`cached` stores every live answer), but the chart behind
# a row landed there only if that row had been opened recently -- so with the
# internet down the page could still *name* every top stock and not draw a
# single one of their graphs. This section closes that gap: one thread walks the
# rows of both tables every pass and keeps each listed symbol's chart at the
# window the page draws fresh on disk, through the very `chart_data` a row click
# takes, so a warmed chart and a clicked one are the same entry, not two that
# can drift apart.
#
# The warmer is deliberately the laziest thread on this server. It sleeps a
# minute when there is nothing due, spends one browser run per *batch* of
# rows it actually needs -- forty PSE rows per shared TradingView socket,
# twenty Yahoo URLs per one page -- and stops its whole pass the moment a
# fetch says the network is not answering, because the rows behind the break
# would learn the same thing at the same price. A machine that never reaches
# the internet costs this thread exactly one `markets.tables` POST per poll
# (the route's own cached read, which fails fast and lands on disk), and no
# browsers at all.

# One `(epoch, timestamp)` per chart key, which is the only clock `row_fresh`
# reads after a key's first look at its epoch: the moment this process fetched
# it, or -- before any fetch -- the `fetchedAt` of the disk copy it adopted.
# A symbol tried within the last quarter-hour is not due again whether it
# landed or not, *until the reconnect epoch moves*, which makes every stamp
# last look and re-adopt from disk (see `row_fresh`). Owned by the warmer
# thread alone, so no lock —
# `_refresh_epoch` is read unlocked, but the worst race is one extra
# disk-adopt pass, and the watch only ever moves the epoch forward. A restart
# forgets the stamps, and the first pass adopts what the disk remembers
# instead of re-fetching it.
_warm_due: dict[str, tuple[int, float]] = {}


# Split out on 2026-11-16. Imported before any older part below, which may read
# these names through "server" while it loads.
from sweeps import (  # noqa: E402,F401
    BULLISH_KEY,
    LEGACY_RECENT_KEY,
    OLDER_RECENT_KEY,
    RECENT_BATCH,
    RECENT_INTERVAL,
    RECENT_KEY,
    RECENT_PH_WAIT,
    RECENT_SPAN,
    RECENT_TTL,
    BULL_CLOSED_TTL,
    BULL_CLOSE_MARGIN,
    _fetch_us_pass,
    bullish_pause,
    _bullish_lock,
    _bullish_state,
    _bullish_thread,
    _recent_lock,
    _recent_state,
    _recent_thread,
    bullish_loop,
    bullish_state,
    fetch_us_bars,
    recent_loop,
    recent_state,
    seed_bullish,
    seed_recent,
    start_bullish_refresh,
    start_recent_refresh,
)
from yahoo_chart import (  # noqa: E402,F401
    LIVE_BAR_GAP_DAYS,
    LIVE_PRINT_MAX_AGE,
    _series_close,
    _within,
    chart_quality,
    exchange_day,
    fill_missing_days,
    full_day_close,
    history_tail,
    last_bar_basis,
    live_point,
    live_print,
    same_exchange_day,
    session_close,
    session_window,
    slim_chart,
    usable_stamp,
    yahoo_bars,
    yahoo_chart,
    yahoo_is_wrong,
    yahoo_meta,
)
from fx_charts import (  # noqa: E402,F401
    ecb_route,
    fx_cross_chart,
    weekend_proxy,
)
from search_rank import (  # noqa: E402,F401
    FX_SEARCH_EXTRA,
    INSTRUMENT_WORDS,
    TICKER_RE,
    _chart_meta_row,
    fx_search_extra,
    probe_ticker,
    relevance,
)
# Split out on 2026-11-18: the chart route (`chart_key`, `chart_data`).
from chart_route import (  # noqa: E402,F401
    chart_data,
    chart_key,
    retry_sparse_research,
)

# The split-out parts. Imported last so every name they reach through
# "server" already exists. Re-exported so "server.<name>" keeps working.
from watchlist import (  # noqa: E402,F401
    _clean_watch,
    _clean_watch_items,
    _watch_lock,
    adopt_watchlist,
    record_watchlist,
    saved_watchlist,
    union_watchlist,
)
from netwatch import (  # noqa: E402,F401
    REFETCH_PARTS,
    _refetch_lock,
    _refetch_opened,
    _refetch_pending,
    _refetch_stale,
    first_paint_pass,
    net_watch_loop,
    note_refetch_done,
    open_refetch_report,
    open_startup_report,
    start_net_watch,
)
from warm import (  # noqa: E402,F401
    WARM_LANDED,
    WARM_OUTAGE,
    _reroute_crypto,
    _row_lock,
    _store_chart,
    _warm_batch_bonds,
    _warm_batch_funds,
    _warm_batch_pse,
    _warm_batch_tokens,
    _warm_batch_yahoo,
    due_rows,
    row_fresh,
    start_row_warming,
    warm_rows_loop,
)
from http_handler import (  # noqa: E402,F401
    Handler,
    kill_running_moli,
    main,
    port_owner,
)


if __name__ == "__main__":
    raise SystemExit(main())
