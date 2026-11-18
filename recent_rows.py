"""The recent table's rows, one function per market.

Split out of recent.py; behaviour unchanged. Every name here is re-exported from
`recent`, and the code reaches its names through `R.`, so a test that patches
`recent.<name>` still reaches it.
"""

from __future__ import annotations

import concurrent.futures
import crypto
import cryptobull
import nasdaq_bars
import ondo
import ondolist
import onset as onset_module
import phfunds
import quality
import rates
import tv

import recent as R


def labeled_onset(stamps, closes, volumes, **kwargs):
    """The current run, bullish or else bearish, from bars already in hand.

    Bullish is asked first. A window that is bullish is not also recorded as
    bearish. A neutral window returns `(None, None)` and the caller may still
    ask `steady_lean`. This is a second walk of the same bars, not a second
    fetch: `onset` returns at the first bar when the latest label is not the
    one it was asked for.
    """
    for want in ("bullish", "bearish"):
        call = onset_module.onset(stamps, closes, volumes, want=want, **kwargs)
        if call is not None:
            return want, call
    return None, None


def us_rows(fetch_us_bars, shelf: dict | None = None) -> tuple[list[dict], dict]:
    """The bullish Ondo stocks and ETFs, and what the scan could not say.

    `fetch_us_bars` is called with the tickers to judge and answers
    `{ticker: (stamps, closes, volumes, meta)}` -- the bars the page's own
    chart draws for that ticker, plus Yahoo's name for it. It is injected
    because the fetch is a browser one and the browser lives in `server.py`.

    A ticker whose bars did not arrive is left out and counted in `missing`:
    the alternative, treating it as "not bullish", would put a fetch failure
    into the table as a fact about the stock.

    A ticker whose bars *did* arrive but stopped weeks ago is left out too, and
    counted in `stale` with the date of its last bar: a frozen price is not a
    price now, and a verdict read off it is a verdict about the month it
    stopped in (see `STALE_GAP_DAYS`, and ATKR as the case that made it
    visible). The note prints those names, so a row that is absent is never
    unexplained.

    The window is Yahoo's own three *calendar* months, not ninety days,
    because that is the window the chart route asks Yahoo for and so the
    window the chart draws. The two are a couple of trading sessions apart,
    which is nothing -- except that `trend.classify` changes regime at 63
    bars, so ninety days (62 bars for a US listing) and Yahoo's window (64
    bars) are judged by different weight tables and can answer differently.
    SPY was the proof: bullish here at +0.27, neutral on its own chart.

    The bars are asked for under the row's `chartSymbol`, which is the
    spelling the chart route draws -- a class share carries Yahoo's dash
    (`BRK-B`), not the shelf's dot (`brk.bon`, `BRK.B`). Judging the shelf's
    spelling would report the name as a fetch failure on every sweep, which is
    a wrong fact about a stock that answers perfectly well under its own name.
    """
    records, from_shelf = R.shelf_universe(shelf)
    symbols = [record.get("chartSymbol") or record.get("ticker")
               for record in records]
    symbols = [symbol for symbol in symbols if symbol]
    if not symbols:
        raise R.RecentError("the Ondo shelf is empty")

    by_symbol: dict[str, dict] = {}
    for record in records:
        by_symbol.setdefault(record.get("chartSymbol") or record.get("ticker"),
                             record)

    try:
        bars = fetch_us_bars(symbols) or {}
    except Exception as exc:
        raise R.RecentError("the US bars could not be fetched: %s" % exc)

    rows: list[dict] = []
    missing: list[str] = []
    stale: list[dict] = []
    flags: dict[str, list] = {}
    fallback: set[str] = set()
    for symbol in symbols:
        record = by_symbol[symbol]
        ticker = record.get("ticker") or symbol
        series = bars.get(symbol)
        if not series:
            missing.append(ticker)
            continue
        stamps, closes, volumes = series[:3]
        meta = series[3] if len(series) > 3 and isinstance(series[3], dict) else {}
        flags[symbol] = quality.check(stamps, closes, volumes)
        if meta.get("fallback"):
            fallback.add(symbol)
        # A series the source stopped printing is not judged at all, in either
        # table: a verdict read off a frozen price is a verdict about the month
        # it stopped in, and the row would carry that month's price as though it
        # were today's. Counted, not swallowed -- the note prints the names and
        # their last bar, because a name that vanished without a word is the
        # thing the reader objected to about the peso floor (see
        # `STALE_GAP_DAYS`).
        gap = R.stale_gap(stamps)
        if gap is not None:
            stale.append(R.stale_entry(ticker, stamps, gap, symbol))
            continue
        side, call = labeled_onset(stamps, closes, volumes,
                                   months=onset_module.WINDOW_MONTHS)
        name = meta.get("name") or record.get("name") or ticker
        kind = meta.get("kind") or record.get("kind") or "Common stock"
        currency = meta.get("currency") or record.get("currency") or "USD"
        if call is None:
            lean = onset_module.steady_lean(
                stamps, closes, volumes, months=onset_module.WINDOW_MONTHS)
            if lean is not None:
                rows.append(R._lean_row(
                    "US", ticker, symbol, ticker, name, kind, currency, lean))
            continue
        rows.append(R._price_row(
            "US", ticker, symbol, ticker, name, kind, currency, call,
            direction=side))
    quality.attach(rows, flags)
    for row in rows:
        if row.get("chartSymbol") in fallback:
            # Read from the second source, not Yahoo: the row says so.
            row["source"] = nasdaq_bars.SOURCE
    return rows, {"universe": len(records), "missing": sorted(missing),
                  "stale": stale, "shelf": from_shelf,
                  "fallback": sorted(fallback)}


