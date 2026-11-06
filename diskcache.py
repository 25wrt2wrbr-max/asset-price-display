#!/usr/bin/env python3
"""Durable cache so the page still has data when the sources do not.

What this is for
----------------
`server.py` already memoises every upstream answer in memory, but a memo dies
with the process and a TTL expiry re-asks the network -- so offline, or with
Moli or Yahoo down, an expired page shows an error where it had a perfectly
good answer minutes ago. This module keeps the last good answer for each cache
key in a JSON file under `.cache/`, and hands it back when a fresh fetch fails.

It is deliberately *not* a second cache tier in front of the live one. The
in-memory `cached()` stays the fast path and the source of truth while the
server runs; disk is written on every success and read when a fetch raises a
transport error -- the same rule `bullish.py`'s sweeper applies in memory
("a failed refresh leaves the previous payload alone"), made to survive a
restart.

Honesty
-------
A value stored here is a statement about the past, so every record carries the
epoch second it was produced, and `load` hands that back beside the value: the
page says "data last retrieved ..." with *retrieval* time, never service time.
`MAX_AGE` (30 days) is the point where an old chart stops being "older data"
and starts being a rumor, so anything past it reads as absent even for a
request that could not reach the network.

Failure policy
--------------
Every filesystem problem -- full disk, permissions, a file edited into
garbage, a write interrupted mid-way -- degrades to "no cached copy", never to
an exception. The cache is a convenience bolted onto a live path; a broken
convenience must not take the real answer down with it.

Standard library only, like everything else here.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time

# A copy older than this reads as absent. The page's longest window is five
# years of weekly bars, so a thirty-day-old answer is still *about* the asset
# being charted; past a month it stops being worth serving offline.
MAX_AGE = 30 * 24 * 3600

# Most files kept, whatever their age: every symbol a reader charts is a file,
# and a personal tool should not turn into a ten-thousand-file junk drawer.
# ~2000 payloads of ~30 KB is a fraction of a gigabyte; past that the oldest
# (by mtime, which is when they were written, which is when they were
# retrieved) are the least likely to be asked for again.
MAX_FILES = 2000

# The sweep runs on this cadence from `store`, so pruning costs one directory
# listing per few hundred writes rather than per request.
_PRUNE_EVERY = 200

_state_lock = threading.Lock()
_writes = 0


def dir() -> str:
    """The cache directory, beside this file, hidden, overridable by
    `APD_CACHE_DIR` (same variable the server's health route reports)."""
    return os.environ.get("APD_CACHE_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".cache")


# The suffix marking a declared record (see `store_plain`), chosen so a plain
# record is separable from a cache copy by *name*: the two kinds age under
# different rules, and reading the extension costs `prune` nothing against
# reading every file's contents to tell them apart.
PLAIN_SUFFIX = ".plain.json"


def _path(key: str, plain: bool = False) -> str:
    """File path for a cache key. Keys are URLs and synthetic strings with
    slashes, colons and arbitrary text in them, so the file *name* is a hash;
    the key itself lives inside the record and `load` compares against it --
    two keys whose hashes collided (astronomically unlikely for SHA-256, but
    the check costs one line) cannot cross-serve."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return os.path.join(dir(), digest + (PLAIN_SUFFIX if plain else ".json"))


def count() -> int:
    """Stored entries now on disk (for `/api/health`); 0 if the directory does
    not exist yet. Declared records (`store_plain`) are excluded -- a list the
    client told us is not an upstream copy we are holding for a rainy day."""
    try:
        return sum(1 for name in os.listdir(dir())
                   if name.endswith(".json") and not name.endswith(PLAIN_SUFFIX))
    except OSError:
        return 0


def store(key: str, value: object) -> None:
    """Remember `value` for `key`, stamped with the current time.

    The write goes to a temp file and is renamed over the target, because a
    reader -- the next process start, after a power loss mid-write -- must see
    either the old value whole or the new one whole; a half-written JSON file
    is a cache miss at best and a crash at worst if something parsed it
    eagerly. `os.replace` is atomic within one filesystem, which the temp file
    is forced onto by living beside its target.

    Best-effort by policy: any OSError is swallowed with a warning to stderr,
    because failing to *save* the future's fallback must not fail the present's
    request.
    """
    global _writes
    path = _path(key)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        os.makedirs(dir(), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"key": key, "fetchedAt": time.time(), "value": value},
                      fh, separators=(",", ":"))
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError) as exc:
        # TypeError/ValueError: `value` holds something JSON cannot encode --
        # a producer should never return that, but the policy is the same.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        sys.stderr.write(f"  diskcache: could not store {key[:60]!r}: {exc}\n")
        return

    with _state_lock:
        _writes += 1
        due = _writes % _PRUNE_EVERY == 0
    if due:
        prune()


def prune() -> None:
    """Drop copies past `MAX_AGE`, leftovers of interrupted writes, and the
    oldest entries once the directory passes `MAX_FILES`.

    Called from `store` every few hundred writes and once at server startup,
    so a folder of months-old symbols shrinks itself without a request ever
    waiting on it. mtime is the age: a file's last write is when it was
    retrieved, so the same clock the records carry.
    """
    now = time.time()
    try:
        names = os.listdir(dir())
    except OSError:
        return
    kept: list[tuple[float, str]] = []
    for name in names:
        path = os.path.join(dir(), name)
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue  # raced with its own deletion
        if name.endswith(".tmp"):
            try:
                os.unlink(path)
            except OSError:
                pass
            continue
        if name.endswith(PLAIN_SUFFIX):
            continue  # declared, not retrieved: never ages, never counts
        if not name.endswith(".json"):
            continue
        if now - mtime > MAX_AGE:
            try:
                os.unlink(path)
            except OSError:
                pass
            continue
        kept.append((mtime, path))
    if len(kept) > MAX_FILES:
        kept.sort()
        for _mtime, path in kept[:len(kept) - MAX_FILES]:
            try:
                os.unlink(path)
            except OSError:
                pass


def store_plain(key: str, value: object) -> None:
    """Remember `value` for `key` with no retrieval stamp, forever.

    For the facts a *client declares* rather than the data a producer fetched --
    today, the browser's watchlist (`server.py`'s `watchlist` section). Two
    properties separate these records from `store`'s: they carry no `fetchedAt`,
    and `prune` leaves them alone entirely -- never aged, never evicted. A
    declared list has no retrieval time to report (promoting it to a cache
    entry would put a fake `fetchedAt` beside the server's real cache records,
    whose docstring promises that field is "the epoch second it was produced"),
    and its value is *membership*: a row the user saved months ago must survive
    a weekend offline, where `MAX_AGE` would delete the declaration and the
    server would forget the list it was explicitly told. There is no
    unbounded-growth risk to trade against either -- the keys are server
    constants, not per-symbol, so the folder holds a handful of these, not ten
    thousand.

    Same atomic temp-and-rename and same swallow-everything failure policy as
    `store`; the module header's "a broken convenience must not take the real
    answer down with it" applies identically here.
    """
    global _writes
    path = _path(key, plain=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        os.makedirs(dir(), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"key": key, "value": value},
                      fh, separators=(",", ":"))
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError) as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        sys.stderr.write(f"  diskcache: could not store {key[:60]!r}: {exc}\n")
        return

    with _state_lock:
        _writes += 1
        due = _writes % _PRUNE_EVERY == 0
    if due:
        prune()


def load_plain(key: str) -> object | None:
    """The last stored plain value for `key`, or None.

    The same fail-silent policy as `load` -- absent, unreadable, corrupt, or a
    stale temp file all read as "nothing declared" -- and the same
    key-inside-the-record check, so a hash collision cannot cross-serve. The
    two kinds of record never meet: they live under different suffixes.
    """
    path = _path(key, plain=True)
    try:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("key") != key:
        return None
    return record.get("value")


def load(key: str) -> tuple[float, object] | None:
    """The last stored `(fetchedAt, value)` for `key`, or None.

    None means "no usable copy": absent, unreadable, corrupt, not JSON, or
    older than `MAX_AGE`. Every one of those is decided here so callers have a
    single shape to handle, and none of them raises -- reading the fallback is
    allowed to fail silently, since the caller's live path already failed
    loudly and this was the rescue attempt.
    """
    path = _path(key)
    try:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("key") != key:
        return None
    fetched_at = record.get("fetchedAt")
    value = record.get("value")
    if not isinstance(fetched_at, (int, float)) or value is None:
        return None
    if time.time() - float(fetched_at) > MAX_AGE:
        return None
    return float(fetched_at), value
