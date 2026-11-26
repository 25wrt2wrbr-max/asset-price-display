"""Daily bars from Nasdaq's public quote API: the fallback when Yahoo is out of reach.

Yahoo, through Moli, is the primary source for US stocks and ETFs. When that
path fails (Moli missing, Chrome crashing, Yahoo refusing) the recent table
would lose its whole US leg. This module answers the same question from a
second, independent source over plain HTTPS: official daily closes, no key.

What it is and is not:

* **Closes only.** There is no extended-hours price, so the newest bar is the
  official close, not Yahoo's patched last bar. A row read from here may
  differ from the chart Yahoo draws for the same ticker, so it is marked
  (`meta["fallback"]`, row `source`) instead of passed off as the primary.
* **US stocks and ETFs only.** No futures, currencies or indices.
* **An outage is not a verdict.** A ticker this cannot read is simply
  missing, as before.

Standard library only.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import sourcestats
from concurrent.futures import ThreadPoolExecutor
import faults
import onset as onset_module
import quality
import trend

HOST = "https://api.nasdaq.com"
TIMEOUT = 15
WORKERS = 4
BREAKER_LIMIT = 5              # consecutive transport failures before aborting a batch
DAYS = 380                     # a little over a year, like RECENT_SPAN = "1y"
ASSET_CLASSES = ("stocks", "etf")
TICKER_RE = re.compile(r"^[A-Z]{1,5}([.-][A-Z])?$")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; asset-price-display)",
           "Accept": "application/json"}
SOURCE = "Nasdaq"
SPAN_MONTHS = {"1mo": 1, "3mo": 3, "6mo": 6, "1y": 12}


def fetch_json(url: str) -> dict:
    """`_fetch_json_untimed`, timed and tallied in `sourcestats`."""
    with sourcestats.timed(url):
        return _fetch_json_untimed(url)


def _fetch_json_untimed(url: str) -> dict:
    """One GET, parsed. Separate so tests can replace the network."""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _number(text) -> float | None:
    try:
        return float(str(text).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def parse_rows(payload: dict) -> list[tuple[int, float, float | None]]:
    """The API's newest-first rows -> ascending `(stamp, close, volume)`.

    A row with no readable date or close is dropped (a gap, as with Yahoo).
    The stamp is 14:30 UTC on the trading date, which is the session open
    Yahoo stamps, so day arithmetic downstream reads the same date.
    """
    table = ((payload.get("data") or {}).get("tradesTable") or {})
    out = []
    for row in table.get("rows") or []:
        try:
            month, day, year = (int(x) for x in str(row.get("date")).split("/"))
            stamp = int(dt.datetime(year, month, day, 14, 30,
                                    tzinfo=dt.timezone.utc).timestamp())
        except (ValueError, TypeError):
            continue
        close = _number(row.get("close"))
        if close is None:
            continue
        volume = _number(row.get("volume"))
        out.append((stamp, close, volume))
    out.sort(key=lambda item: item[0])
    return out


def _history_status(ticker: str, today: dt.date | None = None):
    """`(series, transport_failed)` for one ticker."""
    symbol = ticker.upper().replace("-", ".")
    if not TICKER_RE.match(ticker.upper()):
        return None, False
    today = today or dt.date.today()
    start = today - dt.timedelta(days=DAYS)
    for asset in ASSET_CLASSES:
        query = urllib.parse.urlencode({
            "assetclass": asset, "fromdate": start.isoformat(),
            "todate": today.isoformat(), "limit": 400})
        url = f"{HOST}/api/quote/{urllib.parse.quote(symbol)}/historical?{query}"
        try:
            rows = parse_rows(fetch_json(url))
        except (urllib.error.URLError, OSError, ValueError):
            return None, True      # transport trouble: do not try the next class
        if rows:
            stamps, closes, volumes = (list(x) for x in zip(*rows))
            return (stamps, closes, volumes), False
    return None, False


def history(ticker: str, today: dt.date | None = None) -> tuple[list, list, list] | None:
    """`(stamps, closes, volumes)` for a ticker, or None when it cannot be read."""
    series, _ = _history_status(ticker, today)
    return series


def chart(ticker: str, span: str = "3mo", interval: str = "1d",
          today: dt.date | None = None) -> dict | None:
    """One US equity/ETF chart payload from Nasdaq daily closes, or None.

    Used by `chart_route.chart_data` only when Yahoo/Moli hits a transport
    failure, so clicking a Nasdaq-rescued row on the recent table opens the
    same series on a cold cache instead of returning 502.
    """
    if interval != "1d":
        return None
    sym = (ticker or "").strip().upper()
    series = history(sym, today=today)
    if not series:
        return None
    stamps, closes, volumes = series
    if not stamps:
        return None
    all_bars = [{"t": int(t), "c": round(float(c), 6), "v": v}
                for t, c, v in zip(stamps, closes, volumes)]
    months = SPAN_MONTHS.get(span, 3)
    keep = onset_module.window_now(stamps, len(stamps) - 1, months=months)
    if not keep:
        return None
    points = [{"t": all_bars[i]["t"], "c": all_bars[i]["c"]} for i in keep]
    bar_volumes = [all_bars[i]["v"] for i in keep]
    tail = all_bars[:keep[0]][-100:]
    try:
        call = trend.classify([p["c"] for p in points], bar_volumes)
    except ValueError:
        call = None
    last = points[-1]["c"]
    prev = points[-2]["c"] if len(points) > 1 else None
    return {
        "symbol": sym,
        "name": sym,
        "currency": "USD",
        "exchange": "Nasdaq",
        "type": "EQUITY",
        "timezone": "America/New_York",
        "priceHint": 2,
        "previousClose": prev,
        "marketPrice": last,
        "points": points,
        "barVolumes": bar_volumes,
        "historyTail": tail,
        "trend": call,
        "source": SOURCE,
        "quality": quality.check([p["t"] for p in points],
                                 [p["c"] for p in points], bar_volumes),
    }


def fetch(tickers: list[str]) -> dict[str, tuple]:
    """`{ticker: (stamps, closes, volumes, meta)}` for the tickers that answered.

    The shape `server.fetch_us_bars` returns, with `meta["fallback"]` set so
    the table can say where the bars came from. Tickers that did not answer
    are left out, never answered with an empty series. Aborts early after
    `BREAKER_LIMIT` consecutive transport failures so a full outage does not
    stall the sweep for minutes.
    """
    lock = threading.Lock()
    state = {"streak": 0, "tripped": False}

    def one(ticker):
        with lock:
            if state["tripped"]:
                return ticker, None
        try:
            series, failed = _history_status(ticker)
        except Exception as exc:                                 # one bad ticker is not an outage
            faults.note("Nasdaq bars", exc)
            series, failed = None, True
        with lock:
            if failed:
                state["streak"] += 1
                if state["streak"] >= BREAKER_LIMIT:
                    state["tripped"] = True
            else:
                state["streak"] = 0
        return ticker, series

    out = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for ticker, series in pool.map(one, tickers):
            if series:
                out[ticker] = series + ({"name": "", "kind": "", "currency": "USD",
                                         "fallback": SOURCE},)
    return out
