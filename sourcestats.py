"""Which outside sources answer, how often they fail, and how slow they are.

Every fetch that leaves this machine goes through one small choke point per
source (`crypto._get_json`, `moli_client.moli_get`, ...). Each of those wraps
its call in `timed(url)` (or calls `record`), and this module keeps the tally:

* the last success and the last failure, with the failure's reason;
* per-day counts of calls and failures, and their total and slowest time.

The days are kept on disk (`source-stats.json` in the cache folder), so a
restart does not forget them and a later choice of which source to try first
can rest on weeks of real numbers. `/api/sources` serves `snapshot()`, and
`status.html` draws it.

Recording must never become a failure: every public function here swallows
its own errors (through `faults.note`).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
import urllib.parse

import diskcache
import faults

KEEP_DAYS = 30        # days of counts kept on disk
SAVE_EVERY = 60.0     # seconds between two disk writes
FILE_NAME = "source-stats.json"

# Host -> the name a reader knows the source by. A host not listed here is
# recorded under its own host name, so nothing is lost.
HOSTS = {
    "query1.finance.yahoo.com": "Yahoo Finance",
    "query2.finance.yahoo.com": "Yahoo Finance",
    "finance.yahoo.com": "Yahoo Finance",
    "data-api.binance.vision": "Binance",
    "api.binance.com": "Binance",
    "api.coingecko.com": "CoinGecko",
    "api.kraken.com": "Kraken",
    "api.frankfurter.dev": "Frankfurter (ECB)",
    "api.frankfurter.app": "Frankfurter (ECB)",
    "api.pro.coins.ph": "Coins.ph",
    "coins.llama.fi": "DeFiLlama",
    "app.ondo.finance": "Ondo Finance",
    "api.nasdaq.com": "Nasdaq",
    "scanner.tradingview.com": "TradingView scanner",
    "www.uitf.com.ph": "UITF register (TOAP)",
    "uitf.com.ph": "UITF register (TOAP)",
    "pifa.com.ph": "PIFA",
    "www.pifa.com.ph": "PIFA",
    "www.bpi.com.ph": "BPI Wealth",
    "www.pse.com.ph": "PSE",
    "edge.pse.com.ph": "PSE Edge",
    "www.bsp.gov.ph": "BSP",
    "www.treasury.gov.ph": "Treasury.gov.ph",
}

# Shown on the status page even before their first call, so a source that has
# never answered is visible as "not used yet" rather than missing.
KNOWN = (
    "Yahoo Finance", "Moli browser", "TradingView chart socket",
    "TradingView scanner", "Binance", "CoinGecko", "Frankfurter (ECB)",
    "Coins.ph", "DeFiLlama", "Ondo Finance", "Nasdaq",
    "UITF register (TOAP)", "PIFA", "BPI Wealth",
)

_lock = threading.Lock()
_stats: dict[str, dict] = {}   # name -> {"last": {...}, "days": {date: [...]}}
_loaded = False
_saved_at = 0.0


def name_for(url_or_name: str) -> str:
    """The source name for a URL (by host), or the text itself if not a URL."""
    text = str(url_or_name or "")
    if "://" not in text:
        return text or "unknown"
    host = (urllib.parse.urlsplit(text).hostname or "").lower()
    return HOSTS.get(host, host or "unknown")


def _path() -> str:
    return os.path.join(diskcache.dir(), FILE_NAME)


def _today(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def _load_locked() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            for name, entry in data.items():
                if isinstance(entry, dict) and isinstance(entry.get("days"), dict):
                    days = {day: list(v) for day, v in entry["days"].items()
                            if _good_day(v)}
                    last = entry.get("last")
                    _stats[name] = {"last": dict(last) if isinstance(last, dict) else {},
                                    "days": days}
    except FileNotFoundError:
        pass
    except Exception as exc:
        # Keep the unreadable file beside the new one instead of letting the
        # next save overwrite weeks of counts without a trace.
        faults.note("sourcestats.load", exc)
        try:
            os.replace(_path(), _path() + ".bad")
        except OSError:
            pass


def _good_day(value) -> bool:
    """A day's record: [calls, failures, attempts timed, total s, slowest s]."""
    return (isinstance(value, list) and len(value) == 5
            and all(isinstance(x, (int, float)) for x in value))


def _save_locked(now: float) -> None:
    global _saved_at
    _saved_at = now
    try:
        folder = diskcache.dir()
        os.makedirs(folder, exist_ok=True)
        # Not ".tmp": `diskcache.prune` deletes those from this same folder.
        tmp = _path() + ".writing"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_stats, handle, separators=(",", ":"))
        os.replace(tmp, _path())
    except Exception as exc:
        faults.note("sourcestats.save", exc)


def _prune_locked(now: float) -> None:
    oldest = _today(now - KEEP_DAYS * 86400)
    for entry in _stats.values():
        for day in [d for d in entry["days"] if d < oldest]:
            del entry["days"][day]


