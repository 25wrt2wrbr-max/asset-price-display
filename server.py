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

import bullish
import coinsph
import crypto
import cryptobull
import diskcache
import ecb
import markets
import ondo
import ondolist
import onset as onset_module
import phfunds
import probability
import pse
import rates
import recent
import research_judgment
import trend
import tv

HERE = os.path.dirname(os.path.abspath(__file__))

MOLI = os.environ.get("MOLI_BIN") or shutil.which("moli") or os.path.expanduser("~/.local/bin/moli")

# A Yahoo page is required as the fetch origin (see module docstring) -- but only
# its *origin*, never its content. Yahoo's CORS allowlist is keyed on the Origin
# header, not the path, so `robots.txt` on finance.yahoo.com is an equally good
# origin page, and it is a two-line document instead of a two-megabyte dashboard.
# The quote page costs ~1.6 s to render before the API call inside it even
# starts; robots.txt costs ~0.1 s. The API answers HTTP 200 from either.
ORIGIN_PAGE = "https://finance.yahoo.com/robots.txt"
CHART_HOST = "query1.finance.yahoo.com"
SEARCH_HOST = "query2.finance.yahoo.com"

DEFAULT_PORT = 8000
MOLI_TIMEOUT_MS = 25_000
SUBPROCESS_TIMEOUT = 40
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
WARM_BATCH_TIMEOUT_MS = 45_000
WARM_BATCH_SUBPROCESS_TIMEOUT = 75

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
# The sweep needs a longer browser budget than one chart: a forty-symbol chunk
# answers in about ten seconds, but a chunk that has to be retried runs twice that.
BATCH_TIMEOUT_MS = 60_000
BATCH_SUBPROCESS_TIMEOUT = 90

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

# Runs inside the Moli-rendered Yahoo page. Returns a JSON *string* (Moli writes
# strings as plain text), which we parse on this side.
EVAL_SCRIPT = """(async () => {
  const r = await fetch(%s, { headers: { Accept: "application/json" } });
  return JSON.stringify({ status: r.status, body: await r.text() });
})()"""

# The same fetch, widened to a batch: one Moli run, many chart URLs. The
# browser launch and the Yahoo origin page are the fixed cost of every
# `moli_get` -- roughly a second each -- so a row warmer that fetched one URL
# per run spent most of its pass paying for Chrome, not for data. Fetching N
# URLs inside the page they share amortises that cost N-fold: the page is
# already loaded, the fetches are same-origin like `EVAL_SCRIPT`'s, and each
# result keeps its own HTTP status so a 404 verdict is not promoted to an
# outage. One URL's transport failure (a rejected promise, a non-JSON body)
# is recorded per URL rather than failing the batch -- the caller decides,
# per symbol, whether what came back is an answer or an outage.
BATCH_EVAL_SCRIPT = """(async () => {
  const urls = %s;
  const results = {};
  await Promise.all(urls.map(async (url) => {
    try {
      const r = await fetch(url, { headers: { Accept: "application/json" } });
      results[url] = { status: r.status, body: await r.text() };
    } catch (e) {
      results[url] = { status: 0, body: String(e && e.message || e) };
    }
  }));
  return JSON.stringify(results);
})()"""

_cache: dict[str, tuple[float, object]] = {}

_cache_lock = threading.Lock()


class _Flight:
    """One in-progress `cached()` production, shared by every waiter on its key.

    `leader` is claimed under `_cache_lock` by the thread that produces;
    everyone else waits on `done` and reads `value` or re-raises `error`.
    """

    __slots__ = ("done", "value", "error")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.value = None
        self.error = None


_flights: dict[str, _Flight] = {}

# Where Yahoo and Binance disagree, Yahoo is charting a different instrument
# under the same ticker: JUP-USD is a dead 2017 token at $0.00036, while the
# coin people mean is ~$0.34 -- four orders of magnitude apart. A relative gap
# that large is an objective test for "Yahoo resolved this symbol to the wrong
# thing". No blocklist of tickers is needed, and the crypto Yahoo gets right
# (BTC/ETH/SOL agree to a fraction of a percent) is left alone.
REROUTE_GAP = 0.20

# Moli fetches in flight, so shutdown can reap them instead of orphaning
# browser processes that hold the Moli profile lock.
_running: set[subprocess.Popen] = set()
_running_lock = threading.Lock()


class UpstreamError(RuntimeError):
    """Moli could not be run, or returned something unusable."""


def moli_run(page: str, script: str,
             timeout_ms: int = MOLI_TIMEOUT_MS,
             wall_timeout: float = SUBPROCESS_TIMEOUT) -> str:
    """Run `script` inside the Moli-rendered `page`; return Moli's stdout.

    The single place a browser is shelled out to. Callers differ in the page that
    supplies the origin, in what they make of the output, and in how long they are
    willing to wait: both live above this. `moli_get` and `moli_fallback` want a
    `fetch` envelope, `moli_eval` wants whatever the script itself returned, and
    `moli_sweep` needs the longer budget the whole-universe socket takes.

    `timeout_ms` is Moli's own patience with the page; `wall_timeout` is this
    process's patience with Moli. The second is the one that fires if Moli hangs
    before it can honour the first, so it must stay comfortably larger.
    """
    if not os.path.exists(MOLI):
        raise UpstreamError(
            f"moli not found at {MOLI!r}. Install it from the latest release "
            "(see ~/.claude/skills/moli-webfetch/SKILL.md), or set MOLI_BIN."
        )
    popen = subprocess.Popen(
        [MOLI, "fetch", "--eval", script,
         "--wait-until", "domcontentloaded",
         "--timeout", str(timeout_ms), page],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=HERE,
    )
    with _running_lock:
        _running.add(popen)
    try:
        stdout, stderr = popen.communicate(timeout=wall_timeout)
        returncode = popen.returncode
    except subprocess.TimeoutExpired:
        popen.kill()
        popen.communicate()
        raise UpstreamError(f"moli timed out after {wall_timeout}s")
    finally:
        with _running_lock:
            _running.discard(popen)

    if returncode != 0:
        detail = (stderr or stdout or "").strip()
        raise UpstreamError(f"moli exited {returncode}: {detail[:400] or 'no output'}")

    text = (stdout or "").strip()
    if not text:
        raise UpstreamError("moli produced no output")
    return text


def moli_get(url: str, page: str = ORIGIN_PAGE) -> tuple[int, str]:
    """Fetch `url` through Moli. Returns (http_status, response_body)."""
    text = moli_run(page, EVAL_SCRIPT % json.dumps(url))
    try:
        outer = json.loads(text)
        return int(outer["status"]), outer["body"]
    except (ValueError, KeyError, TypeError) as exc:
        raise UpstreamError(f"unexpected moli output ({exc}): {text[:200]}")


def moli_batch_get(urls: list[str],
                   page: str = ORIGIN_PAGE) -> dict[str, tuple[int, str]]:
    """Fetch several same-origin URLs in one Moli run; `{url: (status, body)}`.

    The row warmer's Yahoo leg. One browser launch, one origin page, N fetches
    -- the per-URL contract matches `moli_get`'s, so a caller can treat each
    result exactly as it would have treated that URL fetched alone: a 404 with
    a `chart.error` body is still a verdict about the symbol, still not
    promoted to an outage by its neighbours.

    A URL whose fetch *rejected* in the page -- connection refused, TLS failure
    -- comes back with status 0 rather than disappearing from the dict, so the
    caller can tell "Yahoo said no" from "the wire said nothing". The run as a
    whole can still fail (`UpstreamError` from `moli_run`): Moli down, the
    envelope never arriving. That is the batch-fatal case, and it is the
    caller's to handle -- every URL it wanted is an outage at once, which is
    the same sentence `moli_get` would have spoken one URL at a time.

    Runs on the longer batch budget (`WARM_BATCH_*`): twenty fetches inside one
    page take longer than one, and a wall timeout that fit a single chart
    would kill a healthy batch's last few responses.
    """
    text = moli_run(page, BATCH_EVAL_SCRIPT % json.dumps(urls),
                    WARM_BATCH_TIMEOUT_MS, WARM_BATCH_SUBPROCESS_TIMEOUT)
    try:
        outer = json.loads(text)
        out = {}
        for url in urls:
            entry = outer[url]
            out[url] = (int(entry["status"]), entry["body"])
        return out
    except (ValueError, KeyError, TypeError) as exc:
        raise UpstreamError(f"unexpected moli batch output ({exc}): {text[:200]}")


def moli_eval(page: str, script: str) -> str:
    """Run a caller's own script in a Moli-rendered `page`, returning its output.

    Unlike `moli_get` this does not unwrap a `(status, body)` envelope, because
    the caller's script speaks its own protocol -- `pse.py` drives a websocket,
    not a fetch -- and parses its own reply.
    """
    return moli_run(page, script)


def moli_sweep(page: str, script: str) -> str:
    """`moli_eval` with the whole-universe budget (see `BATCH_TIMEOUT_MS`).

    The same browser path, given longer: a sweep chunk is one deliberately
    long-lived socket that has to outlive the several seconds a hundred-odd frames
    take to arrive, so it cannot share the per-chart timeout without one of the two
    being wrong.
    """
    return moli_run(page, script, BATCH_TIMEOUT_MS, BATCH_SUBPROCESS_TIMEOUT)


def moli_fallback(url: str) -> tuple[int, str]:
    """`(status, body)` for a non-Yahoo URL, via Moli.

    Binance and CoinGecko answer an ordinary HTTP client and send `*` CORS
    headers, so `crypto.py` tries plain HTTP first. This exists only as a safety
    net -- and it earns its keep, because CoinGecko's rate limiter answers a
    browser navigation with a 429 body, which is exactly what we want to detect.

    Moli is pointed at a page on the target's own host where there is one, so
    the fetch stays same-origin; otherwise a throwaway page on that host.
    """
    split = urllib.parse.urlsplit(url)
    return moli_get(url, page=f"{split.scheme}://{split.netloc}/")


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


# Errors that mean "the network did not answer" rather than "this symbol does
# not exist". Only these are rescued from disk: a genuine "no such symbol" is a
# settled verdict about the instrument, while an outage says nothing about it
# and every caller deserves the fallback. `LookupError` deliberately absent --
# that is the verdict kind.
TRANSIENT_ERRORS = (
    UpstreamError, pse.PseError, markets.MarketError, crypto.CryptoError,
    ecb.EcbError, tv.TvError, ondo.OndoError,
)


def is_transient(exc: Exception) -> bool:
    # `PseNotFound` subclasses `PseError` but is a verdict, not an outage --
    # "TradingView has no symbol X" is an answer about X, and disk must not
    # overrule an answer by serving some older moment's data under its name.
    return isinstance(exc, TRANSIENT_ERRORS) and not isinstance(
        exc, pse.PseNotFound)


def tables_usable(payload) -> bool:
    """Whether a `markets.tables` payload carries any real data.

    The tables report failure *in band* -- one error card per unreachable
    section, so one dead market costs its own card and not the other's -- and
    that design is right for a live answer but invisible to `cached`, which
    only sees a raise. This is the missing sentence: an all-error payload is
    an outage wearing a value's clothes, and disk must not trade last week's
    rows for it. A payload where *any* section answered is usable, even with
    the other's error card in it -- partial truth beats a rescued guess, and
    the page renders per-card errors side by side with the good table.
    """
    if not isinstance(payload, dict):
        return False
    return any(
        (not card.get("error")) and card.get("rows")
        for card in (payload.get("markets") or [])
    )


def cached(key: str, produce, ttl: float = CACHE_TTL, usable=None):
    """Memoize `produce()` for `ttl` seconds, fetching it at most once per key.

    The single-flight part is what makes this more than a memo. The page asks
    for the same symbol twice on every load -- once for the chart, once for its
    watchlist row -- and without it two concurrent misses would each shell out
    their own browser for the same upstream. Callers wait on the one in flight
    and share its result; a producer that raises is forgotten, so the next
    caller tries again rather than inheriting a stuck failure.

    A fresh answer is stored on disk as it is returned (`diskcache`), so the
    newest copy of every key outlives this process. When `produce()` raises a
    transport error, the disk copy is served instead, stamped `cached` and
    `fetchedAt` so the page can date what it draws; the in-memory entry is
    filled with the stamped copy so waiters and the next call see the same
    thing. A producer that raises a *verdict* (`LookupError` -- "no such
    symbol") propagates untouched; disk never overrules an answer, only an
    outage.

    `usable` is the second half of that promise. Some producers carry their
    failures *inside* the payload instead of raising -- `markets.tables`
    returns one error card per unreachable section -- so an outage there is a
    value that "succeeds". Storing it would overwrite the last good copy with
    empty tables and no error to rescue, which is the poison this guard exists
    to stop: when `usable(value)` is false, the disk copy is tried first (it
    is what the fallback path would have served, reached by a different road),
    and only if there is no usable copy is the failing payload served as-is --
    truthful, current, and never written to disk. A disk copy is held to the
    same bar, so a payload poisoned before the guard existed cannot come back
    to life as a fallback.
    """
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        # The leader claim happens under the same lock as the map lookup, so
        # two simultaneous misses cannot both start producing.
        flight = _flights.get(key)
        leader = flight is None
        if leader:
            flight = _flights[key] = _Flight()

    if not leader:
        # Another thread is already producing this key: wait for its answer
        # instead of starting a duplicate fetch.
        flight.done.wait()
        if flight.error is not None:
            raise flight.error
        return flight.value

    try:
        value = produce()
    except Exception as exc:
        fallback = (_stamp_copy(key, str(exc) or type(exc).__name__, usable)
                    if is_transient(exc) else None)
        if fallback is None:
            flight.error = exc
            with _cache_lock:
                _flights.pop(key, None)
            flight.done.set()
            raise
        # The outage is nobody's fault twice over: this request gets the last
        # good copy, and the next caller within the TTL gets it from memory
        # without touching disk or the network again.
        value = fallback
    else:
        if usable is not None and not usable(value):
            # The producer answered without raising, but the answer carries
            # only failures (see the docstring). It is a fallback situation
            # reached by a different road: serve the last good copy stamped as
            # such, or -- if there is none -- the failing payload itself.
            # Either way it is never stored over the last good copy, and the
            # unstorable failing payload is not memoized either, so the next
            # caller tries the network again instead of inheriting a stuck
            # outage -- the same promise the raising path makes.
            fallback = _stamp_copy(
                key, "sources unreachable (all sections failed)", usable)
            if fallback is None:
                # Nothing to rescue: serve the failing payload as-is, but
                # un-memoized and with the flight closed, so the next caller
                # tries the network again rather than inheriting this outage.
                with _cache_lock:
                    _flights.pop(key, None)
                flight.value = value
                flight.done.set()
                return value
            value = fallback
        else:
            diskcache.store(key, value)

    with _cache_lock:
        _cache[key] = (time.time(), value)
        _flights.pop(key, None)
    flight.value = value
    flight.done.set()
    return value


def _stamp_copy(key: str, reason: str, usable=None):
    """The last good copy for `key`, stamped as a fallback, or None.

    The stamp travels with the value (`cached`, `fetchedAt`, and `cacheError`
    naming why the live fetch was abandoned) so the page can date what it draws
    and say so in one look. A dict copy is the only shape that can carry the
    stamps, so a cached list payload (the market tables' wrapper is a dict, but
    a producer could return anything) is honestly refused rather than served
    undated -- with no way to tell the page "this is old", drawing it would
    pass off an old answer as a fresh one, which is exactly the failure this
    feature exists to prevent.

    `usable`, when given, holds the copy to the same bar as a fresh answer: a
    payload stored before such a guard existed can carry failures the way the
    live payload does, and rescuing it would rescue nothing.
    """
    saved = diskcache.load(key)
    if saved is None:
        return None
    fetched_at, value = saved
    if not isinstance(value, dict):
        return None
    if usable is not None and not usable(value):
        return None
    out = dict(value)
    out["cached"] = True
    out["fetchedAt"] = int(fetched_at)
    out["cacheError"] = reason
    return out


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

# The watch thread's most recent answer, for `/api/health`: None until the
# first probe, then at most `NET_PROBE_INTERVAL` old. Read without the lock --
# a health line one poll stale is still the truth about the wire.
_watch_online: bool | None = None


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


# -- reporting when the refetch is actually over ----------------------------------
#
# "Re-fetching everything now" promises a finished set, and three threads
# cooperate to deliver it: the first-paint thread (hero chart and tables --
# startup's prewarm and every reheat alike), the bullish sweep (woken from its
# sleep, sweeping next), and the row warmer (woken, re-deciding what is due --
# leaderboards, the sweep's rows, and the declared watchlist). None of them is
# the leader, so none of them may speak the closing sentence alone; instead the
# report's *opener* names the parts, each thread marks its part when its
# post-edge pass completes, and the last mark prints the line. A pass started
# *before* an edge belongs to the older epoch and cannot close the newer
# report -- the waking loop runs another pass for that, and every path through
# a loop (full queue, empty queue, outage break) ends in a mark, so a slow wire
# cannot strand the sentence.
#
# Startup opens the same report (at epoch 0, before any thread exists to mark
# it), because the boot has exactly the shape the edge has: three threads
# fetching everything, and a reader at the console who is owed one sentence
# saying when the fetching is over. Before this report existed the startup
# marks were dropped silently -- the reasoning was that nobody had been
# promised anything -- but the promise is the point: the console is the only
# place the machine says what it is doing, and "is it done fetching yet" is
# the first question anyone watching a boot asks. The wording differs (nothing
# came *back* at startup), the machinery does not.
#
# But a mark carries more than "the pass ran": it carries whether the pass
# *landed fresh data*, and the closing sentence says which one it is. "The
# pass completed" and "the data is new" came apart twice in practice -- once
# when a warm handed back its own disk copy as a success (the wire died
# mid-queue and `cached` rescued every row from afternoon data), and once when
# an empty declared union made "row charts done" true of nothing at all. A
# reader who later finds 2pm bars under a line claiming the refetch finished
# has learned the wrong lesson from the wrong sentence, so the report now
# distinguishes them: all three parts landed prints "all refetches finished",
# anything that ended without landing prints the parts still stale instead.
# A newer edge opens a newer report either way, and a mark against a closed
# one drops.

REFETCH_PARTS = ("first paint", "bullish sweep", "row charts")
_refetch_lock = threading.Lock()
_refetch_pending: dict[int, set] = {}
_refetch_stale: dict[int, set] = {}
_refetch_opened: dict[int, float] = {}


def open_refetch_report(epoch: int) -> None:
    """Begin the completion report for one reconnection, discarding any older
    epoch still waiting on a thread that stopped reporting it."""
    with _refetch_lock:
        for old in [e for e in _refetch_pending if e < epoch]:
            _refetch_pending.pop(old, None)
            _refetch_stale.pop(old, None)
            _refetch_opened.pop(old, None)
        _refetch_pending[epoch] = set(REFETCH_PARTS)
        _refetch_stale[epoch] = set()
        _refetch_opened[epoch] = time.monotonic()


