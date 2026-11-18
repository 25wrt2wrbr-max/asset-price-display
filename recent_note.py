"""The recent table's status and note lines.

Split out of recent.py; behaviour unchanged. Every name here is re-exported from
`recent`, and the code reaches its names through `R.`, so a test that patches
`recent.<name>` still reaches it.
"""

from __future__ import annotations



import recent as R


def market_status(stats: dict, errors: dict, rows: list[dict]) -> list[dict]:
    """Per market: did it answer, and how fresh is what it said?

    `state` is one of:

    * `live`     -- every instrument answered.
    * `partial`  -- some did not (they are in `missing`, never judged bearish).
    * `fallback` -- Yahoo did not answer, and some bars came from Nasdaq's closes.
    * `offline`  -- the leg failed, or none of its instruments answered.

    `asOf` is the newest bar among the market's own rows (None when it has
    none), so the page can show how recent the data is per market rather than
    one sweep time for all of them.
    """
    newest: dict[str, int] = {}
    for row in rows:
        market = row.get("market")
        last = row.get("last")
        if market and isinstance(last, (int, float)):
            newest[market] = max(newest.get(market, 0), int(last))
    names = list(stats) + [name for name in errors if name not in stats]
    out = []
    for name in names:
        detail = stats.get(name) or {}
        universe = detail.get("universe") or detail.get("scanned") or 0
        missing = len(detail.get("missing") or [])
        fallback = len(detail.get("fallback") or [])
        if name in errors:
            state = "offline"
        elif universe and missing >= universe:
            state = "offline"
        elif fallback:
            state = "fallback"
        elif missing:
            state = "partial"
        else:
            state = "live"
        entry = {"market": name, "state": state, "scanned": universe,
                 "missing": missing, "fallback": fallback,
                 "asOf": newest.get(name)}
        if name in errors:
            entry["detail"] = str(errors[name])
        out.append(entry)
    return out


def kinds_line(kinds: dict) -> str:
    """`{kind: count}` -> "249 common shares, 11 preferred shares, 1 ETF, ...".

    Fixed order and empty kinds dropped, so two sweeps that differ only in
    whether an ETF listed read as one sentence with one clause changed.
    """
    parts = []
    for kind, singular, plural in R.PH_KIND_WORDS:
        count = (kinds or {}).get(kind)
        if not count:
            continue
        parts.append(f"{count} {singular if count == 1 else plural}")
    # Anything the vocabulary above did not name is still counted: an
    # unlisted kind must not vanish from a figure whose whole job is honesty
    # about coverage.
    named = {kind for kind, _, _ in R.PH_KIND_WORDS}
    others = sum(count for kind, count in (kinds or {}).items()
                 if kind not in named)
    if others:
        parts.append(f"{others} other listing{'s' if others != 1 else ''}")
    return ", ".join(parts)


def ph_scan_line(detail: dict) -> str | None:
    """The Philippine scan as one sentence: "263 scanned (249 common shares...)".

    None when the sweep's own account of its universe did not travel (a table
    read from an older disk copy): a made-up count would be worse than the
    shorter line this note had before.
    """
    universe = detail.get("universe")
    if not universe:
        return None
    line = R.kinds_line(detail.get("kinds") or {})
    return f"Philippines: {universe} scanned" + (f" ({line})" if line else "")


def summarize(payload: dict) -> str:
    """One line for the card's note: what was judged, and what answered."""
    rows = len(payload.get("rows") or [])
    stats = payload.get("stats") or {}
    parts = [f"{rows} rows"]
    # Absent on a sweep stored before bearish rows were kept. A zero is only
    # printed once this scan actually looked.
    if "bearish" in payload:
        parts.append(f"{len(payload.get('bearish') or [])} bearish")
    if payload.get("leaning") is not None:
        parts.append(f"{len(payload['leaning'])} leaning bullish")
        # The leaning list is filtered onto app.ondo.finance (see
        # `actionable`), so the note says so -- and says when it could not be,
        # rather than letting an outage read like a shelf that carries none.
        if payload.get("ondoShelf"):
            parts.append("United States rows are Ondo-listed only")
        elif payload["leaning"]:
            parts.append("Ondo list unavailable — leaning rows unfiltered")
    for market, detail in stats.items():
        count = detail.get("count")
        universe = detail.get("universe")
        missing = len(detail.get("missing") or [])
        stale = detail.get("stale") or []
        # The United States leg's universe is the Ondo shelf when it was read,
        # and the scanner's turnover ranking only when it was not. Which one it
        # was is a fact about the sweep, so the note says it instead of letting
        # "478 scanned" imply the shelf when it was a ranking.
        label = market
        if market == "US" and detail.get("shelf") is False:
            label = "US (turnover universe)"
        # The makeup of the Philippine universe, when the sweep sent it: the
        # leg's own line already says "263 scanned", and this says of what.
        breakdown = R.kinds_line(detail.get("kinds") or {})
        if count is not None and universe:
            # A leg that judged a fixed list and kept only the bullish ones --
            # the bond yields -- says both numbers, so a leg with no rows reads
            # as "nothing turned" and not as "nothing was looked at".
            parts.append(f"{label}: {universe} scanned"
                         + (f" ({breakdown})" if breakdown else "")
                         + ("" if count >= universe else f", {count} bullish"))
        elif count is not None:
            parts.append(f"{label}: {count}")
        elif universe:
            parts.append(f"{label}: {universe} scanned"
                         + (f" ({breakdown})" if breakdown else "")
                         + (f", {missing} did not answer" if missing else ""))
        fallback = detail.get("fallback") or []
        if fallback:
            parts.append(f"{len(fallback)} read from Nasdaq closes — Yahoo did not answer")
        hidden = detail.get("hidden")
        if hidden:
            # The floor hides rows, so the note says how many it hid --
            # across both tables, since it applies to a market and not to
            # one of them. A name that is bullish on its own chart and
            # absent from the table has to be explained on the page.
            parts.append(f"{hidden} below ₱{R.MIN_TURNOVER_PHP:,} volume hidden")
        if stale:
            # A series whose source stopped printing is not judged, so the note
            # names it and dates its last bar: the alternative is a name that
            # was in the table yesterday and is gone today with no word, which
            # is exactly what the reader objected to about the peso floor.
            # Three names at most -- this is a one-line note, and the count
            # carries the rest.
            named = ", ".join(
                "%s (last bar %s)" % (entry.get("ticker"), entry.get("lastBar"))
                for entry in stale[:3] if entry.get("ticker"))
            more = "" if len(stale) <= 3 else f" and {len(stale) - 3} more"
            parts.append(f"{len(stale)} stale series hidden: {named}{more}")
    errors = payload.get("errors") or {}
    for market, message in errors.items():
        parts.append(f"{market} unavailable")
    fx = payload.get("fx") or {}
    if fx.get("phpPerUsd"):
        parts.append(f"Converted at USDPHP {fx['phpPerUsd']}")
    elif payload.get("fxError"):
        parts.append("no peso-dollar rate — peso volume figures unavailable")
    return " · ".join(parts)
