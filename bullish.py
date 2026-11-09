#!/usr/bin/env python3
"""Philippine stocks that are bullish, and how long they have been.

Why this module exists
----------------------
The chart already scores every series it draws and names the verdict in its
badge ("Bullish", "Bearish", "Neutral"). This module asks the same question of
the whole PSE universe at once and answers a second one the badge cannot: *when
did that verdict start?* It is a table of the names that are bullish now, each
dated to the bar its current run began on.

The label is the badge's, not a lookalike
-----------------------------------------
"Bullish" here means what `trend.classify` says, on the same window the chart
draws -- there is no second definition of bullish in the project and there is no
second one here. Two things follow, and both are deliberate:

* A row is included if the label on the window **the chart would draw right now**
  is bullish (see `window_now`). That is the badge on the page for that symbol,
  so clicking a row cannot show "Neutral" above a row that called it bullish.
* The onset is dated with the window **the chart would have drawn on the day
  being tested** (see `window_at`). Reconstructing an earlier verdict means
  redrawing the trim around that bar; measuring it from today instead makes the
  walk incoherent, because once the test bar crosses a fixed cutoff the window
  jumps from one bar to fifty and the label flips for no reason.

The two windows agree on every symbol whose latest bar is current, which is
nearly all of them. Where they disagree -- a stale bar makes the badge window
shorter than the anchored one -- the two rules can land either side of the call
threshold, and the row follows the badge, because that is the verdict the reader
can check. The disagreement is not rounded off: `calls` in the payload counts
rows where the walk's own first reading was not bullish, so a boundary case is
visible rather than hidden.

A run is measured in bars, not in days
--------------------------------------
The onset is the first bar of an unbroken run of bullish labels ending at the
latest bar, so it is found by walking backwards one bar at a time and stopping at
the first bar that was not bullish. Walking is cheaper than it sounds: a full
sweep of every bar would be ~53,000 classifications for the universe, while
stopping at the first break costs ~2,700, for the identical answer (`classify` is
the expensive part and the walk calls it once per bar of the runs that exist,
rather than once per bar of history).

Several names turn on the same session whenever the market moves as a whole, so
the date alone is a coarse sort. Rows sharing an onset are broken by the value
traded that session, heaviest first -- the same quantity the leaderboards rank
on: the latest bar's close times its share count, in pesos. That is not a second
liquidity measure invented here. It is the scanner's `Value.Traded` (the number
the README checks against the tape), and it is read from the bar the row is
already priced from rather than fetched separately, so a row's price and its
turnover can never belong to different sessions.

The minimum investment comes with it: the smallest cheque that can buy the
stock, which is `markets.minimum_investment` -- the one board-lot table in the
project, the same one the Philippine leaderboard's column and the chart's own
readout use, not a second copy of it.

Two hundred and seventy bars are fetched per symbol because the walk needs to
redraw a 90-calendar-day window at each bar it tests. Ninety days is ~63 trading
bars, so 270 bars is four windows of history behind the latest bar -- enough that
a run reaching the start of the data is reported as censored rather than
silently dated to a bar that only happens to be the oldest one fetched.

Standard library only. It imports `pse` for the universe and the bars, `onset`
for the window and the walk -- the label itself is `onset`'s, which is
`trend.classify`'s -- and `markets` for the board lot the minimum-investment
column is built from; it has no source of its own. `markets` imports `pse`
rather than the other way round and nothing there reaches back here, so the two
are not a cycle.
"""

from __future__ import annotations

import markets
import onset as onset_module
import pse

# The window the chart trims to, in calendar days: `pse.chart` uses
# RANGE_DAYS["3mo"], and the page's own chart is drawn at RANGE = "3mo". The
# walk itself lives in `onset`, which is where every table that asks "since
# when" gets it -- this module is the Philippine caller of it.
WINDOW_DAYS = onset_module.WINDOW_DAYS

# Every row here is a PSE listing, so every figure is in pesos. The board lot is
# read from `markets`, whose table is the exchange's; naming the currency once
# keeps the rows and the payload from disagreeing about it.
CURRENCY = "PHP"

DAY = 86400


class BullishError(RuntimeError):
    """The universe or its bars could not be had."""


def _window(stamps: list[int], end: int, anchor: int) -> list[int]:
    """Bar indices of the window `pse.chart` draws, for a series ending at `end`.

    A thin wrapper over `onset.window`, which is where the walk itself lives:
    this module is the Philippine caller of it, and the window is the same
    ninety days everywhere -- `pse.chart`'s own trim, measured back from
    `anchor` (now, for the badge's window; the bar's own stamp, for a
    reconstruction of that day).
    """
    return onset_module.window(stamps, end, anchor)


def window_now(stamps: list[int], end: int) -> list[int]:
    """The window the chart draws today -- the badge's own window."""
    return onset_module.window_now(stamps, end)


