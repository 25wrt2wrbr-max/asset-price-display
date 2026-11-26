"""Pre-IPO trading, put in front of a listing's short exchange history.

`ANT` (Anthropic, PBC) priced its IPO at $83.00 on 2026-11-18 and began Nasdaq
trading on 2026-11-19, so Yahoo's `3mo` chart holds three bars and the page
says "three trading days" about a company the market had been pricing since
August. That earlier pricing exists: Entropy's `io:ANTH` perpetual has traded
the same company since 2026-08-19. It does not quote a share price, though --
it quotes a market cap in billions (1,540 on 2026-11-23 is $1.54T, against the
$1.17T public cap that day) -- so the two series cannot simply be appended.

One factor per ticker makes them one line: the whole pre-listing stretch is
multiplied so the last bar before the first session closes at the IPO price.
Every move and every ratio inside that stretch stays exactly as traded, and
the line arrives at $83.00 where the IPO priced. It is a level match, not a
claim that the perp and the stock agreed: on 2026-11-18 the perp implied
$1.72T, 55% above the price the deal cleared at, so the rescaled history ends
at $83 and the exchange bars open at $97.17 -- the first day's pop, which is
what actually happened.

Business days only, on the New York calendar. The perp prints all seven days
and the listing trades five; a chart of one asset should not change its bar
spacing because the source did. Each pre-IPO bar is stamped at 09:30 local, the
same moment the exchange bars carry, so the x-axis is uniform across the join.

Volumes are deliberately *not* carried. Entropy's are contracts, not shares,
so `barVolumes` keeps its alignment with the exchange bars alone; the page's
volume tag then finds no aligned series and stays quiet, which is the honest
reading of a spliced chart.

A failed fetch is not a verdict: any error leaves the chart exactly as Yahoo
gave it -- three bars, still true -- and `faults.note` records why.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.request
from zoneinfo import ZoneInfo

import faults
import market_days
import sourcestats

import server as S

API = "https://api.hyperliquid.xyz/info"
CACHE_PREFIX = "preipo:"
BARS_TTL = 6 * 3600          # a finished pre-listing bar never changes
HISTORY_DAYS = 1000          # far enough back for the 5y chart's own window

# One entry per listing whose exchange history is shorter than the market's
# interest in it. `ipoPrice` is the offer price the deal priced at, from the
# issuer's own release (anthropic.com, 2026-11-18); `firstSession` is the first
# day the ticker traded on the exchange, so the anchor is the bar before it.
MARKETS = {
    "ANT": {
        "market": "io:ANTH",
        "venue": "Entropy io:ANTH",
        "ipoPrice": 83.00,
        "firstSession": dt.date(2026, 11, 19),
    },
}


def ticker(symbol: str) -> str:
    """The mapped ticker for `symbol`, or "" when this module has no history
    for it. Plain exchange tickers only: `PSE:ANT` and `ANTPHP=X` are other
    instruments and must never pick up a US listing's pre-IPO bars."""
    name = (symbol or "").strip().upper()
    return name if name in MARKETS else ""


def is_preipo_symbol(symbol: str) -> bool:
    return bool(ticker(symbol))


def _now_ms() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)


def _fetch(market: str) -> list[dict]:
    """Every daily bar the market has, oldest first, as `{day, o, h, l, c}`."""
    end = _now_ms()
    start = end - int(dt.timedelta(days=HISTORY_DAYS).total_seconds() * 1000)
    body = json.dumps({"type": "candleSnapshot",
                       "req": {"coin": market, "interval": "1d",
                               "startTime": start, "endTime": end}}).encode()
    request = urllib.request.Request(
        API, data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "asset-price-display"})
    try:
        with sourcestats.timed("Entropy"):
            with urllib.request.urlopen(request, timeout=20) as answer:
                payload = json.loads(answer.read().decode())
    except OSError as exc:            # a transport failure, not a verdict
        raise S.UpstreamError("Entropy: %s" % exc) from exc
    rows = []
    for candle in payload or []:
        try:
            rows.append({"day": dt.datetime.utcfromtimestamp(
                             float(candle["t"]) / 1000).date().isoformat(),
                         "o": float(candle["o"]), "h": float(candle["h"]),
                         "l": float(candle["l"]), "c": float(candle["c"])})
        except (KeyError, TypeError, ValueError):
            continue                   # a malformed candle is not a bar
    rows.sort(key=lambda row: row["day"])
    return rows


def bars(market: str) -> list[dict]:
    """`_fetch`, memoised and rescued from disk on an outage like any other
    series. Wrapped in a dict because a rescued copy is stamped with keys."""
    return S.cached(CACHE_PREFIX + market + ":1d",
                    lambda: {"rows": _fetch(market)},
                    ttl=BARS_TTL).get("rows") or []


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "America/New_York")
    except Exception:                  # a payload with no usable timezone
        return ZoneInfo("America/New_York")


def _day(value) -> dt.date | None:
    """A bar's day from the stored ISO string (a date object would not survive
    the disk copy of the bars, so nothing here stores one)."""
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _stamp(day: dt.date, zone: ZoneInfo) -> int:
    """The bar's stamp: the exchange's 09:30 local, the same convention the
    exchange's own daily bars use, so the join does not kink the x-axis."""
    return int(dt.datetime(day.year, day.month, day.day, 9, 30,
                           tzinfo=zone).timestamp())


def extend(payload: dict, symbol: str, interval: str = "1d") -> dict:
    """`payload` with the ticker's pre-IPO bars in front of its own, or
    unchanged when there is nothing honest to add."""
    spec = MARKETS.get(ticker(symbol))
    if not spec or interval != "1d" or not isinstance(payload, dict):
        return payload
    points = payload.get("points") or []
    if not points:
        return payload
    try:
        rows = bars(spec["market"])
    except Exception as exc:          # the chart is the product, history is extra
        faults.note("preipo bars", exc)
        return payload
    if not rows:
        return payload

    zone = _zone(payload.get("timezone"))
    try:
        first = dt.datetime.fromtimestamp(float(points[0]["t"]), zone).date()
    except (KeyError, TypeError, ValueError):
        faults.note("preipo join", ValueError("no usable first bar"))
        return payload

    anchor = None
    for row in rows:
        day = _day(row.get("day"))
        price = row.get("c")
        if day is None or not isinstance(price, (int, float)):
            continue
        if day < spec["firstSession"]:
            anchor = (day, float(price))
    if anchor is None or not anchor[1] > 0:
        faults.note("preipo anchor", ValueError("no bar before the first session"))
        return payload

    older = []
    for row in rows:
        day = _day(row.get("day"))
        price = row.get("c")
        if day is None or not isinstance(price, (int, float)):
            continue
        if day < first and market_days.nyse_open_day(day):
            older.append((day, float(price)))
    if not older:
        return payload

    factor = spec["ipoPrice"] / anchor[1]
    out = dict(payload)
    out["points"] = ([{"t": _stamp(day, zone), "c": price * factor}
                      for day, price in older] + points)
    out["preipo"] = {
        "market": spec["market"],
        "venue": spec["venue"],
        "bars": len(older),
        "from": older[0][0].isoformat(),
        "ipoPrice": spec["ipoPrice"],
        "factor": round(factor, 8),
        "anchor": anchor[0].isoformat(),
        "anchorClose": anchor[1],
    }
    return out
