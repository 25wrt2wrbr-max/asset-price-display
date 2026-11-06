#!/usr/bin/env python3
"""Price history for crypto Yahoo gets wrong.

Why this module exists
----------------------
Yahoo's ticker namespace collides with the crypto one, and it resolves the
collision badly. `JUP-USD` on Yahoo is *Jupiter Project*, a dead 2017 token
trading at $0.00036; the instrument people mean by "Jupiter" is the Solana DEX
token (`jupiter-exchange-solana`, ~$0.34), which Yahoo does not carry at all.
So the symbol cannot be searched for and charts the wrong coin. Coinbase is no
better -- its `JUP-USD` is a third, delisted token. The ticker alone is not an
identity, so we take identity from a source that ranks coins and price from a
venue that actually trades the one we resolved.

    identity   CoinGecko /coins/markets   one call, cached, top 250 by cap
    bars       Binance /api/v3/klines     OHLCV, no key, no rate limit
               (via data-api.binance.vision, the geo-unrestricted mirror)
               Kraken /0/public/OHLC      for a coin Binance has stopped trading

Why not CoinGecko for the bars
------------------------------
Its free tier is 5 requests/minute (`x-ratelimit-limit: 5`; a sixth rapid call
returns 429). That is fine for one cached index lookup and hopeless for a
type-ahead box or a watchlist, so CoinGecko is asked once an hour and Binance
serves the per-request work. Both answer plain HTTP clients -- unlike Yahoo,
which 429s -- so neither needs the browser proxy.

Why the top-250 index
---------------------
Rank separates the real coin from the collision: the live Jupiter is rank 76,
the dead one rank ~4234. Capping the index at 250 coins also keeps it one
request (the full /coins/list is 21,610 entries and would still need ranking to
disambiguate symbol collisions).

Binance covers 138 of those 250 with a `USDT` pair, so a symbol in the index is
not automatically chartable; `coin()` checks both. A coin Binance does not list
(e.g. CRO, LEO) returns None and the caller stays on Yahoo. The pair list moves,
so treat that count as a snapshot, not a constant.

Why "the pair exists" is not "the pair trades"
---------------------------------------------
Binance keeps a **delisted** pair in `ticker/price` at its last price forever, so
the pair list cannot see the difference between a coin trading now and one that
stopped years ago. Measured 2026-11-03, 132 of the top 250 had a `USDT` pair and
five of them were dead: `XMRUSDT` answered $118.70 until its bars were asked for
(they stop 2024-02-20, while Monero traded at $625.94 and Yahoo's own `XMR-USD`
carried that price), `DAIUSDT` stops 2020-08-12, `BTTUSDT` 2022-01-17,
`BEAMUSDT` 2023-01-26 and `LITUSDT` 2025-02-10. A frozen price is worse than no
price: it made `XMR-USD` draw a 2024 window as though it were today's chart, and
-- through `latest_close` -- it made Yahoo's *correct* live price look like the
wrong instrument.

So the bars are the evidence, and `chart()`/`latest_close()` read them:
`STALE_BAR_DAYS` of silence means the pair is not trading, and the coin is then
read from **Kraken**, which still answers for all five (2026-11-03: XMRUSDT →
Kraken `XMRUSD` $624.60, `BTTUSD` 3.63e-07, `BEAMUSD` $0.004076, `LITUSD`
$0.0931, `DAIUSD` $0.99958 -- each a live bar stamped today, and Kraken's 720
daily rows cover two years). Kraken is a *fallback venue*, not a second pair
list: a coin Binance never listed still returns None from `coin()` and stays on
Yahoo, because widening that would reroute every coin whose Yahoo chart merely
reads low. When neither venue is trading the coin, nothing is drawn -- the chart
route then keeps Yahoo's series, which knows what `BTT-USD` is not (its three
months are all zeros while the price is $0.00000036).

Standard library only, so it imports only `trend` and shares the server's
"no dependencies" property.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import trend

COINGECKO_MARKETS = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=250&page=1&sparkline=false"
)
# Binance's public market-data mirror, not `api.binance.com`: the main host
# answers HTTP 451 from some regions ("Service unavailable from a restricted
# location"), which read here as an empty pair list -- so every coin failed the
# `USDT` check, the search box silently lost all crypto additions (PENGU among
# them), and rerouting fell back to Yahoo. `data-api.binance.vision` serves the
# same endpoints with the same payloads and no key, without the geo gate.
BINANCE_TICKER = "https://data-api.binance.vision/api/v3/ticker/price"
BINANCE_KLINES = "https://data-api.binance.vision/api/v3/klines"
BINANCE_24HR = "https://data-api.binance.vision/api/v3/ticker/24hr"

# The fallback venue, for a coin Binance has stopped trading. Plain HTTPS, no
# key; `pair=` takes the concatenated name (`XMRUSD`) and the answer comes back
# under the exchange's own spelling (`XXMRZUSD`), which is why the response is
# read by "the one key that is not `last`" rather than by the name we asked for.
KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC"
# Kraken quotes USD and USDT separately and they are not always both listed
# (`BTTUSD` exists, `BTTUSDT` does not), so both are tried, USD first: it is the
# pair the exchange itself prices in, and the one a dollar chart means.
KRAKEN_QUOTES = ("USD", "USDT")
# Kraken answers at most 720 rows per request whatever the interval, so a five
# year daily request draws two years and claims no more -- the same honest cap
# `ondo.MAX_SPAN_DAYS` puts on a DeFiLlama span.
KRAKEN_MAX_BARS = 720
KRAKEN_INTERVALS = {"1d": 1440, "1w": 10080}

# The index and the pair list barely move, and CoinGecko's budget is 5/minute,
# so an hour is deliberately conservative.
INDEX_TTL = 3600
PAIRS_TTL = 3600
# A last-close probe backs the "Yahoo is charting something else" test, so it
# only has to be fresh enough to catch a collision.
CLOSE_TTL = 300

# How much silence at the end of a pair's bars means it is not trading any more.
# Binance leaves a delisted pair in `ticker/price` indefinitely (see the module
# header): XMRUSDT's newest bar is 2024-02-20, DAIUSDT's 2020-08-12. Five days is
# far past any living daily pair's newest bar -- a pair that trades at all closes
# a bar today, and the newest one is usually still forming -- and far short of a
# dead one's years. A genuinely thin coin that misses five days in a row is
# better served by Yahoo's series than by a chart that stops mid-week.
STALE_BAR_DAYS = 5

HTTP_TIMEOUT = 20
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AssetPriceDisplay/1.0"

# Bars to ask Binance for, per range, at daily resolution. The page draws daily
# closes over three months; the rest is here so the range allowlist stays honest.
RANGE_DAYS = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}

_lock = threading.Lock()
_index_cache: tuple[float, dict | None] = (0.0, None)
_pairs_cache: tuple[float, set | None] = (0.0, None)
_close_cache: dict[str, tuple[float, float | None]] = {}

# Set by the server so a coin source can fall back to the Moli browser path if a
# plain HTTP request is ever refused. Injected rather than imported to keep this
# module free of a cycle back into server.py.
_fallback = None


class CryptoError(RuntimeError):
    """A coin could not be resolved, or its bars could not be fetched."""


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
                    url, headers={"User-Agent": UA, "Accept": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            if _fallback is None:
                break
            status, body = _fallback(url)
            if status >= 400:
                raise CryptoError(f"HTTP {status}")
            return json.loads(body)
        except CryptoError:
            raise
        except Exception as exc:  # urllib raises a wide net of OSErrors
            last = exc
    raise CryptoError(f"coin source unreachable ({url}): {last}")


def _remember(holder: str, value):
    """Store one of the module caches, under the lock."""
    global _index_cache, _pairs_cache
    if holder == "index":
        _index_cache = (time.time(), value)
    else:
        _pairs_cache = (time.time(), value)


def identity_index() -> dict:
    """Top-250 coins by market cap -> {"by_symbol", "ordered"}.

    `by_symbol` keeps the best-ranked coin per ticker, which is what makes a
    lookup unambiguous. On failure the last good index is served rather than
    raising, so a 429 does not blank the search box.
    """
    now = time.time()
    with _lock:
        ts, cached = _index_cache
        if cached is not None and now - ts < INDEX_TTL:
            return cached

    try:
        rows = _get_json(COINGECKO_MARKETS)
        if not isinstance(rows, list):
            raise CryptoError("unexpected markets payload")
    except CryptoError:
        with _lock:
            _, cached = _index_cache
        if cached is not None:
            return cached  # rate-limited, not broken
        raise

    by_symbol: dict[str, dict] = {}
    ordered: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        rank = row.get("market_cap_rank")
        record = {
            "symbol": symbol,
            "name": row.get("name") or symbol,
            "rank": rank if isinstance(rank, int) else None,
            "id": row.get("id"),
        }
        ordered.append(record)
        # Rows arrive market-cap ordered, so the first sighting of a ticker is
        # the highest-ranked one. Do not overwrite it.
        by_symbol.setdefault(symbol, record)

    value = {"by_symbol": by_symbol, "ordered": ordered}
    _remember("index", value)
    return value


def binance_pairs() -> set:
    """Binance spot symbols, as a set (ticker/price is ~160 KB vs 17 MB for
    exchangeInfo, and it lists exactly the pairs that can be charted)."""
    now = time.time()
    with _lock:
        ts, cached = _pairs_cache
        if cached is not None and now - ts < PAIRS_TTL:
            return cached
    try:
        rows = _get_json(BINANCE_TICKER)
        pairs = {str(r.get("symbol")) for r in rows if isinstance(r, dict)}
        pairs.discard("None")
    except CryptoError:
        with _lock:
            _, cached = _pairs_cache
        return cached or set()  # fail closed: no pairs, no reroute
    _remember("pairs", pairs)
    return pairs


def day_tickers() -> list:
    """Every listed symbol's last-24-hours ticker row, as Binance answers it.

    One row per pair -- base volume, `quoteVolume` (the turnover in the quote
    asset), last price, 24-hour change -- which is the raw ranking the
    most-traded table sorts on. The payload is large (several MB, every pair on
    the exchange), so it has no module cache of its own: the scan is the only
    caller, and the server already caches the scan's whole answer.
    """
    rows = _get_json(BINANCE_24HR)
    if not isinstance(rows, list):
        raise CryptoError("unexpected 24-hour ticker payload")
    return rows


def base_symbol(symbol: str) -> str:
    """`JUP-USD` -> `JUP`. Only dashed crypto quote suffixes are stripped, so an
    equity ticker is never mangled."""
    text = (symbol or "").strip().upper()
    for suffix in ("-USDT", "-USDC", "-USD"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def coin(symbol: str) -> dict | None:
    """Resolve a symbol to a chartable coin, or None.

    None means "Yahoo's answer stands": either the ticker is not a top-250 coin
    (equities, ETFs, FX, indices, and long-tail crypto) or Binance has no USDT
    pair for it. Callers treat None as "do not reroute".
    """
    base = base_symbol(symbol)
    if not base:
        return None
    try:
        index = identity_index()
    except CryptoError:
        return None
    record = index["by_symbol"].get(base)
    if record is None:
        return None
    ticker = base + "USDT"
    if ticker not in binance_pairs():
        return None
    resolved = dict(record)
    resolved["ticker"] = ticker
    return resolved


def is_chartable(symbol: str) -> bool:
    return coin(symbol) is not None


def _newest_close_ms(rows) -> float | None:
    """The close stamp of the last well-formed bar, in milliseconds."""
    for row in reversed(rows or []):
        try:
            return float(row[6])
        except (IndexError, TypeError, ValueError):
            continue
    return None


def last_bar_date(rows) -> str | None:
    """The UTC day of the newest bar, for saying *how* old a series is.

    The bar's **open** stamp is its day -- that is where the chart plots it, and
    for a daily bar (Binance closing at 23:59:59.999, Kraken at open+24h) the two
    read the same date.
    """
    for row in reversed(rows or []):
        try:
            return time.strftime("%Y-%m-%d", time.gmtime(float(row[0]) / 1000))
        except (IndexError, TypeError, ValueError):
            continue
    return None


def _is_trading(rows, now: float | None = None) -> bool:
    """Does this pair have a bar recent enough to be today's price?

    A live daily pair's newest bar closes in the future (it is still forming), so
    the test is one-sided: only silence past `STALE_BAR_DAYS` fails. An empty
    answer fails too -- nothing to draw is not a series.
    """
    close_ms = _newest_close_ms(rows)
    if close_ms is None:
        return False
    now = time.time() if now is None else now
    return now - close_ms / 1000.0 <= STALE_BAR_DAYS * 86400


def _klines(ticker: str, interval: str, limit: int) -> list:
    # The ticker is quoted, not pasted: Binance lists pairs whose base asset is
    # not ASCII (`币安人生USDT`), and an unencoded name raises inside urllib, so
    # the pair read as an outage -- `coin()` said chartable and every bars
    # request failed. Quotes are the only characters that need it, exactly as
    # the server's chart URL does for a symbol.
    url = (f"{BINANCE_KLINES}?symbol={urllib.parse.quote(ticker, safe='')}"
           f"&interval={interval}&limit={int(limit)}")
    rows = _get_json(url)
    if not isinstance(rows, list):
        raise CryptoError(f"unexpected klines payload for {ticker}")
    return rows


def _kraken_raw(base: str, interval: str) -> list | None:
    """Kraken's own rows for `base`, or None when it does not list the coin.

    An unknown pair is a **200 with an error list** (`["EQuery:Unknown asset
    pair"]`), not a failure status, so "not listed" has to be read from the body.
    A `CryptoError` here is a transport failure on one quote; the next quote is
    tried, and both failing reads as "no Kraken series" rather than raising --
    the caller still has Yahoo.
    """
    minutes = KRAKEN_INTERVALS.get(interval, 1440)
    for quote in KRAKEN_QUOTES:
        try:
            payload = _get_json(
                f"{KRAKEN_OHLC}?pair={base + quote}&interval={minutes}")
        except CryptoError:
            continue
        if not isinstance(payload, dict) or payload.get("error"):
            continue
        result = payload.get("result")
        if not isinstance(result, dict):
            continue
        for key, rows in result.items():
            if key != "last" and isinstance(rows, list) and rows:
                return rows
    return None


def _kraken_rows(base: str, interval: str, limit: int) -> list:
    """Kraken's bars rewritten into the shape the rest of this module reads.

    Its row is `[time, open, high, low, close, vwap, volume, count]` stamped in
    **seconds** with no close stamp, so the close of a bar is its open plus one
    interval -- the same fact Binance states in its own sixth field, which lets
    `_is_trading`, `last_bar_date` and the drawing loop stay one code path. The
    newest row is the interval still forming, exactly as Binance's is.

    Returns [] when the coin is not on Kraken, so a caller can treat "no venue
    trades it" as one case.
    """
    rows = _kraken_raw(base, interval)
    if not rows:
        return []
    span_ms = KRAKEN_INTERVALS.get(interval, 1440) * 60 * 1000
    out: list[list] = []
    for row in rows[-max(1, min(KRAKEN_MAX_BARS, int(limit))):]:
        try:
            open_ms = int(row[0]) * 1000
            close = float(row[4])
            volume = float(row[6])
        except (IndexError, TypeError, ValueError):
            continue        # tolerate a malformed row rather than lose the series
        out.append([open_ms, None, None, None, close, volume, open_ms + span_ms])
    return out


def _bars(resolved: dict, interval: str, limit: int) -> tuple[list, str]:
    """The newest bars for a coin, and the venue that answered: (rows, venue).

    Binance first -- it is the venue the index resolved the coin against -- and
    Kraken when Binance's pair has stopped trading. When neither is trading, the
    dead Binance rows are handed back so the caller can say *how* old they are.
    """
    rows = _klines(resolved["ticker"], interval, limit)
    if _is_trading(rows):
        return rows, "Binance"
    kraken = _kraken_rows(resolved["symbol"], interval, limit)
    if kraken:
        return kraken, "Kraken"
    return rows, "Binance"


def latest_close(symbol: str, interval: str = "1d") -> float | None:
    """Last completed close, for the disagreement test. Cheap and cached.

    None means "no independent price", which the caller reads as "trust Yahoo".
    A delisted Binance pair is exactly that case: its frozen price is not a
    second opinion about the coin (it is what made Yahoo's live `XMR-USD` look
    wrong), so the pair is skipped and Kraken is asked -- and if Kraken does not
    trade it either, the answer is None.
    """
    resolved = coin(symbol)
    if resolved is None:
        return None
    key = f"{resolved['ticker']}:{interval}"
    now = time.time()
    with _lock:
        hit = _close_cache.get(key)
        if hit and now - hit[0] < CLOSE_TTL:
            return hit[1]
    value = None
    try:
        rows = _klines(resolved["ticker"], interval, 2)
        if not _is_trading(rows, now):
            rows = _kraken_rows(resolved["symbol"], interval, 2)
        if _is_trading(rows, now):
            for row in reversed(rows):
                if int(row[6]) <= now * 1000:  # skip an in-progress bar
                    value = float(row[4])
                    break
    except (CryptoError, IndexError, TypeError, ValueError):
        value = None
    with _lock:
        _close_cache[key] = (now, value)
    return value


def price_hint(price: float) -> int:
    """Decimals to show, by magnitude: $0.00000342, $0.3397, $1.234, $84015.69."""
    if not price:
        return 2
    magnitude = abs(price)
    # Micro-priced coins need enough decimals for two significant figures --
    # six turns PEPE's $0.0000034 into "$0.000003" and SHIB's into "$0.000010".
    if magnitude < 0.001:
        return 8
    if magnitude < 0.01:
        return 6
    if magnitude < 1:
        return 4
    return 2


def chart(symbol: str, span: str, interval: str) -> dict:
    """Daily/weekly bars for a resolved coin, in the server's payload shape.

    Raises CryptoError when the symbol is not chartable, has no bars, or is
    trading on neither venue, so the caller can fall back to Yahoo.
    """
    resolved = coin(symbol)
    if resolved is None:
        raise CryptoError(f"{symbol} is not a chartable crypto pair")

    # A weekly bar covers ~7 days, so the limit has to shrink with the interval;
    # asking for `days` weekly bars would return seven times the range. The cap
    # is Binance's per-request maximum.
    days = RANGE_DAYS.get(span, RANGE_DAYS["3mo"])
    if interval == "1wk":
        source_interval = "1w"
        limit = max(1, min(1000, days // 7))
    else:
        source_interval = "1d"
        limit = days
    rows, venue = _bars(resolved, source_interval, limit)

    if not _is_trading(rows):
        # `coin()` said yes because Binance still lists the pair, but a listed
        # pair is not a trading one (see the module header) and Kraken did not
        # have it either. Drawing what is left would put a 2024 window under
        # today's date, so this refuses instead and the caller keeps Yahoo --
        # which is current for XMR, and, for BTT, honest about having nothing.
        raise CryptoError(
            f"{resolved['symbol']} is not trading on Binance or Kraken "
            f"(newest bar {last_bar_date(rows) or 'missing'})")

    points: list[dict] = []
    volumes: list[float] = []
    now_ms = time.time() * 1000
    live = False
    for index, row in enumerate(rows):
        try:
            open_ms = int(row[0])
            close = float(row[4])
            volume = float(row[5])
            close_ms = int(row[6])
        except (IndexError, TypeError, ValueError):
            continue  # tolerate a malformed row rather than lose the series
        if close_ms > now_ms:
            # The bar still forming. Its close is the last trade, which is
            # the real-time price the badge is asked to judge -- so the newest
            # one is kept and named `liveLastBar`; any other unfinished row
            # would be an upstream oddity and is dropped.
            if index != len(rows) - 1:
                continue
            live = True
        # 8 decimals is Binance's own tick precision for micro-priced coins (and
        # enough for Kraken's, which prints BTT at ten). Rounding looser than
        # that collapses a PEPE-class series (which lives around $0.0000034) onto
        # $0.000003 / $0.000004 / $0.000005 -- a chart of three steps.
        points.append({"t": open_ms // 1000, "c": round(close, 8)})
        volumes.append(volume)

    if not points:
        raise CryptoError(f"No price data for {resolved['symbol']}.")

    # Same contract as the Yahoo path: every series is scored, however short,
    # and only unusable data (a non-positive price) leaves the badge off.
    trend_call = None
    try:
        trend_call = trend.classify([p["c"] for p in points], volumes)
    except ValueError:
        pass

    last = points[-1]["c"]
    previous = points[-2]["c"] if len(points) > 1 else None
    return {
        "symbol": f"{resolved['symbol']}-USD",
        "name": f"{resolved['name']} USD",
        "currency": "USD",
        "exchange": venue,
        "type": "CRYPTOCURRENCY",
        "priceHint": price_hint(last),
        "previousClose": previous,
        "marketPrice": last,
        "points": points,
        # The volume of each bar, aligned to `points`. The badge's own call
        # uses it (the volume signal speaks in the short-window regime), and
        # the "since when" tables need it for the same reason: a walk that
        # redraws a window has to score that window on the same bars the
        # badge scored, volume included.
        "volumes": volumes,
        # The newest bar is the day still trading (its close is the last
        # trade). `server.last_bar_basis` words it "live" while the copy is
        # fresh, never from a disk fallback.
        "liveLastBar": live,
        "trend": trend_call,
        "source": venue,
        "coinRank": resolved["rank"],
    }


def try_chart(symbol: str, span: str, interval: str) -> dict | None:
    """`chart()`, with "not a coin" and "no bars" flattened to None."""
    try:
        return chart(symbol, span, interval)
    except CryptoError:
        return None


def search_coins(query: str, limit: int = 3) -> list[dict]:
    """Coins matching a search box query, best match first.

    Only symbols Binance can actually chart are returned, and every entry is
    labelled with its market-cap rank so a real coin is distinguishable from a
    ticker collision. Never raises: a missing index just means no additions.
    """
    needle = (query or "").strip().lower()
    if len(needle) < 2:
        return []
    try:
        index = identity_index()
    except CryptoError:
        return []
    pairs = binance_pairs()

    scored: list[tuple[int, int, dict]] = []
    for record in index["ordered"]:
        symbol = record["symbol"]
        if symbol + "USDT" not in pairs:
            continue
        ticker = symbol.lower()
        name = record["name"].lower()
        if ticker == needle:
            score = 0            # exact ticker
        elif ticker.startswith(needle):
            score = 1            # ticker prefix
        elif name.startswith(needle):
            score = 2            # name prefix
        elif needle in name:
            score = 3            # name substring
        else:
            continue
        scored.append((score, record["rank"] or 10**9, record))

    scored.sort(key=lambda item: (item[0], item[1]))
    results = []
    for _, rank, record in scored[:limit]:
        # The third column tells coins and equities apart by naming the coin's
        # market-cap rank -- which is exactly what separates the real Jupiter
        # (76) from the dead token (~4234) -- rather than naming a venue. The
        # venue belongs on the chart, where it can say where the bars came from;
        # a symbol Yahoo gets right still charts from Yahoo.
        label = f"crypto · rank {rank}" if rank < 10**9 else "crypto"
        results.append({
            "symbol": f"{record['symbol']}-USD",
            "name": record["name"],
            "exchange": label,
            "type": "CRYPTOCURRENCY",
        })
    return results