def window_at(stamps: list[int], end: int) -> list[int]:
    """The window the chart would have drawn on the day of bar `end`."""
    return onset_module.window_at(stamps, end)


def _label(closes: list[float], volumes: list, idx: list[int]) -> str | None:
    """`trend.classify`'s verdict over `idx`, or None if the slice is unusable.

    A window that cannot be scored has no label, and "no label" is not bullish,
    so an unscorable bar ends a run rather than extending it.
    """
    return onset_module.label(closes, volumes, idx)


def _series(rows: list) -> tuple[list[int], list[float], list]:
    """Socket rows -> (stamps, closes, volumes), cleaned as `pse.chart` cleans them.

    The same tolerances, for the same reasons: a malformed row is skipped rather
    than losing the series, a duplicate timestamp is dropped, and a non-positive
    price is bad data. An index carries no volume at all, so its bars have five
    fields and absent volume is not a malformed row -- the volume signal simply
    has nothing to say.
    """
    stamps: list[int] = []
    closes: list[float] = []
    volumes: list = []
    seen: set[int] = set()
    for row in rows:
        try:
            stamp = int(row[0])
            close = float(row[4])
        except (IndexError, TypeError, ValueError):
            continue
        if stamp in seen or not close > 0:
            continue
        try:
            volume = float(row[5])
        except (IndexError, TypeError, ValueError):
            volume = None
        seen.add(stamp)
        stamps.append(stamp)
        closes.append(close)
        volumes.append(volume)

    order = sorted(range(len(stamps)), key=lambda i: stamps[i])
    return ([stamps[i] for i in order], [closes[i] for i in order],
            [volumes[i] for i in order])


def onset(rows: list) -> dict | None:
    """When the current bullish run began, or None if the name is not bullish now.

    The returned `since` is the timestamp of the first bar of the run -- the bar
    the chart itself would have first labelled bullish and kept labelling so --
    and `run` is how many bars that run covers, counting the latest.

    `turnover` is the latest bar's value traded, close times volume, in pesos:
    the tie-break among names whose runs began on the same session, and the same
    figure the leaderboards rank on. It is None when the bar carries no usable
    volume -- an index, or a row whose volume field did not survive parsing -- and
    None sorts last, because it says nothing about liquidity either way.

    `censored` means the walk reached the oldest bar fetched while still bullish:
    the run is at least `run` bars long and its real start is off the end of the
    data, so the date is a floor. With 270 bars fetched and a 90-day window, that
    needs a run of well over a year's trading, and no PSE name has done it; the
    flag exists so that if one does, the date is not passed off as exact.
    """
    stamps, closes, volumes = _series(rows)
    if len(closes) < 3:
        return None

    # The walk itself is `onset`'s -- one definition of "since when", shared with
    # every other table that asks. What this module adds is the PSE cleaning of
    # the rows and the wording of what the run means for a Philippine stock.
    call = onset_module.onset(stamps, closes, volumes, want="bullish")
    if call is None:
        return None
    return call


def _universe() -> list[dict]:
    """The PSE securities to scan, in index order.

    The index is scanned too (2026-11-09): the reader asked for the PSEi in the
    tables when its own chart is bullish or leaning bullish, and the only way a
    row and its chart can agree is for the index to go through the same walk as
    the stocks. It has no volume and no board lot, so its rows carry neither --
    see `_row_extras`.
    """
    index = pse.stocks_index()
    return list(index["ordered"])


