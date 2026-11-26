"""PSE Edge: the exchange's own site, as a backup for Philippine stock bars.

Why it exists
-------------
Philippine bars come from TradingView's chart socket and the list of names
from its scanner. TradingView's terms forbid reading those undocumented links
by script, so the page could lose both at any time. PSE Edge
(edge.pse.com.ph) is the exchange's own disclosure site, and its company
pages draw their price charts from a JSON link this module reads. It is also
undocumented -- not an official API -- so it lowers the risk, not removes it.

What it gives, and what it does not (verified live 2026-11-23, and in the
reference at github.com/mmangkad/pse-data-scraper, docs/API.md)
--------------------------------------------------------------------------
* `companyDirectory/search.ax`: every listed company, 50 a page, each with
  the two ids the price link needs (`cmDetail('<company>','<security>')`).
  One primary security per company: **no preferred shares, no PSEi**.
* `common/DisclosureCht.ax` (POST, JSON, dates `MM-DD-YYYY`): daily OPEN,
  HIGH, LOW, CLOSE and VALUE, one record per trading day, about a day
  behind. VALUE is **pesos traded, not shares** -- there is no volume field.
  Shares are therefore estimated as VALUE / CLOSE, which gives back VALUE for
  the table's turnover and a fair relative volume for the badge.
* A bad id answers 200 with an empty series: that is a missing name, never
  "no bars" (invariant 3). Repeated dates happen; the last record wins.

Bars are returned in the socket's own row shape, `[t, o, h, l, c, v]`, and
stamped 09:30 Manila like the socket's, so every date rule downstream
(`window_now`, `completed_trade`, `turnover.pse_cutoff`) reads them the same.

Politeness: one request at a time with at least `SPACING` seconds between
them, the directory kept for days and each name's bars for hours.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import threading
import time
import urllib.request
from zoneinfo import ZoneInfo

import diskcache
import faults
import sourcestats

SOURCE = "PSE Edge"
PREFIX = "EDGE:"

BASE = "https://edge.pse.com.ph"
DIRECTORY_URL = BASE + "/companyDirectory/search.ax"
CHART_URL = BASE + "/common/DisclosureCht.ax"
HALTS_URL = BASE + "/disclosureData/halts_and_suspensions_list.do"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0 Safari/537.36"),
}
SPACING = 0.7            # seconds between requests to the site
TIMEOUT = 30
DIRECTORY_TTL = 3 * 86400
BARS_TTL = 6 * 3600      # the data moves once a day
HALTS_TTL = 1800         # halts/suspensions check every 30 min
HALTS_KEY = "pse:edge:halts:v1"
BREAKER_LIMIT = 5        # consecutive transport failures before aborting a batch
HISTORY_DAYS = 400       # the socket's BATCH_BARS (270 bars) in calendar days
MAX_PAGES = 12

_MANILA = ZoneInfo("Asia/Manila")
_net = threading.Lock()
_last_call = 0.0
_halts_lock = threading.Lock()
_halts_memo: tuple[float, dict[str, dict]] | None = None


def is_edge_symbol(symbol: str) -> bool:
    """`EDGE:GLO`: a PSE name charted from PSE Edge's own bars."""
    text = (symbol or "").strip().upper()
    return text.startswith(PREFIX) and len(text) > len(PREFIX)


class EdgeError(Exception):
    """PSE Edge did not answer, or answered with nothing usable."""


def _request(url: str, body: bytes | None = None, extra: dict | None = None) -> bytes:
    """One request, spaced from the last, timed in `sourcestats`."""
    global _last_call
    with _net:
        wait = _last_call + SPACING - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            with sourcestats.timed(url):
                req = urllib.request.Request(url, data=body,
                                             headers={**HEADERS, **(extra or {})})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    if resp.status != 200:
                        raise EdgeError("%s answered HTTP %s" % (url, resp.status))
                    return resp.read()
        except EdgeError:
            raise
        except Exception as exc:              # noqa: BLE001 - transport, any kind
            raise EdgeError("%s did not answer (%s)" % (url, exc))
        finally:
            _last_call = time.monotonic()