def note_refetch_done(part: str, epoch: int, landed: bool = True) -> None:
    """One thread's pass finished; close the report when they all have.

    `epoch` is the event the pass belongs to (0 is startup, 1.. the
    reconnections), read when the pass began, and `landed` is whether that pass
    put *new* data on disk: a sweep that raised, or a warm answered by
    `cached`'s disk rescue, ran its pass without fetching anything, and naming
    that part in the closing line is the whole point of the sentence. A mark
    against an epoch with no open report -- one whose newer edge already
    superseded it -- is true but useless, so it is dropped: nothing in the log
    claims completeness nobody asked for. (Startup's report is open from
    `main()` before any thread starts, so its marks land instead of dropping.)
    """
    with _refetch_lock:
        pending = _refetch_pending.get(epoch)
        if pending is None:
            return
        pending.discard(part)
        if not landed:
            _refetch_stale.setdefault(epoch, set()).add(part)
        if pending:
            return
        stale = sorted(_refetch_stale.pop(epoch, set()))
        elapsed = time.monotonic() - _refetch_opened.pop(epoch, time.monotonic())
        del _refetch_pending[epoch]
    startup = epoch == 0
    verb = "startup warm" if startup else "back online"
    if stale:
        sys.stderr.write(
            f"  {verb}: passes ended ({elapsed:.0f}s), but no fresh data for:"
            f" {', '.join(stale)}"
            + (" -- will retry after the next backoff or reconnection\n"
               if not startup else
               " -- kept the saved copies; the next passes retry\n"))
    else:
        sys.stderr.write(f"  {verb}: all refetches finished ({elapsed:.0f}s)\n")


def open_startup_report() -> None:
    """Open the epoch-0 report the startup threads will close.

    Called from `main()` after the watchlist is adopted and before any warming
    thread starts, so every first pass -- the prewarm's, the sweep's, the row
    warmer's -- marks an *open* report instead of dropping its mark, and the
    console gets the closing sentence the reconnection path has always had.
    Opening it before the port binds also means a reader who opens the page
    mid-warm still sees the line land when warming actually ends.
    """
    open_refetch_report(0)


def first_paint_pass() -> None:
    """The first paint's chart and tables, fetched off the request path.

    Runs as startup's prewarm thread and again on the reconnect edge -- the
    same code, the same keys, the
    same single-flight `cached`, because filling a cold cache and refilling an
    expired one are the same problem in two tenses. The row warmer handles
    *listed* rows by waking from its own sleep and re-deciding what is due;
    this covers the two answers no listed row includes: the hero chart
    (`BTC-USD`, prewarmed but never table-listed) and the leaderboards behind
    the warmer's own queue.

    The epoch is read when the pass begins and reported with its mark: at
    startup that is 0 (the report `main()` opened), after an edge it is the
    new one -- so whichever report is open, this part closes its share of it.
    """
    epoch = _refresh_epoch
    landed = False   # a pass that never ran, or died on the way, landed nothing
    try:
        landed = warm_routes()
    finally:
        note_refetch_done("first paint", epoch, landed=landed)


def net_watch_loop() -> None:
    """Ask the reachability question on a timer; act on the no-to-yes edge.

    The edge, not the state, is the event: `online` starts as the first probe's
    answer, so a server that boots with the internet working does not spend its
    first moments re-warming what the startup prewarm is warming already. A
    yes-to-no edge needs no action at all -- every fetch path already degrades
    to the disk fallback on its own, which is what the watch is *for*: noticing
    when that fallback should stop being served. The probe sleeps a plain
    `time.sleep`, never `_sleep_or_wake`: this loop is the waker, and a waker
    that waited on its own condition could sleep through the very edge it is
    meant to report.
    """
    global _watch_online
    online = net_ok()
    _watch_online = online
    while True:
        time.sleep(NET_PROBE_INTERVAL)
        ok = net_ok()
        _watch_online = ok
        if ok and not online:
            net_reconnected()
        online = ok


def start_net_watch() -> None:
    """Start the connectivity watch. Called once, from `main`.

    Daemon like the threads it supervises: the probe is never worth blocking a
    shutdown on, and waking a half-finished sweep is a courtesy, not a promise.
    """
    threading.Thread(target=net_watch_loop, name="net-watch", daemon=True).start()


# -- what the page declared it is watching ---------------------------------------
#
# The warmer can only keep fresh what it knows to exist, and until now "listed"
# meant "listed by a *source*" -- the leaderboards and the bullish sweep. The
# watchlist is neither: the reader curates it, and it lived in one browser's
# localStorage, so a saved row was invisible to every background thread. The
# reconnect edge refetched the tables and left the user's own symbols at the
# date the page last asked for them -- the one list that matters most to the
# person who made it being the one nothing warms.
#
# So the page now *declares* its list (`POST /api/watch`) and the server keeps
# the durable union of every list ever declared. Union, not last-declaration,
# because the edge belongs to the machine, not to a tab: a server rebooted
# offline, or a weekend with nobody visiting, still knows which symbols the
# reader cares about. Membership is exactly what a list's worth is, so the
# union is right for warming -- a symbol removed months ago costs at most one
# stale chart a quarter-hour, and the page never draws from the union anyway: a
# browser refreshes its own `state.watch` when it sees `/api/health`'s
# `reconnections` counter move, so the two never disagree in front of anyone.
#
# Nothing trusts the declared strings: they are normalised, and reach a fetch
# only through the same `chart_data` a click takes, with `cached`'s single-flight
# in front -- a nonsense symbol costs one upstream lookup and lands nowhere. The
# list itself is **not** capped: the reader's watchlist is their own, and a
# length limit only ever meant "you may keep exactly this many". The declared
# record survives restarts through `diskcache.store_plain`, because a fact the
# server was *told* must not expire like a copy it *fetched*.
#
# The client's side (`index.html`, "staying current without being asked") is
# what keeps the union honest: the list is declared at page load and on every
# save, and re-declared on every `/api/health` poll -- so a symbol added during
# an outage, whose save-time declaration failed, is back on the server within
# 30 seconds of the wire returning.

_watch_lock = threading.Lock()
_watch_union: list[str] = []


def _clean_watch(value) -> list[str]:
    """Validate a declared list: strings, normalised, de-duplicated.

    A client is an untrusted caller, so every property the warmer depends on
    is enforced here rather than assumed: uppercase, trimmed, short enough to
    be a symbol. Length is deliberately *not* enforced -- the list belongs to
    the reader, and the only remaining bound is the request body's own ceiling
    (`read_json`), which exists to stop a junk body being buffered, not to tell
    someone how many assets they may follow. Order is the browser's -- rows are
    drag-sortable, and the warmer reads the head of the list first -- so it
    survives untouched.
    """
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            symbol = str(item.get("symbol") or "").strip().upper()
        elif isinstance(item, str):
            symbol = item.strip().upper()
        else:
            continue
        if not symbol or len(symbol) > 32 or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def record_watchlist(symbols) -> None:
    """A browser declared `symbols`: they join the union and the union is
    persisted. Runs from the route thread; the list swaps whole under the lock,
    so a warmer pass sees either the old world or the new one, never a splice.
    The disk write lives inside the lock too -- outside it, two simultaneous
    declarations could land out of order and leave the smaller union filed."""
    global _watch_union
    cleaned = _clean_watch(symbols)
    with _watch_lock:
        merged = list(_watch_union)
        known = set(merged)
        for symbol in cleaned:
            if symbol not in known:
                known.add(symbol)
                merged.append(symbol)
        _watch_union = merged
        diskcache.store_plain(WATCHLIST_KEY, _watch_union)


def adopt_watchlist(union) -> None:
    """Re-adopt the durable union at startup (see `main`)."""
    global _watch_union
    cleaned = _clean_watch(union)
    with _watch_lock:
        _watch_union = cleaned
    if cleaned:
        sys.stderr.write(f"  watchlist: remembering {len(cleaned)} declared symbols\n")


def union_watchlist() -> list[str]:
    """Every symbol ever declared, for the warmer. A copy: the pass iterates
    while a route thread may be swapping the real list."""
    with _watch_lock:
        return list(_watch_union)


# -- the bullish sweep, held warm by a background thread ------------------------
#
# Everything else on this server can be fetched while a reader waits: a chart is
# a second, the market tables are a few. The bullish sweep reads the whole PSE
# universe and takes ~35s cold, so it cannot be -- and `cached()` is the wrong
# tool for it, because a cache entry that expires puts the next reader in exactly
# the position the cache existed to avoid. So one thread sweeps on a loop and
# leaves the result behind, and a request only ever reads it.
#
# The consequence worth knowing: the first request after a cold start reads an
# empty stand-in, not a half-finished table, and the page says a sweep is running
# rather than showing zero bullish stocks. `pending` in the payload is that
# distinction and is the same flag a refresh sets for the duration of its work.
_bullish_lock = threading.Lock()
_bullish_state: dict = {
    "payload": None,    # the last good sweep, or None before the first one lands
    "error": None,      # why the most recent attempt failed, or None
    "started": 0.0,     # when the last good sweep finished
    # When the most recent sweep *attempt* began. `error` describes that
    # attempt, not the payload, so a reader needs this to know whether the
    # failure is newer than the rows beside it -- see `bullish_state`. A disk
    # seed has no attempt behind it, hence the `max` in the reader.
    "last_attempt": 0.0,
    "running": False,   # a sweep is in flight right now
}
_bullish_thread: threading.Thread | None = None

# The sweep's disk-cache key. Not through `cached()` -- the sweeper owns its own
# schedule -- so it is filed by hand under this one synthetic key, and
# `seed_bullish` is its reader.
BULLISH_KEY = "bullish:scan:v2:t2"  # :t2 -- see CRYPTO_KEY


def seed_bullish() -> None:
    """Hydrate the sweep state from disk, so an offline start still has rows.

    The sweep is the one answer that cannot be refetched on demand -- ~35s is
    far too long for a reader to wait -- so offline the sweeper fails its first
    attempt and a reader would be told "not measured yet" while a full sweep
    from yesterday sits in `.cache/`. A stored copy becomes the payload as any
    live sweep would: the rows are real rows, and `started` is the second they
    were actually swept, which `bullish_state` serves as `checkedAt` exactly as
    it does for a fresh one. The copy carries `cached`/`fetchedAt` stamps so the
    page can say where it came from, and the first sweep of this run replaces
    it wholesale whether it lands or fails, so the seed never has to be undone.

    Runs before the refresh thread starts, so no request can observe the empty
    stand-in for a moment the answer had already been given.
    """
    saved = diskcache.load(BULLISH_KEY)
    if saved is None:
        return
    fetched_at, payload = saved
    # Same refusal as `_disk_fallback`: only a dict can carry the stamps, and
    # only a sweep with rows is worth serving -- an empty saved table would
    # claim "no stock is bullish" from the past, which the stand-in's "not
    # measured yet" beats honestly.
    if not isinstance(payload, dict) or not payload.get("rows"):
        return
    with _bullish_lock:
        if _bullish_state["payload"] is not None:
            return  # a sweep got here first; it knows better than the disk
        seeded = dict(payload)
        seeded["cached"] = True
        seeded["fetchedAt"] = int(fetched_at)
        _bullish_state["payload"] = seeded
        _bullish_state["started"] = float(fetched_at)


def bullish_state() -> dict:
    """The last sweep, or a stand-in saying one has not landed yet.

    Never blocks: it takes the lock, copies what is there and lets go. The
    payload is replaced wholesale by the refresher rather than mutated, so a
    reader cannot see it change while it renders.
    """
    with _bullish_lock:
        payload = _bullish_state["payload"]
        error = _bullish_state["error"]
        started = _bullish_state["started"]
        attempted = max(_bullish_state["last_attempt"], started)
        running = _bullish_state["running"]

    if payload is None:
        return {
            "label": "Bullish Philippine stocks",
            # The same constant the sweep dates its rows in, so the stand-in and
            # a real payload cannot disagree about the currency of the column.
            "currency": bullish.CURRENCY,
            "source": "TradingView",
            "rows": [],
            "universe": 0, "fetched": 0, "missing": [],
            "boundary": 0, "censored": 0,
            "turns": 0, "flat": 0, "against": 0,
            "pending": True,
            "error": error,
        }

    out = dict(payload)
    out["pending"] = running
    # A refresh that failed does not invalidate the rows -- they are still a true
    # statement about when the sweep ran -- so its error travels beside them as
    # `staleError`, and the page can date the table instead of blanking it.
    #
    # But only a failure *newer* than the rows explains them; `error` describes
    # the most recent attempt and `started` the most recent success. A disk
    # seed has no attempt behind it (`last_attempt` is 0 until the first sweep
    # runs), so beside a seeded table a fresh failure says nothing about these
    # rows yet -- it arrives as `staleError` on the next refresh cycle, once a
    # sweep has actually been tried and lost to it.
    out["staleError"] = error if error and attempted > started else None
    # A seeded payload keeps the `cached`/`fetchedAt` stamps `seed_bullish` put
    # on it, which is how the page tells a disk copy from a sweep this process
    # ran; `checkedAt` is the same second either way (`started` is set from the
    # seed's stored time), so one clock dates both origins.
    out["checkedAt"] = int(started)
    return out


def bullish_loop() -> None:
    """Sweep forever, `BULL_TTL` apart. Runs on the refresh thread.

    A failed attempt leaves the previous payload alone. Fifteen-minute-old rows
    with a note saying so are more useful than an empty section, and clearing them
    would turn a transient upstream problem into a permanent-looking one.

    A successful sweep is also filed on disk, unsealed -- the sweeper never
    passes through `cached()`, so it persists by hand under `BULLISH_KEY`, and
    `seed_bullish` is what reads it back on the next start.

    The interval is a `_sleep_or_wake`, so the wait ends -- after a failure
    *or* a success -- the moment the watch sees the wire return. Waking from a
    success costs one extra sweep per reconnection, and buys the table being
    current on the reconnect rather than minutes later: exactly when a reader
    who just lost their internet might open the page. An edge that lands
    *during* the sweep counts as woken too (`since=epoch`), so every
    reconnection is followed by a sweep that saw it -- and reports done for it
    (see `note_refetch_done`) rather than sleeping past its own edge.
    """
    while True:
        epoch = _refresh_epoch
        started = time.time()
        with _bullish_lock:
            _bullish_state["running"] = True
            _bullish_state["last_attempt"] = started
        payload = None
        error = None
        try:
            payload = bullish.scan()
        except Exception as exc:  # a sweep may fail in many ways; none are fatal
            error = str(exc) or type(exc).__name__
        if payload is not None:
            diskcache.store(BULLISH_KEY, payload)
        with _bullish_lock:
            _bullish_state["running"] = False
            _bullish_state["error"] = error
            if payload is not None:
                _bullish_state["payload"] = payload
                _bullish_state["started"] = time.time()
        # A sweep that raised landed nothing: the state keeps its previous
        # payload exactly as designed, and the report says so too. (A sweep
        # cannot "succeed" off disk -- the loop calls `bullish.scan()`
        # directly, never through `cached`, so the only answer that is not
        # fresh data is the exception.)
        note_refetch_done("bullish sweep", epoch, landed=payload is not None)
        _sleep_or_wake(BULL_TTL, since=epoch)


def start_bullish_refresh() -> None:
    """Start the refresher, once. Safe to call more than once."""
    global _bullish_thread
    with _bullish_lock:
        if _bullish_thread is not None and _bullish_thread.is_alive():
            return
        # Daemon: the sweep is not worth blocking a shutdown on, and an in-flight
        # Moli is reaped by `kill_running_moli` like any other.
        _bullish_thread = threading.Thread(
            target=bullish_loop, name="bullish-refresh", daemon=True)
        _bullish_thread.start()


# -- the recently-bullish table ---------------------------------------------------
#
# One table that spans the markets: the Philippine names the sweep above already
# dated, the most-traded United States listings, the chartable coins, and the
# Philippine government bond yields -- each row carrying the day its current run
# began.
#
# It is a sweeper rather than a route for the same reason the Philippine sweep
# is: the United States leg needs a year of daily bars for each of fifty
# tickers, and those bars come from a browser (Yahoo answers plain HTTP
# clients with a 429). A reader should not pay for that, so the answer is
# produced ahead and read what landed.
#
# The Philippine rows are read from the sweep above rather than re-swept: that
# sweep takes about half a minute, and doing it twice would make this table
# fresher than the sweep it is built from -- two answers to one question, which
# is the thing this project keeps refusing to have.

# v4 keeps only the falling-yield rows, so a copy stored before that rule
# change cannot put a bearish tenor back on the table. v3 stored the displayed
# bond-price direction, v2 the yield's own.
# `:t2` -- scored by version 2 of the classifier (see CRYPTO_KEY). Every
# layout version gets the suffix, so the conversions below only ever see a
# table version 2 scored; the plain v2/v3/v4 copies on disk are version-1
# verdicts and are never read again.
# v5 scans the Ondo shelf instead of a turnover ranking -- every stock and ETF
# the shop lists plus its intelligent portfolios -- so a v4 copy holds rows for
# names the reader cannot buy and none for the portfolios. It is still read (and
# filtered onto the shelf, see `seed_recent`) so an offline start has a table,
# but a sweep under the old rule can never pass for one under this rule.
RECENT_KEY = "recent:scan:v5:t2"
LEGACY_RECENT_KEY = "recent:scan:v4:t2"
OLDER_RECENT_KEY = "recent:scan:v3:t2"
RECENT_TTL = 900  # seconds

# The span of history fetched behind the ninety-day window the walk reads. A
# year of daily bars is four windows behind the latest bar, which is what lets
# a run that reaches the start of the fetched data be reported as censored
# rather than dated to the oldest bar fetched.
RECENT_SPAN, RECENT_INTERVAL = "1y", "1d"

# How many tickers go into one browser run. The row warmer's batch size, and
# for the same reason: twenty fetches inside one page is a comfortable load,
# and more than that starts to time out the page's own budget.
RECENT_BATCH = 20

_recent_state = {
    "payload": None,
    "error": None,
    "started": 0.0,
    "last_attempt": 0.0,
    "running": False,
}
_recent_lock = threading.Lock()
_recent_thread: threading.Thread | None = None


def fetch_us_bars(tickers: list[str]) -> dict[str, tuple]:
    """A year of daily bars for each ticker, from Yahoo.

    The browser leg of the recent table. Yahoo answers plain HTTP clients
    with a 429, so the bars are fetched the way every other Yahoo answer in
    this project is fetched: through Moli, in batches, one browser run per
    batch.

    The bars are the ones the page's own chart draws for that ticker -- the
    same URL shape, the same daily interval, a year of them instead of three
    months -- so a row's verdict is the verdict the chart its click opens
    would show. Each answer is `(stamps, closes, volumes, meta)`: the meta is
    `yahoo_meta`, because the recent table's universe is the Ondo shelf's
    tickers and Yahoo holds the company name the shelf does not. A ticker that
    did not answer is left out of the answer entirely rather than answered
    with an empty series: a fetch failure is not a fact about the stock.
    """
    out: dict[str, tuple] = {}
    tickers = [t for t in tickers if t]
    for start in range(0, len(tickers), RECENT_BATCH):
        chunk = tickers[start:start + RECENT_BATCH]
        urls = {ticker: chart_key(ticker, RECENT_SPAN, RECENT_INTERVAL)
                for ticker in chunk}
        try:
            answers = moli_batch_get(list(urls.values()))
        except UpstreamError:
            # The run as a whole failed: every ticker in the chunk is an
            # outage at once, and the next chunk is still worth trying.
            continue
        for ticker, url in urls.items():
            status, body = answers.get(url, (0, ""))
            if status != 200:
                continue
            try:
                payload = json.loads(body)
            except ValueError:
                continue
            try:
                out[ticker] = tuple(yahoo_bars(payload, ticker)) + (
                    yahoo_meta(payload),)
            except LookupError:
                continue    # Yahoo's "no such instrument", a verdict
    return out