def ondo_portfolio_rows(shelf: dict | None = None) -> tuple[list[dict], dict]:
    """The bullish Ondo intelligent portfolios, and what the scan could not say.

    The seven baskets are tokens on the same shelf, so they belong in the same
    two tables -- asked for by name, 2026-11-07: "include all stocks & ETFs,
    and intelligent portfolios". Their bars are the token's own daily price
    from DeFiLlama (`ondo.bars_for`), which is exactly what the chart a click
    opens draws, so a row and its chart are one series as everywhere else.

    The window is the chart's: `ondo` trims to ninety calendar days for `3mo`
    (`RANGE_DAYS`), so this walk asks for the default ninety-day window rather
    than Yahoo's calendar-month one. They are different shops with different
    trims, and the rule is that a row is the verdict its own chart shows.

    A portfolio that did not answer is counted in `missing`, never judged: a
    token six weeks old has 43 bars, and an empty fetch is an outage, not a
    neutral basket.

    Two things are deliberately plain:

    * **No turnover.** A portfolio token is bought and redeemed, not traded on
      an exchange, so its bars carry no volume and the row carries none either
      -- the peso floor does not apply, and the column says so.
    * **A fixed list, and the shelf decides which of it is on sale.** The
      tokens live in `ondo.py` (a chart needs an identity); the shelf says
      which are still listed, and `actionable` filters the leaning half.
    """
    tokens = ondo.portfolio_tokens()
    listed = set(ondolist.portfolios(shelf)) if shelf else None
    rows: list[dict] = []
    missing: list[str] = []
    judged = 0
    for token in tokens:
        ticker = token["ticker"]
        if listed is not None and ticker not in listed:
            # No longer on sale. Not a fetch failure and not a verdict, so it
            # is not counted as either: the shop stopped listing it.
            continue
        try:
            bars = ondo.bars_for(token, R.WALK_SPAN)
        except ondo.OndoError:
            missing.append(ticker)
            continue
        judged += 1
        stamps, closes, volumes = R._series(bars)
        side, call = labeled_onset(stamps, closes, volumes)
        symbol = ondo.symbol_for(ticker)
        hint = ondo.price_hint(bars)
        if call is None:
            lean = onset_module.steady_lean(stamps, closes, volumes)
            if lean is not None:
                row = R._lean_row("Ondo portfolio", symbol, symbol, ticker,
                                token["name"], token.get("kind"), "USD", lean)
                row.update({"turnover": None, "turnoverPhp": None,
                            "priceHint": hint})
                rows.append(row)
            continue
        row = R._price_row("Ondo portfolio", symbol, symbol, ticker,
                         token["name"], token.get("kind"), "USD", call,
                         direction=side)
        row.update({"turnover": None, "turnoverPhp": None, "priceHint": hint})
        rows.append(row)
    return rows, {"universe": judged + len(missing), "missing": sorted(missing)}


