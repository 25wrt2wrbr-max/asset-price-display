#!/usr/bin/env python3
"""The last 24 hours' most-traded crypto, kept only where the chart is bullish
and the rolling day is up.

Why this module exists
----------------------
The page already has two most-traded tables (Philippine and United States,
from the TradingView scanner) and one bullish table (the PSE universe). This
one crosses the two ideas for crypto: rank the market by what was actually
traded over the last twenty-four hours, walk that ranking from the top down,
and keep only the coins whose chart is bullish right now and whose rolling
day is up -- until ten rows are filled. The point of the walk is that the
table is *not* "the ten heaviest coins, whatever their trend": if the top of
the book is bearish, the search expands down the volume ranking until enough
qualifying names are found.

What "most traded" means here
-----------------------------
Binance's 24-hour ticker (`/api/v3/ticker/24hr`, through the same
`data-api.binance.vision` mirror every other Binance call in this project
takes) reports each pair's `quoteVolume` -- the value traded in the quote
asset over the rolling 24 hours. Ranking on `quoteVolume` of the `USDT` pairs
is turnover ranking, the same measure the leaderboards use, in the closest
thing crypto has to a reference currency. Three exclusions keep the ranking
honest:

* **Stablecoins and fiat bases are dropped.** `USDC/USDT` and friends are the
  heaviest "volume" on any exchange, but moving money between two dollars is
  not trading a coin; a euro base is not crypto at all. The lists below are
  explicit rather than inferred -- a near-$1 price heuristic would misfire on
  a coin in a genuine depeg or a slow grind toward a dollar.
* **Only `USDT` pairs are ranked.** The same coin often trades against several
  quotes (`BTCFDUSD`, `BTCTUSD`); ranking every pair would count one coin's
  volume two or three times. USDT is where the turnover is, and -- the
  deciding fact -- identity in this project requires a USDT pair anyway (see
  `crypto.coin`).
* **Only coins the page can chart stay.** `crypto.coin` resolves a base
  through the top-250 CoinGecko index, so long-tail pairs the search box
  cannot name and the chart cannot draw leave the candidate list before any
  bars are fetched. That is a cap on the universe, not a filter on the trend:
  it is the same universe every crypto feature here lives in.

The label is the badge's, not a lookalike
-----------------------------------------
"Bullish" means what `trend.classify` says, on the window the chart draws --
there is no second definition of bullish in the project and there is none
here. The walk does not re-implement the classification: each candidate goes
through `crypto.try_chart(base + "-USD", "3mo", "1d")`, the same function the
chart route ends in for a crypto symbol, and the row keeps the trend call that
payload carries. So a row in this table and the chart its click opens are
labelled by the very same call over the very same bars -- the row cannot say
bullish above a chart whose badge does not.

The price is the chart's own `marketPrice` for the same reason: the latest
*completed* daily close, not the ticker's live print, so a row's price and its
chart can never belong to different moments. The 24-hour change and the 24-hour
turnover are the one figure that is deliberately live -- they describe the
rolling day the table ranks on, and a day is still in progress when the table
is drawn.

Up on the rolling day, too
--------------------------
The classifier judges the window the chart draws -- three months of daily
bars. The table ranks on the rolling day, and the two can disagree: a coin
three months into an uptrend can still be down five percent today. A row that
says bullish above a red 24-hour column reads as anything but bullish -- the
table contradicts its own promise in the reader's eye. The first build shipped
exactly that (every one of its ten rows printed a negative 24-hour change,
three-month uptrends all), which is why this condition exists.

So the walk keeps a candidate only when its 24-hour change is strictly
positive -- the same live figure the row itself prints, judged against the
same green/red colouring the page gives that column. A change of exactly zero
is skipped with the reds: the page's change cell calls zero flat, and
"bullish" that prints flat is the same contradiction one step softer. This is
a second filter, not a second definition of bullish: the chart label stays
`trend.classify`'s on the window the chart draws, unchanged, and a row still
cannot say bullish above a chart whose badge does not. What the table promises
is the conjunction -- bullish on the chart, up on the day -- and the payload's
`flat` count says how many candidates the day condition turned away.

The condition costs nothing to apply. The 24-hour change rides the ticker the
ranking is built from, so a coin that fails it leaves the walk before any bars
are fetched -- a skip, not a probe, which is also why the walk may reach the
whole chartable ranking without its worst case growing.

The search and its bounds
-------------------------
The walk is cheapest done in batches: classification needs bars, bars need one
klines request per coin, and a sequential walk that fills ten rows could
stall on a long bearish stretch. So candidates are probed eight at a time on
a small thread pool -- the shape `markets.tables` already uses for its
independent scanner queries -- and the batch's answers are walked *in volume
order*, so batching changes the speed and not the order. The walk stops at the
first point it has ten bullish rows; a batch over-fetches by at most its own
size.

Two bounds keep the worst case finite. `MAX_CANDIDATES` caps how far down the
ranking the walk may reach -- past it the table ships short rather than
chasing the tail of the book for a row that may not exist. And a coin whose
bars do not answer is skipped and counted in `missing`, exactly as the
Philippine sweep treats a silent symbol: a fetch failure is not a fact about
the trend, and treating it as bearish would let one dead request delete a
qualifying row.

Turnover, both currencies
-------------------------
`turnover` is the 24-hour quote volume in dollars. The peso figure beside it
converts at `markets.php_per_usd` -- the one rate the leaderboards state, not
a second source -- so all three tables on the page agree about what a dollar
is worth. A rate that cannot be had is an annotation failure, not a ranking
one: the dollar column is the ranking, and the payload carries `fxError` for
the page to say so.

Standard library only. It imports `crypto` for the ticker, the identity and
the bars, and `markets` for the cross rate; it has no source of its own, and
nothing imports it but the server.
"""