# ---------------------------------------------------------------- directory

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_IDS = re.compile(r"cmDetail\('(\d+)'\s*,\s*'(\d+)'\)")
_TAG = re.compile(r"<[^>]+>")
_TOTAL = re.compile(r"\[\s*Total\s*(\d+)\s*\]")


def _text(cell: str) -> str:
    return html.unescape(_TAG.sub("", cell)).strip()


def parse_directory_page(page: str) -> list[dict]:
    """One directory page -> [{ticker, name, sector, company, security}]."""
    out = []
    for row in _ROW.findall(page):
        cells = _CELL.findall(row)
        ids = _IDS.search(row)
        if len(cells) < 3 or not ids:
            continue
        ticker = _text(cells[1]).upper()
        if not re.fullmatch(r"[A-Z0-9]{1,8}", ticker):
            continue
        out.append({"ticker": ticker, "name": _text(cells[0]),
                    "sector": _text(cells[2]),
                    "company": ids.group(1), "security": ids.group(2)})
    return out


def directory(fresh: bool = False) -> dict[str, dict]:
    """{ticker: record} for every company PSE Edge lists, kept for days."""
    key = "pse:edge:directory:v1"
    stored = diskcache.load(key)
    if stored and not fresh and time.time() - stored[0] < DIRECTORY_TTL:
        return stored[1]
    try:
        records: dict[str, dict] = {}
        total = None
        for page_no in range(1, MAX_PAGES + 1):
            page = _request(DIRECTORY_URL + "?pageNo=%d&keyword=&sector=&subsector="
                            % page_no).decode("utf-8", "replace")
            if total is None:
                found = _TOTAL.search(page)
                total = int(found.group(1)) if found else None
            rows = parse_directory_page(page)
            if not rows:
                break
            for record in rows:
                records.setdefault(record["ticker"], record)
            if total is not None and len(records) >= total:
                break
        if not records:
            raise EdgeError("the PSE Edge directory came back empty")
        if total is not None and len(records) < total:
            raise EdgeError("the PSE Edge directory stopped at %d of %d"
                            % (len(records), total))
    except EdgeError as exc:
        if stored:
            faults.note("pse_edge.directory", exc)
            return stored[1]           # an older list beats none
        raise
    diskcache.store(key, records)
    return records


# --------------------------------------------------------------------- bars

def _stamp(chart_date: str) -> int | None:
    """'Nov 20, 2026 00:00:00' -> 09:30 Manila that day, the socket's stamp."""
    try:
        day = dt.datetime.strptime(chart_date.strip(), "%b %d, %Y %H:%M:%S").date()
    except (AttributeError, ValueError):
        return None
    return int(dt.datetime.combine(day, dt.time(9, 30), tzinfo=_MANILA).timestamp())


def parse_chart(payload: dict) -> list[list]:
    """`chartData` -> socket-shaped rows, one per date (the last record wins)."""
    by_stamp: dict[int, list] = {}
    for item in (payload or {}).get("chartData") or []:
        if not isinstance(item, dict):
            continue
        stamp = _stamp(item.get("CHART_DATE"))
        try:
            o, h, l, c = (float(item[k]) for k in ("OPEN", "HIGH", "LOW", "CLOSE"))
        except (KeyError, TypeError, ValueError):
            continue
        if stamp is None or not c > 0:
            continue
        try:
            value = float(item.get("VALUE"))
        except (TypeError, ValueError):
            value = None
        shares = value / c if value is not None and value >= 0 else None
        by_stamp[stamp] = [stamp, o, h, l, c, shares]
    return [by_stamp[t] for t in sorted(by_stamp)]


