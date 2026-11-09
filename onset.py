#!/usr/bin/env python3
"""When did a series turn? One window, one label, one walk.

Why this module exists
----------------------
The page asks the same question of three kinds of instrument -- a Philippine
stock, a US stock, a crypto coin, a Philippine government bond yield -- and
wants the same answer every time: *is it bullish now, and since when?* The
label itself already has exactly one definition in this project: `trend.classify`.
What was missing was the second half -- the date the current run began -- and
until now each table that wanted it grew its own copy of the walk. Two copies
of a walk are two answers, and they disagree at the edges.

So the walk lives here, once, and every table that asks "since when" asks it
here. `bullish.py` (the Philippine sweep) is the first caller; the combined
recent-assets table is the second.

The window is the chart's window
--------------------------------
A verdict is only meaningful against the bars it was read from, so the walk
redraws the same three-month window the chart draws at every bar it tests:
90 calendar days, which is ~63 daily bars on an exchange and 90 on a coin
that trades every day -- the window the page's own chart is drawn at, every
bar of which `trend.classify` scores.

Two window shapes, because the sources draw different windows
-------------------------------------------------------------
The window is the chart's window, and the charts do not all cut it the same
way:

* **Ninety days** (`WINDOW_DAYS`) for the sources whose own chart trims in
  days: the Philippine exchange (`pse.RANGE_DAYS["3mo"]`), Binance's daily
  candles, and the Philippine bond yields.
* **Three calendar months** (`WINDOW_MONTHS`) for Yahoo, whose `range=3mo`
  is three *calendar* months and not ninety days. On 2026-10-30 Yahoo answers
  SPY with the bars from 2026-07-30; a ninety-day window starts on 2026-08-01.
  `trend.classify` scores every bar it is given, so two windows two sessions
  apart are two slightly different inputs; the walk asks for the window the
  chart draws, and the shape of that window is the caller's to say. (Version
  1 of the classifier had a regime cliff at 63 bars that made this
  difference flip SPY's label; version 2 has no cliff, but a row must still
  be the verdict its own chart shows.)

The rule this enforces: **a row and the chart its click opens read the same
bars.** The United States rows of the recent table are judged on Yahoo's three
calendar months for exactly this reason.

Two windows, two jobs
---------------------
* `window_now` is the window the chart draws *right now* -- the badge's own
  window. It decides whether a name appears in a table at all: a row is
  included when the label on the window the chart would draw today is bullish,
  so clicking a row can never show "Neutral" above a row that called itself
  bullish.
* `window_at` is the window the chart *would have drawn* on the day of a
  given bar. It is what the walk uses, because reconstructing an earlier
  verdict means redrawing the trim around that bar; measuring the past from
  today's trim instead makes the walk incoherent, since the moment the tested
  bar crosses a fixed cutoff the window jumps from one bar to fifty and the
  label flips for no reason.

The two agree on every series whose latest bar is current. Where they do not
-- a stale bar makes the badge's window shorter than the anchored one -- the
row follows the badge, because that is the verdict a reader can check, and the
disagreement is counted rather than rounded off (`anchored` in the result).

A run is measured in bars, not in days
--------------------------------------
The onset is the first bar of an unbroken run of like labels ending at the
latest bar, found by walking backwards one bar at a time and stopping at the
first bar that was not like it. Bars, because the label is decided a bar at a
time: a run of five is five sessions of it, however far apart they fell. Days
would be a different unit, and one the label never spoke in.

Why a run began is a second question, and `manner` answers it
-------------------------------------------------------------
The date says *when* a run began. It does not say what changed, and on a
rolling window two very different things produce the same label flip:

* **The series turned.** The asset reversed: the recent bars moved in the new
  direction, and the label followed them.
* **The window's base moved.** The oldest bar is the denominator of the
  window's return (`P_end / P_start`). A crash that has aged out of the window
  lifts that return with the price standing still -- the label improves because
  the starting point changed, not because anything happened.

`manner` separates them by reading the same bars the walk already has, over the
last `TURN_BARS` bars *of the run's first bar* -- the moment the label flipped
-- never over today's bars. It is not a second classifier and it does not vote:
the label is exactly the label `trend.classify` gave, and every row in every
table is still the verdict its own chart draws.

The move is reported in the **run's own direction**, so one number and one rule
hold for every caller: a bullish run on a price and a bearish run on a bond
yield (a falling yield, which is what a bond row asks for) both read `turn`
when the series itself moved the way the run says. Measured (2026-10-31, 316
symbols, 663,174 bars, 2,496 bullish runs that followed a bearish regime):

    86.9%  turn      last 20 bars +9.4% median, close at the window's high
    11.8%  flat      last 20 bars +0.8% median -- the crash aged out
     1.3%  against   last 20 bars -3.6% median

So the artifact is real but uncommon: the label is rarely describing something
that did not happen. What it is *not* is a forecast -- the three groups' next
three months were 49.7%, 49.8% and 53.1% up, which is a coin flip, exactly as
every other study in `research/` found. It says how much to trust the *flip*,
not where the price goes. `flat` runs are, however, 2.5x more likely to fall
back to the labels they came from within twenty bars (6.1% vs 2.4%), so it is
the sturdiness of the run being reported, not its future.

`manner` is None when the run begins on the oldest bar fetched (there are no
bars before it to read, and a censored date already says the start is a floor),
or when there are fewer than `TURN_BARS` bars behind it. An absent reading is
left absent rather than guessed -- the same rule as every other missing value
in this project.

Standard library only, like the rest of the project: it imports `trend` for
the label and nothing else.
"""

