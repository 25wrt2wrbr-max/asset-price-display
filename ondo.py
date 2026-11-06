#!/usr/bin/env python3
"""Ondo's tokenized funds: OUSG, the price it trades at, and how to find it.

Why this module exists
----------------------
A reader typed `ousg` into the search box and it answered nothing. Measured
2026-11-02, so the gap is on the record:

* `/v1/finance/search?q=ousg` answers **200 with an empty quote list**, on both
  search hosts, fuzzy off. `q=ondo` answers seven Ondo tokenized *stocks* and
  funds (`ONDO-USD`, `QQQON-USD`, `USOON-USD`, ...) and not this one.
* `/v1/finance/lookup?query=ousg` reports `total: 0` across every type.
* The chart route answers **404** for `OUSG`, `OUSG-USD`, `OUSG-OND`,
  `OUSG29256-USD` -- so there is no spelling of the symbol to fall back on
  either, which is the `probe_ticker` route's whole premise.
* Yahoo can quote the sibling token: `usdy` resolves to `USDY29256-USD`, "Ondo
  US Dollar Yield USD". So this is one instrument the index does not hold, not
  an outage, and no amount of waiting will make it appear.

What the instrument is
----------------------
OUSG is a share of **Ondo's Short-Term U.S. Government Bond Fund** -- a
tokenized T-bill fund. Its price is the fund's per-token value, trading on
Ethereum (and mirrored on Polygon and Solana), and it accrues: the series steps
up with the fund's yield rather than oscillating. Measured 2026-11-02, the
90-day series ran 116.12 -> 117.11, about 2.4% annualised.

That is a property of the instrument, not a classifier bug, and it is the same
one `phfunds` states about a money-market fund: a ninety-day window on a
T-bill token is essentially always bullish, because the thing it tracks only
goes up. The chart says so honestly.

Where the price comes from
--------------------------
**DeFiLlama's coins API** -- `coins.llama.fi/chart/{chain}:{address}`, plain
HTTPS, no key, no rate limit that one chart a minute could reach:

    {"coins": {"ethereum:0x1b19...": {"prices": [{"timestamp": 1793..., "price": 117.1}, ...]}}}

It serves one point per day for a requested `span`, and the newest point is the
current aggregated price. Two things were checked against it before it was
trusted:

* **The number agrees with CoinGecko's to the sixth decimal** -- 117.106259 on
  both, the same day, which is not a coincidence: they read the same on-chain
  market. CoinGecko was the alternative source and was rejected for the bars
  only because its free tier allows five requests a minute, which is fine for
  one cached index lookup and not for a chart the page re-reads every minute.
* **The span is capped at 500 days.** `span=500` returns 500 points; `span=600`
  answers HTTP 400. So the chart route's longer spans (`2y`, `5y`) draw the 500
  days that exist and say no more about the period before it.

The `liveLastBar` claim
-----------------------
The newest point is stamped at the moment of the request and carries the
current price, so the payload says `liveLastBar` -- the page then words it "last
bar is a live price" instead of "close". `server.last_bar_basis` refuses that
word for any payload served from a disk copy, which is the guarantee that keeps
a rescued chart from claiming to be this minute's.

Standard library only, like the rest of the project: it imports `onset` and
`trend` for the verdict, and `pse` for the one table of span days the other
sources already share. `server.py` imports it.
"""

from __future__ import annotations

import datetime
import json
import re
import time
import urllib.request

import onset as onset_module
import pse
import trend

# The symbol prefix a token carries in a URL and in a search row. Yahoo has no
# spelling for OUSG at all, so there is no Yahoo symbol to borrow the way
# `rates.py` borrows `ZB=F`; and a bare `OUSG` is a plausible future Yahoo
# ticker, so the route keys on the prefix -- exactly as `FUND:` and `TVC:` do.
PREFIX = "ONDO:"

