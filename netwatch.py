"""Network watch: notices a dropped and restored connection and re-reads what went stale.

Split out of server.py; behaviour unchanged. See README "Layout".
"""

from __future__ import annotations

import re
import sys
import threading
import time
import bullish
import recent

import server as S


# The watch thread's most recent answer, for `/api/health`: None until the
# first probe, then at most `NET_PROBE_INTERVAL` old. Read without the lock --
# a health line one poll stale is still the truth about the wire.
_watch_online: bool | None = None


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
    epoch = S._refresh_epoch
    landed = False   # a pass that never ran, or died on the way, landed nothing
    try:
        landed = S.warm_routes()
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
    online = S.net_ok()
    _watch_online = online
    while True:
        # Online, a drop is only noticed; offline, the reconnect is what
        # refills the caches, so that side keeps the quick pace.
        time.sleep(S.NET_PROBE_INTERVAL if not online
                   else getattr(S, "NET_PROBE_ONLINE_INTERVAL", S.NET_PROBE_INTERVAL))
        ok = S.net_ok()
        _watch_online = ok
        if ok and not online:
            S.net_reconnected()
        online = ok


def start_net_watch() -> None:
    """Start the connectivity watch. Called once, from `main`.

    Daemon like the threads it supervises: the probe is never worth blocking a
    shutdown on, and waking a half-finished sweep is a courtesy, not a promise.
    """
    threading.Thread(target=net_watch_loop, name="net-watch", daemon=True).start()
