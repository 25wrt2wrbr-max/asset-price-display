"""Cash and stock dividend dates for PSE names, from PSE Edge.

Why it exists
-------------
On its ex-dividend date a PSE stock opens lower by about the dividend. The
chart's bars are the prices as traded (TradingView's PSE closes match PSE
Edge's raw prints except around splits -- see `pse_edge.SPLIT_RATIO`), so
that drop is in the line. Without a marker it reads as weakness. This module
only says *when* the ex-dates were and are; it never touches a label
(`trend.classify` scores the bars exactly as before).

Source (read live 2026-11-26)
-----------------------------
`disclosureData/dividends_and_rights_info_list.ax?DividendsOrRights=Dividends`
on edge.pse.com.ph: an HTML table, 50 rows a page, newest ex-date first
(future dates included), paged by a form POST (`pageNum`, `sortMode=date`,
`dateSortType=DESC`). Columns: company, type of security (`COMMON` or a
preferred code such as `GLOPA`, `BRNPB Series B`), type (Cash / Stock),
rate (free text: `Php0.60`, `P0.35/share`, `$0.0114 per share (USD)`,
`CAD 0.485`, a bare `0.60`), ex-date, record date, payment date, circular.
Each row links `companyInformation/form.do?cmpy_id=NN`; the directory
(`pse_edge.directory`) maps that id to the common share's ticker.

Like the rest of PSE Edge it is not a published API, so a failure leaves the
chart without markers -- never with a wrong one -- and an older stored copy
is used when the site does not answer.
"""

from __future__ import annotations

import datetime as dt
import re
import threading
import time
import urllib.parse

import diskcache
import faults
import pse_edge

SOURCE = "PSE Edge"
LIST_URL = (pse_edge.BASE + "/disclosureData/dividends_and_rights_info_list.ax"
            "?DividendsOrRights=Dividends")
KEY = "pse:edge:dividends:v1"
TTL = 12 * 3600          # the list changes a few times a day at most
HISTORY_DAYS = 400       # covers the longest chart window (one year) and more
MAX_PAGES = 14

_CMPY = re.compile(r"cmpy_id=(\d+)")
_DATE_FMT = "%b %d, %Y"
_lock = threading.Lock()