def rate_rows(fetch_us_bars) -> tuple[list[dict], dict]:
    """The bullish United States Treasury futures, and what the scan could not say.

    The curve is a fixed list (`rates.CONTRACTS`), not a ranking: the
    United States leg above judges the most *traded* listings, and a futures
    contract has no place in that -- the TradingView scanner cannot even name
    one -- so every rate was outside this table whatever its chart said. Seven
    contracts, one per curve point, judged exactly like a stock: Yahoo's daily
    bars, which are the bars the chart a click opens draws (the chart route
    sends `ZB=F` to Yahoo, and `fetch_us_bars` asks for the same URL shape), and
    the same `onset` walk over them.

    The window is Yahoo's own three *calendar* months, as it is for the United
    States leg, because that is the window the chart draws.

    Two things are deliberately not the Philippine bond leg:

    * **Nothing is inverted.** A Treasury future is a price, so the
      classifier's own label is the row's -- a higher quote is a higher bond
      price is bullish. `tv.BONDS` inverts because it reads a yield; there is
      no yield here to read.
    * **No turnover.** A contract's volume counts contracts, and close times
      contracts is not a traded value in any currency, so the row carries
      `turnover: None` -- a dash, the way a bond yield and a fund print one.
      The price carries its own
      precision (`rates.price_hint`), because a Treasury quote's fraction is a
      32nd and two decimals would round it away.

    `fetch_us_bars` is the server's browser fetch, injected for the reason
    `us_rows` gives. It is called a second time rather than being merged into
    the United States leg's call: one leg failing must not take the other with
    it, and six symbols are one browser run (~2 s) inside a sweep that already
    spends most of a minute.

    A contract whose bars did not arrive is counted in `missing` and left out,
    never judged bearish (invariant 3).
    """
    contracts = rates.CONTRACTS
    symbols = [contract["symbol"] for contract in contracts]
    try:
        bars = fetch_us_bars(symbols) or {}
    except Exception as exc:
        raise R.RecentError("the Treasury futures' bars could not be fetched: %s"
                          % exc)

    rows: list[dict] = []
    missing: list[str] = []
    flags: dict[str, list] = {}
    for contract in contracts:
        series = bars.get(contract["symbol"])
        if not series:
            missing.append(contract["ticker"])
            continue
        stamps, closes, volumes = series[:3]
        flags[contract["symbol"]] = quality.check(stamps, closes, volumes, volume=False)
        side, call = labeled_onset(stamps, closes, volumes,
                                   months=onset_module.WINDOW_MONTHS)
        hint = rates.price_hint(closes)
        if call is None:
            lean = onset_module.steady_lean(
                stamps, closes, volumes, months=onset_module.WINDOW_MONTHS)
            if lean is not None:
                row = R._lean_row(
                    "US Treasury", contract["symbol"], contract["symbol"],
                    contract["ticker"], contract["name"], "Treasury future",
                    "USD", lean)
                row.update({"turnover": None, "turnoverPhp": None,
                            "priceHint": hint})
                rows.append(row)
            continue
        row = R._price_row(
            "US Treasury", contract["symbol"], contract["symbol"],
            contract["ticker"], contract["name"], "Treasury future", "USD",
            call, direction=side)
        row.update({"turnover": None, "turnoverPhp": None, "priceHint": hint})
        rows.append(row)
    quality.attach(rows, flags)
    return rows, {"universe": len(contracts),
                  "count": sum(1 for row in rows
                               if not row.get("lean")
                               and row.get("direction") != "bearish"),
                  "missing": sorted(missing)}


