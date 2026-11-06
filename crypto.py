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

Standard library only, so it imports only `trend` and shares the server's
"no dependencies" property.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
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

# The index and the pair list barely move, and CoinGecko's budget is 5/minute,
# so an hour is deliberately conservative.
INDEX_TTL = 3600
PAIRS_TTL = 3600
# A last-close probe backs the "Yahoo is charting something else" test, so it
# only has to be fresh enough to catch a collision.
CLOSE_TTL = 300

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


def _klines(ticker: str, interval: str, limit: int) -> list:
    url = f"{BINANCE_KLINES}?symbol={ticker}&interval={interval}&limit={int(limit)}"
    rows = _get_json(url)
    if not isinstance(rows, list):
        raise CryptoError(f"unexpected klines payload for {ticker}")
    return rows


def latest_close(symbol: str, interval: str = "1d") -> float | None:
    """Last completed close, for the disagreement test. Cheap and cached."""
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

    Raises CryptoError when the symbol is not chartable or has no bars, so the
    caller can fall back to Yahoo.
    """
    resolved = coin(symbol)
    if resolved is None:
        raise CryptoError(f"{symbol} is not a chartable crypto pair")

    # A weekly bar covers ~7 days, so the limit has to shrink with the interval;
    # asking for `days` weekly bars would return seven times the range. The cap
    # is Binance's per-request maximum.
    days = RANGE_DAYS.get(span, RANGE_DAYS["3mo"])
    if interval == "1wk":
        binance_interval = "1w"
        limit = max(1, min(1000, days // 7))
    else:
        binance_interval = "1d"
        limit = days
    rows = _klines(resolved["ticker"], binance_interval, limit)

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
        # 8 decimals is Binance's own tick precision for micro-priced coins.
        # Rounding looser than that collapses a PEPE-class series (which lives
        # around $0.0000034) onto $0.000003 / $0.000004 / $0.000005 -- a chart
        # of three steps.
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
        "exchange": "Binance",
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
        "source": "Binance",
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
