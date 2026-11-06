#!/usr/bin/env python3
"""Most-traded tables for the Philippine and United States markets.

Why this module exists
----------------------
The chart shows one instrument at a time; the page also wants the two *market*
views beside it -- the ten most heavily traded Philippine Stock Exchange
listings and the ten most heavily traded US ones. Both come from TradingView's
scanner, which answers an ordinary HTTP POST in under a second: the same source
`pse.py` already trusts for the PSE universe, and for the same reason. See that
module's docstring for why the scanner can be plain HTTP while PSE *bars*
cannot.

Why a share count cannot answer "most traded"
---------------------------------------------
A share count measures nothing comparable. On this session the PSE's
most-traded listing by value -- PNB Holdings, PHP 1.14bn -- is 69th by share
count, because 952 million shares at PHP 1.20 are not one BDO share at PHP 114.
Ranking on the count puts penny stocks above blue chips, and the distortion is
worse across markets than within one, which is exactly what two side-by-side
tables invite a reader to compare. So the ranking is on **turnover**: the
scanner's `Value.Traded`, the session's traded value in the instrument's own
currency. Sorted on it, each table is the list a reader expects -- the US one
is mega-caps, the PSE one is blue chips -- and as a currency amount it is the
figure that converts honestly for a second column.

`Value.Traded` was checked against the tape before being trusted:
PNB Holdings' 952,828,000 shares at its close of PHP 1.20 multiply to exactly
the PHP 1,143,393,600 the scanner reports, so it is turnover and not a share
count under another name.

Both currencies, from a rate we can name
----------------------------------------
Every row carries its turnover in pesos *and* in dollars regardless of which
market it is in, so each table can show its own money first and the other
market's second. The cross rate comes from TradingView's USDPHP per request and
is reported alongside the tables, so the dollar column is a conversion at a
stated rate rather than one frozen into the source. A missing rate costs the
converted column and its own note; it does not cost either table, because the
native figures are the ranking and the conversion is an annotation on it.

The PSE board lot
-----------------
`pse.py` reports a `pricescale`, but that is the tick size, not the board lot,
and the two only sometimes agree: PNB Holdings closes at PHP 1.20 with a
pricescale of 100 -- which would read as a lot of 100 shares -- while the
exchange's published table puts any stock between PHP 0.50 and PHP 4.99 in the
1,000-share bracket. The board lot is a market-wide rule keyed on price, so it
is encoded here from the exchange's own table (`BOARD_LOTS`) rather than
guessed from a per-instrument field that means something else.

`minimum_investment` is the question the lot size is really asked for -- the
smallest peso cheque that can buy the stock -- and it is answered in one place so
the two routes that show it cannot disagree. The leaderboards and `bullish.py`
multiply a scanner close by it; the chart multiplies the latest bar's close by
it. Both read the same table through the same function, so a figure is the same
wherever the page shows it, and neither caller has to know the brackets.

Standard library only, so this imports only `pse` -- for the scanner POST and
its browser fallback, which it already implements and this module shares rather
than repeats. The server registers that fallback once, with `pse`; nothing here
needs a browser of its own.
"""

from __future__ import annotations

import concurrent.futures
import math

import pse

SCANNER = "https://scanner.tradingview.com"
USDPHP_SCAN = f"{SCANNER}/forex/scan"

# The scanner carries two USDPHP rows: a broker's CFD feed (IG) and ICE/IDC's,
# which is the reference rate. Prefer IDC and fall back to whatever answered,
# rather than taking whichever the sort happened to put first.
PREFERRED_FX = "FX_IDC:USDPHP"

# Rows per table, and candidates per query. The US table merges two queries
# (common stock, ETFs) and either one can fill the table by itself, so each has
# to be asked for the full ten -- asking for fewer would drop a fund that
# belongs above a stock from the merged order.
TOP_N = 10

# Column order is part of the protocol: the scanner answers with a bare `d`
# array, which `_row` zips against this tuple rather than indexing positionally.
COLUMNS = ("name", "description", "close", "volume", "Value.Traded",
           "currency", "exchange", "type", "typespecs",
           "last_bar_update_time")

FX_COLUMNS = ("name", "description", "close", "currency", "last_bar_update_time")

# The PSE Board Lot Table -- the exchange's minimum order size for a price
# range (https://www.pse.com.ph/investing-at-pse/). Brackets are half-open on
# the upper bound, (lo, hi], because the published ranges round their halves:
# "PHP 20.00 to 49.95" means 20.00 up to and including 49.999..., not a set with
# a gap at 49.96-49.99. That reading is not an approximation -- each range
# spans exactly one tick short of the next round price, so no order can land in
# a gap. The last published range is open-ended ("PHP 5,000.00 and above").
BOARD_LOTS = (
    (0.0099, 1_000_000),
    (0.0490, 100_000),
    (0.2490, 10_000),
    (0.4950, 10_000),
    (4.99, 1_000),
    (9.99, 100),
    (19.98, 100),
    (49.95, 100),
    (99.95, 10),
    (199.00, 10),
    (499.80, 10),
    (999.50, 10),
    (1_999, 5),
    (4_998, 5),
)
ABOVE_TOP_LOT = 5

