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
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import faults

HOST = "https://api.nasdaq.com"
TIMEOUT = 15
WORKERS = 4
DAYS = 380                     # a little over a year, like RECENT_SPAN = "1y"
ASSET_CLASSES = ("stocks", "etf")
TICKER_RE = re.compile(r"^[A-Z]{1,5}([.-][A-Z])?$")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; asset-price-display)",
           "Accept": "application/json"}
SOURCE = "Nasdaq"


def fetch_json(url: str) -> dict:
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


def history(ticker: str, today: dt.date | None = None) -> tuple[list, list, list] | None:
    """`(stamps, closes, volumes)` for a ticker, or None when it cannot be read."""
    symbol = ticker.upper().replace("-", ".")
    if not TICKER_RE.match(ticker.upper()):
        return None
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
            return None            # transport trouble: do not try the next class
        if rows:
            stamps, closes, volumes = (list(x) for x in zip(*rows))
            return stamps, closes, volumes
    return None


def fetch(tickers: list[str]) -> dict[str, tuple]:
    """`{ticker: (stamps, closes, volumes, meta)}` for the tickers that answered.

    The shape `server.fetch_us_bars` returns, with `meta["fallback"]` set so
    the table can say where the bars came from. Tickers that did not answer
    are left out, never answered with an empty series.
    """
    def one(ticker):
        try:
            return ticker, history(ticker)
        except Exception as exc:                                 # one bad ticker is not an outage
            faults.note("Nasdaq bars", exc)
            return ticker, None

    out = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for ticker, series in pool.map(one, tickers):
            if series:
                out[ticker] = series + ({"name": "", "kind": "", "currency": "USD",
                                         "fallback": SOURCE},)
    return out