def seed_recent() -> None:
    """Hydrate the recent table's state from disk, so an offline start still has rows.

    The same contract as `seed_bullish`: a stored copy becomes the payload as
    any live sweep would, dated with the second it was actually swept, and the
    first sweep of this run replaces it wholesale.
    """
    saved = diskcache.load(RECENT_KEY)
    legacy = saved is None
    if legacy:
        saved = diskcache.load(LEGACY_RECENT_KEY)
    yield_side = saved is None
    if yield_side:
        saved = diskcache.load(OLDER_RECENT_KEY)
    if saved is None:
        return
    fetched_at, payload = saved
    if not isinstance(payload, dict) or not payload.get("rows"):
        return
    with _recent_lock:
        if _recent_state["payload"] is not None:
            return
        seeded = dict(payload)
        seeded["rows"] = [dict(row) for row in payload["rows"]]
        if yield_side:
            # v2 stored yield directions and scores; v3 onwards display the
            # implied bond-price direction.
            for row in seeded["rows"]:
                if row.get("market") != "Philippine bond":
                    continue
                row["direction"] = {"bullish": "bearish", "bearish": "bullish"}.get(
                    row.get("direction"), row.get("direction"))
                if isinstance(row.get("score"), (int, float)):
                    row["score"] = -row["score"]
        # A copy stored under v2 or v3 still holds the tenors a row was once
        # shown for whatever its verdict. A rising or flat yield is not a row
        # on this table any more, so a stored copy must not resurrect one --
        # and it must not read as a table swept under the old rule either.
        seeded["rows"] = [row for row in seeded["rows"]
                          if row.get("market") != "Philippine bond"
                          or row.get("direction") == "bullish"]
        stats = dict(seeded.get("stats") or {})
        bond_stats = stats.get("Philippine bond")
        if isinstance(bond_stats, dict) and "universe" not in bond_stats:
            # The stored note is rebuilt from these by `recent.summarize`, so
            # the leg has to say how many tenors were read, not only how many
            # rows survived a rule it was swept under.
            kept = sum(1 for row in seeded["rows"]
                       if row.get("market") == "Philippine bond")
            stats["Philippine bond"] = dict(bond_stats,
                                            universe=len(recent.BONDS),
                                            count=kept)
            seeded["stats"] = stats
        # The note is rebuilt from the rows and stats that survive the filter,
        # so a seeded table cannot describe a wider table than it draws.
        #
        # The shelf is read once, from disk (`ondolist.saved`, no network), and
        # used twice. First on the table itself: since v5 the United States
        # rows are the shelf's stocks and ETFs and the portfolios are the
        # shelf's baskets, so a copy swept before that rule (a v4 copy judged
        # the turnover ranking) must not put a name the reader cannot buy back
        # on screen. Second on the leaning list, through `actionable`. With no
        # stored shelf the rows stand -- an outage is not a listing fact, and
        # the next sweep re-decides.
        shelf = ondolist.saved()
        if shelf:
            seeded["rows"] = [
                row for row in seeded["rows"]
                if row.get("market") not in recent.ONDO_CHECKED_MARKETS
                or ondolist.carries(row.get("ticker"), shelf)
                or row.get("market") == "Ondo portfolio"]
        if legacy or yield_side:
            # The stored copy's United States rows came from a turnover
            # ranking, not the shelf. The note is rebuilt from the stats, so
            # the leg has to stop implying a universe it never had.
            us_stats = stats.get("US")
            if isinstance(us_stats, dict):
                stats["US"] = dict(us_stats, shelf=False)
                seeded["stats"] = stats
        # A series that had already stopped when this copy was swept must not
        # come back from disk either: a seed is on screen until the first sweep
        # lands, which is exactly long enough for the reader who objected to
        # ATKR to see it again after a restart. Judged against the copy's own
        # `fetchedAt`, not against now -- bars swept last week were current when
        # they were fetched (`recent.stale_gap`).
        seeded["rows"], stale_rows = recent.drop_stale(seeded["rows"], fetched_at)
        stale_lean: list[dict] = []
        if seeded.get("leaning"):
            seeded["leaning"], stale_lean = recent.drop_stale(
                seeded["leaning"], fetched_at)
        if stale_rows or stale_lean:
            # Counted, so the note says what left the table -- and merged by
            # ticker with whatever the stored stats already carry, because a
            # copy swept under this rule has already named them.
            us_stats = stats.setdefault("US", {})
            if isinstance(us_stats, dict):
                named = {entry.get("ticker")
                         for entry in (us_stats.get("stale") or [])}
                us_stats["stale"] = list(us_stats.get("stale") or []) + [
                    entry for entry in (stale_rows + stale_lean)
                    if entry.get("ticker") not in named]
                seeded["stats"] = stats
        if seeded.get("leaning"):
            seeded["leaning"] = recent.actionable(seeded["leaning"], shelf)
            # The page says which shelf the list was filtered against, and
            # when -- a seeded copy was swept at some earlier moment, so it
            # must not claim that moment as the shelf's age.
            seeded["ondoShelf"] = None if shelf is None else {
                "count": shelf.get("count"),
                "fetchedAt": int(shelf.get("fetchedAt") or 0),
                "cached": bool(shelf.get("cached")),
            }
        seeded["note"] = recent.summarize(seeded)
        seeded["cached"] = True
        seeded["fetchedAt"] = int(fetched_at)
        _recent_state["payload"] = seeded
        _recent_state["started"] = float(fetched_at)


def recent_state() -> dict:
    """The last recent-assets sweep, or a stand-in saying one has not landed yet.

    Never blocks: it takes the lock, copies what is there and lets go. The
    payload is replaced wholesale by the sweeper rather than mutated, so a
    reader cannot see it change while it renders.
    """
    with _recent_lock:
        payload = _recent_state["payload"]
        error = _recent_state["error"]
        started = _recent_state["started"]
        attempted = max(_recent_state["last_attempt"], started)
        running = _recent_state["running"]

    if payload is None:
        return {
            "label": "Recently bullish assets",
            "rows": [],
            "leaning": [],
            "stats": {},
            "errors": {},
            "pending": True,
            "error": error,
        }

    out = dict(payload)
    out["pending"] = running
    # A failed refresh does not invalidate the rows -- they are still a true
    # statement about when the sweep ran -- so its error travels beside them.
    out["staleError"] = error if error and attempted > started else None
    out["checkedAt"] = int(started)
    return out


def recent_loop() -> None:
    """Sweep forever, `RECENT_TTL` apart. Runs on the refresh thread.

    A failed attempt leaves the previous payload alone, for the reason the
    Philippine sweep gives: rows that are fifteen minutes old with a note
    saying so are more useful than an empty section.
    """
    while True:
        epoch = _refresh_epoch
        started = time.time()
        with _recent_lock:
            _recent_state["running"] = True
            _recent_state["last_attempt"] = started
        payload = None
        error = None
        try:
            # The Philippine rows are read from the sweep the server keeps
            # warm, not re-swept: see the note above this block.
            ph_state = bullish_state()
            payload = recent.scan(
                ph_sweep_rows=ph_state.get("rows") or [],
                fetch_us_bars=fetch_us_bars,
                ph_sweep_leaning=ph_state.get("leaning") or [],
                ondo_shelf=ondolist.shelf(),
                # What the Philippine sweep looked at, so the note can say
                # "263 scanned (249 common shares, 11 preferred shares, ...)"
                # instead of only counting the rows that turned bullish.
                ph_sweep_stats={"universe": ph_state.get("universe"),
                                "kinds": ph_state.get("kinds") or {},
                                "missing": ph_state.get("missing") or []})
            payload["checkedAt"] = int(time.time())
            # The one-line summary of the sweep, drawn by the same module that
            # knows what was judged -- so the note and the rows cannot disagree
            # about what was scanned.
            payload["note"] = recent.summarize(payload)
        except Exception as exc:  # a sweep may fail in many ways; none are fatal
            error = str(exc) or type(exc).__name__
        if payload is not None:
            diskcache.store(RECENT_KEY, payload)
        with _recent_lock:
            _recent_state["running"] = False
            _recent_state["error"] = error
            if payload is not None:
                _recent_state["payload"] = payload
                _recent_state["started"] = time.time()
        note_refetch_done("recent sweep", epoch, landed=payload is not None)
        _sleep_or_wake(RECENT_TTL, since=epoch)


def start_recent_refresh() -> None:
    """Start the refresher, once. Safe to call more than once."""
    global _recent_thread
    with _recent_lock:
        if _recent_thread is not None and _recent_thread.is_alive():
            return
        _recent_thread = threading.Thread(
            target=recent_loop, name="recent-refresh", daemon=True)
        _recent_thread.start()


# -- prewarming what the first paint always wants --------------------------------
#
# The page loads BTC-USD (a Yahoo chart), the two market tables, and the bullish
# stand-in -- and the first reader to arrive after `python3 server.py` would pay
# every cold cost at once: two browser round trips for the chart (the chart and
# its watchlist row used to duplicate the work before `cached` learned
# single-flight, and one remains), four scanner queries for the tables, and the
# CoinGecko/Binance identity lookups behind the crypto reroute test.
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

WARM_CHART = ("BTC-USD", WARM_SPAN, WARM_INTERVAL)


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
        (f"chart:{symbol}", lambda: chart_data(symbol, span, interval)),
        (LEADERS_KEY, tables_payload),
        (CRYPTO_KEY, cryptobull_payload),
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
_row_lock = threading.Lock()
_row_thread: threading.Thread | None = None


def row_fresh(key: str, now: float) -> bool:
    """Whether a listed symbol's chart needs no fetch right now.

    The first look at a key per epoch reads its disk file and adopts that
    copy's date as the stamp -- so a server restarted twenty minutes after
    warming ~100 charts spends zero browser runs rediscovering its own cache,
    and a key whose copy is *stale* still gets adopted once: it is due, the
    warmer fetches it, and the fetch replaces the stamp. After the first look
    the stamp answers alone and disk is never consulted again for that epoch,
    so an idle poll over a full table costs ~100 dictionary lookups, not ~100
    file parses.

    A reconnect advances `_refresh_epoch` and that sentence stops being true:
    every stamp belongs to an older epoch, so each key gets its disk re-look
    once more. That is exactly the discrimination the outage blurs. A row whose
    chart *landed* during the outage has a fresh disk copy, re-adopts it, and
    stays not-due -- no browser run. A row whose chart *failed* was stamped
    then but wrote nothing to disk, so the re-look finds an absent-or-stale
    copy and makes it due again at once. Failed attempts forget; successes
    keep -- and an outage keeps its stamp too (see the outcome comment above
    `_store_chart`: an attempt the wire refused still happened, so the row is
    not re-queued inside the same epoch; the reconnect epoch is what un-freezes
    it). Without the epoch, a one-minute outage would freeze every row it
    touched for a full `ROW_STALE_AFTER`.
    """
    stamp = _warm_due.get(key)
    if stamp is None or stamp[0] < _refresh_epoch:
        saved = diskcache.load(key)
        at = saved[0] if saved is not None else -1.0
        _warm_due[key] = (_refresh_epoch, at)
    else:
        at = stamp[1]
    return 0 <= at and now - at < ROW_STALE_AFTER


