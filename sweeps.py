"""The two background sweeps: the Philippine bullish sweep and the recent table.

Split out of server.py; behaviour unchanged. Every name here is re-exported from
`server`, and the code reaches its names through `S.`, so a test that patches
`server.<name>` still reaches it.
"""

from __future__ import annotations

import datetime
import json
import threading
import time
import faults
import bullish
import diskcache
import market_days
import nasdaq_bars
import ondolist
import pse
import pse_outlook
import recent
import us_bars

import server as S


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
    saved = diskcache.load(S.BULLISH_KEY)
    if saved is None:
        return
    fetched_at, payload = saved
    # Same refusal as `_disk_fallback`: only a dict can carry the stamps, and
    # only a sweep with rows is worth serving -- an empty saved table would
    # claim "no stock is bullish" from the past, which the stand-in's "not
    # measured yet" beats honestly.
    # A sweep with leaning names and no bullish ones is a real answer too
    # (2026-11-16: PAL, PHR, FCG leaned while no name was bullish; the empty
    # `rows` made this refuse the copy, and the recent table's first scan then
    # saw no Philippine names at all).
    if not isinstance(payload, dict) or not (
            payload.get("rows") or payload.get("leaning")):
        return
    with S._bullish_lock:
        if S._bullish_state["payload"] is not None:
            return  # a sweep got here first; it knows better than the disk
        seeded = dict(payload)
        seeded["cached"] = True
        seeded["fetchedAt"] = int(fetched_at)
        S._bullish_state["payload"] = seeded
        S._bullish_state["started"] = float(fetched_at)


def bullish_state() -> dict:
    """The last sweep, or a stand-in saying one has not landed yet.

    Never blocks: it takes the lock, copies what is there and lets go. The
    payload is replaced wholesale by the refresher rather than mutated, so a
    reader cannot see it change while it renders.
    """
    with S._bullish_lock:
        payload = S._bullish_state["payload"]
        error = S._bullish_state["error"]
        started = S._bullish_state["started"]
        attempted = max(S._bullish_state["last_attempt"], started)
        running = S._bullish_state["running"]

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
        epoch = S._refresh_epoch
        started = time.time()
        with S._bullish_lock:
            S._bullish_state["running"] = True
            S._bullish_state["last_attempt"] = started
        payload = None
        error = None
        try:
            payload = bullish.scan()
        except Exception as exc:  # a sweep may fail in many ways; none are fatal
            faults.note("Philippine sweep", exc)
            error = str(exc) or type(exc).__name__
        if payload is not None:
            diskcache.store(S.BULLISH_KEY, payload)
        with S._bullish_lock:
            S._bullish_state["running"] = False
            S._bullish_state["error"] = error
            if payload is not None:
                S._bullish_state["payload"] = payload
                S._bullish_state["started"] = time.time()
        # A sweep that raised landed nothing: the state keeps its previous
        # payload exactly as designed, and the report says so too. (A sweep
        # cannot "succeed" off disk -- the loop calls `bullish.scan()`
        # directly, never through `cached`, so the only answer that is not
        # fresh data is the exception.)
        S.note_refetch_done("bullish sweep", epoch, landed=payload is not None)
        S._sleep_or_wake(
            S.bullish_pause() if payload is not None else S.BULL_TTL, since=epoch)


# While the exchange is shut the sweep runs this often instead of every
# `BULL_TTL`. Not "never": the three-month window slides with the calendar, so
# an hourly sweep keeps the dates right while nothing on the tape can move.
BULL_CLOSED_TTL = 3600
# How long past the bell the sweep keeps its normal pace, so one sweep is
# sure to have read the closing print before the pace slows.
BULL_CLOSE_MARGIN = 20 * 60