def crypto_rows() -> tuple[list[dict], dict]:
    """The bullish coins of the chartable USDT ranking.

    The ranking is the one the crypto table walked -- the chartable coins,
    heaviest twenty-four-hour turnover first -- and the bars are Binance's,
    the same ones the crypto chart draws. A coin whose bars did not arrive
    is counted in `missing` rather than judged bearish.

    The walk reads the **whole** ranking, not a top slice: every other market
    on this table is judged exhaustively (the Ondo shelf, the PSE universe, all
    47 funds), and a coin that is bullish on its own chart is a row however
    thinly it trades. A top-25 cut used to be enough when the crypto table sat
    below this one with its own deeper walk; with that table merged in, the cut
    would silently lose rows it was showing -- measured 2026-11-07, the one
    bullish coin of the day (BEAMUSDT, $0.74M traded) ranked around 200th.

    The day condition the crypto table kept is **not** applied. That table was
    a list of what was heavy *and* up today, and a red row under its heading
    read as a fault; this table is the three-month verdict, and the reader asked
    for the three-month reading only -- so the rolling day is not a filter and
    not a figure on the row either.

    Leaning rows are still read only from the first `CRYPTO_LIMIT` candidates,
    so the leaning table is exactly what it was.
    """
    ranked = cryptobull.candidates(cryptobull.MAX_CANDIDATES)
    rows: list[dict] = []
    missing: list[str] = []
    flags: dict[str, list] = {}
    scanned = 0

    def probe(candidate):
        try:
            return crypto.chart(candidate["symbol"], R.WALK_SPAN, R.WALK_INTERVAL)
        except crypto.CryptoNotTrading:
            return "not-trading"   # answered: delisted, not an outage
        except crypto.CryptoError:
            return None

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(R.CRYPTO_WORKERS, max(1, len(ranked)))) as pool:
        charts = list(pool.map(probe, ranked))

    retired = sum(1 for chart in charts if chart == "not-trading")
    ranked, charts = zip(*[(c, ch) for c, ch in zip(ranked, charts)
                           if ch != "not-trading"]) if retired < len(ranked) else ((), ())
    for index, (candidate, chart) in enumerate(zip(ranked, charts)):
        scanned += 1
        if chart is None:
            missing.append(candidate["symbol"])
            continue
        stamps, closes, volumes = R._series(chart.get("points"),
                                          chart.get("volumes"))
        flags[chart["symbol"]] = quality.check(stamps, closes, volumes)
        side, call = labeled_onset(stamps, closes, volumes,
                                   months=R.CRYPTO_WINDOW_MONTHS)
        if call is not None:
            row = R._price_row(
                "Crypto", chart["symbol"], chart["symbol"],
                candidate["ticker"], candidate["name"], "Coin", "USD", call,
                direction=side,
            )
            # The rolling day's change is not carried: this table reports the
            # three-month verdict and the window's own figures, and the reader
            # asked for the three-month reading only (2026-11-07).
            # Decimals the price is drawn at, by magnitude: at the table's
            # default two, a sub-cent coin prints "$0.00", which is a figure
            # that says nothing. The chart's own readout uses the same hint.
            row["priceHint"] = chart.get("priceHint")
            rows.append(row)
            continue
        if index >= R.CRYPTO_LIMIT:
            continue
        lean = onset_module.steady_lean(stamps, closes, volumes,
                                        months=R.CRYPTO_WINDOW_MONTHS)
        if lean is not None:
            rows.append(R._lean_row(
                "Crypto", chart["symbol"], chart["symbol"],
                candidate["ticker"], candidate["name"], "Coin", "USD",
                lean))
    quality.attach(rows, flags)
    return rows, {"universe": len(ranked), "scanned": scanned,
                  "missing": sorted(missing)}