from __future__ import annotations

import concurrent.futures

import crypto
import markets
import pse

# The window every row's label is judged on: the page's own chart window
# (index.html's RANGE/INTERVAL, mirrored as WARM_SPAN/WARM_INTERVAL in
# server.py). A row here and the chart its click opens are labelled over the
# same bars because both ask for this window.
SPAN, INTERVAL = "3mo", "1d"

# Rows in the table, and how far down the 24-hour volume ranking the walk may
# go to fill them. Ten is the table's cap, not its promise: a market where
# fewer than ten qualifying coins are bullish ships a shorter table and says
# how many it scanned -- the same honesty the bullish sweep's note keeps.
#
# The reach is the whole chartable ranking: `crypto.coin` draws the candidate
# list from the top-250 index, so 250 is every pair the page can name, and a
# larger bound could only name pairs the identity check has already dropped.
# The day condition is what makes the deep reach cheap -- a coin flat or down
# on the rolling day is skipped off the ticker before any bars are fetched --
# so walking deeper costs probes only on coins a row could actually show.
MAX_ROWS = 10
MAX_CANDIDATES = 250

# Probes per batch. Eight klines requests at once is well inside what an
# unauthenticated public endpoint serves without a second thought, and eight
# is enough that filling ten rows usually costs two batches.
SCAN_WORKERS = 8

# Bases whose USDT pair is a dollar moving against itself, or a national
# currency quoted against one. Explicit lists, not a price heuristic: see the
# module docstring. A stablecoin this misses would rank wrongly for a day;
# nothing else breaks.
STABLECOINS = {
    "BUSD", "USDC", "FDUSD", "TUSD", "USDP", "USDD", "DAI", "FRAX",
    "PYUSD", "USDE", "USD1", "AEUR", "EURI", "XUSD", "USDG",
    "USDS", "USDF", "RLUSD", "USDB", "USTC", "CUSDT",
}
FIAT_BASES = {
    "EUR", "GBP", "AUD", "TRY", "BRL", "ARS", "JPY", "MXN", "RON", "ZAR",
    "PLN", "CZK", "HUF", "NOK", "SEK", "UAH", "IDR", "CLP", "COP", "NGN",
}


class CryptoBullError(RuntimeError):
    """The 24-hour ranking could not be had, or carried nothing chartable."""


def _candidates(tickers: list) -> list[dict]:
    """The ranking's chartable candidates, heaviest 24-hour turnover first.

    Each candidate carries what the row will eventually show from the ticker
    alone -- base turnover, 24-hour change -- plus the resolved identity
    `crypto.coin` returns. A pair that is not `USDT`-quoted, is a stablecoin
    or a fiat base, moved no volume, or belongs to a coin the page cannot
    resolve is left out here, before any bars are fetched: the identity check
    is a dictionary lookup against two cached answers, so the expensive walk
    only ever sees coins it can actually name and draw.
    """
    out: list[dict] = []
    for row in tickers:
        if not isinstance(row, dict):
            continue
        pair = str(row.get("symbol") or "")
        if not pair.endswith("USDT"):
            continue
        base = pair[:-len("USDT")]
        if base in STABLECOINS or base in FIAT_BASES:
            continue
        try:
            turnover = float(row.get("quoteVolume"))
            change = float(row.get("priceChangePercent"))
        except (TypeError, ValueError):
            continue
        if not turnover > 0:
            continue
        record = crypto.coin(base + "-USD")
        if record is None:
            continue  # not in the top-250 index, or Binance has no USDT pair
        out.append({
            "symbol": base + "-USD",
            "ticker": record["ticker"],
            "name": record["name"],
            "rank": record["rank"],
            "turnover": turnover,
            "change": change,
        })
    out.sort(key=lambda row: -row["turnover"])
    return out