# The tokens this module knows, as a **fixed list** -- the shape `rates.CONTRACTS`
# and `tv.BONDS` have: one entry per instrument, its on-chain identity, and the
# words a reader types. A token is not discovered by any ranking; either you are
# looking at OUSG or you are not.
#
# `aliases` are extra search words, because the fund's own name says "Government
# Bond" where a reader says "treasury".
TOKENS = (
    {
        "ticker": "OUSG",
        "name": "Ondo Short-Term U.S. Government Bond Fund",
        "chain": "ethereum",
        "address": "0x1b19c19393e2d034d8ff31ff34c81252fcbbee92",
        "aliases": ("ousg", "ondo", "treasury", "t bill", "t-bill",
                    "tokenized treasury"),
    },
)

# The venue and the kind, as the page prints them: `ONDO:OUSG · Ondo ·
# tokenized fund · via DeFiLlama`. "Tokenized fund" is the honest word -- the
# number is a fund's per-token value, not a moneymarket quote and not a currency.
EXCHANGE = "Ondo"
QUOTE_TYPE = "Tokenized fund"
SOURCE = "DeFiLlama"

CHART_URL = "https://coins.llama.fi/chart/%s:%s?span=%d&period=1d"

# The endpoint refuses a span past 500 days (measured: 500 answers, 600 is a
# 400), so a longer request is clipped rather than failing the symbol.
MAX_SPAN_DAYS = 500

# Yahoo's spans, the same table the fund and bond charts measure their windows
# in, so a token chart's window is the same shape of thing as theirs.
RANGE_DAYS = pse.RANGE_DAYS

# The newest point is the current price when it is stamped this close to now.
# DeFiLlama re-prices every few minutes, so an hour is comfortably inside "the
# last bar is today's price" and outside "this copy is from some other session".
LIVE_STAMP_AGE = 3600

HTTP_TIMEOUT = 20
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AssetPriceDisplay/1.0"

# Set by the server so the module can fall back to the Moli browser path if a
# plain HTTP request is refused -- the same injection `coinsph.py` and `ecb.py`
# use, so this module never has to import the server back.
_fallback = None

_BY_TICKER = {token["ticker"]: token for token in TOKENS}


class OndoError(RuntimeError):
    """The price could not be read -- the wire, not the instrument."""


class OndoNotFound(LookupError):
    """The symbol is not one of the tokens this module knows."""


def set_http_fallback(fn) -> None:
    """Register a `fn(url) -> (status, body)` used if plain HTTP fails."""
    global _fallback
    _fallback = fn