def bond_rows() -> tuple[list[dict], dict]:
    """The Philippine government bond yields, and how each is trending.

    The same classifier reads the yield; the displayed bond-price direction
    and score are inverted. The run remains the underlying yield's run.

    Only a **falling** yield is a row: that is the one yield movement that
    reads as a bond price going up. A rising yield reads as a falling bond
    price, and a flat one has no run to date at all -- neither is something
    that turned bullish, so neither belongs in this table (changed
    2026-10-31, at the reader's request; the three tenors used to be shown
    whatever their verdict). The tenors that were judged and dropped are
    counted in the leg's stats, so the note above the table still says how
    many of the curve's three points were read.

    The three tenors are fetched together -- one browser run, one socket, three
    sessions on it -- and each is kept for `BOND_CACHE_TTL` afterwards, so a
    sweep fifteen minutes after the last one does not pay for the fetch again.
    """
    rows: list[dict] = []
    missing: list[str] = []

    wanted = [symbol for symbol, _ in R.BONDS]
    series: dict[str, list[dict]] = {}
    ages: dict[str, float] = {}
    # The copies that had to be served past their TTL because the fetch did
    # not answer. A copy inside its TTL is an ordinary cache hit and is not
    # flagged; a copy past it is a fallback, and the reader is told.
    fallbacks: set[str] = set()

    # Fresh copies are used as they are, and the network is only asked for
    # the ones that have none.
    for symbol in wanted:
        bars, age = R._cached_bonds(symbol)
        if bars is not None and age <= R.BOND_CACHE_TTL:
            series[symbol] = bars
            ages[symbol] = age

    if len(series) < len(wanted):
        stale = [symbol for symbol in wanted if symbol not in series]
        fresh = tv.histories(stale)
        for symbol, bars in fresh.items():
            series[symbol] = bars
            ages[symbol] = 0.0
            tv.store_bars(symbol, bars)

    # What the network could not answer is served from an older copy if one
    # exists: a row that says "as of three days ago" is more use than a gap
    # in the curve, and the row says which it is.
    for symbol in wanted:
        if symbol in series:
            continue
        bars, age = R._cached_bonds(symbol)
        if bars is not None and age <= R.BOND_CACHE_KEEP:
            series[symbol] = bars
            ages[symbol] = age
            fallbacks.add(symbol)

    for symbol, name in R.BONDS:
        bars = series.get(symbol)
        if not bars:
            missing.append(symbol)
            continue
        age = ages.get(symbol, 0.0)
        stamps = [bar["t"] for bar in bars]
        closes = [bar["c"] for bar in bars]
        volumes = [0.0] * len(closes)
        call = onset_module.current(stamps, closes, volumes)
        if call is None:
            missing.append(symbol)
            continue

        label = call["label"]
        # A falling yield is the only one kept: read as a bond price it is the
        # one direction this table is about. A rising yield would be a bearish
        # row and a flat one has no run to date, so both are dropped here
        # rather than filtered later by the reader.
        if label != "bearish":
            # A yield in the falling side's hold band is a bond price leaning
            # bullish: same window, same reversal as the row below.
            lean = (onset_module.steady_lean(stamps, closes, volumes,
                                             want="bearish")
                    if label == "neutral" else None)
            if lean is not None:
                row = R._lean_row("Philippine bond", symbol, symbol,
                                symbol.split(":")[-1], name,
                                "Government bond yield", "%", lean)
                row.update({
                    "note": "yield falling",
                    "score": -lean["score"],
                    "significance": (-lean["significance"]
                                     if lean["significance"] is not None
                                     else None),
                    "turnover": None,
                    "tz": "Asia/Manila",
                    "stale": int(age) if symbol in fallbacks else 0,
                })
                rows.append(row)
            continue

        # The run of the direction the yield is actually in, which is the one
        # just checked: bearish, so a falling yield.
        run = onset_module.onset(stamps, closes, volumes, want="bearish")
        if run is None:
            # The badge and the walk disagreed on the latest bar; a row with no
            # date cannot say "since when", so it is counted rather than shown.
            missing.append(symbol)
            continue

        rows.append({
            "market": "Philippine bond",
            "symbol": symbol,
            # The row's chart is drawn from the same TradingView series the row
            # was judged on (see `tv.chart`), so the row is a link like any
            # other and a click opens exactly these bars. Before 2026-10-31 it
            # carried nothing here, because the chart route drew what Yahoo
            # draws and Yahoo quotes no Philippine yield.
            "chartSymbol": symbol,
            "ticker": symbol.split(":")[-1],
            "name": name,
            "kind": "Government bond yield",
            "price": closes[-1],
            "currency": "%",
            "direction": "bullish",
            "note": "yield falling",
            "since": run["since"],
            "run": run["run"],
            "censored": run["censored"],
            "manner": run["manner"],
            "turnMove": run["turnMove"],
            "pullback": run.get("pullback"),
            "score": -call["score"],
            "bars": call["bars"],
            "last": stamps[-1],
            "turnover": None,
            # No three-month move: for a yield the level is the figure, and the
            # direction beside it already says how a bond price read the move.
            # A points change over the window is a figure about a figure, so
            # the table prints none for a yield (asked for by name, 2026-11-07:
            # "for bonds, the most important thing is yield. changes don't mean
            # shit. + the bearish or bullish judgment").
            "windowMove": None,
            "chartable": True,
            # The bars are stamped at the close of the Manila session -- five
            # in the morning, which is 21:00 the day before in UTC. So the
            # date of a bar is read in Manila, and the row says which
            # timezone to read it in rather than leaving the front end to
            # guess. Every other row's bars are stamped inside their own
            # session's own day in UTC, so this one carries the field and the
            # rest do not.
            "tz": "Asia/Manila",
            # How old this reading is, in seconds, when it was served as a
            # fallback -- that is, when the fetch did not answer and a copy
            # past its TTL was used instead. Zero for a fresh fetch and zero
            # for an ordinary cache hit inside its TTL. The table shows it,
            # because a yield row that is three days old should not look like
            # one from today.
            "stale": int(age) if symbol in fallbacks else 0,
        })
    return rows, {"universe": len(R.BONDS),
                  "count": sum(1 for row in rows if not row.get("lean")),
                  "missing": missing}


