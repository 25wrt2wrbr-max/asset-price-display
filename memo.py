"""The memo every route and warmer reads through: \`cached\` and its disk fallback.

Split out of server.py on 2026-11-20, same \`S.x\` pattern as \`sweeps.py\`: the
memo's state (\`_cache\`, \`_cache_lock\`, \`_flights\`) stays in server.py, every
function body reads server's names as \`S.x\`, and server.py re-exports every
name here, so \`server.cached\` and \`mock.patch.object(server, ...)\` still work.
"""

from __future__ import annotations

import threading
import time

import faults
import server as S


class _Flight:
    """One in-progress `cached()` production, shared by every waiter on its key.

    `leader` is claimed under `S._cache_lock` by the thread that produces;
    everyone else waits on `done` and reads `value` or re-raises `error`.
    """

    __slots__ = ("done", "value", "error")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.value = None
        self.error = None


# Errors that mean "the network did not answer" rather than "this symbol does
# not exist". Only these are rescued from disk: a genuine "no such symbol" is a
# settled verdict about the instrument, while an outage says nothing about it
# and every caller deserves the fallback. `LookupError` deliberately absent --
# that is the verdict kind.
TRANSIENT_ERRORS = (
    S.UpstreamError, S.pse.PseError, S.markets.MarketError, S.crypto.CryptoError,
    S.ecb.EcbError, S.tv.TvError, S.ondo.OndoError, S.phfunds.FundError,
)


def is_transient(exc: Exception) -> bool:
    # `PseNotFound` subclasses `PseError` but is a verdict, not an outage --
    # "TradingView has no symbol X" is an answer about X, and disk must not
    # overrule an answer by serving some older moment's data under its name.
    return isinstance(exc, S.TRANSIENT_ERRORS) and not isinstance(
        exc, S.pse.PseNotFound)


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


MEMO_PRUNE_AT = 256      # entries before expired ones are swept out
MEMO_MAX_AGE = 3600      # seconds: the longest ttl any caller passes


def _revalidate_worker(key: str, produce, ttl: float, usable, flight: _Flight) -> None:
    """Background refresh after stale-while-revalidate.

    A transport failure leaves the stamped disk copy already served to the
    page; the flight closes without an error so waiters without a disk copy
    retry on their next call rather than inheriting a stuck failure.
    """
    try:
        try:
            value = produce()
        except Exception as exc:
            # Keep last-good memo if present; never promote a transient outage
            # into "not bullish" for table consumers.
            if not S.is_transient(exc):
                flight.error = exc
            return
        if usable is not None and not usable(value):
            return
        S.diskcache.store(key, value)
        with S._cache_lock:
            now = time.time()
            if len(S._cache) > MEMO_PRUNE_AT:
                for old in [k for k, v in S._cache.items() if now - v[0] > MEMO_MAX_AGE]:
                    del S._cache[old]
            S._cache[key] = (now, value)
        flight.value = value
    finally:
        with S._cache_lock:
            if S._flights.get(key) is flight:
                S._flights.pop(key, None)
        flight.done.set()


def cached(key: str, produce, ttl: float = S.CACHE_TTL, usable=None):
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
    with S._cache_lock:
        hit = S._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        # The leader claim happens under the same lock as the map lookup, so
        # two simultaneous misses cannot both start producing.
        flight = S._flights.get(key)
        leader = flight is None
        if leader:
            flight = S._flights[key] = _Flight()

    expired = not (hit and now - hit[0] < ttl)
    stale = None
    if expired:
        # A disk copy that cannot be read must not escape here: the flight is
        # already claimed, and leaving it open would hang every later caller
        # for this key. With no stale copy the key is simply produced afresh.
        try:
            stale = S._stamp_copy(key, "revalidating", usable)
        except Exception as exc:  # noqa: BLE001 - disk or usable check, any kind
            faults.note("memo stale copy", exc)
            stale = None
        if stale is not None:
            stale["revalidate"] = True

    if leader and stale is not None:
        threading.Thread(
            target=_revalidate_worker,
            args=(key, produce, ttl, usable, flight),
            daemon=True,
        ).start()
        return stale

    if not leader:
        if stale is not None:
            return stale
        # Another thread is already producing this key: wait for its answer
        # instead of starting a duplicate fetch.
        flight.done.wait()
        if flight.error is not None:
            raise flight.error
        return flight.value

    try:
        try:
            value = produce()
        except Exception as exc:
            fallback = (S._stamp_copy(key, str(exc) or type(exc).__name__, usable)
                        if S.is_transient(exc) else None)
            if fallback is None:
                flight.error = exc
                with S._cache_lock:
                    S._flights.pop(key, None)
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
                fallback = S._stamp_copy(
                    key, "sources unreachable (all sections failed)", usable)
                if fallback is None:
                    # Nothing to rescue: serve the failing payload as-is, but
                    # un-memoized and with the flight closed, so the next caller
                    # tries the network again rather than inheriting this outage.
                    with S._cache_lock:
                        S._flights.pop(key, None)
                    flight.value = value
                    flight.done.set()
                    return value
                value = fallback
            else:
                S.diskcache.store(key, value)

        with S._cache_lock:
            now = time.time()
            # Expired entries used to stay for the life of the process (charts are
            # 30-60 KB each). An hour is the longest lifetime any caller asks for,
            # so an entry older than that can never be served as a hit again.
            if len(S._cache) > MEMO_PRUNE_AT:
                for old in [k for k, v in S._cache.items() if now - v[0] > MEMO_MAX_AGE]:
                    del S._cache[old]
            S._cache[key] = (now, value)
            S._flights.pop(key, None)
        flight.value = value
        flight.done.set()
        return value
    except BaseException as exc:
        # Whatever went wrong past the producer (a disk copy that cannot be
        # read, a `usable` check that raises), the flight must close: a flight
        # left open would hang every later caller for this key.
        if not flight.done.is_set():
            flight.error = exc
            with S._cache_lock:
                if S._flights.get(key) is flight:
                    S._flights.pop(key, None)
            flight.done.set()
        raise


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
    saved = S.diskcache.load(key)
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