def bars(ticker: str, fresh: bool = False) -> list[list]:
    """A company's daily bars, socket-shaped. Raises EdgeError when PSE Edge
    does not know the ticker or answers with nothing (a missing name)."""
    ticker = ticker.split(":")[-1].upper()
    key = "pse:edge:bars:v1:" + ticker
    stored = diskcache.load(key)
    if stored and not fresh and time.time() - stored[0] < BARS_TTL:
        return stored[1]
    record = directory().get(ticker)
    if record is None:
        raise EdgeError("PSE Edge does not list %s" % ticker)
    end = dt.datetime.now(_MANILA).date()
    start = end - dt.timedelta(days=HISTORY_DAYS)
    body = json.dumps({"cmpy_id": record["company"],
                       "security_id": record["security"],
                       "startDate": start.strftime("%m-%d-%Y"),
                       "endDate": end.strftime("%m-%d-%Y")}).encode()
    try:
        raw = _request(CHART_URL, body, {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE + "/companyPage/stockData.do"})
        rows = parse_chart(json.loads(raw.decode("utf-8", "replace")))
    except (EdgeError, ValueError) as exc:
        if stored:
            faults.note("pse_edge.bars", exc)
            return stored[1]
        raise EdgeError(str(exc))
    if not rows:
        raise EdgeError("PSE Edge sent no bars for %s" % ticker)
    diskcache.store(key, rows)
    return rows


# PSE Edge prices are the trades as printed, never adjusted for splits or stock
# dividends; TradingView back-adjusts. Measured 2026-11-23 over 241 names:
# identical closes everywhere except COL (TradingView scaled every close before
# 2026-10-16 by 0.625, so its own line jumps +34% on the 19th, while PSE Edge
# shows the real 16% fall) and one day of X. So the sources can disagree around
# a corporate action. A true split (2-for-1 is a 50% "drop" unadjusted) would
# put a false label on a PSE Edge series, so a one-day move this large in the
# recent bars makes it suspect: the sweep leaves the name out (missing, never
# judged) and a chart withholds its label. Only a FALL can be a split, and
# falls this large do not happen otherwise: measured 2026-11-23 over 268 names,
# no one-day fall of 30% in the last 75 bars, while 46 names had one-day
# RISES of 30% or more (thin small caps) -- so rises are never flagged.
SPLIT_RATIO = 0.30
SPLIT_LOOKBACK = 75      # bars: the 3-month window plus the badge's tail


def suspect_split(rows: list[list], lookback: int = SPLIT_LOOKBACK,
                  ratio: float = SPLIT_RATIO) -> int | None:
    """The stamp of the newest one-day fall of `ratio` or more, else None."""
    recent = rows[-lookback:]
    for prev, cur in zip(reversed(recent[:-1]), reversed(recent[1:])):
        if prev[4] > 0 and cur[4] / prev[4] - 1 <= -ratio:
            return cur[0]
    return None


def history_many(symbols) -> dict[str, list]:
    """{"PSE:XXX": rows} for every symbol PSE Edge answered with a series it
    can stand behind; others are left out, exactly as `pse.history_many`
    leaves out a name that did not come (a missing name, never a verdict).
    Stops early after `BREAKER_LIMIT` consecutive transport failures."""
    out: dict[str, list] = {}
    streak = 0
    for symbol in symbols:
        try:
            rows = bars(symbol)
        except EdgeError as exc:
            faults.note("pse_edge.history_many", exc)
            msg = str(exc)
            if "did not answer" in msg or "answered HTTP" in msg:
                streak += 1
                if streak >= BREAKER_LIMIT:
                    faults.note("pse_edge.history_many",
                                EdgeError("stopped after %d consecutive transport failures" % streak))
                    break
            else:
                streak = 0
            continue
        streak = 0
        if suspect_split(rows) is not None:
            faults.note("pse_edge.history_many",
                        EdgeError("%s: possible unadjusted split" % symbol))
            continue
        out[symbol] = rows
    return out


# ------------------------------------------------------ halts & suspensions