def _date(text: str) -> str | None:
    """'Nov 23, 2026' / 'Nov 3, 2026' -> '2026-11-23'; None if unreadable."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    try:
        return dt.datetime.strptime(text, _DATE_FMT).date().isoformat()
    except ValueError:
        return None


_NUM = r"(\d[\d,]*(?:\.\d+)?|\.\d+)"
# A currency mark, then the amount: `Php0.60`, `PHp1.413/share`, `Php/0.054`,
# `P0.35`, `$0.0114`, `CAD 0.485`.
_MONEY = re.compile(r"(?<![A-Z])(PHP|P|US\$|USD|CAD|\$)\s*[/:]?\s*" + _NUM, re.I)
_ANY_NUM = re.compile(_NUM)


def parse_rate(text: str, kind: str) -> tuple[float | None, str | None]:
    """(amount, currency) from the free-text rate; (None, None) when the rate
    is not a per-share cash amount (a stock dividend's percentage, say)."""
    if (kind or "").strip().lower() != "cash":
        return None, None
    text = (text or "").strip()
    marks = _MONEY.findall(text)
    if len(marks) > 1:
        # Two amounts (`P1.00 regular and P0.50 special`, `Php0.60 (approx.
        # US$0.01)`): left unread, so the page shows the source's own words.
        return None, None
    if marks:
        mark, number = marks[0]
        mark = mark.upper()
        currency = "CAD" if mark == "CAD" else "USD" if mark in ("US$", "USD", "$") else "PHP"
    else:
        # No mark (`0.60`, `Four centavos (0.04)`): only a lone number is
        # taken as the amount; two numbers are ambiguous and left unread.
        numbers = _ANY_NUM.findall(text)
        if len(numbers) != 1:
            return None, None
        number = numbers[0]
        currency = ("CAD" if re.search(r"\bCAD\b", text, re.I)
                    else "USD" if re.search(r"\bUSD\b", text, re.I) else "PHP")
    try:
        amount = float(number.replace(",", ""))
    except ValueError:
        return None, None
    return (amount, currency) if amount > 0 else (None, None)


def parse_page(page: str) -> list[dict]:
    """One list page -> [{company_id, company, security, kind, rate, amount,
    currency, ex, record, pay, circular}]; header and odd rows skipped."""
    out = []
    for row in pse_edge._ROW.findall(page):
        cells = pse_edge._CELL.findall(row)
        if len(cells) < 8:
            continue
        text = [pse_edge._text(c) for c in cells]
        ex = _date(text[4])
        if not ex:
            continue
        found = _CMPY.search(row)
        kind = text[2]
        amount, currency = parse_rate(text[3], kind)
        out.append({
            "company_id": found.group(1) if found else None,
            "company": text[0],
            "security": text[1],
            "kind": kind,
            "rate": text[3],
            "amount": amount,
            "currency": currency,
            "ex": ex,
            "record": _date(text[5]),
            "pay": _date(text[6]),
            "circular": text[7],
        })
    return out


def _fetch_page(page_no: int) -> str:
    body = urllib.parse.urlencode({
        "pageNum": page_no, "sortMode": "date",
        "dateSortType": "DESC", "cmpySortType": "ASC",
    }).encode()
    return pse_edge._request(LIST_URL, body, {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": pse_edge.BASE + "/disclosureData/dividends_and_rights_info.ax",
    }).decode("utf-8", "replace")


def fetch_all(today: dt.date | None = None, fetch_page=None) -> list[dict]:
    """Every listed dividend from the newest down to `HISTORY_DAYS` ago."""
    fetch_page = fetch_page or _fetch_page
    floor = ((today or dt.date.today()) - dt.timedelta(days=HISTORY_DAYS)).isoformat()
    rows: list[dict] = []
    seen = set()
    for page_no in range(1, MAX_PAGES + 1):
        page_rows = parse_page(fetch_page(page_no))
        if not page_rows:
            break
        for r in page_rows:
            mark = (r["company_id"], r["security"], r["ex"], r["circular"])
            if mark not in seen:
                seen.add(mark)
                rows.append(r)
        if min(r["ex"] for r in page_rows) < floor:
            break
    if not rows:
        raise pse_edge.EdgeError("the PSE Edge dividend list came back empty")
    return [r for r in rows if r["ex"] >= floor]


RETRY_AFTER = 600        # seconds a failed refresh waits before the next try
_last_failure = 0.0


def listing(fresh: bool = False) -> tuple[list[dict], float, bool]:
    """(rows, fetched_at, from_stored_copy). Raises EdgeError only when the
    site does not answer and nothing is stored. After a failed refresh the
    stored copy is served for `RETRY_AFTER` seconds without asking again, so
    an outage costs one wait, not one per chart opened."""
    global _last_failure
    with _lock:
        stored = diskcache.load(KEY)
        if stored and not fresh and time.time() - stored[0] < TTL:
            return stored[1], stored[0], False
        if stored and time.monotonic() - _last_failure < RETRY_AFTER and _last_failure:
            return stored[1], stored[0], True
        try:
            rows = fetch_all()
        except pse_edge.EdgeError as exc:
            _last_failure = time.monotonic()
            if stored:
                faults.note("pse_dividends.listing", exc)
                return stored[1], stored[0], True
            raise
        diskcache.store(KEY, rows)
        return rows, time.time(), False


def ticker_of(symbol: str) -> str | None:
    """`PSE:BDO`, `EDGE:BDO`, `bdo.ps` -> `BDO`; None for anything else."""
    text = (symbol or "").strip().upper()
    for prefix in ("PSE:", pse_edge.PREFIX):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    else:
        if text.endswith(".PS"):
            text = text[:-3]
        else:
            return None
    return text if re.fullmatch(r"[A-Z0-9]{1,8}", text) else None


def events_for(ticker: str, rows: list[dict], directory: dict) -> list[dict]:
    """The rows that belong to `ticker`, oldest ex-date first.

    A COMMON row belongs to the ticker the directory gives its company id
    (the directory lists each company's primary share). A preferred row names
    its own code (`GLOPA`, `BRNPB Series B`), so it belongs to that code."""
    company = (directory.get(ticker) or {}).get("company")
    out = []
    for r in rows:
        security = (r.get("security") or "").strip().upper()
        if security == "COMMON":
            mine = company is not None and r.get("company_id") == company
        else:
            mine = security.split(" ")[0] == ticker
        if mine:
            out.append({k: r[k] for k in ("kind", "rate", "amount", "currency",
                                          "ex", "record", "pay", "circular")})
    out.sort(key=lambda e: e["ex"])
    return out


def for_symbol(symbol: str, fresh: bool = False, today: dt.date | None = None) -> dict:
    """The `/api/dividends` payload for one PSE symbol. A symbol that is not
    a PSE name raises LookupError (the route answers 404)."""
    ticker = ticker_of(symbol)
    if not ticker:
        raise LookupError("dividend dates are kept only for PSE names")
    rows, fetched_at, cached = listing(fresh=fresh)
    try:
        directory = pse_edge.directory()
    except pse_edge.EdgeError as exc:
        faults.note("pse_dividends.directory", exc)
        directory = {}
    events = events_for(ticker, rows, directory)
    today_iso = (today or dt.date.today()).isoformat()
    upcoming = [e for e in events if e["ex"] >= today_iso]
    return {
        "ok": True,
        "symbol": symbol,
        "ticker": ticker,
        "events": events,
        "next": upcoming[0] if upcoming else None,
        # The oldest ex-date the list reached: before it, no marker means
        # "not known", never "no dividend" (a 2y or 5y chart reaches past it).
        "coverFrom": min((r["ex"] for r in rows), default=None),
        "source": SOURCE,
        "fetchedAt": fetched_at,
        "cached": cached,
        # Without the directory a common share's rows cannot be matched;
        # saying so keeps "no dividends" from reading as a fact.
        "complete": bool(directory),
    }
