"""Row warmer: keeps every table row's chart fetched so it opens offline.

Split out of server.py; behaviour unchanged. See README "Layout".
"""

from __future__ import annotations

import json
import re
import socket
import sys
import threading
import time
import faults
import bullish
import crypto
import diskcache
import markets
import ondo
import phfunds
import pse
import recent
import tv

import server as S
import netwatch


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
    stamp = S._warm_due.get(key)
    if stamp is None or stamp[0] < S._refresh_epoch:
        saved = diskcache.load(key)
        at = saved[0] if saved is not None else -1.0
        S._warm_due[key] = (S._refresh_epoch, at)
    else:
        at = stamp[1]
    return 0 <= at and now - at < S.ROW_STALE_AFTER


def due_rows(bull: dict | None, watch: list[str] | None, now: float,
             recent: dict | None = None):
    """The listed symbols whose chart is not fresh, in queue order.

    A ticker that joins a table between passes has no attempt stamp and
    no disk copy -- it matches neither clock, so it is due the moment it is
    listed. `bull` arrives only once a sweep has landed rows; `recent` is the
    combined recently-bullish table (including bearish and leaning rows), gated
    the same way, so a row it lists (a US ticker, a coin, a Philippine stock, a
    bond yield, a fund) is as retrievable offline as a row on any other table;
    `watch` is the declared watchlist, gated on the same liveness rule, and goes
    *first* -- these are the symbols a human chose to keep, so they lead the
    queue rather than waiting behind the PSE tail. Two tables listing the same
    symbol warm it once, on its first spelling.
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
        key = S.chart_key(symbol, S.WARM_SPAN, S.WARM_INTERVAL)
        if not row_fresh(key, now):
            out.append((key, symbol))

    if watch is not None:
        for symbol in watch:
            add(symbol)
    if bull is not None:
        for key in ("rows", "bearish", "leaning"):
            for row in bull.get(key) or []:
                if isinstance(row, dict):
                    add(row.get("chartSymbol"))
    if recent is not None:
        for key in ("rows", "bearish", "leaning"):
            for row in recent.get(key) or []:
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
        answers = S.moli_batch_get([key for key, _symbol in pairs])
    except S.UpstreamError:
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
                S.slim_chart(payload, symbol, S.WARM_SPAN, S.WARM_INTERVAL)
            except LookupError:
                # A coin Yahoo has no chart for may still be chartable from
                # Binance -- the same substitution `chart_data`'s producer
                # makes when Yahoo errors and the coin resolves.
                coin = crypto.try_chart(symbol, S.WARM_SPAN, S.WARM_INTERVAL)
                if coin is not None:
                    _store_chart(key, coin)
                out[symbol] = WARM_LANDED
            else:
                _store_chart(key, S.slim_chart(payload, symbol, S.WARM_SPAN,
                                              S.WARM_INTERVAL))
                out[symbol] = WARM_LANDED
            continue
        try:
            chart = S.slim_chart(payload, symbol, S.WARM_SPAN, S.WARM_INTERVAL)
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
        if (S.FX_CROSS_RE.fullmatch(symbol.upper())
                and len(chart.get("points") or []) < 2):
            try:
                chart = S.fx_cross_chart(symbol.upper(), S.WARM_SPAN,
                                       S.WARM_INTERVAL, chart)
            except Exception as exc:
                faults.note("warm: currency cross", exc)
        # The warm-side half of the ECB route (`chart_data`'s produce): a
        # no-dollar-leg cross gets the ECB fix series under the same key, so
        # the disk copy a later outage rescues is the honest one, not the
        # fabricated Sunday-dip series. None (an outage, or a pair outside the
        # ECB set) keeps Yahoo's slimmed chart -- the same "Yahoo's answer
        # stands" contract the route speaks.
        if S.FX_CROSS_RE.fullmatch(symbol.upper()):
            pair = symbol.upper()[:-2]
            if "USD" not in (pair[:3], pair[3:]):
                substituted = S.ecb_route(symbol, S.WARM_SPAN, S.WARM_INTERVAL, chart)
                if substituted is not None:
                    chart = substituted
        coin = _reroute_crypto(symbol, chart)
        _store_chart(key, coin or chart)
        out[symbol] = WARM_LANDED
    return out


def _reroute_crypto(symbol: str, chart: dict) -> dict | None:
    """The crypto payload when Yahoo charted the wrong instrument, else None.

    The warm-side half of `chart_data`'s reroute: same test (`yahoo_is_wrong`,
    which refuses to fire for anything but a chartable coin), same
    substitution. Runs after the batch, so the cost is one crypto chart read
    per crypto row rather than a second browser run, and a row that passes
    the test keeps Yahoo's answer.

    That one chart is both the independent price the test needs and the payload
    the warm copy should hold, exactly as `chart_data` does it -- including a
    pair Binance has stopped printing, where `latest_close` answers None but
    Kraken may still chart the coin.
    """
    coin = None
    tried = False
    try:
        if chart.get("type") == "CRYPTOCURRENCY":
            tried = True
            coin = crypto.try_chart(symbol, S.WARM_SPAN, S.WARM_INTERVAL)
        if not S.yahoo_is_wrong(symbol, chart, coin, tried=tried):
            return None
    except Exception as exc:
        faults.note("warm: crypto check", exc)
        return None  # a probe failure is not a verdict; keep Yahoo's answer
    try:
        return coin if coin is not None else crypto.try_chart(
            symbol, S.WARM_SPAN, S.WARM_INTERVAL)
    except Exception as exc:
        faults.note("warm: crypto bars", exc)
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
                                  S.WARM_SPAN, S.WARM_INTERVAL)
    except Exception as exc:
        faults.note("warm: Philippine batch", exc)
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
                                 S.WARM_SPAN, S.WARM_INTERVAL)
    except Exception as exc:
        faults.note("warm: bond batch", exc)
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
                                      S.WARM_SPAN, S.WARM_INTERVAL)
    except Exception as exc:
        faults.note("warm: fund batch", exc)
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
                                   S.WARM_SPAN, S.WARM_INTERVAL)
    except Exception as exc:
        faults.note("warm: token batch", exc)
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
        epoch = S._refresh_epoch
        # The most-traded tables and the 24-hour crypto list are not drawn.
        # The warmer does not fetch them. A direct request to `/api/top` or
        # `/api/cryptobull` still builds an answer.
        bull = S.bullish_state()
        rec = S.recent_state()
        live_bull = (bull if (bull.get("rows") or bull.get("bearish") or bull.get("leaning"))
                     and not bull.get("cached") else None)
        # Bullish, bearish and leaning rows of the recent table, gated the same way.
        live_recent = (rec if (rec.get("rows") or rec.get("bearish") or rec.get("leaning"))
                       and not rec.get("cached") else None)
        # The reader's own list. Gated like the sweeps -- through the probe --
        # because an offline machine costs nothing to ask "is BTC-USD fresh",
        # but launching a browser to answer it is what the outage rules forbid.
        live_watch = S.union_watchlist() if (netwatch._watch_online or netwatch._watch_online is None) else None
        queue = due_rows(live_bull, live_watch, time.time(), live_recent)
        if not queue:
            # Nothing due means every known row's disk copy re-adopted as
            # fresh -- which is the part landing, not merely running. (A pass
            # with nothing *known* to warm -- an undeclared union and no live
            # tables -- reports the same way; the edge's own note is what
            # flags that case, because no mark here can distinguish it.)
            S.note_refetch_done("row charts", epoch, landed=True)
            S._sleep_or_wake(S.WARM_IDLE_POLL, since=epoch)
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
                (pse_queue, _warm_batch_pse, S.WARM_PSE_CHUNK),
                (bond_queue, _warm_batch_bonds, S.BOND_WARM_CHUNK),
                (fund_queue, _warm_batch_funds, S.FUND_WARM_CHUNK),
                (token_queue, _warm_batch_tokens, S.FUND_WARM_CHUNK),
                (yahoo_queue, _warm_batch_yahoo, S.WARM_BATCH)):
            for start in range(0, len(pairs), size):
                chunk = pairs[start:start + size]
                # Stamps first, exactly as the serial loop stamped before each
                # fetch: this chunk reads "attempted at this epoch" from the
                # moment its batch departs. If the wire kills the pass here,
                # these are the rows the backoff covers; the rows behind the
                # break keep no stamp and re-queue after it.
                for key, _symbol in chunk:
                    S._warm_due[key] = (epoch, time.time())
                outcomes = batch(chunk)
                if WARM_OUTAGE in outcomes.values():
                    backoff = True
                    break
                time.sleep(S.WARM_PACING)
            if backoff:
                break
        # The part closes here, at the end of the pass: "row charts landed"
        # means the post-edge queue was *worked to fresh disk copies*, not
        # merely attempted. A pass that ran to the end without breaking landed
        # every row it had; one cut short -- by an outage -- is an honest
        # "not landed", naming the part in the closing line as stale, and a
        # newer edge opens a newer report for the rows still waiting on the
        # wire.
        S.note_refetch_done("row charts", epoch, landed=not backoff)
        if backoff:
            S._sleep_or_wake(S.WARM_BACKOFF, since=epoch)


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