def due_rows(tables: dict | None, bull: dict | None, coins: dict | None,
             watch: list[str] | None, now: float, recent: dict | None = None):
    """The listed symbols whose chart is not fresh, in queue order.

    A ticker that joins a leaderboard between passes has no attempt stamp and
    no disk copy -- it matches neither clock, so it is due the moment it is
    listed. `tables` arrives only while the live sources answered (see
    `warm_rows_loop`); `bull` only once a sweep has landed rows; `coins` the
    same way for the crypto table, whose rows are `BASE-USD` spellings the
    Yahoo batch leg already knows how to reroute to Binance; `recent` is the
    combined recently-bullish table, gated the same way, so a row it lists
    (a US ticker, a coin, a Philippine stock, a bond yield) is as retrievable
    offline as a row on any other table; `watch` is the
    declared union, gated on the same liveness rule, and goes *first* -- these
    are the symbols a human chose to keep, so they lead the queue rather than
    waiting behind the ~90-symbol PSE tail. Two tables listing the same
    symbol -- `PSE:SMM` is a leaderboard regular and a bullish regular -- warm
    it once, on its first spelling.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(symbol):
        if not symbol or not isinstance(symbol, str):
            return
        norm = symbol.strip().upper()
        if not norm or norm in seen:
            return
        seen.add(norm)
        key = chart_key(symbol, WARM_SPAN, WARM_INTERVAL)
        if not row_fresh(key, now):
            out.append((key, symbol))

    if watch is not None:
        for symbol in watch:
            add(symbol)
    if tables is not None:
        for card in tables.get("markets") or []:
            if not isinstance(card, dict):
                continue
            for row in card.get("rows") or []:
                if isinstance(row, dict):
                    add(row.get("chartSymbol"))
    if bull is not None:
        for row in bull.get("rows") or []:
            if isinstance(row, dict):
                add(row.get("chartSymbol"))
    if coins is not None:
        for row in coins.get("rows") or []:
            if isinstance(row, dict):
                add(row.get("chartSymbol"))
    if recent is not None:
        for row in recent.get("rows") or []:
            if isinstance(row, dict):
                add(row.get("chartSymbol"))
    return out


# What one row's warm attempt actually achieved, which the queue reads two
# ways: `WARM_LANDED` continues the pass and re-stamps the row fresh -- the
# batch really did write its disk copy just now; `WARM_OUTAGE` stops the pass
# and keeps the row's pre-departure stamp -- the attempt happened, produced
# nothing, and per `row_fresh` the next epoch's disk re-look, not a retry
# inside this one, is what recovers it. (The batched warmer has no rescue
# outcome: it never reads its own disk copy mid-flight, so there is no
# "handed its own old copy back" to refuse to stamp. A row whose wire died
# while a stale copy sat behind it looks exactly like any other outage here,
# and the copy keeps serving the fallback while the stamp keeps the warmer
# off it until the epoch moves.)
WARM_LANDED, WARM_OUTAGE = "landed", "outage"


def _store_chart(key: str, payload: dict) -> None:
    """Write a warm result straight to the disk copy a route would have written.

    The batched warmer does not go through `cached()` -- a batch produces many
    answers and `cached` produces one -- so it writes what `cached` would have:
    the plain payload under the same `chart_key` spelling, unstamped, exactly
    the shape `_stamp_copy` rescues and `chart_data` serves on the next miss.
    The memory memo is deliberately *not* written: `cached`'s 60-second entry
    belongs to a live fetch a route or click made, and a warmed copy should
    never make a route's next call skip the wire thinking the answer is that
    fresh -- the disk copy is the fallback's, the memo is the route's.

    `diskcache.store` is atomic temp-plus-rename, so a reader mid-rescue sees
    either the old copy or the new one, never a torn file.
    """
    diskcache.store(key, payload)


def _warm_batch_yahoo(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """Warm a chunk of non-PSE rows through one batched Yahoo run.

    `pairs` is `[(chart_key, symbol), ...]` in queue order. Returns
    `{symbol: outcome}` -- one outcome per row, because the batch's fetches all
    complete together (`Promise.all` inside the one page) and each answer
    stands on its own: 2xx with JSON is slimmed and stored (`WARM_LANDED`);
    a 404 carrying `chart.error` is Yahoo's "no such instrument", the same
    `LookupError` verdict the single path raises -- and, like every verdict
    here, a *landed* answer for a row known to exist; status 0 (the page's fetch
    rejected), a non-JSON body, or a 5xx is transport (`WARM_OUTAGE`) for that
    URL alone. The loop, not this function, decides that one outage stops the
    pass -- the same sentence the serial warmer spoke, minus the browser runs
    it took to say it.

    Crypto rows keep their full route semantics: `_reroute_crypto` applies the
    same `yahoo_is_wrong` test `chart_data` applies, at its cheapest moment --
    one cached Binance close per coin, after the batch -- so a warm copy can
    never be Yahoo's mis-resolved answer while the route would have served
    Binance's. A reroute costs one live Binance call only for the rare wrong
    row; a right one never asks Binance at all.
    """
    try:
        answers = moli_batch_get([key for key, _symbol in pairs])
    except UpstreamError:
        # The run as a whole failed -- Moli down, envelope lost. Every row in
        # the chunk is an outage at once, the same sentence `moli_get` would
        # have spoken one URL at a time.
        return {symbol: WARM_OUTAGE for _key, symbol in pairs}

    out: dict[str, str] = {}
    for key, symbol in pairs:
        status, body = answers.get(key, (0, ""))
        try:
            payload = json.loads(body)
        except ValueError:
            out[symbol] = WARM_OUTAGE
            continue
        if status < 200 or (status >= 300 and status != 404):
            # Anything that is not a 2xx and not 404 is the wire being
            # difficult, not an answer about the symbol -- status 0 (the
            # page's fetch rejected), a 3xx the page did not follow, and
            # above all a 429, the reason the plain clients are banned.
            out[symbol] = WARM_OUTAGE
            continue
        if status == 404:
            # Yahoo's own "no" -- a body carrying `chart.error`, exactly the
            # shape `slim_chart` reads a verdict from.
            try:
                slim_chart(payload, symbol, WARM_SPAN, WARM_INTERVAL)
            except LookupError:
                # A coin Yahoo has no chart for may still be chartable from
                # Binance -- the same substitution `chart_data`'s producer
                # makes when Yahoo errors and the coin resolves.
                coin = crypto.try_chart(symbol, WARM_SPAN, WARM_INTERVAL)
                if coin is not None:
                    _store_chart(key, coin)
                out[symbol] = WARM_LANDED
            else:
                _store_chart(key, slim_chart(payload, symbol, WARM_SPAN,
                                              WARM_INTERVAL))
                out[symbol] = WARM_LANDED
            continue
        try:
            chart = slim_chart(payload, symbol, WARM_SPAN, WARM_INTERVAL)
        except LookupError:
            # A 200 whose `chart.result` is empty: an answer about the
            # symbol, stamped like one.
            out[symbol] = WARM_LANDED
            continue
        # A cross Yahoo quotes but has no series for arrives here as a
        # one-bar snapshot -- storing it as-is would overwrite the composed
        # series `chart_data` persists under this key with a single point,
        # and the next offline click would draw one dot. Compose here too,
        # from the legs' live answers, so the disk copy stays a chart. A
        # failure (a leg's verdict, a leg's outage mid-warm) keeps the
        # snapshot: the route's own copy stands until a warmer succeeds.
        if (FX_CROSS_RE.fullmatch(symbol.upper())
                and len(chart.get("points") or []) < 2):
            try:
                chart = fx_cross_chart(symbol.upper(), WARM_SPAN,
                                       WARM_INTERVAL, chart)
            except Exception:
                pass
        # The warm-side half of the ECB route (`chart_data`'s produce): a
        # no-dollar-leg cross gets the ECB fix series under the same key, so
        # the disk copy a later outage rescues is the honest one, not the
        # fabricated Sunday-dip series. None (an outage, or a pair outside the
        # ECB set) keeps Yahoo's slimmed chart -- the same "Yahoo's answer
        # stands" contract the route speaks.
        if FX_CROSS_RE.fullmatch(symbol.upper()):
            pair = symbol.upper()[:-2]
            if "USD" not in (pair[:3], pair[3:]):
                substituted = ecb_route(symbol, WARM_SPAN, WARM_INTERVAL, chart)
                if substituted is not None:
                    chart = substituted
        coin = _reroute_crypto(symbol, chart)
        _store_chart(key, coin or chart)
        out[symbol] = WARM_LANDED
    return out


def _reroute_crypto(symbol: str, chart: dict) -> dict | None:
    """The Binance payload when Yahoo charted the wrong instrument, else None.

    The warm-side half of `chart_data`'s reroute: same test (`yahoo_is_wrong`,
    which refuses to fire for anything but a chartable coin), same
    substitution. Runs after the batch, so the cost is one cached Binance
    close per crypto row rather than a second browser run, and a row that
    passes the test keeps Yahoo's answer without ever asking Binance.
    """
    try:
        if not yahoo_is_wrong(symbol, chart):
            return None
    except Exception:
        return None  # a probe failure is not a verdict; keep Yahoo's answer
    try:
        return crypto.try_chart(symbol, WARM_SPAN, WARM_INTERVAL)
    except Exception:
        return None


def _warm_batch_pse(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """Warm the queue's PSE rows through `pse.charts_many`'s shared sockets.

    `pairs` is `[(chart_key, symbol), ...]` in queue order. One call covers
    the whole PSE leg: `charts_many` chunks forty sessions per socket,
    retries a short chunk, and post-processes each series exactly as the
    single-symbol `chart()` does, so a ~90-row pass costs three-or-fewer
    browser runs instead of ninety.

    The mapping back to outcomes is the module's own contract: a payload is
    `WARM_LANDED` and stored under its `chart_key` spelling; `PseNotFound` is
    a verdict about a symbol the queue knows exists -- its *chart* is
    unchartable -- so it lands like Yahoo's 404 does; `PseError` is transport
    (the socket short, the chunk retried to exhaustion) and is an outage for
    that row. Results are keyed by `charts_many`'s *canonical* spelling
    (`PSE:TEL`), while the queue may carry any spelling that canonicalises to
    it (`tel.ps`), so each pair reads its result through `canonical_symbol`.

    A call-level failure (`charts_many` raising outright -- Moli dead before
    the first socket) is an outage for every row in the leg.
    """
    try:
        results = pse.charts_many([symbol for _key, symbol in pairs],
                                  WARM_SPAN, WARM_INTERVAL)
    except Exception:
        return {symbol: WARM_OUTAGE for _key, symbol in pairs}

    out: dict[str, str] = {}
    for key, symbol in pairs:
        result = results.get(pse.canonical_symbol(symbol))
        if result is None:
            # Neither payload nor exception: only possible for a spelling
            # that canonicalised oddly. Transport, not silence.
            out[symbol] = WARM_OUTAGE
        elif isinstance(result, pse.PseNotFound):
            out[symbol] = WARM_LANDED
        elif isinstance(result, Exception):
            out[symbol] = WARM_OUTAGE
        else:
            _store_chart(key, result)
            out[symbol] = WARM_LANDED
    return out


def _warm_batch_bonds(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """Warm the queue's Philippine bond yields through one TradingView socket.

    `pairs` is `[(chart_key, symbol), ...]`. The three tenors are one curve, so
    `tv.charts_many` reads them from one batched socket run -- the same path the
    PSE leg takes, one market over -- and this maps its answer to the warmer's
    two outcomes, exactly as `_warm_batch_pse` does: a payload is stored under
    its `chart_key` and lands; `TvNotFound` (a spelling that is not one of the
    three tenors) is a verdict about the symbol and lands too; `TvError` -- the
    socket short, no bars -- is transport, an outage for that row.

    The bars behind the payload are the same disk copy the recent table's bond
    legs are judged on (`tv.cached_bars`), so a warm chart and any row that
    tenor grows cannot drift to different bars; only the finished chart is
    stored here.
    """
    try:
        results = tv.charts_many([symbol for _key, symbol in pairs],
                                 WARM_SPAN, WARM_INTERVAL)
    except Exception:
        return {symbol: WARM_OUTAGE for _key, symbol in pairs}

    out: dict[str, str] = {}
    for key, symbol in pairs:
        result = results.get(symbol)
        if isinstance(result, tv.TvNotFound):
            out[symbol] = WARM_LANDED      # a verdict about the symbol
        elif isinstance(result, dict):
            _store_chart(key, result)
            out[symbol] = WARM_LANDED
        else:
            # Nothing came back for this spelling, or the socket refused: not
            # an answer about the instrument.
            out[symbol] = WARM_OUTAGE
    return out


def _warm_batch_funds(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """Warm the queue's Philippine funds through their publishers' documents.

    `pairs` is `[(chart_key, symbol), ...]`. `phfunds.charts_many` reads the
    missing series from whichever registry publishes each fund and builds the
    chart from the same bars the recent table's row was judged on
    (`phfunds.series`), so a warm chart and the row it belongs to cannot drift
    to different bars; only the finished chart is stored here.

    This leg needs no browser: the three fund registers answer plain HTTPS, so
    unlike the PSE, bond and Yahoo legs a chunk costs a handful of requests
    rather than a page. The outcomes map the way the other legs' do -- a payload
    is stored and lands, `FundNotFound` (a code that is not a fund) is a verdict
    about the symbol and lands too, and `FundError` -- the publisher did not
    answer, no usable copy -- is transport, an outage for that row.
    """
    try:
        results = phfunds.charts_many([symbol for _key, symbol in pairs],
                                      WARM_SPAN, WARM_INTERVAL)
    except Exception:
        return {symbol: WARM_OUTAGE for _key, symbol in pairs}

    out: dict[str, str] = {}
    for key, symbol in pairs:
        result = results.get(symbol)
        if isinstance(result, phfunds.FundNotFound):
            out[symbol] = WARM_LANDED      # a verdict about the symbol
        elif isinstance(result, dict):
            _store_chart(key, result)
            out[symbol] = WARM_LANDED
        else:
            # The register did not answer and no copy was worth showing: not an
            # answer about the fund.
            out[symbol] = WARM_OUTAGE
    return out


def _warm_batch_tokens(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """Warm the queue's Ondo tokens from the contract price, one HTTP call each.

    `pairs` is `[(chart_key, symbol), ...]`. The leg exists for the reason the
    bond and fund legs do: sent down the Yahoo leg an `ONDO:` symbol would earn
    a guaranteed 404 per pass, because Yahoo has no spelling for the token at
    all. The outcomes map the way the other legs' do -- a payload is stored and
    lands, `OndoNotFound` (a token this module does not know) is a verdict about
    the symbol and lands too, and `OndoError` -- the price could not be read --
    is transport, an outage for that row.
    """
    try:
        results = ondo.charts_many([symbol for _key, symbol in pairs],
                                   WARM_SPAN, WARM_INTERVAL)
    except Exception:
        return {symbol: WARM_OUTAGE for _key, symbol in pairs}

    out: dict[str, str] = {}
    for key, symbol in pairs:
        result = results.get(symbol)
        if isinstance(result, ondo.OndoNotFound):
            out[symbol] = WARM_LANDED      # a verdict about the symbol
        elif isinstance(result, dict):
            _store_chart(key, result)
            out[symbol] = WARM_LANDED
        else:
            out[symbol] = WARM_OUTAGE
    return out


def warm_rows_loop() -> None:
    """Keep every table-listed chart retrievable offline. Runs on its thread.

    Reads the tables, the sweep and the crypto table through the same paths
    the routes read, so a refresh seen by a browser is the same one this
    thread sees, and every pass -- not every click -- decides what is due.

    Both payloads gate on the live answer, not just the disk one: an outage
    payload's rows are already listed and their charts already on disk, and
    launching a browser per row to rediscover the outage is exactly what the
    `cached` stamp says not to do. A fetch that *raises* -- live source gone
    and no usable copy -- stops the pass outright; the rest of the queue is
    one outage wearing ninety rows, and each of them has been tried within
    the quarter-hour or will be when something answers again.

    The queue is drained in batches, not one row at a browser run. That is
    the change that took a pass from ~215 seconds to under twenty: ~100 rows
    each paid a full Moli launch (~1-3s) plus `WARM_PACING`, so most of a
    pass was the price of Chrome, not of data. Now the rows split by
    upstream -- PSE rows through `pse.charts_many`'s shared sockets,
    everything else through `moli_batch_get`'s one page -- and a pass costs a
    handful of browser runs total. Watch order survives the batching: the
    queue is built watchlist-first and chunked in order, so the head of the
    first chunk is what a reader chose, not what a leaderboard happened to
    list.

    The stamps tell the same "attempted" story the serial loop told, but per
    *chunk* rather than per queue: each chunk's stamps go down immediately
    before its batch departs, so a pass killed between batches leaves every
    row it never sent unstamped and due -- and an outage inside a chunk keeps
    that chunk's stamps (the attempt happened, produced nothing) while the
    rows behind the break, never sent, stay unstamped and re-queue after the
    backoff. The batched path has no rescue outcome -- it never reads its own
    disk copy mid-flight, so there is no stale re-serve to refuse to stamp;
    that distinction belonged to the single-row path and does not exist here
    (see the outcome comment above `_store_chart`).

    The two outage sleeps are `_sleep_or_wake`, so "when something answers
    again" is the moment the watch says it does, not the moment the backoff or
    the idle poll happens to run out; and the epoch the watch bumps makes the
    woken pass re-consult disk, so the rows that failed come back into the
    queue and the rows that landed stay out of it. A queue pass stamps its
    attempts with *its own* epoch, so an edge that lands mid-pass marks them as
    older-epoch too: the next pass re-looks them, and the rows the edge proved
    untried re-queue at once -- the same rule that keeps `note_refetch_done`
    honest, which the "row charts" part of every report is. That mark now
    carries the pass's verdict -- landed if the queue was worked to fresh
    copies, not landed if it broke on an outage -- so the closing console line
    cannot report a refill the wire refused to make.
    """
    time.sleep(10)  # let the first paint's own fetches have the browser first
    while True:
        epoch = _refresh_epoch
        try:
            tables = tables_payload()
        except Exception as exc:  # not even a disk copy: nothing to list
            sys.stderr.write(f"  warm rows: tables unreadable ({exc})\n")
            tables = None
        bull = bullish_state()
        try:
            coins = cryptobull_payload()
        except Exception as exc:  # not even a disk copy: nothing to list
            sys.stderr.write(f"  warm rows: crypto table unreadable ({exc})\n")
            coins = None
        rec = recent_state()
        live_tables = tables if tables is not None and not tables.get("cached") else None
        live_bull = (bull if bull.get("rows") and not bull.get("cached")
                     else None)
        live_coins = (coins if coins.get("rows") and not coins.get("cached")
                      else None)
        # The combined recently-bullish table is a fifth source, gated the same
        # way: a row it lists is as retrievable offline as a row on any other
        # table, so its US tickers and coins warm alongside the rest.
        live_recent = (rec if rec.get("rows") and not rec.get("cached")
                       else None)
        # The fourth queue source is the reader's own list. Gated like the other
        # three -- through the probe, not through a tables fetch -- because an
        # offline machine costs nothing to ask "is BTC-USD fresh", but launching
        # a browser to answer it is exactly what the outage rules are for.
        live_watch = union_watchlist() if (_watch_online or _watch_online is None) else None
        queue = due_rows(live_tables, live_bull, live_coins, live_watch,
                         time.time(), live_recent)
        if not queue:
            # Nothing due means every known row's disk copy re-adopted as
            # fresh -- which is the part landing, not merely running. (A pass
            # with nothing *known* to warm -- an undeclared union and no live
            # tables -- reports the same way; the edge's own note is what
            # flags that case, because no mark here can distinguish it.)
            note_refetch_done("row charts", epoch, landed=True)
            _sleep_or_wake(WARM_IDLE_POLL, since=epoch)
            continue
        # Split the queue by upstream, preserving order within each side.
        # Both legs take (key, symbol) pairs -- `charts_many` canonicalises
        # spellings and dedupes internally, so it gets the raw symbols and
        # maps results back through `canonical_symbol`. The legs run in this
        # order -- the PSE socket first, the bond socket and the Yahoo page
        # after -- because a socket chunk has the longer fixed cost and the
        # Yahoo leg is the one crypto rows pay a second call from. The bonds
        # are separated from the PSE rows rather than merged with them because
        # their bars come from `tv.py`'s own cache and their chart is built by
        # `tv.charts_many`; sent down the Yahoo leg they would be a guaranteed
        # 404 per pass, which is what made them worth their own leg.
        bond_queue = [(key, symbol) for key, symbol in queue
                      if tv.is_bond_symbol(symbol)]
        fund_queue = [(key, symbol) for key, symbol in queue
                      if not tv.is_bond_symbol(symbol)
                      and phfunds.is_fund_symbol(symbol)]
        token_queue = [(key, symbol) for key, symbol in queue
                       if not tv.is_bond_symbol(symbol)
                       and not phfunds.is_fund_symbol(symbol)
                       and ondo.is_ondo_symbol(symbol)]
        pse_queue = [(key, symbol) for key, symbol in queue
                     if not tv.is_bond_symbol(symbol)
                     and not phfunds.is_fund_symbol(symbol)
                     and not ondo.is_ondo_symbol(symbol)
                     and pse.is_pse_symbol(symbol)]
        yahoo_queue = [(key, symbol) for key, symbol in queue
                       if not tv.is_bond_symbol(symbol)
                       and not phfunds.is_fund_symbol(symbol)
                       and not ondo.is_ondo_symbol(symbol)
                       and not pse.is_pse_symbol(symbol)]
        backoff = False
        for pairs, batch, size in (
                (pse_queue, _warm_batch_pse, WARM_PSE_CHUNK),
                (bond_queue, _warm_batch_bonds, BOND_WARM_CHUNK),
                (fund_queue, _warm_batch_funds, FUND_WARM_CHUNK),
                (token_queue, _warm_batch_tokens, FUND_WARM_CHUNK),
                (yahoo_queue, _warm_batch_yahoo, WARM_BATCH)):
            for start in range(0, len(pairs), size):
                chunk = pairs[start:start + size]
                # Stamps first, exactly as the serial loop stamped before each
                # fetch: this chunk reads "attempted at this epoch" from the
                # moment its batch departs. If the wire kills the pass here,
                # these are the rows the backoff covers; the rows behind the
                # break keep no stamp and re-queue after it.
                for key, _symbol in chunk:
                    _warm_due[key] = (epoch, time.time())
                outcomes = batch(chunk)
                if WARM_OUTAGE in outcomes.values():
                    backoff = True
                    break
                time.sleep(WARM_PACING)
            if backoff:
                break
        # The part closes here, at the end of the pass: "row charts landed"
        # means the post-edge queue was *worked to fresh disk copies*, not
        # merely attempted. A pass that ran to the end without breaking landed
        # every row it had; one cut short -- by an outage -- is an honest
        # "not landed", naming the part in the closing line as stale, and a
        # newer edge opens a newer report for the rows still waiting on the
        # wire.
        note_refetch_done("row charts", epoch, landed=not backoff)
        if backoff:
            _sleep_or_wake(WARM_BACKOFF, since=epoch)


def start_row_warming() -> None:
    """Start the row warmer, once. Safe to call more than once."""
    global _row_thread
    with _row_lock:
        if _row_thread is not None and _row_thread.is_alive():
            return
        # Daemon like the sweeper: an in-flight Moli is reaped by
        # `kill_running_moli` at shutdown, and a warm-up is not worth holding
        # the process open for.
        _row_thread = threading.Thread(
            target=warm_rows_loop, name="warm-rows", daemon=True)
        _row_thread.start()


def exchange_day(meta: dict, stamp) -> dt.date | None:
    """The calendar day a stamp falls on in the exchange's own timezone.

    Every guard that has to tell "this price belongs to this bar" from "this
    price belongs to a neighbouring session" asks this one question, so it is
    answered here: a bar and a print on different days are different sessions,
    whatever their distance in hours. None when the zone name is unusable (Yahoo
    does not always send a usable one) or the stamp is out of the platform's
    range, so a caller refuses rather than guessing a day.
    """
    try:
        zone = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
        return dt.datetime.fromtimestamp(stamp, zone).date()
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None


def same_exchange_day(meta: dict, a, b) -> bool:
    """True when two stamps land on one calendar day in the exchange's zone."""
    left = exchange_day(meta, a)
    return left is not None and left == exchange_day(meta, b)