def _parse_edge_date(text: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(text.strip(), "%b %d, %Y").date()
    except (AttributeError, ValueError):
        return None


def parse_halts_page(page: str, today: dt.date | None = None) -> dict[str, dict]:
    """PSE Edge Halts & Suspensions HTML -> `{ticker: record}` for active
    suspensions/halts (lifting TBA/empty/future) and same-day halts.

    Older already-lifted halts are ignored so quiet normal stocks stay clean.
    The newest entry per ticker wins (the table is newest-first).
    """
    today = today or dt.datetime.now(_MANILA).date()
    out: dict[str, dict] = {}
    for row in _ROW.findall(page or ""):
        cells = [_text(c) for c in _CELL.findall(row)]
        if len(cells) < 7:
            continue
        raw_syms, action, exec_date, exec_time, lift_date, lift_time, circular = cells[:7]
        action_low = action.lower()
        if "halt" not in action_low and "suspend" not in action_low and "suspension" not in action_low:
            continue
        lift_norm = lift_date.strip().upper()
        if lift_norm in ("", "-", "TBA", "N/A", "UNTIL FURTHER NOTICE"):
            lifted_day = None
            active = True
            same_day = False
        else:
            lifted_day = _parse_edge_date(lift_date)
            if lifted_day is None:
                continue
            active = lifted_day > today
            same_day = lifted_day == today
        if not (active or same_day):
            continue
        rec = {
            "action": "Suspension" if "suspend" in action_low or "suspension" in action_low else "Halt",
            "date": exec_date,
            "time": exec_time,
            "lifting": "TBA" if lifted_day is None else lift_date,
            "liftingTime": "" if lifted_day is None else lift_time,
            "circular": circular,
            "active": active,
            "sameDay": same_day,
            "source": SOURCE,
        }
        for part in re.split(r"[,;/\s]+", raw_syms):
            ticker = part.strip().upper()
            if re.fullmatch(r"[A-Z0-9]{1,8}", ticker):
                out.setdefault(ticker, rec)
    return out


def halts(fresh: bool = False) -> dict[str, dict]:
    """Active & same-day PSE halts/suspensions, best-effort cached for 30 min."""
    global _halts_memo
    now = time.time()
    with _halts_lock:
        if _halts_memo and not fresh and now - _halts_memo[0] < HALTS_TTL:
            return dict(_halts_memo[1])
    stored = diskcache.load(HALTS_KEY)
    if stored and not fresh and now - stored[0] < HALTS_TTL:
        with _halts_lock:
            _halts_memo = (stored[0], stored[1])
        return dict(stored[1])
    try:
        page = _request(HALTS_URL).decode("utf-8", "replace")
        found = parse_halts_page(page)
    except EdgeError as exc:
        faults.note("pse_edge.halts", exc)
        fallback = stored[1] if (stored and isinstance(stored[1], dict)) else {}
        with _halts_lock:
            _halts_memo = (now - HALTS_TTL + 300, fallback)
        return dict(fallback)
    diskcache.store(HALTS_KEY, found)
    with _halts_lock:
        _halts_memo = (now, found)
    return dict(found)


def halt_for(symbol: str) -> dict | None:
    """The active/same-day halt or suspension record for a PSE symbol, else None."""
    ticker = (symbol or "").strip().upper().split(":")[-1]
    if not ticker:
        return None
    return halts().get(ticker)


def envelope(symbol: str) -> dict:
    """The `pse._history` shape (`meta`, `bars`) for the chart builder."""
    ticker = symbol.split(":")[-1].upper()
    record = directory().get(ticker) or {}
    return {"meta": {"name": record.get("name") or ticker,
                     "exchange": "Philippine Stock Exchange",
                     "currency": "PHP", "type": "stock"},
            "bars": bars(ticker), "source": SOURCE}


def universe() -> list[dict]:
    """The stock list in `pse.stocks_index` record shape, for when the
    TradingView scanner is gone. No preferred shares and no PSEi: PSE Edge
    lists one primary security per company."""
    out = []
    for ticker, record in sorted(directory().items()):
        out.append({"symbol": "PSE:" + ticker, "ticker": ticker,
                    "name": record.get("name") or ticker,
                    "kind": "ETF" if record.get("sector") == "ETF" else "EQUITY",
                    "cap": None, "pricescale": None, "source": SOURCE})
    return out