def fund_rows() -> tuple[list[dict], dict]:
    """The bullish Philippine funds, judged on the NAVPU series they publish.

    A fund has no ticker, no exchange and no volume: what it has is one net
    asset value per unit, struck once a business day by its manager. `phfunds`
    reads that series from whichever registry publishes the fund, keeps the
    business days, and hands back the same bars a click on the row will plot --
    so this leg, like every other, is the chart's own window and the chart's
    own classifier (invariant 1).

    Three things are worth knowing about what comes out:

    * **No turnover.** A fund is not traded, so the row carries `turnover:
      None`, and the volume column prints a dash rather than a zero.
    * **A money market fund is always bullish.** Its NAVPU accrues interest
      every day and never marks to a loss, so the three-month window on one is
      essentially always "bullish", and its run is always *censored* ("at least
      this long"). That is a true statement about a cash fund; it is not a
      signal about the market.
    * **A fund that did not answer is missing, not bearish.** Its publisher may
      be down; either way it is counted in `missing` and left out, because a
      fetch failure must never appear as a verdict about a fund (invariant 3).

    The series itself is cached for `phfunds.CACHE_TTL`, so a sweep fifteen
    minutes after the last one reads its funds from disk: a NAVPU is published
    once a business day, and re-reading it four times an hour would buy nothing
    but traffic.
    """
    codes = [entry[0] for entry in phfunds.FUNDS]
    answers = phfunds.refresh(codes)
    rows: list[dict] = []
    missing: list[str] = []
    flags: dict[str, list] = {}
    for code in codes:
        answer = answers.get(code)
        if not isinstance(answer, dict) or not answer.get("bars"):
            missing.append(code)
            continue
        bars = answer["bars"]
        stamps = [bar["t"] for bar in bars]
        closes = [bar["c"] for bar in bars]
        # A fund publishes no volume, so there is nothing for a volume signal
        # to read: zeros are "no volume to say", which is what the classifier
        # expects of a series that has none (the same value the Philippine
        # sweep gives an index).
        volumes = [0.0] * len(closes)
        flags[phfunds.symbol_for(code)] = quality.check(stamps, closes, volumes, volume=False)
        side, call = labeled_onset(stamps, closes, volumes)
        if call is None:
            lean = onset_module.steady_lean(stamps, closes, volumes)
            if lean is not None:
                fund = phfunds.record(code)
                row = R._lean_row(
                    "Philippine fund", phfunds.symbol_for(code),
                    phfunds.symbol_for(code), code, fund["name"],
                    {"Equity": "Equity fund", "Bond": "Bond fund",
                     "Balanced": "Balanced fund",
                     "PERA": "PERA fund"}.get(fund["category"], "Fund"),
                    fund["currency"], lean)
                row.update({
                    "turnover": None,
                    "turnoverPhp": None,
                    "priceHint": phfunds.price_hint(bars),
                    "stale": int(answer["age"]) if answer.get("stale") else 0,
                })
                rows.append(row)
            continue
        # A money-market or short-term fund accrues. A bearish label on one is
        # not a run, so it is left off the bearish list. It is not "missing":
        # the series answered.
        if side == "bearish" and code in phfunds.ACCRUAL_FUNDS:
            continue
        fund = phfunds.record(code)
        rows.append({
            "market": "Philippine fund",
            # The row is a link: `FUND:<CODE>` is what the chart route reads,
            # and it draws exactly these bars through `phfunds.chart`.
            "symbol": phfunds.symbol_for(code),
            "chartSymbol": phfunds.symbol_for(code),
            "ticker": code,
            "name": fund["name"],
            "kind": {"Equity": "Equity fund", "Bond": "Bond fund",
                     "Balanced": "Balanced fund",
                     "PERA": "PERA fund"}.get(fund["category"], "Fund"),
            "category": fund["category"],
            "price": call["price"],
            "currency": fund["currency"],
            "direction": side,
            "since": call["since"],
            "run": call["run"],
            "censored": call["censored"],
            "manner": call["manner"],
            "turnMove": call["turnMove"],
            "pullback": call.get("pullback"),
            "score": call["score"],
            "bars": call["bars"],
            "last": call["last"],
            "turnover": None,
            "turnoverPhp": None,
            # The window's move, like every other price row's.
            "windowMove": R._window_move(call),
            # A four-decimal NAVPU printed at two would round away the only
            # digits that moved this month, so the row carries its own
            # precision for the table to honour.
            "priceHint": phfunds.price_hint(bars),
            "chartable": True,
            # Seconds the reading predates this sweep, when the publisher did
            # not answer and a stored copy was shown instead. Zero for a fresh
            # fetch or a copy inside its TTL.
            "stale": int(answer["age"]) if answer.get("stale") else 0,
        })
    quality.attach(rows, flags)
    return rows, {"universe": len(codes), "scanned": len(codes),
                  "missing": sorted(missing)}


