"""The Philippine market by sector: the PSEi, the All Shares index and the six
sector indexes, in one fixed eight-row table.

Each row is the very chart payload the page draws when the row is clicked
(`server.chart_data(symbol, "3mo", "1d")`), so a row and its chart are one
series and one verdict (invariant 1). The page reads the label, the moves and
the high/low tag off those points with the same functions the chart uses.

Built in the background every `TTL` seconds; the route never waits on it and
answers with the last finished table (`pending` before the first one lands).
An index that does not answer is listed in `errors`, never as a neutral row.

TradingView's spellings (checked 2026-11-23): PSE:PSEI, PSE:ALL, PSE:FIN,
PSE:IND, PSE:HDG, PSE:PRO, PSE:SVC, PSE:M_O.
"""

from __future__ import annotations

import threading
import time

import diskcache
import faults

INDEXES = (
    ("PSE:PSEI", "PSEi"),
    ("PSE:ALL", "All Shares"),
    ("PSE:FIN", "Financials"),
    ("PSE:IND", "Industrial"),
    ("PSE:HDG", "Holding Firms"),
    ("PSE:PRO", "Property"),
    ("PSE:SVC", "Services"),
    ("PSE:M_O", "Mining & Oil"),
)
TTL = 900
CACHE_KEY = "sectors:pse:v1"

_lock = threading.Lock()
_payload: dict = {"pending": True, "rows": [], "errors": {}}
_built_at = 0.0
_built_epoch = -1
_thread: threading.Thread | None = None


def seed() -> None:
    """Hydrate the sector table from disk at startup so offline starts have rows."""
    global _payload, _built_at
    saved = diskcache.load(CACHE_KEY)
    if saved is None:
        return
    fetched_at, payload = saved
    if not isinstance(payload, dict) or not payload.get("rows"):
        return
    seeded = dict(payload)
    seeded["cached"] = True
    seeded["fetchedAt"] = int(fetched_at)
    seeded["pending"] = False
    with _lock:
        if not _payload.get("rows"):
            _payload = seeded
            _built_at = 0.0  # still trigger a live refresh once asked


def _preload_batch() -> None:
    """Fetch all eight PSE index charts on one TradingView socket and prime
    each symbol's memo/disk entry so `chart_data` hits cache instead of opening
    eight separate browser runs."""
    try:
        import pse
        import server as S
    except Exception:
        return
    symbols = [sym for sym, _ in INDEXES]
    try:
        batched = pse.charts_many(symbols, "3mo", "1d", chunk=len(symbols),
                                  workers=1, attempts=2)
    except Exception as exc:                  # noqa: BLE001 - best-effort speedup
        faults.note("sectors batch", exc)
        return
    now = time.time()
    for sym, chart in (batched or {}).items():
        if not isinstance(chart, dict) or not chart.get("points"):
            continue
        key = S.chart_key(sym, "3mo", "1d")
        diskcache.store(key, chart)
        with S._cache_lock:
            S._cache[key] = (now, chart)


def build(chart_data, batch: bool = False) -> dict:
    """One pass over the eight indexes through `chart_data`."""
    if batch:
        _preload_batch()
    rows, errors = [], {}
    for symbol, name in INDEXES:
        try:
            data = chart_data(symbol, "3mo", "1d")
        except Exception as exc:              # noqa: BLE001 - reported per row
            faults.note("sectors " + symbol, exc)
            errors[symbol] = str(exc)
            continue
        row = {
            "symbol": symbol,
            "name": name,
            "trend": data.get("trend"),
            "points": [{"t": p["t"], "c": p["c"]} for p in data.get("points") or []],
            "source": data.get("source"),
            "lastBarBasis": data.get("lastBarBasis"),
        }
        if data.get("cached"):
            row["cached"] = True
            row["fetchedAt"] = data.get("fetchedAt")
        rows.append(row)
    return {"rows": rows, "errors": errors, "checkedAt": int(time.time()),
            "pending": False}


def _refresh(chart_data, batch: bool = False, epoch: int | None = None) -> None:
    global _payload, _built_at, _built_epoch, _thread
    try:
        payload = build(chart_data, batch=batch)
        if payload["rows"] and not all(r.get("cached") for r in payload["rows"]):
            diskcache.store(CACHE_KEY, payload)
        with _lock:
            if payload["rows"] or not _payload.get("rows"):
                _payload = payload
            else:
                # Every index failed: keep the last good table on screen and
                # say why beside it, the way the other tables do.
                _payload = dict(_payload, staleError="; ".join(payload["errors"].values()))
            _built_at = time.time()
            if epoch is not None:
                _built_epoch = epoch
    finally:
        with _lock:
            _thread = None


def state(chart_data, epoch: int | None = None) -> dict:
    """The last finished table; starts a refresh when it is older than TTL or
    after a reconnection bumped `epoch`."""
    global _thread
    with _lock:
        reconnected = epoch is not None and epoch > _built_epoch
        due = (reconnected or time.time() - _built_at >= TTL) and _thread is None
        if due:
            _thread = threading.Thread(target=_refresh, args=(chart_data, True, epoch),
                                       name="sectors", daemon=True)
            _thread.start()
        return _payload
