"""The watchlist the page reports: what the client is looking at, kept for the warmers.

Split out of server.py; behaviour unchanged. See README "Layout".
"""

from __future__ import annotations

import re
import sys
import threading
import time
import bullish
import diskcache

import server as S


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
    """A browser declared `symbols`: replace the stored list and persist it.
    Runs from the route thread; the list swaps whole under the lock, so a
    warmer pass sees either the old world or the new one, never a splice.
    The disk write lives inside the lock too -- outside it, two simultaneous
    declarations could land out of order."""
    global _watch_union
    cleaned = _clean_watch(symbols)
    with _watch_lock:
        _watch_union = cleaned
        diskcache.store_plain(S.WATCHLIST_KEY, _watch_union)


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