from __future__ import annotations

import calendar
import datetime
import time

import trend

# The window the chart trims to, in calendar days. 90 days is the page's own
# three-month range (`pse.RANGE_DAYS["3mo"]`, the chart route's `3mo`, and the
# page's `RANGE` constant), so the walk reads the same bars the badge does.
WINDOW_DAYS = 90

DAY = 86400

# The window Yahoo's own three-month span draws: three *calendar* months back
# from today, which is not the same as ninety days (see the module docstring).
# Verified against Yahoo on 2026-10-30: `range=3mo` answered with the bars
# from 2026-07-30, `range=6mo` with 2026-04-30 and `range=1y` with
# 2025-10-30 -- each exactly three calendar months, six calendar months and
# twelve calendar months before the day of the request.
WINDOW_MONTHS = 3

# How far back the "why did this run begin" read looks, in bars, and how much of
# a move counts as a move. Twenty bars is about a month of trading -- long
# enough to hold a turn, short enough that a crash still inside the window has
# not yet aged out of it. Two percent over that span is the threshold the
# measurements in the module docstring were taken at; it is deliberately coarse,
# because the three answers are only meant to distinguish a real reversal from a
# standing-still one, and a finer cut would claim a precision the label does not
# have.
TURN_BARS = 20
TURN_MOVE = 0.02


def day_start(ts: int) -> int:
    """The UTC midnight of the day `ts` falls in."""
    return ts - (ts % DAY)


def months_back(ts: int, months: int) -> int:
    """The UTC midnight of the day `months` calendar months before `ts`'s day.

    This is the rule Yahoo's own `range=` spans use, and the one the chart's
    window has to follow for the chart and the table to read the same bars.
    Month arithmetic is not day arithmetic: 2026-10-30 minus three calendar
    months is 2026-07-30, which is 92 days back, not 90 -- and the two days
    in between are two trading sessions the chart draws.

    A day that does not exist in the target month (the 31st of a 30-day
    month) is pulled back to that month's last day, which is what a calendar
    does when you walk back into a shorter month.
    """
    moment = datetime.datetime.fromtimestamp(day_start(ts),
                                              datetime.timezone.utc)
    year, month = moment.year, moment.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return int(datetime.datetime(year, month, day,
                                  tzinfo=datetime.timezone.utc).timestamp())


