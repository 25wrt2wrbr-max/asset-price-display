"""Quiet failures, said on the console instead of swallowed.

Many fetches and cache writes here are allowed to fail: the page falls back to
an older copy, or leaves a row out. That is right for the reader, but a failure
nobody can see is a failure nobody can trace. `note(where, exc)` prints one
line the first time a kind of failure happens at a place, then stays quiet for
`REPEAT` seconds and says how many more it saw in between -- so an outage
that fails a hundred tickers is a line, not a hundred.

It never raises: reporting a failure must not become one.
"""

from __future__ import annotations

import sys
import threading
import time

REPEAT = 600  # seconds between two lines about the same failure at the same place

_lock = threading.Lock()
_seen: dict[tuple[str, str], list] = {}   # (where, kind) -> [last printed, held back]
counts: dict[str, int] = {}               # where -> how many times, ever


def note(where: str, exc: BaseException | None = None) -> None:
    """Record a failure that the caller is about to carry on past."""
    try:
        kind = type(exc).__name__ if exc is not None else "failed"
        now = time.time()
        with _lock:
            counts[where] = counts.get(where, 0) + 1
            entry = _seen.get((where, kind))
            if entry is not None and now - entry[0] < REPEAT:
                entry[1] += 1
                return
            held = entry[1] if entry is not None else 0
            _seen[(where, kind)] = [now, 0]
        detail = " ".join(str(exc).split())[:200] if exc is not None else ""
        line = "  quiet failure: %s: %s" % (where, kind)
        if detail:
            line += ": " + detail
        if held:
            line += " (and %d more like it since the last report)" % held
        sys.stderr.write(line + "\n")
    except Exception:
        pass


def reset() -> None:
    """Forget what was reported. For tests."""
    with _lock:
        _seen.clear()
        counts.clear()