# Instrument names. `type` is too coarse to do this alone -- it says "stock" for
# a preferred series exactly as for a common share -- so the finer `typespecs`
# field is what names it, the same split `pse._kind` makes.
KINDS = {
    ("stock", "common"): "Common stock",
    ("stock", "preferred"): "Preferred",
    ("fund", "etf"): "ETF",
    ("fund", "closedend"): "Closed-end fund",
    ("fund", "mutualfund"): "Mutual fund",
    ("dr", ""): "Depositary receipt",
}

MARKETS = (
    {
        "key": "ph",
        "label": "Philippines",
        "section": "philippines",
        "currency": "PHP",
        # No instrument-type filter: the 263-row universe is securities already,
        # every PSE listing trades on the same board-lot table, and anything
        # reaching the top ten by turnover has earned its place in a table of
        # what was most traded.
        "typespecs": (),
        # The chart takes a PSE symbol with its venue attached -- `PSE:TEL`,
        # because bare `TEL` is TE Connectivity.
        "keepVenue": True,
    },
    {
        "key": "us",
        "label": "United States",
        "section": "america",
        "currency": "USD",
        # Common stock and ETFs. This filter is load-bearing rather than a
        # nicety: the America section is venue-wide, so an unfiltered query
        # ranks OTC shells by share count into the top ten (EARI at $0.00025,
        # XCPL at $0.0001) and would do so on turnover too, since a venue that
        # trades trillions a day has no floor worth speaking of. The two specs
        # are separate queries because `type` cannot express "stock or fund"
        # (its `in` operator rejects a list) and `typespecs` is the finer field,
        # which also carries `preferred` and `closedend` -- three orders of
        # magnitude below the tenth slot at this session's turnover, so they are
        # left out rather than fetched and discarded.
        "typespecs": ("common", "etf"),
        # Yahoo takes the bare ticker for a US listing.
        "keepVenue": False,
    },
)


class MarketError(RuntimeError):
    """The market source could not be reached, or returned something unusable."""