def full_day_close(meta: dict, last_stamp: int) -> float | None:
    """The newest session's price *including* pre- and after-hours trading.

    Yahoo's daily bars are regular-session closes: Friday's bar ends at the
    16:00 bell, and everything traded after it is invisible in that bar. The
    chart wants the most recent price for the session still in progress, so the
    newest bar is drawn at `meta.fulldayPrice` -- the same session's price with
    the extended sessions folded in -- while every older bar keeps its official
    close. Once a newer session starts, yesterday's bar falls back to being an
    ordinary bar and the close returns on its own: the patch only ever touches
    the last one.

    Three guards, each of which returns None so the caller draws the plain
    close:

    * `hasPrePostMarketData` false -- the instrument has no extended session to
      fold in. That covers crypto, FX, futures, mutual funds and every PSE name,
      and for those `fulldayPrice` is simply the regular price.
    * no usable `fulldayPrice` in the payload.
    * the extended print belongs to a *newer* session than the last bar. This is
      the pre-market case: on a Monday morning the daily series can still end at
      Friday while `fulldayPrice` already carries Monday's pre-market print, and
      dating Friday's bar with Monday's price would be a lie. The two are
      compared as calendar dates in the exchange's own timezone, taken from the
      payload's `currentTradingPeriod`.
    """
    if not meta.get("hasPrePostMarketData"):
        return None
    price = meta.get("fulldayPrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    session_start = regular.get("start")
    if session_start is None:
        return None
    if not same_exchange_day(meta, last_stamp, session_start):
        return None
    return float(price)


def live_print(meta: dict, last_stamp: int) -> dict | None:
    """The price of the session trading now, when no *bar* exists for it yet.

    `full_day_close` folds an extended-hours print into the newest bar, and
    that only works while that bar is the session trading now. Between one
    session's close and the next one's first daily bar -- 04:00 to 09:30 New
    York, and again from the 16:00 bell until Yahoo gives up the after-hours
    print -- the newest bar is an *older* session's, while `fulldayPrice`
    already carries a print belonging to a newer one. Dating that price to the
    old bar would be a lie (that is `full_day_close`'s third guard), so the
    chart used to stop at the old official close and stay there while the
    market moved. Measured 2026-11-03 at 04:15 New York: AAPL had printed
    322.13 in pre-market against a Monday close of 338.32, and the page showed
    only 338.32 labelled "close".

    This is that print, kept out of the bars so the chart can draw it as the
    *newest* point under the current session's own date instead of rewriting an
    older bar. The stamp is the session's regular open, which is exactly where
    Yahoo will put the day's real bar, so the synthetic point is replaced by
    the real one when it arrives rather than sitting beside it.

    None when there is nothing honest to add: no extended session on the
    instrument, no usable `fulldayPrice`, no session schedule, the newest bar
    already belongs to this session (then `full_day_close` is the one that
    folds), or the newest bar is more than `LIVE_BAR_GAP_DAYS` old -- a halt or
    a dead listing is not a session that is trading.
    """
    if not meta.get("hasPrePostMarketData"):
        return None
    price = meta.get("fulldayPrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    session_start = usable_stamp(regular.get("start"))
    if session_start is None:
        return None
    if same_exchange_day(meta, last_stamp, session_start):
        return None
    if session_start - last_stamp > LIVE_BAR_GAP_DAYS * 86400:
        return None
    return {"t": int(session_start), "c": round(float(price), 6)}


def session_close(meta: dict, quote: dict, index: int, stamp: int) -> float | None:
    """The newest session's price when Yahoo left that bar's `close` null.

    Yahoo sometimes answers a *completed* session's daily bar with open, high,
    low and volume filled in and `close` left null. Verified 2026-10-31
    (Saturday, after the Friday 2026-10-30 close): every US symbol tried
    answered that way -- SPY, AAPL, MSFT, KO and XOM all ended at a Friday bar
    whose open/high/low/volume were present and whose close was null -- while
    `meta.regularMarketPrice` carried the close (KO 94.08) stamped at
    2026-10-30T20:00:02Z. The prior sessions were untouched.

    Dropping such a bar as a gap (which is right for a holiday row, where the
    whole row is null) amputates the newest session instead: the chart ended a
    day early, the badge scored 64 bars ending 10-29, and every US table row
    was one session behind -- KO read **neutral 0.2183** where the same
    classifier on the same window including Friday reads **bullish 0.2930**.

    So the newest bar's close is filled from the payload's own headline price,
    under four guards that each refuse rather than invent one:

    * a usable positive `regularMarketPrice`;
    * a usable `regularMarketTime`, whose *calendar day* in the exchange's own
      timezone must equal the bar's. That is what keeps a Monday pre-market
      print from being dated to Friday's bar, the same mistake `full_day_close`
      guards against from the other side;
    * a bar that looks like a session really happened -- volume, or a high/low,
      is present. A stamped all-null holiday row fills nothing. The one
      exception is a mutual fund (`instrumentType` MUTUALFUND): its "bar" is a
      NAV the manager strikes and publishes as a price, so Yahoo can carry the
      day's NAV in `regularMarketPrice` for hours before the row itself is
      filled in (VFIAX on 2026-10-31: an all-null 10-30 row, `regularMarketPrice`
      699.87 stamped 2026-10-31T00:08Z = 10-30 20:08 in New York). The day
      guard above still has to pass, so a weekend or holiday row cannot borrow
      the previous NAV;
    * when both high and low are usable, the price must sit inside them, so a
      stale or unrelated headline number cannot be dressed as a close.
    """
    price = meta.get("regularMarketPrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    observed = meta.get("regularMarketTime")
    if not isinstance(observed, (int, float)) or isinstance(observed, bool) or observed <= 0:
        return None
    if not same_exchange_day(meta, stamp, observed):
        return None

    def number(values):
        value = values[index] if index < len(values) else None
        return (float(value) if isinstance(value, (int, float))
                and not isinstance(value, bool) else None)

    volume = number(quote.get("volume") or [])
    low, high = number(quote.get("low") or []), number(quote.get("high") or [])
    fund = (meta.get("instrumentType") or "").upper() == "MUTUALFUND"
    if not (volume and volume > 0) and not (low and high) and not fund:
        return None
    if low and high and not (low <= price <= high):
        return None
    return float(price)


def yahoo_meta(payload: dict) -> dict:
    """The three things the recent table needs about a symbol, from its meta.

    A name to print under the ticker, the instrument's kind in the words the
    page already uses (`markets.KINDS`), and its currency. The table asks
    Yahoo rather than a scanner because since 2026-11-07 its universe is the
    Ondo shelf, which names tokens and not companies: `nvdaon` says nothing
    about NVIDIA, and the chart's own payload does.

    Anything missing falls through as an empty string or `USD` rather than a
    guess, and a caller keeps its own fallback first.
    """
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    meta = result.get("meta") or {}
    instrument = str(meta.get("instrumentType") or "").upper()
    return {
        "name": meta.get("longName") or meta.get("shortName") or "",
        "kind": {
            "EQUITY": "Common stock",
            "ETF": "ETF",
            "MUTUALFUND": "Mutual fund",
            "INDEX": "Index",
            "CRYPTOCURRENCY": "Crypto",
            "CURRENCY": "Currency",
            "FUTURE": "Future",
        }.get(instrument, ""),
        "currency": str(meta.get("currency") or "").upper(),
    }


def yahoo_bars(payload: dict, symbol: str):
    """Yahoo's chart payload -> (stamps, closes, volumes), aligned.

    Split out of `slim_chart` because two callers need the arrays and not
    the chart: the slimmed payload the page draws, and the recent-assets
    table, which has to walk the series bar by bar to find the day the run
    began. The alignment rules are the ones the chart has always used -- a
    bar with no close is a gap and is dropped, and a bar with no volume
    keeps a None rather than borrowing its neighbour's -- with the one
    exception `session_close` covers: the *newest* bar is kept even when
    Yahoo left its close null, because that is a session whose close has
    not been published as a bar yet, not a gap.

    The newest bar's close is replaced by its extended-hours price when the
    payload carries one for that same session (`full_day_close`). It happens
    here, in the one function both callers read their bars through, so the
    chart's badge and the recent table's row are still scored on one series.

    Raises LookupError when the payload carries no usable series.
    """
    chart = payload.get("chart") or {}
    result = (chart.get("result") or [None])[0]
    if not result:
        message = (chart.get("error") or {}).get("description")
        raise LookupError(message or f"No price data for {symbol!r}.")

    meta = result.get("meta") or {}
    indicators = result.get("indicators") or {}
    quote = (indicators.get("quote") or [{}])[0]

    stamps = result.get("timestamp") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    # The newest stamped bar is the only one a missing close is allowed to
    # survive: Yahoo can publish a finished session's open/high/low/volume
    # before it publishes the close itself (see `session_close`). Older rows
    # with no close stay gaps.
    newest = len(stamps) - 1
    newest_close = (closes[newest] if 0 <= newest < len(closes) else None)
    if newest >= 0 and newest_close is None:
        newest_close = session_close(meta, quote, newest, stamps[newest])

    out_stamps: list[int] = []
    out_closes: list[float] = []
    out_volumes: list = []
    for i, stamp in enumerate(stamps):
        close = closes[i] if i < len(closes) else None
        if close is None:
            if i == newest and newest_close is not None:
                close = newest_close
            else:
                continue  # holidays / halts leave gaps
        out_stamps.append(int(stamp))
        out_closes.append(round(float(close), 6))
        out_volumes.append(volumes[i] if i < len(volumes) else None)

    if not out_stamps:
        raise LookupError(f"No usable price data for {symbol!r}.")
    full_day = full_day_close(meta, out_stamps[-1])
    if full_day is not None:
        out_closes[-1] = round(full_day, 6)
    return out_stamps, out_closes, out_volumes


def history_tail(all_points: list[dict], drawn: list[dict],
                 want: int | None = None) -> list[dict]:
    """The bars immediately before a drawn window, oldest first.

    The badge's steadiness reading (`onset.decorate`) asks the classifier the
    same question of the previous few windows, and a window ending four bars ago
    needs the four bars the trim just dropped. This hands them over: at most
    `want` (default `onset.LEAN_HOLD_BARS`) bars, each `{t, c, v}` so a prefix
    window is scored on the same numbers the table's walk would have used --
    including its volume, which is a signal the classifier reads.

    It rides in every chart payload, so it stays tiny: five bars, nothing drawn.
    """
    want = onset_module.LEAN_HOLD_BARS if want is None else want
    if not all_points or not drawn or not want:
        return []
    first = drawn[0]["t"]
    before = [point for point in all_points if point["t"] < first]
    return before[-want:]


def slim_chart(payload: dict, symbol: str, span: str | None = None,
               interval: str = "1d") -> dict:
    """Reduce Yahoo's chart payload to what the page actually draws.

    `span` is the range the payload was fetched for. When it is one of the
    calendar-month spans Yahoo itself understands, the payload is trimmed to
    the same window -- Yahoo's own rule, three calendar months back from
    today for `3mo` -- so the chart draws exactly the bars the badge reads and
    the recent table reads. Yahoo's own payload already matches this today;
    trimming here makes the agreement structural rather than a coincidence
    of how many bars the span happened to return.

    The window is not re-derived here: it is `onset.window_now`, the same
    function the walk in the recent table asks, so the two cannot drift apart
    the way two copies of a rule can.

    Only daily bars are trimmed. The cutoff is a day boundary, and a weekly
    bar spans seven days with its stamp on the week's first day -- comparing
    that stamp against a day boundary would amputate a bar that lies partly
    inside the window. Weekly charts keep Yahoo's own payload, and their badge
    is read from the bars they draw, which is the same rule the daily charts
    follow. One measured cost of that rule, stated so nobody rediscovers it
    by accident (2026-10-31, SPY `3mo`): the daily badge scores 63 daily bars
    with the backtested ensemble (-0.1985), while the weekly badge scores 15
    weekly bars -- 13 after the classifier's 63-bar tail -- through the
    short-window damping, sqrt(15/50) = 0.55 (-0.0091). Same label words,
    same threshold, entirely different machinery, because the backtest
    validated 63 *daily* bars and nothing else. The page itself only ever
    requests `1d`; a non-daily badge is the drawn bars' verdict, not the
    validated one.

    The newest bar is drawn at its extended-hours price when the payload has
    one for that session (`full_day_close`, applied inside `yahoo_bars`), and
    `extendedLastBar` says whether it happened, so the page can name the
    figure instead of letting a post-market print pass for a closing price.

    The payload also carries the `session` the newest bar belongs to -- the
    regular trading window and whether it is that bar's own session -- which is
    what `last_bar_basis` reads to call the figure live, pre-market,
    after-hours or a plain close. The window is Yahoo's; the decision is not
    made here, because it depends on the clock at read time, not at fetch time.

    `livePrint` is the other end of that: when the newest bar belongs to an
    *older* session than the one trading now, the payload keeps the current
    session's price beside the bars instead of dating it to an old one (see
    `live_print`), and `chart_data` draws it as today's point while one of that
    session's windows is open.
    """
    chart = payload.get("chart") or {}
    result = (chart.get("result") or [None])[0]
    if not result:
        message = (chart.get("error") or {}).get("description")
        raise LookupError(message or f"No price data for {symbol!r}.")

    meta = result.get("meta") or {}

    stamps, closes, volumes_used = yahoo_bars(payload, symbol)
    points = [{"t": stamp, "c": close}
              for stamp, close in zip(stamps, closes)]
    # Every bar the payload holds, volumes included, before the trim: what is
    # left out of the window becomes the badge's history (`history_tail`).
    every_bar = [{"t": stamp, "c": close, "v": volume}
                 for stamp, close, volume
                 in zip(stamps, closes, volumes_used)]

    months = SPAN_MONTHS.get(span) if span else None
    if months and interval == "1d":
        keep = onset_module.window_now(stamps, len(stamps) - 1,
                                        months=months)
        points = [points[i] for i in keep]
        volumes_used = [volumes_used[i] for i in keep]

    # The bars just before the drawn window, so the badge's lean can be checked
    # over the previous few sessions (`onset.decorate`). Yahoo was asked for a
    # longer range than the chart draws for exactly this (`chart_data`), so a
    # 3-month chart still has bars behind its window; a chart whose payload
    # starts at the window has no tail and keeps its lean unfiltered, which is
    # the honest answer to "not enough history to judge".
    tail = history_tail(every_bar, points)

    # The trend call is scored on the same bars the chart draws, volumes aligned
    # to them. Any failure here is non-fatal: the chart is the product, the badge
    # is an annotation, so a data quirk must not blank the page. Every series is
    # scored regardless of length; only unusable prices raise.
    trend_call = None
    try:
        trend_call = trend.classify([p["c"] for p in points], volumes_used)
    except ValueError:
        pass  # non-positive price in the series

    return {
        "symbol": meta.get("symbol") or symbol,
        "name": meta.get("longName") or meta.get("shortName") or symbol,
        "currency": meta.get("currency") or "",
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "",
        "type": meta.get("instrumentType") or "",
        "timezone": meta.get("exchangeTimezoneName") or "",
        "priceHint": meta.get("priceHint") or 2,
        "previousClose": meta.get("chartPreviousClose"),
        "marketPrice": meta.get("regularMarketPrice"),
        "extendedLastBar": full_day_close(meta, stamps[-1]) is not None,
        "livePrint": live_print(meta, stamps[-1]) if interval == "1d" else None,
        "session": session_window(meta, stamps[-1]),
        "points": points,
        "trend": trend_call,
        # The bars before the window, for the badge's steadiness reading. Not
        # drawn; kept so `chart_data` can ask the same question of the previous
        # few windows on every read, cached copies included.
        "historyTail": tail,
        "source": "Yahoo",
    }


def session_window(meta: dict, last_stamp: int) -> dict | None:
    """Yahoo's trading windows for the newest bar's session, if it says them.

    `pre`, `regular` and `post` are the payload's own `currentTradingPeriod`
    stamps, `[start, end]` each (a zero-length one is left out, which is how
    Yahoo spells "this instrument has no extended session"), and
    `coversLastBar` says whether those windows are the last bar's own session
    -- the same day question `full_day_close` asks before it folds an
    extended-hours print in, asked here about the bar itself. Without that flag
    a chart fetched on a Saturday would carry Friday's windows, and a Friday
    bar could be called live on a Friday evening reading.

    None when the payload carries no usable regular window: the honest answer
    for an instrument Yahoo does not schedule, which `last_bar_basis` then
    reads as a plain close.
    """
    periods = meta.get("currentTradingPeriod") or {}
    regular = periods.get("regular") or {}
    start, end = usable_stamp(regular.get("start")), usable_stamp(regular.get("end"))
    if start is None or end is None or end <= start:
        return None
    session = {
        "regular": [int(start), int(end)],
        "coversLastBar": same_exchange_day(meta, last_stamp, start),
    }
    # `lastPrint` is when the last regular-session trade printed. It is what
    # tells a window that is open from a market that is *trading*: Yahoo models
    # a nearly round-the-clock instrument (GC=F) as a whole calendar day, so
    # its window covers a Friday evening when the exchange has shut for the
    # weekend -- but the last print inside that window is hours old.
    last_print = usable_stamp(meta.get("regularMarketTime"))
    if last_print is not None:
        session["lastPrint"] = int(last_print)
    for name in ("pre", "post"):
        window = periods.get(name) or {}
        a, b = usable_stamp(window.get("start")), usable_stamp(window.get("end"))
        if a is not None and b is not None and b > a:
            session[name] = [int(a), int(b)]
    return session


def last_bar_basis(data: dict, now: float | None = None) -> str:
    """What the newest drawn bar's number *is*: live, pre-market, after-hours,
    a weekend price, or a closing price.

    Every bar but the newest is the session's settled close. The newest is
    whichever of these things Yahoo's session clock and the payload say it is:

    * `live` -- the regular session belongs to that bar, is open now, and a
      trade printed in the last half hour: the bar's close *is* the last trade.
    * `pre` -- an extended-hours print was folded into the bar
      (`extendedLastBar`) and the pre-market window is open.
    * `after` -- the same fold, with the post-market window open: the figure is
      the last after-hours trade of that session.
    * `live` also for a Binance coin whose newest bar is the day still
      trading (`liveLastBar`, set by `crypto.chart`), unless the copy is a
      disk fallback.
    * `weekend` for the peso pair's Saturday and Sunday, whose bars come from
      Coins.ph's USDC/PHP book (`weekend_proxy`) because the FX week is shut --
      a real traded price, but not an interbank close.
    * `pre` / `after` also for the session in progress when no bar exists for
      it yet (`live_point`): the point is today's date carrying the print of
      the session now trading, so it can be a pre-market or after-hours figure
      but never a settled close -- the session it belongs to has not settled.
    * `live` also for a PSE bar dated today while the exchange is open
      (`pse.session_window`): TradingView hands today's candle from the opening
      bell, so that bar is the price trading now, not a close. It reads `close`
      from 15:15 Manila, on a holiday, and from a disk fallback.
    * `close` -- everything else, including every payload whose source has no
      session to speak of (a fund's NAVPU, a bond yield).

    Two things keep this from over-claiming. The clock decides, not the price:
    once the extended session ends Yahoo stops folding the after-hours print in
    and reports the regular close again (AAPL read 344.807 while the post
    session ran on 2026-10-30 and 344.63 after it), so a figure outside those
    windows is a close however it was fetched. And a live call needs a *recent
    print*, so a window that is nominally open while the exchange is shut --
    Yahoo's whole-calendar-day window for a future, on a Friday night -- is not
    mistaken for a market that is trading.

    Decided at read time, not fetch time -- a chart served from the memory memo
    or from a disk copy an hour later must not still claim to be live. This is
    the one place the call is made; the page words the result (`lastBarBasis`)
    and never derives it.
    """
    points = data.get("points") or []
    # A Binance day still trading: its close is the last trade. A disk
    # fallback is hours old by definition, so it never reads live.
    if points and data.get("liveLastBar") and not data.get("cached"):
        return "live"
    # A bar the source is still writing, on a market whose clock we keep: the
    # PSE hands today's candle from the opening bell (`pse.session_window`), so
    # the newest point *is* the price trading now while the exchange is open.
    # The exchange publishes its session, so the window is an absolute stamp
    # that expires by itself -- tomorrow this same payload reads close, and a
    # disk fallback never reads live at all.
    forming = data.get("session") or {}
    if points and forming.get("formingBar") and not data.get("cached"):
        if _within(forming.get("regular"),
                   time.time() if now is None else now):
            return "live"
    # The newest bar is a weekend price for the peso pair: the FX week is shut,
    # and the number is Coins.ph's USDC/PHP close for that Manila day (see
    # `weekend_proxy`). It is neither an interbank close nor a live FX print, so
    # it says whose price it is rather than borrowing either word.
    if points and (data.get("weekendProxy") or {}).get("stamps"):
        if points[-1]["t"] == data["weekendProxy"]["stamps"][-1]:
            return "weekend"
    session = data.get("session") or {}
    if not points or not session.get("coversLastBar"):
        return "close"
    now = time.time() if now is None else now
    # The newest point is the print of a session that has not settled: a
    # pre-market trade before the regular open, the last extended print after
    # it. It never reads "close" -- the session it belongs to is the one still
    # in progress -- and it says which of the two by the clock, not by the
    # window the payload happened to ship.
    if data.get("livePointStamp") == points[-1]["t"]:
        ended = (session.get("regular") or [None, None])[1]
        if ended is not None and now >= ended:
            return "after"
        return "pre"
    regular = session.get("regular") or [None, None]
    if regular[0] is not None and regular[0] <= now < regular[1]:
        printed = session.get("lastPrint")
        if (printed is not None and printed >= regular[0]
                and now - printed <= LIVE_PRINT_MAX_AGE):
            return "live"
    if not data.get("extendedLastBar"):
        return "close"
    if _within(session.get("pre"), now):
        return "pre"
    if _within(session.get("post"), now):
        return "after"
    return "close"


def _within(window, now: float) -> bool:
    """Whether `now` falls inside a `[start, end]` window (None-safe)."""
    return bool(window) and len(window) == 2 and window[0] <= now < window[1]


def live_point(card: dict, now: float | None = None) -> dict:
    """Append the session now trading as a new newest point, while it trades.

    `slim_chart` ships the price of the session in progress as `livePrint`
    (`live_print`). It is drawn only while one of *that* session's extended
    windows is open now, and only when the chart still ends at an older bar:
    from the 16:00 bell until 04:00 New York Yahoo folds nothing -- it reports
    the regular close again -- so there is no print to add and the newest bar
    keeps its own close. That stretch is a gap in the source, and this function
    does not paper over it by repeating the close as a "live" price.

    Read time, not fetch time, and on a copy: `points` is the memo entry's
    list. A chart served from the memo or from a disk copy must not still carry
    a pre-market point late in the session, so the decision is remade on every
    read and the appended point disappears as soon as the real bar exists.

    A disk fallback is left alone: `cached` means the payload was fetched hours
    ago, and a copy may not invent a price for a session it never saw. It draws
    the bars it stored and says how old they are.
    """
    live = card.get("livePrint") or {}
    stamp, price = live.get("t"), live.get("c")
    if not stamp or not price or card.get("cached"):
        return card
    points = card.get("points") or []
    if not points or points[-1]["t"] >= stamp:
        return card                     # the real bar is here; nothing to add
    session = card.get("session") or {}
    now = time.time() if now is None else now
    if not (_within(session.get("pre"), now) or _within(session.get("post"), now)):
        return card                     # nothing is trading: the close stands
    out = dict(card)
    out["points"] = points + [{"t": int(stamp), "c": float(price)}]
    # The appended point sits where the session's own daily bar will sit, so
    # the payload's window *does* cover the newest point now -- which is what
    # `last_bar_basis` reads before it allows anything but "close".
    out["session"] = dict(session, coversLastBar=True)
    out["livePointStamp"] = int(stamp)
    return out


def usable_stamp(value) -> float | None:
    """A Yahoo epoch second as a number, or None if it is missing/not one."""
    return (float(value) if isinstance(value, (int, float))
            and not isinstance(value, bool) else None)


# How recently the last regular-session trade must have printed for the newest
# bar to be called a *live* price. Yahoo's `currentTradingPeriod.regular` is a
# schedule, and for an instrument that trades nearly around the clock (a future,
# an FX pair) it is a whole calendar day -- so on a Friday evening the window is
# still open while the exchange has shut for the weekend. The last print inside
# that window is then hours old, which is the difference this bound measures.
# Half an hour is long enough that a thinly traded name which has not printed
# since the bell still reads as live, and short enough that a closed market
# cannot pass for an open one.
LIVE_PRINT_MAX_AGE = 1800  # seconds

# How far behind the session that is trading the newest *bar* may be for
# `live_print` to trust `fulldayPrice` as that session's print. A weekend plus a
# holiday fits comfortably; a halted name or a dead listing does not, and its
# last price must not be redrawn as today's pre-market trade.
LIVE_BAR_GAP_DAYS = 5


def yahoo_chart(url: str, symbol: str, span: str | None = None,
                interval: str = "1d") -> dict:
    """Fetch and slim one Yahoo chart. Raises LookupError for "no such symbol",
    UpstreamError for a transport failure."""
    status, body = moli_get(url)
    try:
        payload = json.loads(body)
    except ValueError:
        raise UpstreamError(f"Upstream returned non-JSON (HTTP {status})")
    # Yahoo reports "no data" as a 404 with a chart.error object, so only a 5xx
    # is a genuine transport problem.
    if status >= 500:
        raise UpstreamError(f"Upstream HTTP {status}")
    return slim_chart(payload, symbol, span, interval)


def fx_cross_chart(symbol: str, span: str, interval: str,
                   snapshot: dict | None = None) -> dict:
    """Chart a currency cross Yahoo quotes but has no history for.

    `JPYPHP=X` answers with a live price and a single bar: a pair with no
    dollar leg has no series upstream. The legs that compose it do -- `PHP=X`
    and `JPY=X` are fully charted -- so the cross is divided out of them, both
    expressed per dollar: value of one quote-unit over value of one base-unit.
    Where Yahoo did answer with its own snapshot, that quote's name, currency
    and live price ride along, so the headline number stays Yahoo's even though
    the bars beneath it are composed.

    Raises LookupError when the legs share too few days to draw, and lets
    UpstreamError / ZeroDivisionError through from the legs; the caller treats
    every failure as "serve what Yahoo gave" rather than failing the symbol.
    """
    base, quote = symbol[:3], symbol[3:6]

    def per_usd(code: str) -> list[dict]:
        # `JPY=X` quotes yen *per* dollar, but `EUR=X` quotes dollars *per*
        # euro -- market convention, not a Yahoo quirk -- so those legs invert.
        data = chart_data(f"{code}=X", span, interval)
        return [{"t": p["t"], "c": 1.0 / p["c"]} if code in USD_QUOTED_BASES else p
                for p in data["points"]]

    base_pts, quote_pts = per_usd(base), per_usd(quote)
    quote_by_t = {p["t"]: p["c"] for p in quote_pts}
    points = [{"t": p["t"], "c": round(quote_by_t[p["t"]] / p["c"], 6)}
              for p in base_pts if p["t"] in quote_by_t]

    # Each leg's forming daily bar is stamped at its own fetch instant, so the
    # final stamps differ and strict alignment drops today's price. Both last
    # closes *are* today for a daily FX series, so re-append their cross.
    if base_pts and quote_pts:
        live_t = max(base_pts[-1]["t"], quote_pts[-1]["t"])
        if not points or points[-1]["t"] < live_t:
            points.append({"t": live_t,
                           "c": round(quote_pts[-1]["c"] / base_pts[-1]["c"], 6)})

    if len(points) < 2:
        raise LookupError(f"No shared history for {symbol!r}.")

    out = dict(snapshot or {})
    try:
        out["trend"] = trend.classify([p["c"] for p in points])
    except ValueError:
        out["trend"] = None
    out.update({
        "symbol": out.get("symbol") or symbol,
        "name": out.get("name") or f"{base}/{quote}",
        "currency": out.get("currency") or quote,
        "exchange": out.get("exchange") or "CCY",
        "type": "CURRENCY",
        "priceHint": out.get("priceHint") or 4,
        "previousClose": out.get("previousClose") or points[-2]["c"],
        "marketPrice": out.get("marketPrice") or points[-1]["c"],
        "points": points,
        "source": "Yahoo (USD legs)",
    })
    return out


def ecb_route(symbol: str, span: str, interval: str,
              yahoo: dict | None = None) -> dict | None:
    """The ECB payload for a no-USD-leg cross, with Yahoo's headline kept.

    Yahoo fabricates a weekly "Sunday reopen" bar for crosses it does not
    really chart (`EURPHP=X` printed 68.37 on 2026-10-04 against ~70.35
    elsewhere -- a three percent dip that no market ever traded). The ECB's
    daily fix is the honest series: one rate per business day, so a phantom
    Sunday bar is impossible, and Frankfurter serves it keyless. `ecb.chart`
    raises EcbError on a wire failure (an outage -- rescued from disk like any
    other) and LookupError when the pair is outside the ECB's 30 currencies
    (a verdict -- None, and the Yahoo chart stands).

    The bars are ECB's; the headline stays Yahoo's where Yahoo has one. The
    fix is a once-a-day snapshot, so a weekend headline Yahoo quotes live --
    today's 70.266 -- is more current than Friday's fix, and the payload keeps
    Yahoo's name and currency so the page renders the instrument identically.
    Yahoo's *trend* is not kept: it was scored over the fabricated bars, and
    a badge scored on phantom dips is the artifact the reader is looking at.

    Returns None when ECB has nothing (or the wire failed), and the caller
    serves Yahoo's answer -- the same contract `crypto.try_chart` speaks.
    """
    try:
        data = ecb.chart(symbol, span, interval)
    except LookupError:
        return None
    except ecb.EcbError:
        return None
    if yahoo:
        keep = yahoo.get("marketPrice")
        if isinstance(keep, (int, float)) and keep > 0:
            data["marketPrice"] = keep
        # `previousClose` deliberately not kept: it belongs to the same
        # fabricated snapshot the bars do (Yahoo quoted 72.518 against a
        # series that closed 70.475), and a headline change computed from it
        # would show the phantom dip the ECB bars exist to remove. The ECB
        # payload's own `previousClose` -- the second-to-last fix -- stands.
        for field in ("name", "currency", "symbol", "priceHint"):
            if yahoo.get(field) is not None:
                data[field] = yahoo[field]
    return data


def weekend_proxy(card: dict) -> dict:
    """Fill a peso-pair chart's Saturdays and Sundays from Coins.ph's USDC/PHP book.

    The FX week is Monday to Friday, so a USD/PHP chart drawn on a weekend ends
    on Friday's close and shows nothing of the two days since -- which is
    exactly when a Philippine reader looks at the peso. `coinsph.py` supplies
    those two days from the stablecoin's own peso book: the same instrument's
    question ("what is a dollar worth in pesos?") answered by a venue that
    trades through the weekend, at its own price rather than Yahoo's.

    Three rules, all of them the reader's to check against the payload:

    * The bars are the stablecoin's closes, and `weekendProxy.stamps` names every
      one of them, so the page can say whose price a point is instead of letting
      it pass for an interbank close.
    * A weekday is never touched, and a *weekend* day Yahoo drew is replaced --
      that bar carries Friday's close under a Saturday stamp (see `coinsph`),
      which is the gap being filled.
    * An outage is a no-op. Nothing here can turn a working chart into an error,
      and a chart that cannot be filled is still the chart Yahoo drew.

    The badge is re-scored downstream, on the points this returns, so the label
    and the line stay one series (invariant 1). The window is longer for it --
    a three-month FX chart gains about 26 bars -- and that is stated here rather
    than hidden, because a 91-bar window is not a 63-bar one.
    """
    points = card.get("points") or []
    if not points:
        return card
    try:
        filled, stamps, age = coinsph.fill(points)
    except coinsph.CoinsError:
        return card               # an outage, not a verdict: draw what Yahoo gave
    if not stamps:
        return card

    out = dict(card)
    out["points"] = filled
    out["weekendProxy"] = {
        "source": "Coins.ph",
        "pair": "USDC/PHP",
        "stamps": stamps,
        "price": next(p["c"] for p in reversed(filled) if p["t"] == stamps[-1]),
        # Seconds since the stablecoin series was read: a weekend reading is a
        # daily close, so an old copy is reported as old rather than reprinted
        # as this minute's.
        "age": int(age),
    }
    return out


def relevance(row: dict, needle: str) -> int:
    """Sort key: how directly a search result answers the query.

    Deliberately source-agnostic and capped well above any tiebreak below, so
    it only ever separates matches from near-misses and never reorders two
    equally good ones -- within a rank the original order survives.
    """
    symbol = row["symbol"].upper()
    name = (row.get("name") or "").lower()
    # BTC-USD, ^GSPC, GC=F and PSE:TEL all name their instrument in the leading
    # token. A `PSE:` prefix is a venue, so the ticker is what follows it, not
    # what precedes it -- split(":")[0] would tokenise "PSE:TEL" to "pse" and no
    # exact PSE hit would ever rank. Where a symbol carries no colon, the whole
    # string comes back either way, so [-1] is safe for both shapes.
    token = symbol.split("-")[0].split(":")[-1].split(".")[0].lstrip("^=").lower()
    # A fund's code is the instrument's whole name, hyphens and all: "BPI-HLTH"
    # is one code, not the token "BPI" followed by something, so the split above
    # would file an exact fund query behind Yahoo's noise. A `FUND:` symbol
    # carries no venue with its own listings, so the code after the prefix is
    # the token.
    if symbol.startswith(phfunds.PREFIX):
        token = symbol[len(phfunds.PREFIX):].lower()
    if token == needle or name == needle:
        return 0                      # AAPL for "apple", BTC-USD for "btc"
    if token.startswith(needle) or name.startswith(needle):
        return 1                      # PEPE-USD for "pepe"
    if needle in name:
        return 2                      # "jupiter" inside a fund's long name
    return 3                          # surfaced by Yahoo on some other signal


# Yahoo's search answers a single-currency query with the crosses its index
# holds and omits the peso crosses it will still serve *by name*: "krwphp"
# finds `KRWPHP=X` outright, but "krw" lists six other won pairs and none of
# them is the won→peso cross, and "jpy" likewise omits the yen→peso cross
# (`JPYPHP=X`) from every query that names the yen alone. Both are crosses
# this server charts honestly -- no dollar leg, so the ECB fix series under
# `ecb_route` -- yet no query a reader would actually type could ever reach
# them. This table names the queries that hide a cross and the cross each
# one hides; `fx_search_extra` turns them into rows. Hand-curated like
# `pse.SYNONYMS`: the omission is Yahoo's index, not a rule we could query.
FX_SEARCH_EXTRA: dict[str, tuple[str, ...]] = {
    "krw": ("KRWPHP=X",),
    "won": ("KRWPHP=X",),
    "jpy": ("JPYPHP=X",),
    "yen": ("JPYPHP=X",),
    "php": ("JPYPHP=X", "KRWPHP=X"),
    "peso": ("JPYPHP=X", "KRWPHP=X"),
    "philippine peso": ("JPYPHP=X", "KRWPHP=X"),
}


def fx_search_extra(needle: str) -> list[dict]:
    """Search rows for the peso crosses Yahoo's own index hides.

    The same shape Yahoo's rows carry (`KRWPHP=X` / "KRW/PHP" / CCY), so the
    page renders an addition indistinguishably from an original. The caller
    de-duplicates against `seen` before appending, so a cross Yahoo did list
    is never described twice.
    """
    rows = []
    for symbol in FX_SEARCH_EXTRA.get(needle) or ():
        rows.append({
            "symbol": symbol,
            "name": f"{symbol[:3]}/{symbol[3:6]}",
            "exchange": "CCY",
            "type": "CURRENCY",
        })
    return rows


# A word that could be a ticker: `VTV`, `BRK.B`, `BTC-USD`, `GC=F`, `^GSPC`,
# `JPYPHP=X`. Only a word of this shape is ever handed to the chart route as a
# symbol, so a sentence is never mistaken for one.
TICKER_RE = re.compile(r"^[A-Za-z^][A-Za-z0-9.\-=^]{0,11}$")

# Words that only name the *kind* of thing a reader wants, never the thing
# itself. "vtv etf" is still a ticker query, so its first word is probed; any
# other multi-word query is prose and is left to the search index rather than
# guessed at. That guard is what stops "the long bond" from resolving to `THE`
# (Target Hospitality) on a day the index answers nothing.
INSTRUMENT_WORDS = {
    "etf", "etfs", "fund", "funds", "stock", "stocks",
    "share", "shares", "index", "trust", "adr", "adrs",
}


def probe_ticker(text: str) -> dict | None:
    """The instrument `text` *names*, for a query Yahoo's search could not answer.

    Yahoo's search index refuses some queries for instruments it holds: measured
    2026-11-02, `/v1/finance/search?q=vtv` answered **HTTP 500** on query1 and
    query2 alike, with and without parameters, while `VTV` charted normally,
    `/v1/finance/quoteType/?symbol=VTV` resolved it, and the query `vt` listed it
    third. So the search box had no way to reach one of the largest US ETFs,
    and the failure was an index bug, not a missing instrument.

    Resolving the word as a *symbol* is the fallback, and the chart route is
    what resolves it: a row is offered only for a symbol it draws, carrying the
    name and venue it reports. `markets.yahoo_symbol` supplies the one spelling
    difference (`BRK.B` charts as `BRK-B`), so the row a reader clicks is the
    chart that answers.

    A multi-word query is tried by its first word only when every other word
    names the *kind* of thing asked for ("vtv etf" -> `VTV`), because the
    caller reaches this having been told nothing at all by the index. Any other
    multi-word query is prose and is not guessed at. Returns None when nothing
    resolves, so a dead end stays a dead end rather than becoming a guess.
    """
    words = [word for word in re.split(r"[^A-Za-z0-9.\-=^]+", text) if word]
    candidates = [text]
    if len(words) > 1 and all(word.lower() in INSTRUMENT_WORDS
                              for word in words[1:]):
        candidates.append(words[0])
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or not TICKER_RE.match(candidate):
            continue
        row = _chart_meta_row(markets.yahoo_symbol(candidate.upper()))
        if row:
            return row
    return None


def _chart_meta_row(symbol: str) -> dict | None:
    """One search row from the chart payload for `symbol`, or None."""
    url = (f"https://{CHART_HOST}/v8/finance/chart/"
           f"{urllib.parse.quote(symbol, safe='')}?range=5d&interval=1d")
    try:
        status, body = moli_get(url)
        if status >= 400:
            return None
        result = ((json.loads(body).get("chart") or {}).get("result") or [None])[0]
    except (UpstreamError, ValueError):
        return None
    if not result:
        return None
    meta = result.get("meta") or {}
    kind = str(meta.get("instrumentType") or "").upper()
    resolved = str(meta.get("symbol") or "").strip()
    # A type the search route would have offered, a symbol to ask the chart
    # route for, and at least one bar behind it: a row with no history is a
    # row that cannot be drawn, which is the thing search exists to avoid.
    if kind not in KEEP_QUOTE_TYPES or not resolved or not result.get("timestamp"):
        return None
    return {
        "symbol": resolved,
        "name": meta.get("longName") or meta.get("shortName") or resolved,
        "exchange": (meta.get("fullExchangeName")
                     or meta.get("exchangeName") or ""),
        "type": kind,
    }


def yahoo_is_wrong(symbol: str, data: dict) -> bool:
    """Is Yahoo charting a different instrument than this ticker names?

    Only asked of crypto -- that is where the collisions are -- and only when
    the ticker resolves to a chartable coin. Compares Yahoo's last close against
    Binance's for the same coin: the real Jupiter is ~1000x apart from the dead
    token, while BTC/ETH/SOL agree to a fraction of a percent.
    """
    if data.get("type") != "CRYPTOCURRENCY":
        return False
    points = data.get("points") or []
    if not points:
        return False
    truth = crypto.latest_close(symbol)
    if not truth:
        return False                  # no independent price: trust Yahoo
    ours = float(points[-1]["c"])
    if ours == truth:
        return False
    return abs(ours - truth) / abs(truth) > REROUTE_GAP


def chart_key(symbol: str, span: str, interval: str) -> str:
    """The cache key a chart is stored under, for either upstream.

    Lifted out of `chart_data` because the row warmer needs to ask "is this
    symbol's chart fresh?" without going through the chart itself -- and the
    answer is only honest if it reads through the *same* key the chart writes
    through, the way `LEADERS_KEY` keeps `warm_routes` and `api_top` honest.
    The Yahoo leg is the URL itself; the PSE and bond legs are synthetic
    because TradingView has no URL to key on. A bond key is deliberately *not*
    the key its raw bars live under (`tv.BOND_CACHE_PREFIX`): the bars are
    shared with the recent table's row, the finished chart is not.
    """
    if tv.is_bond_symbol(symbol):
        return f"tv:{symbol.strip().upper()}:{span}:{interval}"
    if pse.is_pse_symbol(symbol):
        return f"pse:{symbol.upper()}:{span}:{interval}"
    if phfunds.is_fund_symbol(symbol):
        # The fund's own synthetic key, for the same reason the bond's is: the
        # bars live under their own key (`phfunds.CACHE_PREFIX`) because they
        # are shared with the recent table's row, and the finished chart is not.
        return f"fund:{symbol.strip().upper()}:{span}:{interval}"
    if ondo.is_ondo_symbol(symbol):
        # A token Yahoo has no spelling for at all (see `ondo.py`), so its chart
        # needs a key of its own; nothing else in the project stores a `ondo:`.
        return f"ondo:{symbol.strip().upper()}:{span}:{interval}"
    quoted = urllib.parse.quote(symbol, safe="")
    return (f"https://{CHART_HOST}/v8/finance/chart/{quoted}"
            f"?range={span}&interval={interval}")


def retry_sparse_research(symbol, data, answer, refs, now, fetch_pse, fetch_pse_peers):
    """Try longer same-source histories without changing the studied window or chart."""
    if pse.is_pse_symbol(symbol) or data.get("cached"):
        return answer
    if not any(answer.get(d, {}).get("reason") == research_judgment.TOO_FEW_WINDOW_BARS
               for d in ("bullish", "bearish")):
        return answer
    for span in ("2y", "5y"):
        try:
            history = chart_data(symbol, span, "1d")
            # Never combine feeds, identities, stale data or adjusted price
            # series. Re-evaluate the original window from one complete series.
            if (history.get("cached") or not data.get("symbol") or
                    str(history.get("symbol", "")).upper() != str(data["symbol"]).upper() or
                    history.get("source") != data.get("source") or
                    history.get("type") != data.get("type")):
                continue
            candidate = research_judgment.evaluate(symbol, history, refs, now,
                                                   fetch_pse, fetch_pse_peers)
            if any(candidate.get(d, {}).get("status") != "unavailable"
                   for d in ("bullish", "bearish")):
                return candidate
        except Exception:
            # A failed research-only fetch cannot change the chart or invent a call.
            continue
    return answer


def chart_data(symbol: str, span: str, interval: str) -> dict:
    """The chart payload for one symbol, from cache or upstream.

    The route logic, lifted out of `Handler` so the startup prewarm can ask for
    the first paint's chart through the same code a request takes -- warming and
    serving cannot then drift apart. Validation stays in the route (bad input is
    a caller error, and the prewarm only ever passes constants).

    Raises LookupError (Yahoo "no such symbol") or `pse.PseNotFound` for a
    symbol no source knows; UpstreamError / `pse.PseError` for transport, which
    is a verdict about the network, not the symbol.
    """
    # A PSE symbol is served entirely from TradingView. Routed before the
    # Yahoo URL is even built, because Yahoo has no PSE equities: asking it
    # would spend a Moli round trip to earn a guaranteed 404.
    if tv.is_bond_symbol(symbol):
        # A Philippine bond yield has the same problem, one market over: Yahoo
        # quotes no Philippine yield at all, so the route would earn a 404 for
        # `TVC:PH10Y` -- a spelling Yahoo does not even tokenise as a ticker.
        # `tv.py` reads the series off the same TradingView socket the PSE rows
        # use, and the row that opened this chart was judged on that very
        # series (see `recent.bond_rows`), so the badge and the table agree.
        def bond_produce():
            return tv.chart(symbol, span, interval)

        data = cached(chart_key(symbol, span, interval), bond_produce)
    elif phfunds.is_fund_symbol(symbol):
        # A fund is the third instrument neither Yahoo nor TradingView quotes:
        # it has no ticker and no exchange, only the NAVPU its manager strikes
        # once a business day. Routed here before the Yahoo URL is built, for
        # the same reason the PSE and bond symbols are -- Yahoo would spend a
        # Moli round trip to answer 404 -- and drawn from the very series the
        # recent table's row was judged on (see `recent.fund_rows`), so the
        # badge and the row agree by construction.
        def fund_produce():
            return phfunds.chart(symbol, span, interval)

        data = cached(chart_key(symbol, span, interval), fund_produce)
    elif symbol.strip().upper().startswith(phfunds.PREFIX):
        # A `FUND:` spelling this module does not know is a verdict about the
        # symbol, not something to ask Yahoo about: Yahoo has never quoted a
        # Philippine fund, so the only thing a round trip could add is a
        # misleading "may be delisted".
        raise LookupError("%r is not one of the funds this page charts." % symbol)
    elif ondo.is_ondo_symbol(symbol):
        # A token neither Yahoo nor TradingView quotes: OUSG has no spelling
        # Yahoo's index or chart route answers at all (measured 2026-11-02 --
        # see `ondo.py`), so asking it would spend a Moli round trip to earn a
        # guaranteed 404. DeFiLlama prices the contract on chain.
        def token_produce():
            return ondo.chart(symbol, span, interval)

        data = cached(chart_key(symbol, span, interval), token_produce)
    elif symbol.strip().upper().startswith(ondo.PREFIX):
        # The same verdict the fund prefix earns: an `ONDO:` spelling this
        # module does not know is about the symbol, not about the wire.
        raise LookupError("%r is not one of the Ondo tokens this page charts."
                          % symbol)
    elif pse.is_pse_symbol(symbol):

        def pse_produce():
            return pse.chart(symbol, span, interval)

        data = cached(chart_key(symbol, span, interval), pse_produce)
    else:
        url = chart_key(symbol, span, interval)
        # What Yahoo is asked for, versus what the chart draws: one span wider,
        # so the badge has bars behind its window (`FETCH_SPAN`). The cache key
        # stays the requested span's URL, because that is the chart this entry
        # holds -- and the entry is the trimmed chart, not Yahoo's answer.
        fetch_url = chart_key(symbol, FETCH_SPAN.get(span, span), interval)

        def produce():
            # Yahoo's answer is the default, crypto or not.
            yahoo = None
            yahoo_error = None
            try:
                yahoo = yahoo_chart(fetch_url, symbol, span, interval)
            except LookupError as exc:
                yahoo_error = exc          # Yahoo has no such instrument
            # A transport failure is not a verdict about the symbol, so let it
            # propagate rather than quietly substituting another source.

            # A bare futures ticker is not one of Yahoo's symbols -- the
            # Treasury contract is `ZB=F` -- so "zb" submitted straight from
            # the search box used to end in "no usable price data" for a
            # contract that charts perfectly well. Asked again as the contract,
            # and only after Yahoo refused the bare spelling: `UB` is a real
            # ETF and keeps its own chart. The payload names the symbol it
            # actually drew, so the meta line says where the price came from.
            if yahoo is None and isinstance(yahoo_error, LookupError):
                alias = rates.chart_alias(symbol)
                if alias:
                    try:
                        yahoo = yahoo_chart(
                            chart_key(alias, FETCH_SPAN.get(span, span),
                                      interval),
                            alias, span, interval)
                    except LookupError:
                        pass

            if yahoo is not None and not yahoo_is_wrong(symbol, yahoo):
                # A cross with no dollar leg is one Yahoo composes rather than
                # charts, and its composed series carries a phantom weekly
                # "Sunday reopen" bar ~3% below the true cross -- the fix
                # snapshot is one per business day, so those bars cannot exist
                # there. Only such crosses route here: a USD-leg cross
                # (`USDPHP=X`) has genuine Sunday bars -- the FX week really
                # does open Sunday 21:05 GMT -- and keeps Yahoo's series.
                # None (an outage, or a pair outside the ECB set) leaves
                # Yahoo's chart standing rather than failing the symbol.
                if FX_CROSS_RE.fullmatch(symbol.upper()):
                    pair = symbol.upper()[:-2]
                    if "USD" not in (pair[:3], pair[3:]):
                        substituted = ecb_route(symbol, span, interval, yahoo)
                        if substituted is not None:
                            return substituted
                return yahoo

            coin = crypto.try_chart(symbol, span, interval)
            if coin is not None:
                return coin
            if yahoo is not None:
                return yahoo               # disagreement, but nothing better
            raise yahoo_error

        try:
            data = cached(url, produce)
        except LookupError:
            # A bare token ticker is not one of Yahoo's symbols and Yahoo has no
            # spelling for the token at all, so "ousg" typed into the search box
            # and submitted without picking the suggestion ended in "No usable
            # price data" for an instrument the page can chart. Asked as the
            # token, and only after Yahoo refused the typed spelling -- the same
            # rule the Treasury contracts follow, so a listing that really
            # trades under the bare ticker keeps its own chart. The chart is
            # stored under the token's own key, so the second read of "OUSG"
            # costs nothing upstream.
            token_symbol = ondo.alias(symbol)
            if not token_symbol:
                raise
            data = cached(chart_key(token_symbol, span, interval),
                          lambda: ondo.chart(token_symbol, span, interval))

        # A currency cross Yahoo quotes but has no history for -- one bar,
        # not a series -- is divided out of its dollar legs instead. Guarded
        # on the snapshot shape, so a pair Yahoo does chart (EURUSD=X) keeps
        # its own series untouched. A missing leg is a verdict about the
        # legs, not the cross: fall back to Yahoo's snapshot rather than
        # failing the symbol. A leg *outage* is treated the same way: online
        # it means one wire hiccup costs the cross its series for a memo
        # lifetime, and offline it is the difference between the chart the
        # user clicked for and a 502 -- `fx_cross_chart`'s own contract is
        # "the caller treats every failure as serve what Yahoo gave", and
        # this block is that caller.
        if (FX_CROSS_RE.fullmatch(symbol.upper())
                and len(data.get("points") or []) < 2):
            try:
                data = fx_cross_chart(symbol.upper(), span, interval, data)
            except (LookupError, ZeroDivisionError):
                pass
            except TRANSIENT_ERRORS:
                # An outage during synthesis: the legs failed offline while
                # the cross's own copy was rescued, so `data` still carries
                # that stamped copy. Serving it beats failing the symbol,
                # and keeping it stamped keeps `cached`'s memo entry the
                # same shape a direct rescue would have produced.
                pass
            else:
                # Synthesis succeeded: persist the composed series under the
                # cross's own key, so the disk copy a later outage rescues
                # is the full chart and not the one-bar snapshot Yahoo
                # stores. A stale rescue is a chart, not a headline. The
                # stamps are stripped when `data` itself was a rescue -- the
                # disk copy is stored plain, the way `cached` would have.
                _store_chart(url, {k: v for k, v in data.items()
                                   if k not in ("cached", "fetchedAt",
                                                "cacheError")})

    # The cache holds one shared dict; the range/interval stamps are per
    # response, so callers get a copy, never the entry itself.
    out = dict(data)
    # The peso pair's weekend, drawn from Coins.ph's USDC/PHP book: the FX week
    # is Monday to Friday, so a chart read on a Saturday or a Sunday otherwise
    # stops at Friday's close. Applied to the copy, after the memo, so the
    # Yahoo-only answer stays what is stored and a weekend bar is never
    # mistaken for a bar Yahoo published. Before the re-score below, because
    # the badge must read the series the plot draws.
    if interval == "1d" and coinsph.is_usd_php(symbol):
        out = weekend_proxy(out)
    # The session trading now, when Yahoo has not published a bar for it yet:
    # the chart draws that print as today's point instead of stopping at
    # yesterday's official close (see `live_point`). Before the re-score below,
    # because the badge reads the series the plot draws.
    if interval == "1d":
        out = live_point(out)
    if pse.is_pse_symbol(symbol) and out.get("source") == "TradingView" and not out.get("longTermContext"):
        out["longTermContext"] = {"status": "insufficient",
                                  "reason": "Longer history was not saved in this cached chart"}
    # Older offline chart copies contain the previous classifier's verdict.
    # Re-score the exact points drawn, so an outage cannot resurrect that call.
    points = out.get("points") or []
    try:
        call = trend.classify([p["c"] for p in points])
    except (KeyError, TypeError, ValueError):
        call = None
    # ... and then the one place the steady-lean rule is applied to a badge, so
    # the chart, the watchlist tag and the leaning table agree about the same
    # asset at the same moment (2026-11-07). The drawn window and the bars
    # behind it (`historyTail`, shipped by every producer that has them) are
    # handed over together; a series with no tail keeps its lean, because an
    # unanswerable question is not a negative one.
    if call is not None:
        drawn = [p for p in points
                 if isinstance(p, dict) and p.get("t") is not None
                 and p.get("c") is not None]
        tail = [p for p in (out.get("historyTail") or [])
                if isinstance(p, dict) and p.get("t") is not None
                and p.get("c") is not None]
        # Only when every drawn point can be read: a payload this code cannot
        # align is not one to decorate from, so the badge keeps its plain call.
        if drawn and len(drawn) == len(points):
            full = tail + drawn
            stamps = [int(p["t"]) for p in full]
            closes = [float(p["c"]) for p in full]
            volumes = [p.get("v") or 0.0 for p in full]
            yahoo_months = (SPAN_MONTHS.get(span)
                            if out.get("source") == "Yahoo" else None)
            call = onset_module.decorate(
                call, stamps, closes, volumes,
                months=yahoo_months,
                days=pse.RANGE_DAYS.get(span, pse.RANGE_DAYS["3mo"]))
    if out.get("yieldSeries"):
        # A bond yield's badge reads as a bond price, not as the yield's own
        # direction -- the same reversal the recent table's row makes, applied
        # here so a row and the chart its click opens cannot label one series
        # two ways. `yieldTrend` keeps the classifier's unreversed call beside
        # it, because "the yield rose" is the fact and "bonds bearish" is the
        # inference drawn from it.
        out["yieldTrend"] = call
        call = tv.bond_price_call(call)
    # A daily series the source has stopped printing is not a price now, and
    # nothing on this payload may say otherwise -- the same rule the table
    # applies before it judges a shelf name (see `recent.STALE_GAP_DAYS`, and
    # ATKR as the case that made it visible: three weeks of a frozen $94.96
    # charted as a close with a "leaning bullish" badge on it). The line is
    # still drawn -- it is the history that exists -- but the verdict and the
    # profit odds are withheld, because both are claims about now.
    #
    # Yahoo only, and daily only. The trading days of the US market are what
    # makes five days of silence meaningful; the PSE, the funds and the bonds
    # close for long holidays (see the constant), and a weekly bar is stamped
    # at the start of its week, so its age is not a session's.
    if interval == "1d" and out.get("source") == "Yahoo":
        drawn_stamps = [p["t"] for p in points
                        if isinstance(p, dict) and p.get("t") is not None]
        gap = recent.stale_gap(drawn_stamps)
        if gap is not None:
            out["staleDays"] = int(round(gap))
            out["staleBar"] = recent.utc_day(max(drawn_stamps))
            call = None
        elif "staleDays" in out:
            # A copy cannot keep a staleness claim it did not earn on this read
            # -- the same rule `lastBarBasis` follows: decided from the drawn
            # bars and the clock, never carried.
            out.pop("staleDays", None)
            out.pop("staleBar", None)
    out["trend"] = call
    out["range"] = span
    out["interval"] = interval
    # The last *finished* PSE session, in pesos: the newest drawn bar that is
    # not dated today in Manila, times its volume. Decided here, not in
    # `pse.chart`, for the same reason `lastBarBasis` is decided here -- a
    # payload fetched mid-session and served hours later (or tomorrow, from a
    # disk copy) must not keep reporting the day it was fetched on. Daily only:
    # a weekly bar's volume is a week's, so its product is not a trading day's
    # value. Every source but TradingView's PSE leg carries no `volumes`, and
    # `completed_trade` answers None for them, so the readout simply hides.
    if interval == "1d" and pse.is_pse_symbol(symbol):
        traded_day, traded_shares, traded_value = pse.completed_trade(
            out.get("points") or [],
            out.get("volumes") or [],
            now=time.time())
        out["tradedDay"] = traded_day
        out["tradedShares"] = traded_shares
        out["tradedTurnover"] = traded_value
    # Separate from the descriptive badge: project the drawn daily returns,
    # including mean-estimation uncertainty and assumed round-trip costs.
    # Withheld for a series that has stopped (`staleDays` above): an estimate
    # about the next three months of an instrument the source no longer prints
    # is an estimate about nothing.
    out["profitProbability"] = (None if out.get("staleDays") is not None
                                else probability.estimate(out))
    # What the newest bar's number is -- a live price, an extended-hours print
    # or a settled close -- decided from the payload and the clock *now*, so a
    # chart served from the memory memo or from a disk copy cannot claim to be
    # live on the strength of what was true when it was fetched.
    out["lastBarBasis"] = last_bar_basis(out)
    return out


class Handler(SimpleHTTPRequestHandler):
    server_version = "AssetPriceDisplay/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    # -- helpers -----------------------------------------------------------

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The reader hung up before the answer landed -- a superseded
            # poll the page aborted, a tab closing mid-fetch. The answer
            # has nowhere to go and nothing about the data was wrong, so
            # drop it quietly instead of raising (which, on this dead
            # socket, would only print a second traceback from fail()).
            self.close_connection = True

    def fail(self, status: int, message: str) -> None:
        self.send_json(status, {"error": message})

    def refuse(self) -> None:
        """Answer a probe path with a bare 404: the status line and nothing
        else. `send_response_only` adds no headers, so even the Server line
        that names Python is withheld."""
        self.send_response_only(404)
        self.end_headers()

    def log_message(self, fmt, *args):  # quieter, one line per request
        sys.stderr.write("  %s\n" % (fmt % args))

    def log_request(self, code="-", size="-"):
        # Unknown paths get probed constantly from outside this project
        # (`/health`, then `/v1/models` — background machinery that mistook
        # this port for some other service's). A 404 here is that noise, not
        # a reader's broken link, so it takes no console space; every
        # request this server actually serves still logs.
        if code == 404:
            return
        self.log_message('"%s" %s %s', self.requestline, str(code), str(size))

    def log_error(self, fmt, *args):
        # The 404 half of the pair above (`code 404, message File not
        # found`), dropped for the same reason.
        if args and args[0] == 404:
            return
        self.log_message(fmt, *args)

    # -- routes ------------------------------------------------------------

    def do_GET(self):
        route = urllib.parse.urlparse(self.path)
        # Probes for services this is not (`/health`, `/v1/models` -- the
        # latter an LLM-server convention) get a bare refusal: a status line
        # and nothing after it. No health payload, no model list, no error
        # page, not even the Server header -- whoever is asking learns
        # nothing about what runs here.
        if route.path in ("/health", "/v1/models"):
            return self.refuse()
        try:
            if route.path == "/api/chart":
                return self.api_chart(route.query)
            if route.path == "/api/research-judgment":
                return self.api_research_judgment(route.query)
            if route.path == "/api/search":
                return self.api_search(route.query)
            if route.path == "/api/top":
                return self.api_top()
            if route.path == "/api/bullish":
                return self.api_bullish()
            if route.path == "/api/cryptobull":
                return self.api_cryptobull()
            if route.path == "/api/recent":
                return self.api_recent()
            if route.path == "/api/health":
                return self.send_json(200, {
                    "ok": True,
                    "moli": MOLI,
                    "moliFound": os.path.exists(MOLI),
                    # The offline fallback is only as good as what is on disk,
                    # so say where that is and how much of it exists.
                    "cacheDir": diskcache.dir(),
                    "cacheEntries": diskcache.count(),
                    # What the connectivity watch last saw, and how many times
                    # it has caught the wire coming back -- the two facts that
                    # explain why the cache holds what it holds right now.
                    "online": _watch_online,
                    "reconnections": _refresh_epoch,
                    # What the warmer has been *told* to care about: the
                    # declared union, so a reader can see whether the list the
                    # server holds is the list they are looking at.
                    "watchlist": union_watchlist(),
                })
        except (UpstreamError, pse.PseError) as exc:
            return self.fail(502, str(exc))
        except Exception as exc:  # never let the page see a traceback
            return self.fail(500, f"{type(exc).__name__}: {exc}")
        return super().do_GET()

    def read_json(self):
        """Parse the request body as JSON, capped like everything a browser
        sends here; raises ValueError (the route's 400) on size or syntax.

        The cap is a memory guard, not a product limit: the only body this
        server reads is a declared watchlist, and that list has no length
        ceiling any more (see `_clean_watch`). Two megabytes holds ten thousand
        `{symbol, name}` pairs -- far past any list a person curates -- while
        still refusing to buffer a stream that never ends.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("bad Content-Length")
        if length > 2 * 1024 * 1024:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_POST(self):
        route = urllib.parse.urlparse(self.path)
        if route.path != "/api/watch":
            return self.fail(404, "Unknown endpoint")
        try:
            body = self.read_json()
        except (ValueError, UnicodeDecodeError) as exc:
            return self.fail(400, f"Expected a JSON list: {exc}")
        # Accept the page's own shape (an array of {symbol, name}) directly;
        # wrapped is tolerated too, since `_clean_watch` reads either spelling.
        symbols = body if isinstance(body, list) else body.get("symbols") \
            if isinstance(body, dict) else None
        if symbols is None:
            return self.fail(400, "Expected a JSON array of {symbol, name}")
        # A declared list may legitimately be empty -- the reader deleted every
        # row -- and the union is a union, so an empty declaration records
        # nothing and simply answers with what is still held warm.
        record_watchlist(symbols)
        return self.send_json(200, {"ok": True, "watchlist": union_watchlist()})

    def api_chart(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        symbol = (params.get("symbol") or [""])[0].strip()
        span = (params.get("range") or ["3mo"])[0]
        interval = (params.get("interval") or ["1d"])[0]

        if not symbol:
            return self.fail(400, "Missing ?symbol=")
        if len(symbol) > 32:
            return self.fail(400, "Symbol too long")
        if span not in ALLOWED_RANGES:
            return self.fail(400, f"Unsupported range {span!r}")
        if interval not in ALLOWED_INTERVALS:
            return self.fail(400, f"Unsupported interval {interval!r}")

        try:
            data = chart_data(symbol, span, interval)
        except (LookupError, pse.PseNotFound) as exc:
            return self.fail(404, str(exc))
        return self.send_json(200, data)

    def api_research_judgment(self, query: str) -> None:
        """Separate request: slow research inputs never hold up chart loading."""
        params = urllib.parse.parse_qs(query)
        symbol = (params.get("symbol") or [""])[0].strip().upper()
        if not symbol or len(symbol) > 32:
            return self.fail(400, "Missing or invalid ?symbol=")
        try:
            # A full year is needed to reconstruct the first monthly signal's
            # window even at month end. The chart route preserves actual source.
            data = chart_data(symbol, "3mo" if pse.is_pse_symbol(symbol) else "1y", "1d")
            def fetch_pse_snapshot(name):
                def produce():
                    rows = pse.history_many([name], count=pse.MAX_BARS).get(name, [])
                    if not rows:
                        raise UpstreamError("Philippine stock history unavailable")
                    return {"rows": rows}
                return cached(f"research:pse-history:v1:{name}", produce, ttl=3600)
            def fetch_pse(name):
                return fetch_pse_snapshot(name)["rows"]
            refs = research_judgment.references()
            def fetch_pse_peers():
                # One shared, bounded snapshot for all stocks, never a new
                # market-wide browser sweep per row or per concurrent request.
                def produce():
                    rows = pse.history_many(sorted(refs["pse_universe"]), count=120)
                    if len(rows) < max(11, int(len(refs["pse_universe"]) * .8)):
                        raise UpstreamError("Philippine peer history incomplete")
                    return {"rows": rows}
                snapshot = cached("research:pse-peers:v1", produce, ttl=3600)
                # Never silently reuse an outage fallback as a fresh peer rank.
                return {} if snapshot.get("cached") else snapshot["rows"]
            import datetime as dt
            now = dt.datetime.now(dt.timezone.utc)
            answer = research_judgment.evaluate(symbol, data, refs, now, fetch_pse,
                                                fetch_pse_peers)
            answer = retry_sparse_research(symbol, data, answer, refs, now, fetch_pse,
                                           fetch_pse_peers)
            if not any(answer[d].get("status") == "signaled" for d in ("bullish", "bearish")):
                try:
                    now = dt.datetime.now(dt.timezone.utc)
                    if pse.is_pse_symbol(symbol):
                        history = fetch_pse_snapshot(symbol)
                        points = [{"t": row[0], "c": row[4]} for row in history["rows"] if len(row) > 4]
                        zone = "Asia/Manila"
                    else:
                        history = chart_data(symbol, "2y", "1d")
                        if (history.get("source") != data.get("source") or
                                str(history.get("symbol", "")).upper() != str(data.get("symbol", "")).upper()):
                            raise UpstreamError("Long history resolved to a different asset or source")
                        points = history.get("points") or []
                        source = history.get("source")
                        zone = ("UTC" if source == "Binance" else
                                history.get("timezone") or refs.get("timezones", {}).get(symbol))
                    answer["fallback"] = research_judgment.historical_baseline(points, symbol, zone, now)
                    if history.get("cached"):
                        answer["fallback"]["cached"] = True
                        answer["fallback"]["fetchedAt"] = history.get("fetchedAt")
                except Exception:
                    answer["fallback"] = research_judgment.unavailable("Asset history could not be retrieved")
        except Exception:
            # Network failures and absent research files are not market calls.
            answer = {"market": None, "bullish": research_judgment.unavailable("Research data or source unavailable"),
                      "bearish": research_judgment.unavailable("Research data or source unavailable"),
                      "note": "Historical research hit rates are not individual probabilities."}
        return self.send_json(200, answer)

    def api_top(self) -> None:
        """Both most-traded tables, plus the cross rate their dollar column uses.

        No parameters, so there is nothing to validate -- the shape of what comes
        back is fixed by `markets`. Each market carries its own `error`, so one
        section being unreachable still serves the other's table; see
        `markets.tables`.
        """
        # `tables_payload` is what the prewarm thread and the row warmer read
        # as well, so a browser's tables and the warmed ones are the same call
        # through the same key; the helper's docstring carries the caching and
        # stamping rationale.
        return self.send_json(200, tables_payload())

    def api_bullish(self) -> None:
        """The bullish table, as the background sweeper last left it.

        No fetch happens here and no parameters are read: the answer is whatever
        `bullish_state` holds, which is why this route returns in milliseconds
        whether the sweep behind it took thirty-five seconds or failed outright.
        A failure is reported in the payload rather than as a status, because the
        table is a section of the page and a section that cannot load should say
        so in place (see `markets.tables` for the same convention).
        """
        return self.send_json(200, bullish_state())

    def api_cryptobull(self) -> None:
        """The bullish crypto table, cached and stamped like the leaderboards.

        Unlike `/api/bullish` this *can* fetch on demand -- the crypto scan is
        seconds of plain HTTPS, not a half-minute browser sweep -- so the route
        is `cryptobull_payload`, the same `cached` path the prewarm pass reads.
        A cold miss is answered by the one scan already in flight rather than
        starting a second, and an outage serves the last good copy stamped
        `cached`, dated on the page like every other fallback.
        """
        return self.send_json(200, cryptobull_payload())

    def api_recent(self) -> None:
        """The recently-bullish table, as the background sweeper last left it.

        No fetch happens here and no parameters are read, for the reason
        `/api/bullish` gives: the United States leg is fifty tickers' worth of
        browser-fetched bars, and a reader should not pay for that. The answer
        is whatever the sweeper produced, dated.
        """
        return self.send_json(200, recent_state())

    def api_search(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        text = (params.get("q") or [""])[0].strip()
        if not text:
            return self.send_json(200, {"results": []})
        if len(text) > 64:
            return self.fail(400, "Query too long")

        quoted = urllib.parse.quote(text, safe="")
        url = (f"https://{SEARCH_HOST}/v1/finance/search?q={quoted}"
               f"&quotesCount=10&newsCount=0&enableFuzzyQuery=false")

        def produce():
            # A refused search is an *empty* answer here, not a failure of the
            # whole route. Yahoo 500s some queries outright (see
            # `probe_ticker`), and raising used to abort the supplements below
            # with it, so a reader typing "vtv" got an error page instead of a
            # row and a Philippine fund query got nothing when the index
            # hiccuped. `moli_get` failing at the transport level still raises:
            # that is the browser, not the index.
            quotes = []
            status, body = moli_get(url)
            if status < 400:
                try:
                    quotes = json.loads(body).get("quotes") or []
                except ValueError:
                    quotes = []           # a body that is not the JSON it claims
            results = []
            seen = set()
            for quote in quotes:
                symbol = quote.get("symbol")
                if not symbol or quote.get("quoteType") not in KEEP_QUOTE_TYPES:
                    continue
                seen.add(symbol.upper())
                results.append({
                    "symbol": symbol,
                    "name": quote.get("longname") or quote.get("shortname") or symbol,
                    "exchange": quote.get("exchDisp") or "",
                    "type": quote.get("quoteType") or "",
                })

            # Nothing from Yahoo at all, and the query is itself a ticker: ask
            # the chart route whether that symbol exists. This is what finds
            # VTV, whose every search query the index answers with HTTP 500 --
            # and what keeps a *dead* ticker denied, since only a symbol the
            # chart route draws becomes a row.
            if not results:
                probed = probe_ticker(text)
                if probed:
                    results.append(probed)
                    seen.add(probed["symbol"].upper())

            # Yahoo has no listing for some coins at all -- the real Jupiter
            # among them -- so no query can surface them. Add what the coin
            # index knows and Yahoo does not. A ticker both sources report
            # becomes one row, described by the coin rather than by Yahoo, so
            # the venue matches where the bars will actually come from.
            for match in crypto.search_coins(text):
                key = match["symbol"].upper()
                if key not in seen:
                    results.append(match)
                    seen.add(key)
                    continue
                # A ticker both sources report becomes one row, described by
                # what the coin is rather than by Yahoo's venue tag: "CCC" is
                # where the dead token trades, and naming it was part of what
                # made search misleading.
                for row in results:
                    if row["symbol"].upper() == key:
                        row["name"] = match["name"]
                        row["exchange"] = match["exchange"]
                        break

            # Yahoo carries no PSE equities, so every Philippine listing the
            # search box should offer has to be added from the PSE universe.
            # Same de-dupe as the coins above, though a `PSE:`-prefixed symbol
            # can never collide with a Yahoo one.
            for match in pse.search_stocks(text):
                key = match["symbol"].upper()
                if key not in seen:
                    results.append(match)
                    seen.add(key)

            # No fund Yahoo lists, and no fund a reader can find by any query
            # this project asks it: a Philippine fund has no ticker at all.
            # The funds this page charts are offered from the one table that
            # knows them, so a reader can reach one by name ("health care") as
            # well as by the code a row prints (`BPI-HLTH`). A `FUND:` symbol
            # cannot collide with a Yahoo one.
            for match in phfunds.search_funds(text):
                key = match["symbol"].upper()
                if key not in seen:
                    results.append(match)
                    seen.add(key)

            # Nor tokens: OUSG is in no Yahoo answer at all -- `/search?q=ousg`
            # returns an empty list, `/lookup?query=ousg` reports `total: 0`,
            # and every chart spelling is a 404 (measured 2026-11-02, see
            # `ondo.py`) -- even though the page charts it from the contract's
            # on-chain price. The row carries the `ONDO:` prefix, so it cannot
            # collide with a Yahoo symbol.
            for match in ondo.search_tokens(text):
                key = match["symbol"].upper()
                if key not in seen:
                    results.append(match)
                    seen.add(key)

            # A no-dollar-leg cross Yahoo will serve by name ("krwphp" finds
            # `KRWPHP=X`) but hides from every query that names one leg alone
            # ("krw" lists six other won pairs, none of them the peso cross).
            # The supplement fires on the exact needle -- "PHP" and "php" hide
            # the same crosses -- and its rows join the pool before the sort,
            # where `relevance` files them honestly: for "krw" the cross ranks
            # with the other won pairs (its ticker starts with the query),
            # while "peso" leaves it among the remainder, which is still
            # showing it where Yahoo showed nothing. De-duplicated against
            # `seen`, so a cross Yahoo did list is never described twice.
            needle = text.lower()
            for row in fx_search_extra(needle):
                key = row["symbol"].upper()
                if key not in seen:
                    results.append(row)
                    seen.add(key)

            # The United States Treasury futures. Yahoo's index holds "zb" and
            # "t-bond" but not the words a reader uses: "30-year treasury bond"
            # answers with six Korean ETFs and "long bond" with three KB funds,
            # because the contract's own Yahoo name ("U.S. Treasury Bond
            # Futures,Dec-") contains neither "30" nor "year". So the curve
            # `rates.py` knows is offered here, where a query can reach it by
            # tenor, by desk name ("the long bond") or by ticker. Yahoo-shaped
            # rows, de-duplicated against `seen` like every other supplement.
            rate_rows = rates.search_contracts(text)
            rate_order = {symbol.upper(): index for index, symbol
                          in enumerate(rates.named_contracts(text))}
            for row in rate_rows:
                key = row["symbol"].upper()
                if key not in seen:
                    results.append(row)
                    seen.add(key)

            # Float an exact hit above the noise: Yahoo answers "pepe" with
            # seven low-cap variants and omits the real coin, so appending it
            # would bury it. Ties keep each source's own order (sort is stable).
            pse_rows = [r for r in results if pse.is_pse_symbol(r["symbol"])]
            yahoo_rows = [r for r in results if not pse.is_pse_symbol(r["symbol"])]
            if pse.market_query(text):
                # "philippines" is not a name any PSE listing contains, so
                # `relevance` would file every PSE row behind Yahoo's, and
                # Yahoo's answer here is `EPHE` plus a wall of `^NQPHLMT` index
                # codes. A query that names the market wants the market's
                # securities, so those rows go first and Yahoo's follow.
                results = pse_rows + yahoo_rows
            elif pse_rows and min((relevance(r, needle) for r in yahoo_rows),
                                  default=99) > 0:
                # No Yahoo row answers this query by ticker, only by resembling
                # it -- and for a Philippine company those rows are foreign and
                # OTC shells. "pldt" is really answered by `PHI` (a NYSE
                # closed-end fund), `PLDTX`, `PLO.HM`, `PLO.SG`... while the
                # Manila listing sits seventh. So a PSE row that matches leads,
                # unless Yahoo's best is an exact ticker hit -- which is how
                # "tel" still puts TE Connectivity first, with `PSE:TEL` next.
                results = (sorted(pse_rows, key=lambda r: relevance(r, needle))
                           + sorted(yahoo_rows, key=lambda r: relevance(r, needle)))
            else:
                results.sort(key=lambda row: relevance(row, needle))
            # A fund query has no competitor worth deferring to. Yahoo's index
            # has never heard of a Philippine fund, so its rows for "alfm" are
            # `ALFMF` (an OTC shell) and for "pera" a wall of Perak and Peraso
            # -- near-misses dressed as answers. So the funds whose *code*
            # answers the query lead, unless another row is an exact ticker hit
            # (which is what the reader typed, and outranks any supplement).
            # Matching the code rather than the name is deliberate: "health"
            # should still find the health-care stocks first, while "pera"
            # and "alfm" are names only the funds answer.
            words = [w for w in re.split(r"[^a-z0-9]+", needle) if w]
            def answers_by_code(row):
                code = row["symbol"].split(":", 1)[-1].lower()
                return bool(words) and all(w in code for w in words)
            lead = [r for r in results
                    if phfunds.is_fund_symbol(r["symbol"])
                    and answers_by_code(r)]
            exact_elsewhere = any(relevance(r, needle) == 0 for r in results
                                  if not phfunds.is_fund_symbol(r["symbol"]))
            if lead and not exact_elsewhere:
                rest = [r for r in results if r not in lead]
                results = (sorted(lead, key=lambda r: relevance(r, needle))
                           + rest)

            # A query that *names* a Treasury contract -- "zb", "30-year
            # treasury bond", "long bond", "t-note" -- wants that contract, and
            # not an ETF or a fund that happens to be marketed with the same
            # words. `rates.named_contracts` is the list of the ones the query
            # named specifically (the bare word "treasury" names the asset
            # class and is not in it), so those rows lead in the curve's own
            # order. Same guard as the funds above: an exact ticker hit
            # elsewhere is what the reader typed and outranks any supplement,
            # which is why "bond" still puts the `BOND` ETF first.
            named = sorted((r for r in results
                            if r["symbol"].upper() in rate_order),
                           key=lambda r: rate_order[r["symbol"].upper()])
            named_exact = any(relevance(r, needle) == 0 for r in results
                              if r["symbol"].upper() not in rate_order)
            if named and not named_exact:
                rest = [r for r in results if r not in named]
                results = named + rest
            return {"results": results[:10]}

        return self.send_json(200, cached(f"search:{url}", produce))


def kill_running_moli() -> None:
    """Terminate any Moli fetch still in flight (called at shutdown)."""
    with _running_lock:
        procs = list(_running)
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def port_owner(port: int) -> int | None:
    """PID listening on `port`, or None if it is free or lsof is unavailable."""
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5,
        ).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return int(out[0]) if out else None


def main() -> int:
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Not a port: {sys.argv[1]!r}", file=sys.stderr)
            return 2

    # Signals are delivered on the main thread, which is the one blocked in
    # serve_forever(), so raising there breaks out of the accept loop. (Calling
    # sys.exit() from a worker thread would only end that thread.) Restoring
    # the default handler afterwards makes a second Ctrl-C kill outright.
    def _stop(signum, _frame):
        signal.signal(signum, signal.SIG_DFL)
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
    except ValueError:  # no signal handling outside the main thread
        pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        owner = port_owner(port)
        print(f"Port {port} is already in use.", file=sys.stderr)
        if owner:
            print(f"  Held by PID {owner} — stop it with:  kill {owner}", file=sys.stderr)
        print(f"  Or run this server elsewhere:        python3 {os.path.basename(__file__)} {port + 1}",
              file=sys.stderr)
        return 1
    server.daemon_threads = True  # don't block shutdown on idle keep-alive threads

    # Housekeeping for the offline copies first: one directory scan here is
    # cheaper than the amortised sweep inside `store` noticing months-old
    # symbols on the 200th write of a session that never asked for them.
    diskcache.prune()

    moli_ok = os.path.exists(MOLI)
    print("Asset price display")
    print(f"  page   http://127.0.0.1:{port}/")
    print(f"  moli   {MOLI}  {'(found)' if moli_ok else '(NOT FOUND - requests fall back to the cache below)'}")
    print(f"  cache  {diskcache.dir()}  ({diskcache.count()} saved answers for offline use)")
    print("  stop   Ctrl-C\n")

    # Hydrate the sweep from disk before the refresher starts: the first
    # request must not see the empty stand-in for a table that exists in the
    # cache folder, and a seed racing a live sweep is the one ordering that
    # must not happen (see `seed_bullish`).
    seed_bullish()
    # The recently-bullish table is seeded the same way, for the same reason:
    # its first sweep is a browser sweep, so an offline start must not show an
    # empty table while a dated copy sits in `.cache/`.
    seed_recent()
    # Same reason for the watchlist, one degree quieter: the warmer starts on a
    # timer of its own and reads the declared union every pass, so a server
    # rebooted -- or one that simply has no browser open yet -- still knows
    # which symbols the reader asked it to keep current (see `WATCHLIST_KEY`).
    adopt_watchlist(diskcache.load_plain(WATCHLIST_KEY))
    # Open the startup completion report before any warming thread exists: the
    # three first passes below (first paint, bullish sweep, row charts) mark it
    # as each finishes, and the last mark prints the closing sentence --
    # "startup warm: all refetches finished (Ns)" -- so the console says when
    # the boot's fetching is over, the same way it does after a reconnection.
    open_startup_report()
    # Started before the first request can arrive, and before the port even
    # accepts one: the sweep's whole design depends on it being already underway
    # (or already done) by the time a reader asks, since nothing waits for it.
    start_bullish_refresh()
    # The recently-bullish table sweeps on its own clock for the same reason,
    # and for one more: it reads the Philippine sweep's rows, so it must not
    # outrun the sweep it is built from.
    start_recent_refresh()
    # Same reasoning for the caches the first paint reads, once instead of
    # forever: the browser round trips go after the port opens so binding is
    # never kept waiting, and a reader who arrives mid-warm-up waits only on
    # what is genuinely still missing.
    #
    # Warmed even when Moli is missing: with no browser the producers fail at
    # once, and `cached` turns each failure into a stamped disk copy -- so a
    # reader arriving offline is served the dated fallback immediately instead
    # of paying for a doomed live fetch per route.
    start_prewarm()
    # And the perpetual one: the prewarm fills the hero's caches, this thread
    # keeps *every listed row's* chart retrievable, pass after pass, whether or
    # not anyone clicks it. It waits for the first paint's fetches to clear the
    # browser before it starts spending round trips (see `warm_rows_loop`), so
    # launching it here costs a reader nothing.
    start_row_warming()
    # The eye that decides when all of the above should stop working to a
    # schedule: watches for the internet coming back and, on that edge,
    # expires the memos, wakes the sleepers, and re-warms the first paint --
    # so new data lands the moment it is reachable, not the moment someone
    # opens the page or a backoff happens to end (see `net_watch_loop`).
    start_net_watch()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nshutting down…")
        server.server_close()
        kill_running_moli()
        print("stopped — port released")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