def record(source: str, ok: int = 0, failed: int = 0,
           seconds: float | None = None, error: str | None = None,
           now: float | None = None) -> None:
    """Add `ok` answered and `failed` unanswered calls to `source`'s tally.

    `seconds` is how long the whole attempt took (one browser run can carry
    many calls; its time is counted once). `error` is the newest failure's
    reason, kept short.
    """
    try:
        now = time.time() if now is None else now
        name = name_for(source)
        with _lock:
            _load_locked()
            entry = _stats.setdefault(name, {"last": {}, "days": {}})
            # [calls, failures, attempts timed, total seconds, slowest seconds]
            day = entry["days"].setdefault(_today(now), [0, 0, 0, 0.0, 0.0])
            day[0] += int(ok) + int(failed)
            day[1] += int(failed)
            if seconds is not None:
                day[2] += 1
                day[3] = round(day[3] + float(seconds), 3)
                day[4] = round(max(day[4], float(seconds)), 3)
            last = entry["last"]
            if ok:
                last["okAt"] = now
            if failed:
                last["failAt"] = now
                last["error"] = " ".join(str(error or "failed").split())[:200]
            if seconds is not None:
                last["seconds"] = round(float(seconds), 3)
            if now - _saved_at >= SAVE_EVERY:
                _prune_locked(now)
                _save_locked(now)
    except Exception as exc:
        faults.note("sourcestats.record", exc)


_HTTP_CODE = re.compile(r"HTTP (\d{3})")


def is_answer(exc: BaseException) -> bool:
    """Whether an exception is the source *answering* "no" (an HTTP 4xx such as
    "no such pair") rather than not answering. 408 and 429 are the source
    refusing to answer, so they stay failures -- the same rule Yahoo's 404
    follows in `moli_client`."""
    code = getattr(exc, "code", None)
    if not isinstance(code, int):
        match = _HTTP_CODE.search(str(exc))
        code = int(match.group(1)) if match else None
    return code is not None and 400 <= code < 500 and code not in (408, 429)


@contextlib.contextmanager
def timed(source: str):
    """Time the block and record it, re-raising any exception. An exception is
    a failure unless it is the source's own "no" (`is_answer`)."""
    start = time.monotonic()
    try:
        yield
    except BaseException as exc:
        if is_answer(exc):
            record(source, ok=1, seconds=time.monotonic() - start)
        else:
            record(source, failed=1, seconds=time.monotonic() - start,
                   error="%s: %s" % (type(exc).__name__, exc))
        raise
    record(source, ok=1, seconds=time.monotonic() - start)


def flush() -> None:
    """Write the tally to disk now (at shutdown)."""
    with _lock:
        _load_locked()
        _save_locked(time.time())


def _sum(days: dict, since: str) -> dict:
    calls = failed = timed_n = 0
    total = slowest = 0.0
    for day, (c, f, n, t, s) in days.items():
        if day >= since:
            calls += c
            failed += f
            timed_n += n
            total += t
            slowest = max(slowest, s)
    return {
        "calls": calls,
        "failed": failed,
        "failRate": round(failed / calls, 4) if calls else None,
        "avgSeconds": round(total / timed_n, 3) if timed_n else None,
        "slowestSeconds": round(slowest, 3) if timed_n else None,
    }


def snapshot(now: float | None = None) -> dict:
    """Every source's state: `ok` / `failing` / `unused`, last times, and
    counts for today, the last 7 days and the last 30 days."""
    now = time.time() if now is None else now
    with _lock:
        _load_locked()
        names = list(dict.fromkeys(list(KNOWN) + sorted(_stats)))
        rows = []
        for name in names:
            entry = _stats.get(name) or {"last": {}, "days": {}}
            last = entry["last"]
            ok_at, fail_at = last.get("okAt"), last.get("failAt")
            if ok_at is None and fail_at is None:
                state = "unused"
            elif fail_at is not None and (ok_at is None or fail_at > ok_at):
                state = "failing"
            else:
                state = "ok"
            rows.append({
                "source": name,
                "state": state,
                "lastOkAt": ok_at,
                "lastFailAt": fail_at,
                "lastError": last.get("error") if fail_at is not None else None,
                "lastSeconds": last.get("seconds"),
                "today": _sum(entry["days"], _today(now)),
                "week": _sum(entry["days"], _today(now - 6 * 86400)),
                "month": _sum(entry["days"], _today(now - (KEEP_DAYS - 1) * 86400)),
            })
    return {"now": now, "keepDays": KEEP_DAYS, "sources": rows}


def reset() -> None:
    """Forget everything in memory, and read the disk again on next use. For tests."""
    global _loaded, _saved_at
    with _lock:
        _stats.clear()
        _loaded = False
        _saved_at = 0.0