def _number(value) -> float | None:
    """A finite float, or None. Booleans are excluded on purpose: True is 1."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _kind(row_type, specs) -> str:
    """TradingView's `type` + `typespecs` -> the instrument name the page shows.

    A row can carry several specs; only the first names the instrument, and an
    unrecognised pair falls back to the coarse `type` rather than to a blank.
    """
    if isinstance(specs, list):
        first = str(specs[0]) if specs else ""
    else:
        first = str(specs or "")
    return KINDS.get((str(row_type), first), str(row_type or "security").title())


def board_lot(price: float | None) -> int | None:
    """The PSE board lot for `price`, or None if there is no usable price.

    See `BOARD_LOTS` for the table and the docstring for why this is not read
    off the instrument's `pricescale`.
    """
    if price is None or not price > 0:
        return None
    for upper, lot in BOARD_LOTS:
        if price <= upper:
            return lot
    return ABOVE_TOP_LOT


def minimum_investment(price: float | None) -> tuple[int | None, float | None]:
    """The smallest cheque that buys `price` -> (shares, pesos), or (None, None).

    The board lot times the price, for any caller holding a PSE price. Public
    and shared on purpose: the leaderboards price a row from a scanner close and
    the chart from its latest bar, and two routes that multiplied for themselves
    could drift on the lot table. A price with no usable value yields no lot and
    no figure, never a zero -- the caller shows a dash rather than claiming a
    stock can be bought for nothing.
    """
    if price is None or not price > 0:
        return None, None
    lot = board_lot(price)
    if lot is None:
        return None, None
    return lot, lot * float(price)


def _scan(section: str, typespec: str | None, limit: int) -> list[dict]:
    """Top `limit` securities in a scanner `section`, by native turnover."""
    body = {
        "filter": ([{"left": "typespecs", "operation": "has", "right": typespec}]
                   if typespec else []),
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": list(COLUMNS),
        "sort": {"sortBy": "Value.Traded", "sortOrder": "desc"},
        "range": [0, limit],
    }
    payload = pse.post_json(f"{SCANNER}/{section}/scan", body)
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise MarketError(f"unexpected scanner payload for {section!r}")
    scanned = []
    for raw in rows:
        row = _row(raw)
        if row is not None:
            scanned.append(row)
    return scanned


def _row(raw) -> dict | None:
    """One scanner row -> our record, or None if it cannot be ranked.

    A row with no turnover has no place in a turnover ranking, so it is dropped
    rather than sorted to the bottom on a zero.
    """
    if not isinstance(raw, dict):
        return None
    symbol = str(raw.get("s") or "")
    cells = dict(zip(COLUMNS, list(raw.get("d") or [])))
    turnover = _number(cells.get("Value.Traded"))
    if not symbol or turnover is None or turnover <= 0:
        return None
    return {
        "symbol": symbol,
        "ticker": symbol.split(":")[-1],
        "name": str(cells.get("description") or symbol.split(":")[-1]),
        "venue": str(cells.get("exchange") or symbol.split(":")[0]),
        "kind": _kind(cells.get("type"), cells.get("typespecs")),
        "price": _number(cells.get("close")),
        "currency": str(cells.get("currency") or ""),
        "turnover": turnover,
        "session": _number(cells.get("last_bar_update_time")),
        "lot": None,
        "lotCost": None,
        "lotCostUsd": None,
    }


def yahoo_symbol(ticker: str) -> str:
    """A United States ticker in the spelling the chart route draws it in.

    The scanner names a class share with a dot (`BRK.B`); Yahoo names the same
    listing with a dash (`BRK-B`), and the chart route asks Yahoo. The
    difference is not cosmetic: the chart route answers `BRK.B` with a 404, so
    a row carrying it would be a row that cannot be drawn -- and, in the recent
    table, a name that looked up and never answered.

    Only a US listing reaches this: a PSE row keeps its venue prefix instead.
    """
    return (ticker or "").replace(".", "-")


def _rank_rows(market: dict, rows) -> dict:
    """One market's table, ranked, from rows already fetched and merged.

    The US table merges two queries, so the merge is by symbol before the sort
    -- a ticker cannot appear in both, but the merge should not depend on that.
    The fetching itself lives in `tables`, which runs the leaf scans side by
    side; this function never touches the network.
    """
    rows = sorted(rows, key=lambda row: row["turnover"], reverse=True)[:TOP_N]

    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        # The symbol the chart route is called with: a PSE listing keeps its
        # venue prefix, a US one drops it -- and takes Yahoo's spelling of a
        # class share, which is a dash rather than a dot (`yahoo_symbol`).
        row["chartSymbol"] = row["symbol"] if market["keepVenue"] \
            else yahoo_symbol(row["ticker"])
        if market["currency"] == "PHP":
            # Only the PSE has a board lot, so only its table carries a minimum
            # investment. It is computed by the shared helper rather than here,
            # so this figure and the chart's are the same arithmetic.
            row["lot"], row["lotCost"] = minimum_investment(row["price"])

    return {
        "key": market["key"],
        "label": market["label"],
        "currency": market["currency"],
        "source": "TradingView",
        # The session the turnover belongs to. Every row carries the same
        # stamp, so the latest is the table's.
        "session": max((row["session"] for row in rows if row["session"]), default=None),
        "rows": rows,
        "error": None,
    }


def _convert(rows: list[dict], php_per_usd: float | None) -> None:
    """Give every row its turnover in both currencies, in place.

    The scanner already reports each row in its own currency, so only the other
    one is computed. A row in some third currency keeps its native figure and
    neither converted one; the page then shows that figure under the row's own
    code rather than a conversion this module cannot justify.
    """
    for row in rows:
        native = row["turnover"]
        currency = (row["currency"] or "").upper()
        row["turnoverPhp"] = native if currency == "PHP" else None
        row["turnoverUsd"] = native if currency == "USD" else None
        if php_per_usd:
            if currency == "PHP":
                row["turnoverUsd"] = native / php_per_usd
            elif currency == "USD":
                row["turnoverPhp"] = native * php_per_usd
            # The minimum investment is a peso amount by construction -- the
            # board lot exists only on the PSE -- so it converts like one.
            if row["lotCost"] is not None:
                row["lotCostUsd"] = row["lotCost"] / php_per_usd


def php_per_usd() -> dict:
    """The peso-dollar rate the tables convert at.

    Raises MarketError if no rate can be had. The caller treats that as a
    missing column rather than a missing table: the native figures are the
    ranking, and the dollar column is an annotation on them.
    """
    body = {
        "filter": [{"left": "name", "operation": "match", "right": "USDPHP"}],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": list(FX_COLUMNS),
        "sort": {"sortBy": "volume", "sortOrder": "desc"},
        "range": [0, 5],
    }
    payload = pse.post_json(USDPHP_SCAN, body)
    quoted = [row for row in (payload.get("data") or []) if isinstance(row, dict)]
    if not quoted:
        raise MarketError("the scanner returned no USDPHP quote")

    pick = next((row for row in quoted if row.get("s") == PREFERRED_FX), quoted[0])
    cells = dict(zip(FX_COLUMNS, list(pick.get("d") or [])))
    rate = _number(cells.get("close"))
    if not rate or rate <= 0:
        raise MarketError("the USDPHP quote carried no usable rate")
    return {
        "pair": "USDPHP",
        "phpPerUsd": rate,
        "symbol": str(pick.get("s") or ""),
        "source": "TradingView",
        "session": _number(cells.get("last_bar_update_time")),
    }


def us_universe(limit: int = 50) -> list[dict]:
    """The most-traded United States listings, heaviest turnover first.

    The universe the "most traded today" card is built from, but not the card:
    that one asks for ten and stops; this one asks for as many as the caller
    wants to judge, because the recent-assets table wants every heavily
    traded US name it can find a verdict for, not the first ten.

    The same two queries the card makes -- common stock and ETF -- because
    `type` cannot express "stock or fund" and the finer `typespecs` field
    carries three orders of magnitude more turnover in the funds than in the
    preferreds and closed-end funds it also carries. Those two are left out
    for the same reason the card leaves them out: they do not reach a table
    of what was most traded.

    Raises `MarketError` when the scanner cannot be reached; a caller that
    wants one card to survive another's outage catches it and carries on.
    """
    market = next((m for m in MARKETS if m["key"] == "us"), None)
    if market is None:
        raise MarketError("the United States market is not configured")
    merged: dict[str, dict] = {}
    for typespec in market["typespecs"]:
        for row in _scan(market["section"], typespec, limit):
            merged.setdefault(row["symbol"], row)
    rows = sorted(merged.values(), key=lambda row: -row["turnover"])[:limit]
    for row in rows:
        # The chart route is called with the bare ticker for a US listing, in
        # the spelling that route draws: `BRK-B`, not the scanner's `BRK.B`.
        row["chartSymbol"] = yahoo_symbol(row["ticker"])
    return rows


def _scan_jobs() -> list[tuple[dict, object]]:
    """Every leaf scanner query the tables need, as (market, typespec) pairs.

    A market with no typespec filter is one job; the US market, which merges
    `common` and `etf`, is two. These are ordinary HTTP POSTs that answer in a
    few hundred milliseconds and share nothing, so they are worth issuing at
    once -- see `tables`.
    """
    return [(market, typespec)
            for market in MARKETS
            for typespec in (market["typespecs"] or (None,))]


def tables() -> dict:
    """Both tables, plus the cross rate their converted columns use.

    Each market is fetched independently, so one section being unreachable costs
    its own card and not the other's. That failure is carried in the payload as
    `error` and rendered, rather than raised, because a page that already has
    one good table should not lose it to the other's outage.

    The five upstream queries -- the cross rate and the leaf scans behind the
    two cards -- are independent plain HTTPs answered by the same scanner in a
    few hundred milliseconds each, and the page asks for all of them the moment
    it loads. Run one after another that is the two-second wait on a cold
    cache; side by side it is one query's wait. Each leaf keeps its own error,
    so a section that fails still fails alone rather than taking the pool with
    it.
    """
    jobs = _scan_jobs()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs) + 1) as pool:
        fx_future = pool.submit(php_per_usd)
        scan_futures = {(market["key"], typespec):
                        pool.submit(_scan, market["section"], typespec, TOP_N)
                        for market, typespec in jobs}
        # `result()` waits on every future, so nothing is cancelled on the way
        # out of the block; an exception raised here would strand a worker.
        try:
            fx = fx_future.result()
            fx_error = None
        except (MarketError, pse.PseError) as exc:
            fx, fx_error = None, str(exc)
        scanned = {}
        for key, future in scan_futures.items():
            try:
                scanned[key] = future.result()
            except (MarketError, pse.PseError) as exc:
                scanned[key] = exc

    rate = fx["phpPerUsd"] if fx else None
    cards = []
    for market in MARKETS:
        # The merge is still by symbol in the market's own typespec order --
        # same first-wins rule as the sequential version, just gathered faster.
        merged: dict[str, dict] = {}
        card_error = None
        for typespec in (market["typespecs"] or (None,)):
            rows = scanned[(market["key"], typespec)]
            if isinstance(rows, Exception):
                # The one failure that survives for this card; later typespecs
                # are still merged if they answered.
                card_error = card_error or rows
                continue
            for row in rows:
                merged.setdefault(row["symbol"], row)
        if card_error is not None and not merged:
            card = {
                "key": market["key"], "label": market["label"],
                "currency": market["currency"], "source": "TradingView",
                "session": None, "rows": [], "error": str(card_error),
            }
        else:
            card = _rank_rows(market, merged.values())
            _convert(card["rows"], rate)
        cards.append(card)

    return {"fx": fx, "fxError": fx_error, "markets": cards}