def ph_rows(sweep_rows: list[dict], direction: str = "bullish") -> list[dict]:
    """The Philippine sweep's rows, in this table's row shape.

    The sweep already dated every name it found. `direction` is which list
    those rows belong on. A row that is missing its date is left out rather
    than shown undated: a "since" column that is blank on a row that has one
    everywhere else reads as a rendering fault.
    """
    rows = []
    for row in sweep_rows or []:
        if not row.get("since"):
            continue
        rows.append({
            "market": "Philippines",
            "symbol": row.get("symbol"),
            "chartSymbol": row.get("chartSymbol") or row.get("symbol"),
            "ticker": row.get("ticker"),
            "name": row.get("name"),
            "kind": row.get("kind"),
            "price": row.get("price"),
            "currency": row.get("currency") or "PHP",
            "direction": direction,
            "since": row.get("since"),
            "run": row.get("run"),
            "censored": row.get("censored"),
            "manner": row.get("manner"),
            "turnMove": row.get("turnMove"),
            "pullback": row.get("pullback"),
            "score": row.get("score"),
            "bars": row.get("bars"),
            "last": row.get("last"),
            "turnover": row.get("turnover"),
            "windowMove": R._window_move(row),
            "chartable": True,
        })
    return rows


def ph_lean_rows(sweep_leaning: list[dict]) -> list[dict]:
    """The Philippine sweep's leaning names, in this table's lean-row shape."""
    rows = []
    for row in sweep_leaning or []:
        rows.append({
            "market": "Philippines",
            "symbol": row.get("symbol"),
            "chartSymbol": row.get("chartSymbol") or row.get("symbol"),
            "ticker": row.get("ticker"),
            "name": row.get("name"),
            "kind": row.get("kind"),
            "price": row.get("price"),
            "currency": row.get("currency") or "PHP",
            "direction": "neutral",
            "lean": "bullish",
            "score": row.get("score"),
            "significance": row.get("significance"),
            "progress": row.get("progress"),
            "bars": row.get("bars"),
            "last": row.get("last"),
            "turnover": row.get("turnover"),
            "held": row.get("held"),
            "holdBars": row.get("holdBars"),
            "chartable": True,
        })
    return rows
