#!/usr/bin/env python3
"""Collect a fixed, illustrative multi-asset sample through Yahoo via Moli.

Run: python3 forecast_collect.py
The list is selected today and is not a historical point-in-time universe.
Data is research-only; it does not alter the live app's cached prices.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

import server

ROOT = pathlib.Path(__file__).resolve().parent
DESTINATION = ROOT / "research" / "market-history.json"
START = int(dt.datetime(2006, 1, 1, tzinfo=dt.timezone.utc).timestamp())
UNIVERSE = {
    "us_equity": ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "JPM",
                  "BAC", "WMT", "XOM", "CVX", "JNJ", "PG", "KO", "DIS", "PFE",
                  "IBM", "INTC", "AMD", "NFLX", "V", "MA", "ORCL", "CSCO", "GE",
                  "BA", "CAT", "MCD", "NKE", "UNH", "HD", "COST", "ADBE", "CRM"],
    "fund": ["SPY", "QQQ", "IWM", "DIA", "VTI", "EFA", "EEM", "GLD", "SLV", "TLT",
             "IEF", "HYG", "LQD", "VNQ", "USO", "XLF", "XLE", "XLK"],
    "crypto": ["BTC-USD", "ETH-USD", "LTC-USD", "XRP-USD", "BCH-USD", "ADA-USD",
               "DOGE-USD", "SOL-USD", "AVAX-USD", "LINK-USD", "DOT-USD"],
    "currency": ["EURUSD=X", "GBPUSD=X", "JPY=X", "EURJPY=X", "AUDUSD=X", "USDPHP=X",
                 "EURPHP=X", "CHF=X", "CAD=X", "NZDUSD=X"],
}


def clean(payload, today):
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise ValueError("missing chart result")
    timezone = result.get("meta", {}).get("exchangeTimezoneName") or "UTC"
    try:
        zone = ZoneInfo(timezone)
    except (ValueError, KeyError):
        raise ValueError("unknown exchange timezone")
    local_day = today.astimezone(zone).date()
    stamps = result.get("timestamp") or []
    quote_data = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote_data.get("close") or []
    opens = quote_data.get("open") or []
    volumes = quote_data.get("volume") or []
    rows = []
    seen = set()
    for i, stamp in enumerate(stamps):
        try:
            stamp = int(stamp)
            day = dt.datetime.fromtimestamp(stamp, zone).date()
            close = float(closes[i])
            if day >= local_day or day in seen or not math.isfinite(close) or close <= 0:
                continue
            opening = float(opens[i]) if i < len(opens) and opens[i] is not None else None
            volume = float(volumes[i]) if i < len(volumes) and volumes[i] is not None else None
            if opening is not None and (not math.isfinite(opening) or opening <= 0):
                opening = None
            if volume is not None and not math.isfinite(volume):
                volume = None
            rows.append([stamp, opening, close, volume])
            seen.add(day)
        except (ValueError, TypeError, IndexError, OverflowError, OSError):
            continue
    rows.sort(key=lambda row: row[0])
    if not rows:
        raise ValueError("no completed price bars")
    return timezone, rows


def collect():
    now = dt.datetime.now(dt.timezone.utc)
    symbols = {symbol: category for category, items in UNIVERSE.items() for symbol in items}
    urls = {symbol: f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?period1={START}&period2={int(time.time())}&interval=1d" for symbol in symbols}
    data = {"collected_at": now.isoformat(), "source": "Yahoo Finance daily chart bars via Moli; close, not dividend-adjusted",
            "universe": symbols, "missing": {}, "bars": {}, "timezones": {}, "window_months": 3}
    items = list(symbols)
    for start in range(0, len(items), 10):
        chunk = items[start:start + 10]
        try:
            answers = server.moli_batch_get([urls[s] for s in chunk])
        except server.UpstreamError as exc:
            data["missing"].update({symbol: str(exc) for symbol in chunk})
            continue
        for symbol in chunk:
            status, body = answers.get(urls[symbol], (0, ""))
            try:
                if status != 200:
                    raise ValueError(f"HTTP {status}")
                zone, rows = clean(json.loads(body), now)
                data["bars"][symbol] = rows
                data["timezones"][symbol] = zone
            except (ValueError, KeyError, TypeError) as exc:
                data["missing"][symbol] = str(exc)
        print(f"Processed {min(start + 10, len(items))}/{len(items)}; received {len(data['bars'])}", flush=True)
    # Avoid replacing a prior successful collection with an outage.
    if not data["bars"]:
        raise RuntimeError(f"No series received: {data['missing']}")
    DESTINATION.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Saved {len(data['bars'])}/{len(symbols)} histories to {DESTINATION}; missing: {data['missing']}")


if __name__ == "__main__":
    collect()