def window(stamps: list[int], end: int, anchor: int,
           days: int = WINDOW_DAYS, months: int | None = None) -> list[int]:
    """Bar indices of the window that ends at bar `end`, measured back from `anchor`.

    `anchor` is the timestamp the window is measured back from, and it is the
    whole difference between the badge's window and a reconstruction of an
    earlier one: today, the window is measured back from now; on the day of bar
    `end`, it is measured back from that day's bar.

    `months` asks for a calendar-months window (Yahoo's own spans) and `days`
    for the ninety-day one. Exactly one of them is used: `months` when it is
    given, `days` otherwise.

    Mirrors the chart's own trim, including its fallback: if the window would
    hold fewer than two bars -- a series that has gone quiet for longer than
    the window, so the chart would be blank -- it takes the last `MIN_BARS`
    bars instead.
    """
    cutoff = (months_back(anchor, months) if months
              else anchor - days * DAY)
    start = next((i for i in range(end + 1) if stamps[i] >= cutoff), None)
    if start is None or end - start + 1 < 2:
        start = max(0, end + 1 - max(2, trend.MIN_BARS))
    return list(range(start, end + 1))


def window_now(stamps: list[int], end: int, days: int = WINDOW_DAYS,
               months: int | None = None) -> list[int]:
    """The window the chart draws today -- the badge's own window."""
    return window(stamps, end, int(time.time()), days=days, months=months)


def window_at(stamps: list[int], end: int, days: int = WINDOW_DAYS,
              months: int | None = None) -> list[int]:
    """The window the chart would have drawn on the day of bar `end`."""
    return window(stamps, end, stamps[end], days=days, months=months)


def label(closes: list[float], volumes: list, idx: list[int]) -> str | None:
    """`trend.classify`'s verdict over the bars `idx` names, or None.

    A window that cannot be scored has no label, and "no label" is not
    bullish, so an unscorable bar ends a run rather than extending it.
    """
    try:
        return trend.classify([closes[i] for i in idx],
                              [volumes[i] for i in idx])["label"]
    except (ValueError, IndexError):
        return None


def turn(closes: list[float], start: int, want: str) -> tuple[str | None, float | None]:
    """Did the series itself move when the run began, or only the window's base?

    Read at `start`, the run's first bar -- the moment the label flipped -- over
    the `TURN_BARS` bars before it, and signed in the run's own direction so
    that one rule holds for a price and for a bond yield alike. Returns
    `(manner, move)`:

    * `"turn"`    -- the series moved with the run (`move >= TURN_MOVE`), which
      is what a reversal looks like: the recent bars are the ones that did it.
    * `"against"` -- it moved the other way (`move <= -TURN_MOVE`), so the run
      is being carried by the window's base while the series itself drifts
      back. The least trustworthy of the three.
    * `"flat"`    -- it went nowhere (`|move| < TURN_MOVE`). The run began
      because the oldest bar -- the return's denominator -- left the window.

    `move` is that same quantity, so a caller can print the number the word was
    cut from. Both are `None` when there are not `TURN_BARS` bars behind `start`
    (a censored run has none at all): no reading rather than an invented one.
    """
    if start < TURN_BARS:
        return None, None
    base = closes[start - TURN_BARS]
    if not base > 0:
        return None, None
    move = closes[start] / base - 1.0
    if want == "bearish":
        move = -move
    if move >= TURN_MOVE:
        return "turn", move
    if move <= -TURN_MOVE:
        return "against", move
    return "flat", move


def current(stamps: list[int], closes: list[float], volumes: list,
           days: int = WINDOW_DAYS, months: int | None = None) -> dict | None:
    """The badge's own call on the latest bar: the label and score of today.

    This is the question the chart's badge answers, asked of a series rather
    than of a chart. `None` when the series cannot be scored at all.

    A table row that shows a direction needs this, not just the run: the run
    is the *date* the direction began, and the direction is the call that
    begins it. For a price the two are the same thing -- bullish is bullish --
    but for a yield they are not: the same algorithm read over a yield series
    calls a falling yield "bearish", because the numbers are falling, and the
    reader wants both halves said out loud.
    """
    n = len(closes)
    if n < 3 or len(stamps) != n:
        return None
    used = window_now(stamps, n - 1, days=days, months=months)
    try:
        call = trend.classify([closes[i] for i in used],
                              [volumes[i] for i in used])
    except (ValueError, IndexError):
        return None
    return {
        "label": call["label"],
        "score": call["score"],
        "confidence": call["confidence"],
        "window": len(used),
        "bars": n,
    }


