"""Yahoo's chart answer turned into the page's chart: bars, sessions, the live print.

Split out of server.py; behaviour unchanged. Every name here is re-exported from
`server`, and the code reaches its names through `S.`, so a test that patches
`server.<name>` still reaches it.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from zoneinfo import ZoneInfo
import crypto
import onset as onset_module
import quality
import trend

import server as S


def exchange_day(meta: dict, stamp) -> dt.date | None:
    """The calendar day a stamp falls on in the exchange's own timezone.

    Every guard that has to tell "this price belongs to this bar" from "this
    price belongs to a neighbouring session" asks this one question, so it is
    answered here: a bar and a print on different days are different sessions,
    whatever their distance in hours. None when the zone name is unusable (Yahoo
    does not always send a usable one) or the stamp is out of the platform's
    range, so a caller refuses rather than guessing a day.
    """
    try:
        zone = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
        return dt.datetime.fromtimestamp(stamp, zone).date()
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None


def same_exchange_day(meta: dict, a, b) -> bool:
    """True when two stamps land on one calendar day in the exchange's zone."""
    left = S.exchange_day(meta, a)
    return left is not None and left == S.exchange_day(meta, b)


def full_day_close(meta: dict, last_stamp: int) -> float | None:
    """The newest session's price *including* pre- and after-hours trading.

    Yahoo's daily bars are regular-session closes: Friday's bar ends at the
    16:00 bell, and everything traded after it is invisible in that bar. The
    chart wants the most recent price for the session still in progress, so the
    newest bar is drawn at `meta.fulldayPrice` -- the same session's price with
    the extended sessions folded in -- while every older bar keeps its official
    close. Once a newer session starts, yesterday's bar falls back to being an
    ordinary bar and the close returns on its own: the patch only ever touches
    the last one.

    Three guards, each of which returns None so the caller draws the plain
    close:

    * `hasPrePostMarketData` false -- the instrument has no extended session to
      fold in. That covers crypto, FX, futures, mutual funds and every PSE name,
      and for those `fulldayPrice` is simply the regular price.
    * no usable `fulldayPrice` in the payload.
    * the extended print belongs to a *newer* session than the last bar. This is
      the pre-market case: on a Monday morning the daily series can still end at
      Friday while `fulldayPrice` already carries Monday's pre-market print, and
      dating Friday's bar with Monday's price would be a lie. The two are
      compared as calendar dates in the exchange's own timezone, taken from the
      payload's `currentTradingPeriod`.
    """
    if not meta.get("hasPrePostMarketData"):
        return None
    price = meta.get("fulldayPrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    session_start = regular.get("start")
    if session_start is None:
        return None
    if not S.same_exchange_day(meta, last_stamp, session_start):
        return None
    return float(price)


def live_print(meta: dict, last_stamp: int) -> dict | None:
    """The price of the session trading now, when no *bar* exists for it yet.

    `full_day_close` folds an extended-hours print into the newest bar, and
    that only works while that bar is the session trading now. Between one
    session's close and the next one's first daily bar -- 04:00 to 09:30 New
    York, and again from the 16:00 bell until Yahoo gives up the after-hours
    print -- the newest bar is an *older* session's, while `fulldayPrice`
    already carries a print belonging to a newer one. Dating that price to the
    old bar would be a lie (that is `full_day_close`'s third guard), so the
    chart used to stop at the old official close and stay there while the
    market moved. Measured 2026-11-03 at 04:15 New York: AAPL had printed
    322.13 in pre-market against a Monday close of 338.32, and the page showed
    only 338.32 labelled "close".

    This is that print, kept out of the bars so the chart can draw it as the
    *newest* point under the current session's own date instead of rewriting an
    older bar. The stamp is the session's regular open, which is exactly where
    Yahoo will put the day's real bar, so the synthetic point is replaced by
    the real one when it arrives rather than sitting beside it.

    None when there is nothing honest to add: no extended session on the
    instrument, no usable `fulldayPrice`, no session schedule, the newest bar
    already belongs to this session (then `full_day_close` is the one that
    folds), or the newest bar is more than `LIVE_BAR_GAP_DAYS` old -- a halt or
    a dead listing is not a session that is trading.
    """
    if not meta.get("hasPrePostMarketData"):
        return None
    price = meta.get("fulldayPrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    session_start = S.usable_stamp(regular.get("start"))
    if session_start is None:
        return None
    if S.same_exchange_day(meta, last_stamp, session_start):
        return None
    if session_start - last_stamp > S.LIVE_BAR_GAP_DAYS * 86400:
        return None
    return {"t": int(session_start), "c": round(float(price), 6)}


def session_close(meta: dict, quote: dict, index: int, stamp: int) -> float | None:
    """The newest session's price when Yahoo left that bar's `close` null.

    Yahoo sometimes answers a *completed* session's daily bar with open, high,
    low and volume filled in and `close` left null. Verified 2026-10-31
    (Saturday, after the Friday 2026-10-30 close): every US symbol tried
    answered that way -- SPY, AAPL, MSFT, KO and XOM all ended at a Friday bar
    whose open/high/low/volume were present and whose close was null -- while
    `meta.regularMarketPrice` carried the close (KO 94.08) stamped at
    2026-10-30T20:00:02Z. The prior sessions were untouched.

    Dropping such a bar as a gap (which is right for a holiday row, where the
    whole row is null) amputates the newest session instead: the chart ended a
    day early, the badge scored 64 bars ending 10-29, and every US table row
    was one session behind -- KO read **neutral 0.2183** where the same
    classifier on the same window including Friday reads **bullish 0.2930**.

    So the newest bar's close is filled from the payload's own headline price,
    under four guards that each refuse rather than invent one:

    * a usable positive `regularMarketPrice`;
    * a usable `regularMarketTime`, whose *calendar day* in the exchange's own
      timezone must equal the bar's. That is what keeps a Monday pre-market
      print from being dated to Friday's bar, the same mistake `full_day_close`
      guards against from the other side;
    * a bar that looks like a session really happened -- volume, or a high/low,
      is present. A stamped all-null holiday row fills nothing. The one
      exception is a mutual fund (`instrumentType` MUTUALFUND): its "bar" is a
      NAV the manager strikes and publishes as a price, so Yahoo can carry the
      day's NAV in `regularMarketPrice` for hours before the row itself is
      filled in (VFIAX on 2026-10-31: an all-null 10-30 row, `regularMarketPrice`
      699.87 stamped 2026-10-31T00:08Z = 10-30 20:08 in New York). The day
      guard above still has to pass, so a weekend or holiday row cannot borrow
      the previous NAV;
    * when both high and low are usable, the price must sit inside them, so a
      stale or unrelated headline number cannot be dressed as a close.
    """
    price = meta.get("regularMarketPrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    observed = meta.get("regularMarketTime")
    if not isinstance(observed, (int, float)) or isinstance(observed, bool) or observed <= 0:
        return None
    if not S.same_exchange_day(meta, stamp, observed):
        return None

    def number(values):
        value = values[index] if index < len(values) else None
        return (float(value) if isinstance(value, (int, float))
                and not isinstance(value, bool) else None)

    volume = number(quote.get("volume") or [])
    low, high = number(quote.get("low") or []), number(quote.get("high") or [])
    fund = (meta.get("instrumentType") or "").upper() == "MUTUALFUND"
    if not (volume and volume > 0) and not (low and high) and not fund:
        return None
    if low and high and not (low <= price <= high):
        return None
    return float(price)


def yahoo_meta(payload: dict) -> dict:
    """The three things the recent table needs about a symbol, from its meta.

    A name to print under the ticker, the instrument's kind in the words the
    page already uses (`markets.KINDS`), and its currency. The table asks
    Yahoo rather than a scanner because since 2026-11-07 its universe is the
    Ondo shelf, which names tokens and not companies: `nvdaon` says nothing
    about NVIDIA, and the chart's own payload does.

    Anything missing falls through as an empty string or `USD` rather than a
    guess, and a caller keeps its own fallback first.
    """
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    meta = result.get("meta") or {}
    instrument = str(meta.get("instrumentType") or "").upper()
    return {
        "name": meta.get("longName") or meta.get("shortName") or "",
        "kind": {
            "EQUITY": "Common stock",
            "ETF": "ETF",
            "MUTUALFUND": "Mutual fund",
            "INDEX": "Index",
            "CRYPTOCURRENCY": "Crypto",
            "CURRENCY": "Currency",
            "FUTURE": "Future",
        }.get(instrument, ""),
        "currency": str(meta.get("currency") or "").upper(),
    }


def yahoo_bars(payload: dict, symbol: str):
    """Yahoo's chart payload -> (stamps, closes, volumes), aligned.

    Split out of `slim_chart` because two callers need the arrays and not
    the chart: the slimmed payload the page draws, and the recent-assets
    table, which has to walk the series bar by bar to find the day the run
    began. The alignment rules are the ones the chart has always used -- a
    bar with no close is a gap and is dropped, and a bar with no volume
    keeps a None rather than borrowing its neighbour's -- with the one
    exception `session_close` covers: the *newest* bar is kept even when
    Yahoo left its close null, because that is a session whose close has
    not been published as a bar yet, not a gap.

    The newest bar's close is replaced by its extended-hours price when the
    payload carries one for that same session (`full_day_close`). It happens
    here, in the one function both callers read their bars through, so the
    chart's badge and the recent table's row are still scored on one series.

    Raises LookupError when the payload carries no usable series.
    """
    chart = payload.get("chart") or {}
    result = (chart.get("result") or [None])[0]
    if not result:
        message = (chart.get("error") or {}).get("description")
        raise LookupError(message or f"No price data for {symbol!r}.")

    meta = result.get("meta") or {}
    indicators = result.get("indicators") or {}
    quote = (indicators.get("quote") or [{}])[0]

    stamps = result.get("timestamp") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    # The newest stamped bar is the only one a missing close is allowed to
    # survive: Yahoo can publish a finished session's open/high/low/volume
    # before it publishes the close itself (see `session_close`). Older rows
    # with no close stay gaps.
    newest = len(stamps) - 1
    newest_close = (closes[newest] if 0 <= newest < len(closes) else None)
    if newest >= 0 and newest_close is None:
        newest_close = S.session_close(meta, quote, newest, stamps[newest])

    out_stamps: list[int] = []
    out_closes: list[float] = []
    out_volumes: list = []
    for i, stamp in enumerate(stamps):
        close = closes[i] if i < len(closes) else None
        if close is None:
            if i == newest and newest_close is not None:
                close = newest_close
            else:
                continue  # holidays / halts leave gaps
        out_stamps.append(int(stamp))
        out_closes.append(round(float(close), 6))
        out_volumes.append(volumes[i] if i < len(volumes) else None)

    if not out_stamps:
        raise LookupError(f"No usable price data for {symbol!r}.")
    full_day = S.full_day_close(meta, out_stamps[-1])
    if full_day is not None:
        out_closes[-1] = round(full_day, 6)
    return out_stamps, out_closes, out_volumes


def history_tail(all_points: list[dict], drawn: list[dict],
                 want: int | None = None) -> list[dict]:
    """The bars immediately before a drawn window, oldest first.

    The badge's steadiness reading (`onset.decorate`) asks the classifier the
    same question of the previous few windows, and a window ending four bars ago
    needs the four bars the trim just dropped. This hands them over: at most
    `want` (default `onset.LEAN_HOLD_BARS`) bars, each `{t, c, v}` so a prefix
    window is scored on the same numbers the table's walk would have used --
    including its volume, which is a signal the classifier reads.

    It rides in every chart payload, so it stays tiny: five bars, nothing drawn.
    """
    want = onset_module.LEAN_HOLD_BARS if want is None else want
    if not all_points or not drawn or not want:
        return []
    first = drawn[0]["t"]
    before = [point for point in all_points if point["t"] < first]
    return before[-want:]


def slim_chart(payload: dict, symbol: str, span: str | None = None,
               interval: str = "1d") -> dict:
    """Reduce Yahoo's chart payload to what the page actually draws.

    `span` is the range the payload was fetched for. When it is one of the
    calendar-month spans Yahoo itself understands, the payload is trimmed to
    the same window -- Yahoo's own rule, three calendar months back from
    today for `3mo` -- so the chart draws exactly the bars the badge reads and
    the recent table reads. Yahoo's own payload already matches this today;
    trimming here makes the agreement structural rather than a coincidence
    of how many bars the span happened to return.

    The window is not re-derived here: it is `onset.window_now`, the same
    function the walk in the recent table asks, so the two cannot drift apart
    the way two copies of a rule can.

    Only daily bars are trimmed. The cutoff is a day boundary, and a weekly
    bar spans seven days with its stamp on the week's first day -- comparing
    that stamp against a day boundary would amputate a bar that lies partly
    inside the window. Weekly charts keep Yahoo's own payload, and their badge
    is read from the bars they draw, which is the same rule the daily charts
    follow. One measured cost of that rule, stated so nobody rediscovers it
    by accident (2026-10-31, SPY `3mo`): the daily badge scores 63 daily bars
    with the backtested ensemble (-0.1985), while the weekly badge scores 15
    weekly bars -- 13 after the classifier's 63-bar tail -- through the
    short-window damping, sqrt(15/50) = 0.55 (-0.0091). Same label words,
    same threshold, entirely different machinery, because the backtest
    validated 63 *daily* bars and nothing else. The page itself only ever
    requests `1d`; a non-daily badge is the drawn bars' verdict, not the
    validated one.

    The newest bar is drawn at its extended-hours price when the payload has
    one for that session (`full_day_close`, applied inside `yahoo_bars`), and
    `extendedLastBar` says whether it happened, so the page can name the
    figure instead of letting a post-market print pass for a closing price.

    The payload also carries the `session` the newest bar belongs to -- the
    regular trading window and whether it is that bar's own session -- which is
    what `last_bar_basis` reads to call the figure live, pre-market,
    after-hours or a plain close. The window is Yahoo's; the decision is not
    made here, because it depends on the clock at read time, not at fetch time.

    `livePrint` is the other end of that: when the newest bar belongs to an
    *older* session than the one trading now, the payload keeps the current
    session's price beside the bars instead of dating it to an old one (see
    `live_print`), and `chart_data` draws it as today's point while one of that
    session's windows is open.
    """
    chart = payload.get("chart") or {}
    result = (chart.get("result") or [None])[0]
    if not result:
        message = (chart.get("error") or {}).get("description")
        raise LookupError(message or f"No price data for {symbol!r}.")

    meta = result.get("meta") or {}

    stamps, closes, volumes_used = S.yahoo_bars(payload, symbol)
    points = [{"t": stamp, "c": close}
              for stamp, close in zip(stamps, closes)]
    # Every bar the payload holds, volumes included, before the trim: what is
    # left out of the window becomes the badge's history (`history_tail`).
    every_bar = [{"t": stamp, "c": close, "v": volume}
                 for stamp, close, volume
                 in zip(stamps, closes, volumes_used)]

    months = S.SPAN_MONTHS.get(span) if span else None
    if months and interval == "1d":
        keep = onset_module.window_now(stamps, len(stamps) - 1,
                                        months=months)
        points = [points[i] for i in keep]
        volumes_used = [volumes_used[i] for i in keep]

    # The bars just before the drawn window, so the badge's lean can be checked
    # over the previous few sessions (`onset.decorate`). Yahoo was asked for a
    # longer range than the chart draws for exactly this (`chart_data`), so a
    # 3-month chart still has bars behind its window; a chart whose payload
    # starts at the window has no tail and keeps its lean unfiltered, which is
    # the honest answer to "not enough history to judge".
    tail = S.history_tail(every_bar, points, want=100)

    # The trend call is scored on the same bars the chart draws, volumes aligned
    # to them. Any failure here is non-fatal: the chart is the product, the badge
    # is an annotation, so a data quirk must not blank the page. Every series is
    # scored regardless of length; only unusable prices raise.
    trend_call = None
    try:
        trend_call = trend.classify([p["c"] for p in points], volumes_used)
    except ValueError:
        pass  # non-positive price in the series

    # Yahoo's FX priceHint is often a flat 4. A micro cross (VND/PHP ~0.0025)
    # then prints every bar the same; raise the hint to what the rate's size
    # needs, never below Yahoo's own ask.
    hint = meta.get("priceHint") or 2
    try:
        hint = int(hint)
    except (TypeError, ValueError):
        hint = 2
    if ((meta.get("instrumentType") or "").upper() == "CURRENCY"
            and points):
        hint = max(hint, crypto.price_hint(points[-1]["c"]))

    return {
        "symbol": meta.get("symbol") or symbol,
        "name": meta.get("longName") or meta.get("shortName") or symbol,
        "currency": meta.get("currency") or "",
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "",
        "type": meta.get("instrumentType") or "",
        "timezone": meta.get("exchangeTimezoneName") or "",
        "priceHint": hint,
        "previousClose": meta.get("chartPreviousClose"),
        "marketPrice": meta.get("regularMarketPrice"),
        "extendedLastBar": S.full_day_close(meta, stamps[-1]) is not None,
        "livePrint": S.live_print(meta, stamps[-1]) if interval == "1d" else None,
        "session": S.session_window(meta, stamps[-1]),
        "points": points,
        # Each drawn bar's volume, for the page's volume tag only. Not named
        # `volumes`: that key means "venue volumes" to `fill_missing_days`
        # and `completed_trade`. A point added later (a filled day, a live
        # print) breaks the alignment, and the page then shows no tag.
        "barVolumes": list(volumes_used),
        "trend": trend_call,
        # The bars before the window, for the badge's steadiness reading. Not
        # drawn; kept so `chart_data` can ask the same question of the previous
        # few windows on every read, cached copies included.
        "historyTail": tail,
        "source": "Yahoo",
        # Defects in the bars drawn (a gap, a frozen run, a split-sized jump),
        # described and never acted on: the verdict above is unchanged.
        "quality": S.chart_quality(points, volumes_used, meta, interval),
    }


def chart_quality(points: list[dict], volumes: list, meta: dict, interval: str) -> list[dict]:
    """`quality.check` on the drawn bars. Daily bars only: a weekly or monthly
    chart has gaps by construction. Only stocks and ETFs are expected to carry
    volume; a currency or a future has none, and that is not a defect."""
    if interval != "1d":
        return []
    kind = str(meta.get("instrumentType") or "").upper()
    return quality.check([p["t"] for p in points], [p["c"] for p in points],
                         volumes, volume=kind in ("EQUITY", "ETF"))


def session_window(meta: dict, last_stamp: int) -> dict | None:
    """Yahoo's trading windows for the newest bar's session, if it says them.

    `pre`, `regular` and `post` are the payload's own `currentTradingPeriod`
    stamps, `[start, end]` each (a zero-length one is left out, which is how
    Yahoo spells "this instrument has no extended session"), and
    `coversLastBar` says whether those windows are the last bar's own session
    -- the same day question `full_day_close` asks before it folds an
    extended-hours print in, asked here about the bar itself. Without that flag
    a chart fetched on a Saturday would carry Friday's windows, and a Friday
    bar could be called live on a Friday evening reading.

    None when the payload carries no usable regular window: the honest answer
    for an instrument Yahoo does not schedule, which `last_bar_basis` then
    reads as a plain close.
    """
    periods = meta.get("currentTradingPeriod") or {}
    regular = periods.get("regular") or {}
    start, end = S.usable_stamp(regular.get("start")), S.usable_stamp(regular.get("end"))
    if start is None or end is None or end <= start:
        return None
    session = {
        "regular": [int(start), int(end)],
        "coversLastBar": S.same_exchange_day(meta, last_stamp, start),
    }
    # `lastPrint` is when the last regular-session trade printed. It is what
    # tells a window that is open from a market that is *trading*: Yahoo models
    # a nearly round-the-clock instrument (GC=F) as a whole calendar day, so
    # its window covers a Friday evening when the exchange has shut for the
    # weekend -- but the last print inside that window is hours old.
    last_print = S.usable_stamp(meta.get("regularMarketTime"))
    if last_print is not None:
        session["lastPrint"] = int(last_print)
    for name in ("pre", "post"):
        window = periods.get(name) or {}
        a, b = S.usable_stamp(window.get("start")), S.usable_stamp(window.get("end"))
        if a is not None and b is not None and b > a:
            session[name] = [int(a), int(b)]
    return session


def last_bar_basis(data: dict, now: float | None = None) -> str:
    """What the newest drawn bar's number *is*: live, pre-market, after-hours,
    a weekend price, or a closing price.

    Every bar but the newest is the session's settled close. The newest is
    whichever of these things Yahoo's session clock and the payload say it is:

    * `live` -- the regular session belongs to that bar, is open now, and a
      trade printed in the last half hour: the bar's close *is* the last trade.
    * `pre` -- an extended-hours print was folded into the bar
      (`extendedLastBar`) and the pre-market window is open.
    * `after` -- the same fold, with the post-market window open: the figure is
      the last after-hours trade of that session.
    * `live` also for a Binance coin whose newest bar is the day still
      trading (`liveLastBar`, set by `crypto.chart`), unless the copy is a
      disk fallback.
    * `weekend` for the peso pair's Saturday and Sunday, whose bars come from
      Coins.ph's USDC/PHP book (`weekend_proxy`) because the FX week is shut --
      a real traded price, but not an interbank close.
    * `pre` / `after` also for the session in progress when no bar exists for
      it yet (`live_point`): the point is today's date carrying the print of
      the session now trading, so it can be a pre-market or after-hours figure
      but never a settled close -- the session it belongs to has not settled.
    * `live` also for a PSE bar dated today while the exchange is open
      (`pse.session_window`): TradingView hands today's candle from the opening
      bell, so that bar is the price trading now, not a close. It reads `close`
      from 15:15 Manila, on a holiday, and from a disk fallback.
    * `close` -- everything else, including every payload whose source has no
      session to speak of (a fund's NAVPU, a bond yield).

    Two things keep this from over-claiming. The clock decides, not the price:
    once the extended session ends Yahoo stops folding the after-hours print in
    and reports the regular close again (AAPL read 344.807 while the post
    session ran on 2026-10-30 and 344.63 after it), so a figure outside those
    windows is a close however it was fetched. And a live call needs a *recent
    print*, so a window that is nominally open while the exchange is shut --
    Yahoo's whole-calendar-day window for a future, on a Friday night -- is not
    mistaken for a market that is trading.

    Decided at read time, not fetch time -- a chart served from the memory memo
    or from a disk copy an hour later must not still claim to be live. This is
    the one place the call is made; the page words the result (`lastBarBasis`)
    and never derives it.
    """
    points = data.get("points") or []
    # A Binance day still trading: its close is the last trade. A disk
    # fallback is hours old by definition, so it never reads live.
    if points and data.get("liveLastBar") and not data.get("cached"):
        return "live"
    # A bar the source is still writing, on a market whose clock we keep: the
    # PSE hands today's candle from the opening bell (`pse.session_window`), so
    # the newest point *is* the price trading now while the exchange is open.
    # The exchange publishes its session, so the window is an absolute stamp
    # that expires by itself -- tomorrow this same payload reads close, and a
    # disk fallback never reads live at all.
    forming = data.get("session") or {}
    if points and forming.get("formingBar") and not data.get("cached"):
        if S._within(forming.get("regular"),
                   time.time() if now is None else now):
            return "live"
    # The newest bar is a weekend price for the peso pair: the FX week is shut,
    # and the number is Coins.ph's USDC/PHP close for that Manila day (see
    # `weekend_proxy`). It is neither an interbank close nor a live FX print, so
    # it says whose price it is rather than borrowing either word.
    if points and (data.get("weekendProxy") or {}).get("stamps"):
        if points[-1]["t"] == data["weekendProxy"]["stamps"][-1]:
            return "weekend"
    session = data.get("session") or {}
    if not points or not session.get("coversLastBar"):
        return "close"
    now = time.time() if now is None else now
    # The newest point is the print of a session that has not settled: a
    # pre-market trade before the regular open, the last extended print after
    # it. It never reads "close" -- the session it belongs to is the one still
    # in progress -- and it says which of the two by the clock, not by the
    # window the payload happened to ship.
    if data.get("livePointStamp") == points[-1]["t"]:
        ended = (session.get("regular") or [None, None])[1]
        if ended is not None and now >= ended:
            return "after"
        return "pre"
    regular = session.get("regular") or [None, None]
    if regular[0] is not None and regular[0] <= now < regular[1]:
        printed = session.get("lastPrint")
        if (printed is not None and printed >= regular[0]
                and now - printed <= S.LIVE_PRINT_MAX_AGE):
            return "live"
    if not data.get("extendedLastBar"):
        return "close"
    if S._within(session.get("pre"), now):
        return "pre"
    if S._within(session.get("post"), now):
        return "after"
    return "close"


def _within(window, now: float) -> bool:
    """Whether `now` falls inside a `[start, end]` window (None-safe)."""
    return bool(window) and len(window) == 2 and window[0] <= now < window[1]


def live_point(card: dict, now: float | None = None) -> dict:
    """Append the session now trading as a new newest point, while it trades.

    `slim_chart` ships the price of the session in progress as `livePrint`
    (`live_print`). It is drawn only while one of *that* session's extended
    windows is open now, and only when the chart still ends at an older bar:
    from the 16:00 bell until 04:00 New York Yahoo folds nothing -- it reports
    the regular close again -- so there is no print to add and the newest bar
    keeps its own close. That stretch is a gap in the source, and this function
    does not paper over it by repeating the close as a "live" price.

    Read time, not fetch time, and on a copy: `points` is the memo entry's
    list. A chart served from the memo or from a disk copy must not still carry
    a pre-market point late in the session, so the decision is remade on every
    read and the appended point disappears as soon as the real bar exists.

    A disk fallback is left alone: `cached` means the payload was fetched hours
    ago, and a copy may not invent a price for a session it never saw. It draws
    the bars it stored and says how old they are.
    """
    live = card.get("livePrint") or {}
    stamp, price = live.get("t"), live.get("c")
    if not stamp or not price or card.get("cached"):
        return card
    points = card.get("points") or []
    if not points or points[-1]["t"] >= stamp:
        return card                     # the real bar is here; nothing to add
    session = card.get("session") or {}
    now = time.time() if now is None else now
    if not (S._within(session.get("pre"), now) or S._within(session.get("post"), now)):
        return card                     # nothing is trading: the close stands
    out = dict(card)
    out["points"] = points + [{"t": int(stamp), "c": float(price)}]
    # The appended point sits where the session's own daily bar will sit, so
    # the payload's window *does* cover the newest point now -- which is what
    # `last_bar_basis` reads before it allows anything but "close".
    out["session"] = dict(session, coversLastBar=True)
    out["livePointStamp"] = int(stamp)
    return out


def usable_stamp(value) -> float | None:
    """A Yahoo epoch second as a number, or None if it is missing/not one."""
    return (float(value) if isinstance(value, (int, float))
            and not isinstance(value, bool) else None)


# How recently the last regular-session trade must have printed for the newest
# bar to be called a *live* price. Yahoo's `currentTradingPeriod.regular` is a
# schedule, and for an instrument that trades nearly around the clock (a future,
# an FX pair) it is a whole calendar day -- so on a Friday evening the window is
# still open while the exchange has shut for the weekend. The last print inside
# that window is then hours old, which is the difference this bound measures.
# Half an hour is long enough that a thinly traded name which has not printed
# since the bell still reads as live, and short enough that a closed market
# cannot pass for an open one.
LIVE_PRINT_MAX_AGE = 1800  # seconds

# How far behind the session that is trading the newest *bar* may be for
# `live_print` to trust `fulldayPrice` as that session's print. A weekend plus a
# holiday fits comfortably; a halted name or a dead listing does not, and its
# last price must not be redrawn as today's pre-market trade.
LIVE_BAR_GAP_DAYS = 5


def yahoo_chart(url: str, symbol: str, span: str | None = None,
                interval: str = "1d") -> dict:
    """Fetch and slim one Yahoo chart. Raises LookupError for "no such symbol",
    UpstreamError for a transport failure."""
    status, body = S.moli_get(url)
    try:
        payload = json.loads(body)
    except ValueError:
        raise S.UpstreamError(f"Upstream returned non-JSON (HTTP {status})")
    # Yahoo reports "no data" as a 404 with a chart.error object, so only a 5xx
    # is a genuine transport problem.
    if status >= 500:
        raise S.UpstreamError(f"Upstream HTTP {status}")
    return S.slim_chart(payload, symbol, span, interval)


def _series_close(point) -> float | None:
    """One usable close from a chart point, or None (invariant 3's shape)."""
    try:
        value = float(point["c"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def yahoo_is_wrong(symbol: str, data: dict,
                   coin: dict | None = None,
                   tried: bool = False) -> bool:
    """Is Yahoo charting a different instrument than this ticker names?

    Only asked of crypto -- that is where the collisions are -- and only when
    the ticker resolves to a chartable coin. The independent reading is the
    crypto module's own chart (`coin`), which is only returned when a venue is
    *actually* trading it, so a frozen delisted price can never be the second
    opinion (the rule that fixed XMR on 2026-11-03).

    A last close alone is not enough. Measured 2026-11-11: Yahoo's BEAM-USD had
    fallen to 0.005319 while Kraken's Beam rose to 0.004457 -- 19.3% apart,
    inside the old 20% gap -- so the single-price test said "trust Yahoo" and a
    neutral chart of a different coin stood beside a bullish row. The two
    *series* never agreed: Yahoo -37.7% over the window, Kraken +225.8%. So the
    shared bars are compared: one coin quoted at two venues holds a near-
    constant price ratio across them, and two different coins do not.

    `coin` is the chart the caller already fetched for the reroute, so the test
    costs no second upstream read. `tried` says that fetch was made and answered
    nothing -- every venue is silent, so there is no independent price to ask
    for again. A standalone call with neither still falls back to the cheap
    cached close. With no independent price at all, Yahoo's answer stands: a
    missing fetch is not a verdict about the coin.
    """
    if data.get("type") != "CRYPTOCURRENCY":
        return False
    points = data.get("points") or []
    if not points:
        return False
    coin_points = (coin or {}).get("points") or []
    if not coin_points:
        # No series to compare: the legacy single-price answer, or none at all
        # when the chart read was made and every venue was silent.
        truth = None if tried else crypto.latest_close(symbol)
        ours = S._series_close(points[-1])
        if not truth or ours is None:
            return False              # no independent price: trust Yahoo
        return abs(ours - truth) / abs(truth) > S.REROUTE_GAP

    # `slim_chart` and `crypto.chart` cut the same calendar window, so their
    # daily stamps line up (measured 2026-11-11: 93 of 93 on BEAM-USD,
    # BTC-USD and XMR-USD). Match by stamp, not by position, so a venue's odd
    # bar cannot pair with another day's close.
    coin_by_stamp: dict = {}
    for point in coin_points:
        value = S._series_close(point)
        if value is not None:
            coin_by_stamp[point.get("t")] = value
    ratios = []
    for point in points:
        value = S._series_close(point)
        other = coin_by_stamp.get(point.get("t"))
        if value is not None and other is not None:
            ratios.append(value / other)
    if len(ratios) >= S.SERIES_BARS:
        # A ratio that travels across the window is two price lines, however
        # close their newest closes happen to be. A flat one is one coin.
        if max(ratios) / min(ratios) - 1 > S.REROUTE_GAP:
            return True
    # Kept for a series too short to read a shape from, and for a constant
    # offset between two venues: either way a missing reading is not a verdict.
    ours, truth = S._series_close(points[-1]), S._series_close(coin_points[-1])
    if ours is None or not truth:
        return False
    return abs(ours - truth) / abs(truth) > S.REROUTE_GAP


def fill_missing_days(yahoo: dict, coin: dict | None, interval: str) -> dict:
    """Yahoo's crypto series with any day *inside* it that it skipped filled in.

    Measured 2026-11-16: Yahoo's XMR-USD has no bar for 2026-11-15 (14th, then
    16th), while Kraken printed one. Yahoo stays the series when it agrees with
    the coin's own venue, so the hole stayed in the chart. A day between two
    Yahoo bars that the venue has is added from the venue; nothing before the
    first or after the last Yahoo bar is touched, and a coin the venue does not
    trade changes nothing. Daily bars only.
    """
    if interval != "1d" or not coin:
        return yahoo
    points = yahoo.get("points") or []
    have = {p.get("t") for p in points}
    if len(points) < 2 or yahoo.get("volumes"):
        return yahoo
    first, last = points[0].get("t"), points[-1].get("t")
    extra = []
    for point in coin.get("points") or []:
        t = point.get("t")
        if (t not in have and isinstance(t, (int, float))
                and first < t < last and S._series_close(point) is not None):
            extra.append({"t": t, "c": point["c"]})
    if not extra:
        return yahoo
    out = dict(yahoo)
    out["points"] = sorted(points + extra, key=lambda p: p["t"])
    out["filledDays"] = sorted(p["t"] for p in extra)
    return out