def _kinds(records: list[dict]) -> dict[str, int]:
    """`{kind: count}` over the scanned universe, for the note under the table.

    The point of the count is that a reader cannot otherwise tell 262 listings
    from a handful: the note names how many of each thing was looked at, in a
    fixed order (see `recent.kinds_line`).
    """
    counts: dict[str, int] = {}
    for record in records:
        kind = str(record.get("kind") or "UNKNOWN")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def scan(count: int = pse.BATCH_BARS) -> dict:
    """The bullish table: every PSE security bullish now, newest onset first.

    The index is one of them since 2026-11-09 (see `_universe`); the leaning
    list is built in the same pass, so an index that leans is a leaning row.

    Raises `BullishError` only when the universe itself cannot be had or no bars
    arrive at all. A symbol that does not answer is left out of the table and
    counted in `missing` -- the alternative, treating it as "not bullish", would
    put a fetch failure into the table as a fact about the stock.
    """
    universe = _universe()
    if not universe:
        raise BullishError("the PSE universe is empty")

    by_symbol = {record["symbol"]: record for record in universe}
    try:
        bars = pse.history_many(list(by_symbol), count=count)
    except pse.PseError as exc:
        raise BullishError(str(exc))

    if not bars:
        raise BullishError("no bars arrived for any PSE symbol")

    rows = []
    leaning = []
    for symbol, series in bars.items():
        record = by_symbol.get(symbol)
        if record is None:
            continue
        # An index has no volume and no board lot. Its bars carry no volume
        # column at all, so `onset` already answers None; the lot would be a
        # fiction (the index is not purchasable in board lots), so it is not
        # asked for. Everything else reads the exchange's own board lot.
        is_index = record.get("kind") == "INDEX"
        call = onset(series)
        if call is None:
            # Neutral on its chart but in the bullish hold band: a near-miss,
            # listed apart and never as a bullish row (see `onset.leaning`).
            # `steady_lean` is the table's own filter on top of it -- clear of
            # the drift line and held for days, not flickering (2026-11-07).
            lean = onset_module.steady_lean(*_series(series))
            if lean is not None:
                lot, lot_cost = ((None, None) if is_index
                                 else markets.minimum_investment(lean["price"]))
                leaning.append({
                    "symbol": symbol,
                    "chartSymbol": symbol,
                    "ticker": record["ticker"],
                    "name": record["name"],
                    "kind": record["kind"],
                    "currency": CURRENCY,
                    "lot": lot,
                    "lotCost": lot_cost,
                    # No traded value for an index: there are no shares to
                    # trade, and `None` keeps it out of the peso floor rather
                    # than reporting a zero the market never printed.
                    "turnover": None if is_index else lean["turnover"],
                    **{k: lean[k] for k in
                       ("price", "score", "significance", "progress", "bars",
                        "last", "window", "held", "holdBars")},
                })
            continue
        # The minimum investment: the board lot for this price times the price,
        # in the currency the row is quoted in. The lot table is the exchange's,
        # and the arithmetic is shared with the leaderboards and the chart so
        # all three show the same figure for the same close.
        lot, lot_cost = ((None, None) if is_index
                         else markets.minimum_investment(call["price"]))
        rows.append({
            "symbol": symbol,
            # The chart takes a PSE symbol with its venue attached -- bare `TEL`
            # is TE Connectivity -- so the row's own symbol is what it loads.
            "chartSymbol": symbol,
            "ticker": record["ticker"],
            "name": record["name"],
            "kind": record["kind"],
            "price": call["price"],
            "currency": CURRENCY,
            "lot": lot,
            "lotCost": lot_cost,
            "turnover": None if is_index else call["turnover"],
            **{k: call[k] for k in
               ("since", "run", "censored", "anchored", "manner", "turnMove",
                "score", "bars", "last", "window", "windowFirst")},
        })

    # Newest onset first. Ties -- several names turning on the same session, which
    # is what a market-wide move looks like -- are broken by that session's traded
    # value, heaviest first, so a tie falls to the quantity the leaderboards rank
    # on rather than to something this table invented. A row with no volume sorts
    # last among its own date whatever its run: silence about liquidity is not
    # evidence of it. The longer run and then the ticker finish the order, so two
    # scans agree on a total one.
    rows.sort(key=lambda row: (-row["since"], -(row["turnover"] or 0.0),
                               -row["run"], row["ticker"]))

    return {
        "label": "Bullish Philippine stocks",
        "currency": CURRENCY,
        "source": "TradingView",
        "rows": rows,
        # Closest to the entry bar first.
        "leaning": sorted(leaning, key=lambda row: (-row["progress"],
                                                    row["ticker"])),
        "universe": len(universe),
        # How many of each thing the universe holds -- common shares, preferred
        # shares, an ETF, a closed-end fund, the index. The notes under both
        # tables print this, so a reader can see the breadth of the scan rather
        # than take a row count on trust.
        "kinds": _kinds(universe),
        "fetched": len(bars),
        "missing": sorted(set(by_symbol) - set(bars)),
        # Rows where the anchored window and the badge's window disagreed about
        # the latest bar -- the boundary cases described in the docstring.
        "boundary": sum(1 for row in rows if not row["anchored"]),
        "censored": sum(1 for row in rows if row["censored"]),
        # Why each run began (onset.manner): a "turn" is the series itself
        # having moved, "flat" is the window's oldest bar having left it. Counted
        # rather than filtered -- the manner is not a forecast and must not
        # remove a row whose own chart calls it bullish.
        "turns": sum(1 for row in rows if row["manner"] == "turn"),
        "flat": sum(1 for row in rows if row["manner"] == "flat"),
        "against": sum(1 for row in rows if row["manner"] == "against"),
        "error": None,
    }


def summarize(payload: dict) -> str:
    """One line for the card's note: what was scanned, and how much of it answered."""
    rows = len(payload.get("rows") or [])
    scanned = payload.get("fetched") or 0
    universe = payload.get("universe") or 0
    note = f"{rows} of {scanned} scanned bullish"
    if scanned < universe:
        note += f" ({universe - scanned} did not answer)"
    return note