def leaning(stamps: list[int], closes: list[float], volumes: list,
            want: str = "bullish", days: int = WINDOW_DAYS,
            months: int | None = None) -> dict | None:
    """The badge's window when it reads Neutral but leans `want`, else None.

    "Leaning" is `trend.classify`'s own `lean`: the latest window sits in the
    hold band on `want`'s side (score >= HOLD_SCORE, drift t >= HOLD_T) but has
    not met the entry bar, so the badge says Neutral. It is the same call on
    the same window the chart draws -- a near-miss of the one definition of
    bullish, not a second one -- and it has no run and no date, because no
    label was ever given.
    """
    n = len(closes)
    if n < 3 or len(stamps) != n:
        return None
    used = window_now(stamps, n - 1, days=days, months=months)
    try:
        call = trend.classify([closes[i] for i in used],
                              [volumes[i] for i in used])
    except (ValueError, IndexError):
        return None
    if call["label"] != "neutral" or call["lean"] != want:
        return None
    volume = volumes[n - 1]
    return {
        "score": call["score"],
        "significance": call["significance"],
        "progress": call["progress"],
        "bars": n,
        "last": stamps[n - 1],
        "price": closes[n - 1],
        "turnover": closes[n - 1] * volume if volume else None,
        "window": len(used),
    }


# The leaning table's steadiness rule, at the reader's request (2026-11-07):
# "is there a way to filter out 'fragile' stocks like AAPL from being shown to
# me? it's been going Neutral to leaning bullish and then back to Neutral
# multiple times now".
#
# Measured over the last 120 sessions on 464 shelf names before the rule was
# chosen: the median name flipped its leaning tag 4 times, and among the names
# leaning on the day measured the median was 10 (AAPL 14, its drift reading
# running 1.26, 1.42, 1.26, 1.01, 0.76, 1.19, 1.02, 1.01). A tag on the 1.00
# line is one soft bar from gone, and a reader watching it learns nothing.
#
# The two conditions are measured, not stylistic: the same 120 sessions say this
# pair cuts the median name's flips from 4 to 0 and the count of tag episodes
# across the population from 1,024 to 359, at a cost of 11 leaning rows down to
# 5 on the day it was measured.
LEAN_MARGIN = 1.15
LEAN_HOLD_BARS = 5
LEAN_HOLD_NEED = 4

# The fewest bars a prefix must hold before its lean is worth consulting. Below
# this the window is a stub and the classifier is answering about the start of
# the data rather than about the asset -- the same floor the walk uses to call a
# run censored.
LEAN_MIN_HISTORY = 11


def lean_hold(stamps: list[int], closes: list[float], volumes: list,
              want: str = "bullish", days: int = WINDOW_DAYS,
              months: int | None = None,
              hold: int = LEAN_HOLD_BARS) -> int | None:
    """How many of the last `hold` bars answered "leaning", or None.

    The same call, asked of the window the chart would have drawn on each of
    those bars -- `window_now` trims every prefix, so the question is
    "would this have read the same yesterday?", not "does a shorter window
    lean too?". That is the whole difference between a tag that is a reading
    and a tag that is a coin flip.

    None means the series does not reach far enough back to answer at all:
    a missing reading, which callers must not treat as a flicker.
    """
    n = len(closes)
    if n < LEAN_MIN_HISTORY or len(stamps) != n:
        return None
    held = 0
    for back in range(hold):
        end = n - 1 - back
        if end + 1 < LEAN_MIN_HISTORY:
            return None
        if leaning(stamps[:end + 1], closes[:end + 1], volumes[:end + 1],
                   want=want, days=days, months=months) is not None:
            held += 1
    return held