def _get_json(url: str):
    """Fetch JSON, plain HTTP first, then the registered fallback."""
    last: Exception | None = None
    for via_plain in (True, False):
        try:
            if via_plain:
                req = urllib.request.Request(
                    url, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            if _fallback is None:
                break
            status, body = _fallback(url)
            if status >= 400:
                raise OndoError(f"HTTP {status}")
            return json.loads(body)
        except OndoError:
            raise
        except Exception as exc:      # urllib raises a wide net of errors
            last = exc
    raise OndoError(f"DeFiLlama unreachable ({url}): {last}")


# -- identity ---------------------------------------------------------------

def canonical(symbol: str) -> str | None:
    """`ONDO:<TICKER>` for a token this module knows, or None.

    Only the prefixed spelling is accepted here. A bare `OUSG` is left to the
    chart route, which asks Yahoo first and comes back to `alias` only after
    Yahoo refuses it -- the same rule `rates.chart_alias` follows, so a real
    listing that happens to trade under the bare ticker keeps its own chart.
    """
    text = (symbol or "").strip().upper()
    if not text.startswith(PREFIX):
        return None
    return text if text[len(PREFIX):] in _BY_TICKER else None


def is_ondo_symbol(symbol: str) -> bool:
    """Whether `symbol` names one of the tokens this module knows."""
    return canonical(symbol) is not None


def record(symbol: str) -> dict:
    """The token's own record: ticker, name, chain, contract address."""
    canonical_symbol = canonical(symbol)
    if canonical_symbol is None:
        raise OndoNotFound("%r is not one of the tokens this page charts." % symbol)
    return _BY_TICKER[canonical_symbol[len(PREFIX):]]


def symbol_for(ticker: str) -> str:
    """The chart symbol for a token ticker, e.g. `ONDO:OUSG`."""
    return PREFIX + ticker.upper()


def alias(symbol: str) -> str | None:
    """The token a bare ticker names ("OUSG" -> `ONDO:OUSG`), or None.

    Asked by the chart route **only after Yahoo has refused the typed spelling**,
    for the reason `rates.chart_alias` exists: a reader who types "ousg" and
    presses Enter without picking the suggestion should get the chart, but a
    ticker that really is listed keeps its own.
    """
    text = (symbol or "").strip().upper()
    token = _BY_TICKER.get(text)
    return symbol_for(token["ticker"]) if token else None


# -- the price --------------------------------------------------------------

def _parse(document: dict, key: str) -> list[dict]:
    """DeFiLlama's chart document -> bars, oldest first.

    The payload nests one point list per `chain:address` key it was asked for;
    `key` is the one this module asked for, so a document that answered about
    some other contract can never be drawn as this token's series.
    """
    points = ((document or {}).get("coins") or {}).get(key, {}).get("prices") or []
    bars: list[dict] = []
    for point in points:
        try:
            stamp = int(point["timestamp"])
            close = float(point["price"])
        except (KeyError, TypeError, ValueError):
            continue                    # a row this module does not understand
        if stamp <= 0 or not close > 0:
            continue                    # a bar with no trade behind it
        bars.append({"t": stamp, "c": close})
    if not bars:
        raise OndoError("DeFiLlama returned no usable price points")
    bars.sort(key=lambda bar: bar["t"])
    return bars


def bars_for(token: dict, span: str) -> list[dict]:
    """One token's daily points for the chart's span.

    Raises `OndoError` when the wire fails or answers nothing usable -- an
    outage, which the chart route rescues from disk like any other.
    """
    days = min(MAX_SPAN_DAYS, RANGE_DAYS.get(span, RANGE_DAYS["3mo"]))
    key = "%s:%s" % (token["chain"], token["address"])
    return _parse(_get_json(CHART_URL % (token["chain"], token["address"], days)),
                  key)


def price_hint(bars: list[dict]) -> int:
    """Decimals this token's price is quoted with, 2 to 4.

    The same rule `phfunds.price_hint` and `rates.price_hint` follow: the last
    sixty bars say how precisely the number is published, and the clamp keeps a
    source's float noise from asking for six decimals on a $117 quote.
    """
    decimals = 2
    for bar in list(bars or [])[-60:]:
        text = repr(float(bar.get("c", 0))).rstrip("0")
        if "." in text:
            decimals = max(decimals, len(text.split(".")[1]))
    return min(4, decimals)


def _weekly(bars: list[dict]) -> list[dict]:
    """Daily bars -> one bar per ISO week, the week's last point.

    Only for a weekly chart, which the page does not ask for; it exists so
    `interval=1wk` is an answer rather than a 404, the same allowance a fund
    chart makes.
    """
    weeks: dict[tuple[int, int], dict] = {}
    for bar in bars:
        moment = datetime.datetime.fromtimestamp(bar["t"], datetime.timezone.utc)
        weeks[moment.isocalendar()[:2]] = bar
    return [weeks[key] for key in sorted(weeks)]


def _chart_payload(token: dict, bars: list[dict], span: str, interval: str,
                   now: float | None = None) -> dict:
    """One token's bars -> the chart payload the page draws.

    The trim is `onset.window_now`, the same function the tables' walks ask, so
    the badges here read the window the plot draws -- the project's oldest rule.
    A weekly chart is not trimmed, for the reason `server.slim_chart` gives: a
    weekly bar spans days on both sides of the boundary.
    """
    now = time.time() if now is None else now
    ordered = sorted(bars, key=lambda bar: bar["t"])
    points = [{"t": int(bar["t"]), "c": round(float(bar["c"]), 6)}
              for bar in ordered]
    if interval == "1wk":
        points = [{"t": int(bar["t"]), "c": round(float(bar["c"]), 6)}
                  for bar in _weekly(ordered)]
    elif points:
        keep = onset_module.window_now(
            [p["t"] for p in points], len(points) - 1,
            days=RANGE_DAYS.get(span, RANGE_DAYS["3mo"]))
        points = [points[i] for i in keep]
    if not points:
        raise OndoNotFound("No price data for %s in this window." % token["name"])

    try:
        call = trend.classify([p["c"] for p in points])
    except ValueError:
        call = None      # an unscorable series still draws; it just has no badge

    newest = points[-1]["t"]
    return {
        "symbol": symbol_for(token["ticker"]),
        "name": token["name"],
        "currency": "USD",
        # The meta line reads "symbol · exchange · type · via source", so the
        # two halves of the identity are split between them: who issues it here,
        # where the bars were read from in `source`.
        "exchange": EXCHANGE,
        "type": QUOTE_TYPE,
        "priceHint": price_hint(ordered),
        "previousClose": points[-2]["c"] if len(points) > 1 else None,
        "marketPrice": points[-1]["c"],
        "points": points,
        "trend": call,
        # The source's newest point is stamped now and carries the price trading
        # right now, so the bar is live -- and `server.last_bar_basis` refuses
        # that word for a copy served from disk, which keeps a rescued chart
        # from claiming to be this minute's. A weekly bar is a week, not a
        # moment, so it never makes the claim.
        "liveLastBar": bool(interval != "1wk"
                            and now - newest <= LIVE_STAMP_AGE),
        "source": SOURCE,
    }


def chart(symbol: str, span: str = "3mo", interval: str = "1d") -> dict:
    """The chart payload for one token, fetched now.

    Raises `OndoNotFound` for a symbol that is not a token (a verdict about the
    symbol) and `OndoError` when the price could not be read (an outage, which
    the caller rescues from the chart cache like any other).
    """
    token = record(symbol)
    return _chart_payload(token, bars_for(token, span), span, interval)


def charts_many(symbols: list[str], span: str = "3mo",
                interval: str = "1d") -> dict[str, dict | Exception]:
    """`chart()` for several tokens, each answer keyed by the spelling asked.

    The row warmer's leg, so a watchlisted token's chart is retrievable offline
    like every other row's. A symbol that could not be built maps to its
    exception, letting the warmer tell a verdict from a broken wire the way the
    other legs do.
    """
    out: dict[str, dict | Exception] = {}
    for spelling in symbols:
        try:
            out[spelling] = chart(spelling, span, interval)
        except Exception as exc:          # noqa: BLE001 - reported per symbol
            out[spelling] = exc
    return out


# -- search -----------------------------------------------------------------

def _haystack(token: dict) -> str:
    """Everything a query may match, normalised to lower-case words."""
    return " ".join((token["ticker"], token["name"],
                     *token["aliases"])).lower()


def search_tokens(needle: str, limit: int = 3) -> list[dict]:
    """Tokens whose ticker, name or alias answers `needle`, best first.

    The search box asks Yahoo, which has never heard of OUSG, and this
    supplement exists for the same reason the PSE, fund and Treasury ones do:
    what a source does not list, the page still has to be able to find. Every
    word of the query must appear in the token's ticker, name or aliases, so
    "ousg" and "ondo short term" both find it while "ondo stock" does not
    (that is a different Ondo product, and Yahoo lists those itself).

    Rows are shaped like the search route's other rows (`symbol`, `name`,
    `exchange`, `type`) so the suggest list draws them without a special case.
    """
    words = [word for word in re.split(r"[^a-z0-9]+", (needle or "").lower())
             if word]
    if not words:
        return []
    scored: list[tuple[int, int, dict]] = []
    for index, token in enumerate(TOKENS):
        haystack = _haystack(token)
        if not all(word in haystack for word in words):
            continue
        ticker = token["ticker"].lower()
        name = token["name"].lower()
        if ticker == words[0]:
            rank = 0                       # the ticker itself
        elif ticker.startswith(words[0]):
            rank = 1
        elif name.startswith(words[0]):
            rank = 2
        else:
            rank = 3
        scored.append((rank, index, {
            "symbol": symbol_for(token["ticker"]),
            "name": token["name"],
            "exchange": EXCHANGE,
            "type": QUOTE_TYPE,
        }))
    scored.sort(key=lambda item: item[:2])
    return [row for _rank, _index, row in scored[:limit]]
