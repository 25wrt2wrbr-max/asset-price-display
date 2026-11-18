"""Data-quality checks on a daily series, so a bad feed is flagged, not trusted.

A row or chart built from broken bars should say so beside the verdict. These
checks only *describe* the series; they never change a label, never hide a
row, and never fetch anything. (A series that stopped printing altogether is a
different case, handled by `recent.stale_gap`.)

Each flag is `{"code": ..., "text": ...}`. The codes:

* `bad_price`  -- a close that is zero, negative or not a number.
* `unordered` -- timestamps that repeat or run backwards.
* `gap`       -- two neighbouring bars further apart than `MAX_GAP_DAYS`.
* `jump`      -- one bar moved by more than `JUMP_RATIO` (a split, or a bad print).
* `frozen`    -- the last `FROZEN_RUN` closes are identical.
* `no_volume` -- most of the recent bars carry no volume (only when the market has one).
"""

from __future__ import annotations

import math

MAX_GAP_DAYS = 10        # holidays and weekends stay well under this
JUMP_RATIO = 0.5         # a single bar moving more than 50%
FROZEN_RUN = 10          # identical closes in a row, newest end of the series
VOLUME_LOOKBACK = 20
VOLUME_MISSING_SHARE = 0.5
DAY = 86_400


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def check(stamps, closes, volumes=None, *, volume: bool = True) -> list[dict]:
    """The flags for one series, empty when it looks sound.

    `volume` says whether the market has trading volume at all: a fund or a
    yield has none, and "no volume" is not a defect there.
    """
    flags: list[dict] = []
    n = min(len(stamps or []), len(closes or []))
    if n == 0:
        return flags
    stamps = list(stamps)[:n]
    closes = list(closes)[:n]

    if any(not _is_number(c) or c <= 0 for c in closes):
        flags.append({"code": "bad_price",
                      "text": "A close is zero, negative or missing"})

    numeric_stamps = [s for s in stamps if _is_number(s)]
    if len(numeric_stamps) != n or any(b <= a for a, b in zip(stamps, stamps[1:])):
        flags.append({"code": "unordered",
                      "text": "Bar dates repeat or run backwards"})
    else:
        widest = max(((b - a) / DAY for a, b in zip(stamps, stamps[1:])), default=0)
        if widest > MAX_GAP_DAYS:
            flags.append({"code": "gap",
                          "text": "A %d-day gap between two bars" % round(widest)})

    good = [c for c in closes if _is_number(c) and c > 0]
    biggest = 0.0
    for a, b in zip(good, good[1:]):
        biggest = max(biggest, abs(b / a - 1.0))
    if biggest > JUMP_RATIO:
        flags.append({"code": "jump",
                      "text": "One bar moved %.0f%% — a split or a bad print?" % (biggest * 100)})

    if len(good) >= FROZEN_RUN and len(set(good[-FROZEN_RUN:])) == 1:
        flags.append({"code": "frozen",
                      "text": "The last %d closes are identical" % FROZEN_RUN})

    if volume and volumes is not None and n >= VOLUME_LOOKBACK:
        recent = list(volumes)[-VOLUME_LOOKBACK:]
        empty = sum(1 for v in recent if not _is_number(v) or v <= 0)
        if empty / len(recent) >= VOLUME_MISSING_SHARE:
            flags.append({"code": "no_volume",
                          "text": "Most recent bars carry no volume"})
    return flags


def attach(rows, flags_by_key: dict, key: str = "chartSymbol") -> None:
    """Put `quality` on every row whose `key` has flags. Mutates `rows`."""
    for row in rows:
        flags = flags_by_key.get(row.get(key))
        if flags:
            row["quality"] = flags