def steady_lean(stamps: list[int], closes: list[float], volumes: list,
                want: str = "bullish", days: int = WINDOW_DAYS,
                months: int | None = None, margin: float = LEAN_MARGIN,
                hold: int = LEAN_HOLD_BARS,
                need: int = LEAN_HOLD_NEED) -> dict | None:
    """`leaning`, kept only when it is steady enough for the near-miss table.

    Two questions, both about the same bars:

    * **Is it clear of the line?** The drift must be at least `margin` (1.15)
      in the lean's own direction -- not merely across the 1.00 hold bar.
    * **Has it stayed there?** The same call, asked of the window the chart
      would have drawn on each of the last `hold` bars, must have answered
      "leaning" on at least `need` of them (`lean_hold`).

    The answer is `leaning`'s own dict with two extras (`held`, `holdBars`), or
    None. **It never changes a label.** A row that survives is still the verdict
    its chart draws; this says only whether that verdict is steady enough to be
    worth putting in a list of near-misses.

    `decorate` applies the same two questions to a chart's badge, so a chart,
    a watchlist row and this table cannot disagree: they all print a lean only
    when it is steady, and all of them keep the raw reading (`leanRaw`) beside
    it.
    """
    call = leaning(stamps, closes, volumes, want=want, days=days, months=months)
    if call is None:
        return None
    drift = call.get("significance")
    if drift is None or abs(drift) < margin:
        return None

    held = lean_hold(stamps, closes, volumes, want=want, days=days,
                     months=months, hold=hold)
    if held is None or held < need:
        return None

    out = dict(call)
    out["held"] = held
    out["holdBars"] = hold
    return out


def decorate(call: dict | None, stamps: list[int], closes: list[float],
             volumes: list, days: int = WINDOW_DAYS,
             months: int | None = None) -> dict | None:
    """A `trend.classify` call, with its lean kept only if it is steady.

    This is the one place the "steady lean" rule is applied to a chart's badge,
    so every surface that shows a verdict -- the main price graph, the
    watchlist tag, the leaning table -- says the same thing about the same
    asset at the same moment. Asked for by name, 2026-11-07: "how about we make
    the filtering consistent ... 'watchlist' and the main price graph judgment".

    What changes and what does not:

    * **The label, score and drift are the classifier's, untouched.** A chart
      that would say Bullish still says Bullish; this function never earns or
      removes a label.
    * **`lean` is set to None when the lean is not steady**, which is what makes
      a flickering name read "Neutral" on the chart and in the rail instead of
      flickering with it.
    * **Nothing is lost.** `leanRaw` keeps the classifier's own reading, and
      `held` / `holdBars` / `steady` say why it was withheld, so the page can
      explain itself on hover rather than quietly hiding a fact.

    `stamps`, `closes` and `volumes` are the window *and the bars behind it* --
    the drawn window is what `call` already judged, the history is what makes
    the steadiness answerable. A series too short to look back over answers
    `steady: None` and keeps its lean: an unanswerable question is not a
    negative one (invariant 3).
    """
    if not call:
        return call
    lean = call.get("lean")
    out = dict(call)
    out["leanRaw"] = lean
    out["holdBars"] = LEAN_HOLD_BARS
    out["held"] = None
    out["steady"] = None
    if not lean:
        return out
    held = lean_hold(stamps, closes, volumes, want=lean, days=days,
                     months=months)
    drift = call.get("significance")
    if held is None or drift is None:
        return out                       # not answerable: keep the lean
    out["held"] = held
    out["steady"] = held >= LEAN_HOLD_NEED and abs(drift) >= LEAN_MARGIN
    if not out["steady"]:
        out["lean"] = None
    return out