def bullish_pause(now: float | None = None) -> float:
    """Seconds to wait after a sweep that landed.

    `BULL_TTL` while the Philippine exchange trades (the bell to twenty
    minutes past the close, weekdays); otherwise `BULL_CLOSED_TTL`, shortened
    so the wait never runs past the next opening bell. A day the exchange's
    own list names a holiday (`market_days.pse_holiday`) is a closed day, so
    it is swept hourly; a holiday the list does not name reads as a trading
    day and is swept at the normal pace.
    """
    here = datetime.datetime.fromtimestamp(
        time.time() if now is None else now, pse_outlook.MANILA)
    opened = datetime.datetime.combine(here.date(), pse.SESSION_OPEN,
                                       tzinfo=pse_outlook.MANILA)
    closed = datetime.datetime.combine(
        here.date(), pse.SESSION_CLOSE, tzinfo=pse_outlook.MANILA
    ) + datetime.timedelta(seconds=S.BULL_CLOSE_MARGIN)
    if market_days.pse_open_day(here.date()) and opened <= here < closed:
        return S.BULL_TTL
    nxt = opened if here < opened else opened + datetime.timedelta(days=1)
    for _ in range(14):              # a bounded walk: a bad list cannot hang it
        if market_days.pse_open_day(nxt.date()):
            break
        nxt += datetime.timedelta(days=1)
    return max(60.0, min(float(S.BULL_CLOSED_TTL), (nxt - here).total_seconds()))


def start_bullish_refresh() -> None:
    """Start the refresher, once. Safe to call more than once."""
    with S._bullish_lock:
        if S._bullish_thread is not None and S._bullish_thread.is_alive():
            return
        # Daemon: the sweep is not worth blocking a shutdown on, and an in-flight
        # Moli is reaped by `kill_running_moli` like any other.
        S._bullish_thread = threading.Thread(
            target=S.bullish_loop, name="bullish-refresh", daemon=True)
        S._bullish_thread.start()


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

# How many tickers go into one browser run. `moli_batch_get` keeps at most
# `BATCH_CONCURRENCY` (20) fetches in flight at once inside the page, so one
# browser launch can handle a large slice of the US shelf without restarting
# Chrome every twenty tickers, while still isolating any single browser crash
# to that slice.
RECENT_BATCH = 160

_recent_state = {
    "payload": None,
    "error": None,
    "started": 0.0,
    "last_attempt": 0.0,
    "running": False,
}
_recent_lock = threading.Lock()
_recent_thread: threading.Thread | None = None


def _us_zone(payload: dict) -> str:
    """The exchange's timezone name from a Yahoo chart payload, or ''."""
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    return str((result.get("meta") or {}).get("exchangeTimezoneName") or "")


def _fetch_us_pass(plan: dict[str, bool], now: float, out: dict[str, tuple],
                   outage: set[str]) -> tuple[list[str], bool]:
    """One round of browser runs for `plan` (`{ticker: wants the full year}`).

    Fills `out` and `outage`. Answers the tickers whose fresh month did not
    fit their stored year (they need the full year, see `us_bars.merge`) and
    whether any full year landed.
    """
    refetch: list[str] = []
    landed_full = False
    tickers = list(plan)
    for start in range(0, len(tickers), S.RECENT_BATCH):
        chunk = tickers[start:start + S.RECENT_BATCH]
        urls = {ticker: S.chart_key(
                    ticker, S.RECENT_SPAN if plan[ticker] else us_bars.TAIL_SPAN,
                    S.RECENT_INTERVAL)
                for ticker in chunk}
        try:
            answers = S.moli_batch_get(list(urls.values()))
        except S.UpstreamError:
            # The run as a whole failed: every ticker in the chunk is an
            # outage at once, and the next chunk is still worth trying.
            outage.update(chunk)
            continue
        for ticker, url in urls.items():
            status, body = answers.get(url, (0, ""))
            if status != 200:
                if status != 404:
                    outage.add(ticker)
                else:
                    us_bars.drop(ticker)    # Yahoo's verdict; keep no old year
                continue
            try:
                payload = json.loads(body)
            except ValueError:
                outage.add(ticker)
                continue
            try:
                bars = tuple(S.yahoo_bars(payload, ticker))
            except LookupError:
                record = None if plan[ticker] else us_bars.get(ticker)
                if record is None:
                    us_bars.drop(ticker)
                    continue    # Yahoo's "no such instrument", a verdict
                # An empty month over a stored year: the series printed
                # nothing new (a name that stopped trading), so the stored
                # year is still the whole answer. The daily full read is
                # what notices if the name is gone altogether.
                us_bars.put(ticker, (record["s"], record["c"], record["v"]),
                            record.get("meta") or {}, record.get("tz") or "",
                            now, full=False)
                out[ticker] = us_bars.series(record)
                continue
            meta = S.yahoo_meta(payload)
            zone = _us_zone(payload)
            if plan[ticker]:
                us_bars.put(ticker, bars, meta, zone, now, full=True)
                landed_full = True
                out[ticker] = bars + (meta,)
                continue
            record = us_bars.get(ticker)
            joined = None if record is None else us_bars.merge(
                (record["s"], record["c"], record["v"]), bars,
                zone or record.get("tz") or "")
            if joined is None:
                refetch.append(ticker)
                continue
            us_bars.put(ticker, joined, meta, zone or record.get("tz") or "",
                        now, full=False)
            out[ticker] = tuple(joined) + (meta,)
    return refetch, landed_full