def candidates(limit: int = MAX_CANDIDATES) -> list[dict]:
    """The chartable USDT ranking, heaviest 24-hour turnover first.

    The walk's candidate list, without the walk. `scan` uses it to fill a
    table of ten; other callers want the same list to look at more of it --
    the recent-assets table asks what the *whole* chartable ranking says, not
    what the first ten of it say, so it needs the ranking itself rather than
    the rows the walk happened to stop on.

    Raises `CryptoBullError` when the ranking itself cannot be had or carries
    nothing chartable: a ranking of nothing is not an answer.
    """
    ranked = _candidates(crypto.day_tickers())
    if not ranked:
        raise CryptoBullError("no chartable USDT pair answered with volume")
    return ranked[:limit]


def _probe(candidate: dict) -> dict | None:
    """One candidate's chart payload, or None when it would not answer.

    `try_chart` flattens "not chartable" and "no bars" to None; the walk reads
    both the same way -- unanswered, counted in `missing`, not judged bearish.
    """
    return crypto.try_chart(candidate["symbol"], SPAN, INTERVAL)


def scan(count: int = MAX_ROWS) -> dict:
    """The table: the heaviest bullish-and-up coins of the last 24 hours, top first.

    Raises `CryptoBullError` only when the ranking itself cannot be had or
    carries nothing chartable. A coin that does not answer is left out of the
    table and counted in `missing` -- the alternative, treating it as "not
    bullish", would put a fetch failure into the table as a fact about the
    coin. A coin flat or down on the rolling day is left out earlier still and
    counted in `flat` -- it failed on the ticker, before any bars were asked
    for.
    """
    candidates = _candidates(crypto.day_tickers())
    if not candidates:
        raise CryptoBullError("no chartable USDT pair answered with volume")

    walk = candidates[:MAX_CANDIDATES]
    # The day condition runs here, off the ticker the ranking came from: a
    # coin flat or down on the rolling day leaves the walk before any bars
    # are fetched. `scanned` keeps counting probes; the note carries how many
    # the day condition turned away.
    up = [row for row in walk if row["change"] > 0]
    flat = len(walk) - len(up)
    rows: list[dict] = []
    missing: list[str] = []
    scanned = 0

    # Probed in batches, walked in order: `pool.map` yields the chunk's answers
    # in the order it was given them, so the volume ranking survives the
    # parallelism and the table's order is the ranking's, not the threads'.
    for start in range(0, len(up), SCAN_WORKERS):
        chunk = up[start:start + SCAN_WORKERS]
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(chunk)) as pool:
            charts = list(pool.map(_probe, chunk))
        for candidate, chart in zip(chunk, charts):
            scanned += 1
            if chart is None:
                missing.append(candidate["symbol"])
                continue
            call = chart.get("trend") or {}
            if call.get("label") != "bullish":
                continue
            rows.append({
                "symbol": chart["symbol"],
                # The chart takes the dash spelling, exactly what a row click
                # loads -- the same promise the bullish table's rows keep.
                "chartSymbol": chart["symbol"],
                "ticker": candidate["ticker"],
                "name": candidate["name"],
                "rank": candidate["rank"],
                "price": chart["marketPrice"],
                # Decimals to show the price at, by magnitude: a sub-cent
                # coin's close at two decimals is $0.00, which says nothing.
                # The same helper the chart's own readout prices with.
                "priceHint": crypto.price_hint(chart["marketPrice"]),
                "currency": "USD",
                "turnover": candidate["turnover"],
                "change": candidate["change"],
                "score": call.get("score"),
                "confidence": call.get("confidence"),
            })
            if len(rows) >= count:
                break
        if len(rows) >= count:
            break

    # The peso column converts at the leaderboards' own rate. An unavailable
    # rate costs the annotation, not the table: `turnover` stays the ranking.
    try:
        fx = markets.php_per_usd()
        fx_error = None
    except (markets.MarketError, pse.PseError) as exc:
        fx, fx_error = None, str(exc)
    rate = fx["phpPerUsd"] if fx else None
    for row in rows:
        row["turnoverUsd"] = row["turnover"]
        row["turnoverPhp"] = row["turnover"] * rate if rate else None

    return {
        "label": "Most traded crypto — 24 hours",
        "currency": "USD",
        "source": "Binance",
        "rows": rows,
        "target": count,
        "scanned": scanned,
        "universe": len(candidates),
        "flat": flat,
        "missing": sorted(missing),
        "fx": fx,
        "fxError": fx_error,
        "error": None,
    }


def summarize(payload: dict) -> str:
    """One line for the card's note: what was scanned, and how much of it answered."""
    rows = len(payload.get("rows") or [])
    scanned = payload.get("scanned") or 0
    universe = payload.get("universe") or 0
    flat = payload.get("flat") or 0
    note = f"{rows} of {scanned} scanned bullish"
    if flat:
        note += f", {flat} skipped flat or down on the day"
    if scanned + flat < universe:
        note += f" (search stopped at the {MAX_ROWS}-row cap)"
    return note