def onset(stamps: list[int], closes: list[float], volumes: list,
          want: str = "bullish", days: int = WINDOW_DAYS,
          months: int | None = None) -> dict | None:
    """When the current run of `want` labels began, or None if it is not running.

    `want` is the label the run is made of: "bullish" for a price that is
    going up, and "bearish" for a series that is going down -- which is what a
    bond yield is asked for, because a falling yield is the same algorithm
    applied to the yield's own numbers rather than to a price.

    The returned `since` is the timestamp of the first bar of the run -- the
    bar the chart itself would have first labelled and kept labelling -- and
    `run` is how many bars that run covers, counting the latest.

    `turnover` is the latest bar's value traded, close times volume, in the
    instrument's own currency. It is None when the bar carries no usable
    volume -- a yield, or a row whose volume did not survive parsing -- and
    None sorts last, because it says nothing about liquidity either way.

    `censored` means the run reaches past the oldest bar fetched: the run is
    at least `run` bars long and its real start is off the end of the data,
    so the date is a floor. Two ways to get there. The plain one: the walk
    reached bar 0. The quiet one, which is how a steady series actually hits
    it: the walk walked into the data floor, where the window it tests is the
    growing prefix of the series, and below `MIN_RETURNS + 1` bars (11) a
    verdict is about how little history there is rather than about the
    asset. A run that walks past that
    point is dated to where the judging could last continue and flagged
    censored -- without this, a money-market fund whose every window is
    bullish came back with `censored: false` and an exact-looking date 13
    days after its history begins (measured 2026-10-31: ALFM-MM, BPI-MM and
    BPI-ST all stopped at bar 9 and dated their runs to 2025-10-09), and
    invariant 4 was never actually enforceable, because the label on a 1-bar
    window is always neutral and the walk could never reach bar 0.

    `anchored` records whether the walk's own first reading agreed with the
    badge's -- the boundary cases the module docstring describes. A row
    follows the badge either way; this only says how often the two differed.

    `manner` says *why* the run began -- `"turn"`, `"flat"` or `"against"` --
    read over the `TURN_BARS` bars before the run's first bar, and `turnMove`
    is the move it was cut from, signed in the run's own direction. It is a
    reading of the same bars, not a second classifier, and it does not change
    the label or the date. `None` when there is no history behind the run to
    read. See "Why a run began is a second question" in the module docstring.

    `months` asks for a calendar-months window and `days` for the ninety-day
    one -- the window the caller's own chart draws. See the module docstring
    for why the shape of the window decides the answer.
    """
    n = len(closes)
    if n < 3 or len(stamps) != n:
        return None

    last = n - 1
    # Inclusion is the badge's window (see the module docstring).
    if label(closes, volumes,
             window_now(stamps, last, days=days, months=months)) != want:
        return None

    # The walk's first step reads the latest bar through the anchored window,
    # which is the same question the badge answers from the other window.
    anchored = label(closes, volumes,
                     window_at(stamps, last, days=days,
                               months=months)) == want

    start = last
    while start - 1 >= 0 and label(closes, volumes,
                                   window_at(stamps, start - 1, days=days,
                                             months=months)) == want:
        start -= 1

    used = window_now(stamps, last, days=days, months=months)
    try:
        score = trend.classify([closes[i] for i in used],
                               [volumes[i] for i in used])["score"]
    except (ValueError, IndexError):
        score = None

    # The window's first bar's close, shipped as a raw price rather than as a
    # move: a price's move is a percentage and a yield's is a number of
    # percentage points, and only the caller knows which series it asked about.
    # `price` above is the other end of the same pair, so the table's
    # three-month column and the chart's hero delta ("+12.95% three-month move,
    # since Jul 31") are computed from one window, not two.
    first = closes[used[0]] if used else None

    # The value traded on the bar the price comes from. A missing volume is not
    # a zero-volume session, so the turnover is left as None rather than 0.0.
    volume = volumes[last]
    turnover = closes[last] * volume if volume else None

    # Why the run began: read at its first bar, over the bars before it, never
    # over today's -- the question is what changed when the label flipped.
    manner, turn_move = turn(closes, start, want)

    # The data floor. Below MIN_RETURNS + 1 bars the tested window is a
    # stub of the series' first days, so a stop inside it is the walk
    # running out of judgable history, not a bar that judged against the
    # run. The date is a floor; say so.
    censored = start <= trend.MIN_RETURNS

    return {
        "since": stamps[start],
        "run": last - start + 1,
        "censored": censored,
        "anchored": anchored,
        "manner": manner,
        "turnMove": round(turn_move, 4) if turn_move is not None else None,
        "score": score,
        "bars": n,
        "last": stamps[last],
        "price": closes[last],
        "turnover": turnover,
        "window": len(used),
        # The window's first drawn close -- see `first` above. The pair
        # (`windowFirst`, `price`) is what a caller's move is computed from.
        "windowFirst": first,
    }