def fetch_us_bars(tickers: list[str], now: float | None = None) -> dict[str, tuple]:
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

    The year is not downloaded on every sweep (2026-11-16, see `us_bars.py`):
    once a ticker's year is stored, a sweep asks only for the last month and
    lays it over the stored year, and the full year is asked again once a day
    or the moment the two do not fit. While New York is closed, a ticker read
    after the close is read again only once an hour. A fetch that fails is
    still an outage -- stored bars are never served in place of an answer
    that did not come.
    """
    now = time.time() if now is None else now
    out: dict[str, tuple] = {}
    outage: set[str] = set()    # no answer at all -- not Yahoo's "no such instrument"
    tickers = [t for t in tickers if t]
    plan: dict[str, bool] = {}
    for ticker in tickers:
        record = us_bars.get(ticker)
        if record is not None and us_bars.settled(record, ticker, now):
            out[ticker] = us_bars.series(record)
            continue
        plan[ticker] = (record is None
                        or now - float(record.get("fullAt") or 0) >= us_bars.FULL_EVERY)
    refetch, landed_full = S._fetch_us_pass(plan, now, out, outage)
    if refetch:
        _again, more = S._fetch_us_pass({t: True for t in refetch}, now, out, outage)
        landed_full = landed_full or more
    # Filed on disk when a full year landed, and once per closed stretch after
    # the close has settled, so a restart at the weekend starts with Friday's
    # finished bars instead of downloading 474 years again.
    closed = us_bars.closed_since(now)
    if plan and (landed_full or (
            closed is not None and now >= closed + us_bars.SETTLE
            and us_bars.saved_at() < closed + us_bars.SETTLE)):
        us_bars.save(now)
    # Yahoo or Moli being down loses the whole US leg, so the tickers that got
    # no answer at all are asked of a second, independent source: Nasdaq's
    # official daily closes. Their rows are marked (`source`), because a close
    # without Yahoo's extended-hours patch is not quite the chart's series.
    # Yahoo's own "no such instrument" is never second-guessed.
    if outage:
        try:
            out.update(nasdaq_bars.fetch(sorted(outage - set(out))))
        except Exception as exc:
            faults.note("Nasdaq fallback bars", exc)
            pass    # the fallback failing leaves them missing, as before
    return out


def seed_recent() -> None:
    """Hydrate the recent table's state from disk, so an offline start still has rows.

    The same contract as `seed_bullish`: a stored copy becomes the payload as
    any live sweep would, dated with the second it was actually swept, and the
    first sweep of this run replaces it wholesale.
    """
    saved = diskcache.load(S.RECENT_KEY)
    legacy = saved is None
    if legacy:
        saved = diskcache.load(S.LEGACY_RECENT_KEY)
    yield_side = saved is None
    if yield_side:
        saved = diskcache.load(S.OLDER_RECENT_KEY)
    if saved is None:
        return
    fetched_at, payload = saved
    if not isinstance(payload, dict) or not payload.get("rows"):
        return
    with S._recent_lock:
        if S._recent_state["payload"] is not None:
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
        seeded["healthHistory"] = recent.load_health_history()
        seeded["cached"] = True
        seeded["fetchedAt"] = int(fetched_at)
        S._recent_state["payload"] = seeded
        S._recent_state["started"] = float(fetched_at)


def recent_state() -> dict:
    """The last recent-assets sweep, or a stand-in saying one has not landed yet.

    Never blocks: it takes the lock, copies what is there and lets go. The
    payload is replaced wholesale by the sweeper rather than mutated, so a
    reader cannot see it change while it renders.
    """
    with S._recent_lock:
        payload = S._recent_state["payload"]
        error = S._recent_state["error"]
        started = S._recent_state["started"]
        attempted = max(S._recent_state["last_attempt"], started)
        running = S._recent_state["running"]

    if payload is None:
        return {
            "label": "Recently bullish assets",
            "rows": [],
            "bearish": [],
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


RECENT_PH_WAIT = 240  # seconds the first scan waits for the Philippine sweep


def recent_loop() -> None:
    """Sweep forever, `RECENT_TTL` apart. Runs on the refresh thread.

    A failed attempt leaves the previous payload alone, for the reason the
    Philippine sweep gives: rows that are fifteen minutes old with a note
    saying so are more useful than an empty section.
    """
    while True:
        ph_unlanded = False
        epoch = S._refresh_epoch
        started = time.time()
        with S._recent_lock:
            S._recent_state["running"] = True
            S._recent_state["last_attempt"] = started
        payload = None
        error = None
        try:
            # The Philippine rows are read from the sweep the server keeps
            # warm, not re-swept: see the note above this block.
            ph_state = S.bullish_state()
            # Do not scan past a Philippine sweep that has not landed: the
            # table would hold "Philippines: 0" for a full RECENT_TTL.
            waited = 0
            while (ph_state.get("pending")
                   and not (ph_state.get("rows") or ph_state.get("leaning"))
                   and waited < S.RECENT_PH_WAIT):
                time.sleep(5)
                waited += 5
                ph_state = S.bullish_state()
            ph_unlanded = bool(
                ph_state.get("pending")
                and not (ph_state.get("rows") or ph_state.get("leaning")))
            # Built under its own name and published only once every step
            # below succeeded, so a failure never ships a half-built table.
            built = recent.scan(
                ph_sweep_rows=ph_state.get("rows") or [],
                fetch_us_bars=S.fetch_us_bars,
                ph_sweep_leaning=ph_state.get("leaning") or [],
                # Missing key: a sweep stored before bearish rows were kept.
                # None, not [], so the note does not claim the exchange was
                # judged bearish when that pass never asked.
                ph_sweep_bearish=(ph_state["bearish"]
                                  if "bearish" in ph_state else None),
                ondo_shelf=ondolist.shelf(),
                # What the Philippine sweep looked at, so the note can say
                # "263 scanned (249 common shares, 11 preferred shares, ...)"
                # instead of only counting the rows that turned bullish.
                ph_sweep_stats={"universe": ph_state.get("universe"),
                                "kinds": ph_state.get("kinds") or {},
                                "missing": ph_state.get("missing") or [],
                                "edge": ph_state.get("edge") or []})
            built["checkedAt"] = int(time.time())
            # The one-line summary of the sweep, drawn by the same module that
            # knows what was judged -- so the note and the rows cannot disagree
            # about what was scanned.
            built["note"] = recent.summarize(built)
            built["healthHistory"] = recent.record_health_history(
                built.get("health") or [])
            payload = built
        except Exception as exc:  # a sweep may fail in many ways; none are fatal
            faults.note("recent sweep", exc)
            error = str(exc) or type(exc).__name__
        if payload is not None:
            diskcache.store(S.RECENT_KEY, payload)
            try:
                import notify
                notify.observe_recent(payload, S.union_watchlist())
            except Exception as exc:
                faults.note("notify.observe_recent", exc)
        with S._recent_lock:
            S._recent_state["running"] = False
            S._recent_state["error"] = error
            if payload is not None:
                S._recent_state["payload"] = payload
                S._recent_state["started"] = time.time()
        S.note_refetch_done("recent sweep", epoch, landed=payload is not None)
        # Scanned without the Philippine sweep: look again soon, not in 15 min.
        S._sleep_or_wake(60 if ph_unlanded else S.RECENT_TTL, since=epoch)


def start_recent_refresh() -> None:
    """Start the refresher, once. Safe to call more than once."""
    with S._recent_lock:
        if S._recent_thread is not None and S._recent_thread.is_alive():
            return
        S._recent_thread = threading.Thread(
            target=S.recent_loop, name="recent-refresh", daemon=True)
        S._recent_thread.start()
