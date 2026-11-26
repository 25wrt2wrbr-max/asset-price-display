"""Morning desk pack: macro peers, filings, BSP/BTR, overnight moves.

Stdlib only. Disk cache preferred; transport failures return stale copies or
empty lists — never a negative verdict about an asset.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import time
import urllib.parse
import urllib.request

import diskcache
import faults
import pse_edge
import sourcestats

BASE_EDGE = pse_edge.BASE
FILINGS_URL = BASE_EDGE + "/announcements/search.ax"

COMMODITIES = [
    {"symbol": "GC=F", "name": "Gold"},
    {"symbol": "CL=F", "name": "WTI crude"},
    {"symbol": "BZ=F", "name": "Brent"},
    {"symbol": "HG=F", "name": "Copper"},
    {"symbol": "SI=F", "name": "Silver"},
    {"symbol": "NG=F", "name": "Nat gas"},
]

# Regional indices and liquid single names. Yahoo daily bars for ^JKSE / ^KLSE
# often lag a session; .SI / .JK / .KL names track the prior local close.
ASEAN = [
    {"symbol": "^STI", "name": "STI (Singapore)", "delay": "same day"},
    {"symbol": "^JKSE", "name": "Jakarta Composite", "delay": "often T+1 on Yahoo"},
    {"symbol": "^KLSE", "name": "KLCI (Malaysia)", "delay": "often T+1 on Yahoo"},
    {"symbol": "D05.SI", "name": "DBS (Singapore)", "delay": "prior session"},
    {"symbol": "TLKM.JK", "name": "Telkom Indonesia", "delay": "prior session"},
    {"symbol": "MAYBANK.KL", "name": "Maybank (Malaysia)", "delay": "prior session"},
]

FILINGS_TTL = 1800

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_POPUP = re.compile(r"openPopup\('([^']+)'\)")
_HREF = re.compile(r'href="([^"]+)"', re.I)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}


def _sym_ticker(symbol: str) -> str:
    text = (symbol or "").strip().upper()
    for prefix in ("PSE:", "EDGE:"):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def _company_label(symbol: str) -> str:
    """Strip exchange prefix for display; filings search uses the ticker."""
    return _sym_ticker(symbol)


def filings_for(symbol: str) -> list[dict]:
    """Recent PSE Edge announcements for a ticker (best-effort keyword search)."""
    ticker = _sym_ticker(symbol)
    if not ticker:
        return []
    cache_key = "deskpack:filings:" + ticker
    saved = diskcache.load(cache_key)
    if saved and time.time() - saved[0] < FILINGS_TTL:
        return saved[1] if isinstance(saved[1], list) else []

    end = dt.date.today()
    start = end - dt.timedelta(days=90)
    body = urllib.parse.urlencode({
        "pageNo": "1",
        "keyword": ticker,
        "fromDate": start.strftime("%m-%d-%Y"),
        "toDate": end.strftime("%m-%d-%Y"),
        "dateSortType": "DESC",
    }).encode()
    try:
        with sourcestats.timed(FILINGS_URL):
            req = urllib.request.Request(
                FILINGS_URL, data=body, method="POST",
                headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    raise pse_edge.EdgeError("HTTP %s" % resp.status)
                raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        faults.note("deskpack.filings", exc)
        if saved and isinstance(saved[1], list):
            return saved[1]
        return []

    rows = []
    for block in _ROW.findall(raw):
        if "openPopup" not in block or "colspan" in block:
            continue
        cells = _CELL.findall(block)
        if len(cells) < 4:
            continue
        company_html = cells[0]
        title_html = cells[1]
        time_html = cells[3]
        company = html.unescape(_TAG.sub("", company_html)).strip()
        title = html.unescape(_TAG.sub("", title_html)).strip()
        when = html.unescape(_TAG.sub("", time_html)).strip()
        popup = _POPUP.search(title_html)
        href = _HREF.search(company_html)
        if popup:
            url = BASE_EDGE + "/disclosure/view.ax?fileId=" + popup.group(1)
        elif href:
            url = urllib.parse.urljoin(BASE_EDGE + "/", href.group(1))
        else:
            url = FILINGS_URL
        rows.append({"title": title, "time": when, "url": url, "company": company})
        if len(rows) >= 25:
            break

    diskcache.store(cache_key, rows)
    return rows


def bsp_policy() -> dict:
    """The BSP policy rate for the digest, from the rates strip's saved copy.

    bsp.gov.ph refuses scripts ("Access Denied", 2026-11-26), so the rate is
    read by `phrates` from TradingView. This reads only its saved copy -- no
    network call -- so the digest and the strip can never disagree.
    """
    import phrates  # lazy: phrates imports server, which imports this module
    snap = phrates.saved() or {}
    policy = snap.get("policy") or {}
    rate = policy.get("rate")
    return {
        "rrp": ("%.2f%%" % rate) if rate is not None else None,
        "since": policy.get("since"),
        "source": snap.get("source") or "TradingView",
        "cached": True,
    }


def btr_auctions() -> list[dict]:
    """Treasury auction rows: none. treasury.gov.ph sits behind a bot wall, so
    the bill yields come from `phrates` (market yields, shown on the strip)."""
    return []


def _last_two_pct(chart: dict | None) -> float | None:
    if not chart or not isinstance(chart, dict):
        return None
    pts = chart.get("points") or []
    closes = [p["c"] for p in pts if isinstance(p, dict) and p.get("c") is not None]
    if len(closes) < 2:
        return None
    prev, last = closes[-2], closes[-1]
    if not prev:
        return None
    return round((last / prev - 1) * 100, 2)


def _disk_chart(server_mod, symbol: str) -> dict | None:
    key = server_mod.chart_key(symbol, server_mod.WARM_SPAN, server_mod.WARM_INTERVAL)
    saved = diskcache.load(key)
    if saved and isinstance(saved[1], dict):
        return saved[1]
    return None


def overnight_moves(server_mod) -> list[dict]:
    """Overnight % move (last two daily closes) for watchlist + commodities."""
    symbols = []
    seen = set()
    for item in server_mod.saved_watchlist():
        sym = item.get("symbol")
        if sym and sym not in seen:
            seen.add(sym)
            symbols.append(sym)
    for row in COMMODITIES:
        sym = row["symbol"]
        if sym not in seen:
            seen.add(sym)
            symbols.append(sym)

    out = []
    for sym in symbols:
        chart = _disk_chart(server_mod, sym)
        pct = _last_two_pct(chart)
        if pct is None:
            continue
        out.append({
            "symbol": sym,
            "name": (chart or {}).get("name") or sym,
            "pct": pct,
            "currency": (chart or {}).get("currency"),
        })
    out.sort(key=lambda r: abs(r["pct"]), reverse=True)
    return out


def _pulse_hints(moves: list[dict]) -> list[str]:
    hints = []
    for row in moves[:6]:
        pct = row.get("pct")
        if pct is None:
            continue
        sign = "+" if pct > 0 else ""
        hints.append("%s %s%s%% overnight" % (row.get("symbol"), sign, pct))
    return hints


def deskpack_snapshot(server_mod) -> dict:
    """Non-blocking bundle for `/api/deskpack`."""
    moves = overnight_moves(server_mod)
    comm = []
    for row in COMMODITIES:
        chart = _disk_chart(server_mod, row["symbol"])
        comm.append({
            **row,
            "overnightPct": _last_two_pct(chart),
        })
    return {
        "ok": True,
        "generatedAt": int(time.time()),
        "commodities": comm,
        "asean": list(ASEAN),
        "bsp": bsp_policy(),
        "btr": btr_auctions(),
        "overnightMoves": moves,
        "pulseHints": _pulse_hints(moves),
    }


def enrich_digest(digest: dict, server_mod) -> dict:
    """Attach desk-pack fields to a digest dict (mutates and returns)."""
    if not isinstance(digest, dict):
        return digest
    moves = overnight_moves(server_mod)
    digest["overnightMoves"] = moves
    digest["commodities"] = [
        {**row, "overnightPct": _last_two_pct(_disk_chart(server_mod, row["symbol"]))}
        for row in COMMODITIES
    ]
    digest["asean"] = list(ASEAN)
    digest["bsp"] = bsp_policy()
    digest["btr"] = btr_auctions()
    digest["pulseHints"] = _pulse_hints(moves)
    return digest