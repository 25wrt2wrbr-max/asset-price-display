"""Background macOS notifications, server-synced price alarms, and `/api/digest`.

Because background sweeps (`sweeps.py`) and row warming (`warm.py`) keep
running even with no browser open, the server sees watched trend flips and
price-alarm crossings as soon as fresh data lands. This module:

* Persists browser-declared price alarms (`alarms:v1` via `diskcache.store_plain`)
  so background threads can evaluate crossings and post native macOS Notification
  Center banners (`osascript` using `on run argv` — no string interpolation).
* Tracks the last fresh trend badge per watched symbol (`notify:watch_state:v1`)
  and sends a notification when a watched symbol flips trend (never on first
  observation, and never from cached or stale data).
* Builds `/api/digest` from warm server state without blocking on upstream calls.

Standard library only. Disabled automatically when `APD_NOTIFY=0` or off macOS.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

import diskcache
import faults
import market_days

_MANILA = ZoneInfo("Asia/Manila")
_PSE_OPEN = dt.time(9, 30)
_PSE_CLOSE = dt.time(15, 15)


def pse_session_status(now: float | None = None) -> dict:
    """Whether the Philippine exchange is in its regular session right now.

    Also ships seconds to the next open or close when that moment is today
    (or the next open day), so the morning ribbon can count down without
    inventing a session calendar of its own.
    """
    here = dt.datetime.fromtimestamp(now if now is not None else time.time(), _MANILA)
    open_day = market_days.pse_open_day(here.date())
    clock = here.time()
    trading = open_day and _PSE_OPEN <= clock < _PSE_CLOSE
    if not open_day:
        state = "holiday" if here.weekday() < 5 else "weekend"
    elif clock < _PSE_OPEN:
        state = "pre-open"
    elif clock < _PSE_CLOSE:
        state = "open"
    else:
        state = "closed"

    seconds_to_open = None
    seconds_to_close = None
    if state == "open":
        close_at = dt.datetime.combine(here.date(), _PSE_CLOSE, _MANILA)
        seconds_to_close = max(0, int((close_at - here).total_seconds()))
    elif state in ("pre-open", "closed", "weekend", "holiday"):
        day = here.date()
        # Next open: later today if pre-open, else walk forward calendar days.
        if state == "pre-open" and open_day:
            open_at = dt.datetime.combine(day, _PSE_OPEN, _MANILA)
        else:
            open_at = None
            for step in range(1, 15):
                cand = day + dt.timedelta(days=step)
                if market_days.pse_open_day(cand):
                    open_at = dt.datetime.combine(cand, _PSE_OPEN, _MANILA)
                    break
        if open_at is not None:
            seconds_to_open = max(0, int((open_at - here).total_seconds()))

    return {
        "state": state,
        "trading": trading,
        "localTime": here.strftime("%H:%M"),
        "date": here.date().isoformat(),
        "secondsToOpen": seconds_to_open,
        "secondsToClose": seconds_to_close,
    }

ALARMS_KEY = "alarms:v1"
WATCH_STATE_KEY = "notify:watch_state:v1"

_APPLESCRIPT = (
    "on run argv\n"
    "  set t to item 1 of argv\n"
    "  set sub to item 2 of argv\n"
    "  set body to item 3 of argv\n"
    "  if sub is \"\" then\n"
    "    display notification body with title t\n"
    "  else\n"
    "    display notification body with title t subtitle sub\n"
    "  end if\n"
    "end run"
)

_lock = threading.Lock()
_alarms: list[dict] | None = None
_watch_state: dict[str, dict] | None = None


def enabled() -> bool:
    """Whether native macOS notifications should fire."""
    flag = os.environ.get("APD_NOTIFY", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    return sys.platform == "darwin"


def send(title: str, body: str, subtitle: str = "") -> bool:
    """Post one native macOS Notification Center banner via osascript.

    Arguments are passed through `on run argv`, never interpolated into source.
    Best-effort: failures are noted once and never raise.
    """
    if not enabled():
        return False
    try:
        res = subprocess.run(
            ["osascript", "-e", _APPLESCRIPT, "--",
             str(title)[:120], str(subtitle)[:120], str(body)[:240]],
            capture_output=True, text=True, timeout=5,
        )
        return res.returncode == 0
    except Exception as exc:                  # noqa: BLE001 - best-effort OS hook
        faults.note("notify.send", exc)
        return False


def _norm_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _clean_alarms(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        sym = _norm_symbol(raw.get("symbol"))
        try:
            target = float(raw.get("target"))
        except (TypeError, ValueError):
            continue
        if not sym or len(sym) > 32 or not math.isfinite(target):
            continue
        aid = str(raw.get("id") or f"{sym}:{target}")[:64]
        if aid in seen:
            continue
        seen.add(aid)
        last = raw.get("last")
        try:
            last = float(last) if last is not None else None
            if last is not None and not math.isfinite(last):
                last = None
        except (TypeError, ValueError):
            last = None
        fired = raw.get("fired") if isinstance(raw.get("fired"), dict) else None
        out.append({
            "id": aid,
            "symbol": sym,
            "name": str(raw.get("name") or sym)[:120],
            "target": target,
            "last": last,
            "unit": raw.get("unit"),
            "currency": raw.get("currency"),
            "priceHint": raw.get("priceHint"),
            "created": raw.get("created"),
            "fired": fired,
        })
    return out


def load_alarms() -> list[dict]:
    global _alarms
    with _lock:
        if _alarms is None:
            saved = diskcache.load_plain(ALARMS_KEY)
            _alarms = _clean_alarms(saved)
        return [dict(a) for a in _alarms]


def save_alarms(items) -> list[dict]:
    """Replace the stored alarm list from the browser (preserving any server-fired
    state if the same alarm ID was already triggered on the server)."""
    global _alarms
    cleaned = _clean_alarms(items)
    with _lock:
        if _alarms is None:
            _alarms = _clean_alarms(diskcache.load_plain(ALARMS_KEY))
        prior_fired = {a["id"]: a["fired"] for a in _alarms if a.get("fired")}
        prior_last = {a["id"]: a["last"] for a in _alarms if a.get("last") is not None}
        for a in cleaned:
            if not a.get("fired") and a["id"] in prior_fired:
                a["fired"] = prior_fired[a["id"]]
            if a.get("last") is None and a["id"] in prior_last:
                a["last"] = prior_last[a["id"]]
        _alarms = cleaned
        diskcache.store_plain(ALARMS_KEY, _alarms)
        return [dict(a) for a in _alarms]


def alarm_crossed(prev: float | None, now: float | None, target: float) -> str | None:
    """Exact twin of `static/alarms.js` `alarmCrossed(prev, now, target)`."""
    if prev is None or now is None:
        return None
    if not (math.isfinite(prev) and math.isfinite(now) and math.isfinite(target)):
        return None
    if prev < target and now >= target:
        return "up"
    if prev > target and now <= target:
        return "down"
    return None


def _fmt_price(value: float, unit=None, currency=None, hint=None) -> str:
    digits = 2
    try:
        if hint is not None:
            digits = min(max(int(hint), 0), 6)
    except (TypeError, ValueError):
        pass
    text = f"{value:,.{digits}f}"
    if unit == "%":
        return text + "%"
    if currency:
        return f"{currency} {text}"
    return text


def check_alarms(symbol: str, price: float | None, unit=None, currency=None) -> list[dict]:
    """Evaluate armed server-side alarms for `symbol` on a fresh live price."""
    global _alarms
    if price is None or not math.isfinite(price):
        return []
    key = _norm_symbol(symbol)
    triggered: list[dict] = []
    with _lock:
        if _alarms is None:
            _alarms = _clean_alarms(diskcache.load_plain(ALARMS_KEY))
        changed = False
        for a in _alarms:
            if a.get("fired") or _norm_symbol(a["symbol"]) != key:
                continue
            direction = alarm_crossed(a.get("last"), price, a["target"])
            # The same price again changes nothing on disk: only a new price
            # or a firing is worth a write.
            if a.get("last") != price:
                a["last"] = price
                changed = True
            if direction:
                changed = True
                a["fired"] = {"at": int(time.time() * 1000), "price": price, "dir": direction}
                triggered.append(dict(a))
        if changed:
            diskcache.store_plain(ALARMS_KEY, _alarms)
    for a in triggered:
        arrow = "rose to" if a["fired"]["dir"] == "up" else "fell to"
        p_txt = _fmt_price(price, a.get("unit") or unit, a.get("currency") or currency, a.get("priceHint"))
        t_txt = _fmt_price(a["target"], a.get("unit") or unit, a.get("currency") or currency, a.get("priceHint"))
        send(f"Price alarm: {a['symbol']}",
             f"{a['symbol']} {arrow} {p_txt}, crossing {t_txt}.",
             a.get("name") or "")
    return triggered


def _badge_phrase(trend_call: dict | None, include_lean: bool = True) -> str | None:
    if not isinstance(trend_call, dict):
        return None
    label = trend_call.get("label")
    if label not in ("bullish", "bearish", "neutral"):
        return None
    word = label.capitalize()
    if include_lean and label == "neutral" and trend_call.get("lean") in ("bullish", "bearish"):
        return f"{word} · leaning {trend_call['lean']}"
    if trend_call.get("pullback") and label != "neutral":
        return f"{word}, {'pulling back' if label == 'bullish' else 'bouncing'}"
    return word


def _load_watch_state_locked() -> dict[str, dict]:
    global _watch_state
    if _watch_state is None:
        raw = diskcache.load_plain(WATCH_STATE_KEY)
        _watch_state = dict(raw) if isinstance(raw, dict) else {}
    return _watch_state


def observe_chart(symbol: str, payload: dict, watched: set[str] | None = None) -> None:
    """Inspect a fresh (non-cached, non-stale) chart payload for alarm crossings
    and watched-symbol trend changes."""
    if not isinstance(payload, dict) or payload.get("cached") or payload.get("staleDays") is not None:
        return
    if (payload.get("stale") or 0) > 0:
        return
    pts = payload.get("points") or []
    # Raw warm payloads have not passed through chart_route's stale_gap check.
    if payload.get("source") in ("Yahoo", "Nasdaq") and pts:
        import recent
        stamps = [p["t"] for p in pts if isinstance(p, dict) and p.get("t") is not None]
        if stamps and recent.stale_gap(stamps) is not None:
            return
    last = pts[-1].get("c") if pts and isinstance(pts[-1], dict) else None
    sym = _norm_symbol(payload.get("symbol") or symbol)
    if not sym:
        return
    if isinstance(last, (int, float)) and math.isfinite(last):
        check_alarms(sym, float(last), payload.get("unit"), payload.get("currency"))

    if watched is not None and sym not in watched and _norm_symbol(symbol) not in watched:
        return
    # Notify only on confirmed label / pullback transitions (undecorated leans
    # on raw warm payloads have not passed onset.decorate's steadiness gate).
    phrase = _badge_phrase(payload.get("trend"), include_lean=False)
    if not phrase:
        return
    notify_args = None
    with _lock:
        state = _load_watch_state_locked()
        prev = state.get(sym)
        if prev and prev.get("phrase") and prev.get("phrase") != phrase:
            notify_args = (
                f"Trend change: {sym}",
                f"{prev['phrase']} → {phrase}",
                payload.get("name") or "",
            )
        # Written only when the badge changed (or is new): a repeat of the same
        # label is no news, so neither the memory copy nor the file is touched.
        label = payload["trend"]["label"]
        if not prev or prev.get("phrase") != phrase or prev.get("label") != label:
            state[sym] = {"phrase": phrase, "label": label,
                          "price": last, "at": int(time.time())}
            diskcache.store_plain(WATCH_STATE_KEY, state)
    if notify_args:
        send(*notify_args)


def observe_recent(payload: dict, watched: list[str] | None = None) -> None:
    """Check armed alarms against fresh prices in a completed recent sweep."""
    if not isinstance(payload, dict) or payload.get("cached"):
        return
    seen: set[str] = set()
    for bucket in ("rows", "bearish", "leaning"):
        for row in payload.get(bucket) or []:
            if not isinstance(row, dict) or row.get("stale"):
                continue
            sym = _norm_symbol(row.get("chartSymbol") or row.get("symbol"))
            price = row.get("price")
            if not sym or sym in seen or not isinstance(price, (int, float)):
                continue
            seen.add(sym)
            check_alarms(sym, float(price), "%" if row.get("currency") == "%" else None,
                         row.get("currency"))


def build_digest(server_mod, netwatch_mod) -> dict:
    """Compact non-blocking summary for `/api/digest` (Shortcuts / menu bar)."""
    rec = server_mod.recent_state()
    health = rec.get("health") or []
    watch_items = server_mod.saved_watchlist()
    watch_out = []
    for item in watch_items:
        sym = item["symbol"]
        key = server_mod.chart_key(sym, server_mod.WARM_SPAN, server_mod.WARM_INTERVAL)
        saved = diskcache.load(key)
        chart = saved[1] if saved and isinstance(saved[1], dict) else None
        pts = (chart.get("points") or []) if chart else []
        trend_call = chart.get("trend") if chart else None
        first_c = pts[0]["c"] if len(pts) > 1 and isinstance(pts[0], dict) else None
        last_c = pts[-1]["c"] if pts and isinstance(pts[-1], dict) else None
        pct = round((last_c / first_c - 1) * 100, 2) if first_c and last_c else None
        watch_out.append({
            "symbol": sym,
            "name": item.get("name") or (chart.get("name") if chart else sym),
            "label": trend_call.get("label") if isinstance(trend_call, dict) else None,
            "phrase": _badge_phrase(trend_call),
            "price": last_c,
            "currency": chart.get("currency") if chart else None,
            "change3mPct": pct,
        })

    # Fresh turns: rows whose onset equals the newest bar for their market.
    fresh_turns = []
    for direction, key in (("bullish", "rows"), ("bearish", "bearish")):
        bucket = rec.get(key) or []
        latest_by_mkt: dict[str, int] = {}
        for r in bucket:
            m = r.get("market") or ""
            latest_by_mkt[m] = max(latest_by_mkt.get(m, 0), int(r.get("last") or 0))
        for r in bucket:
            m = r.get("market") or ""
            if r.get("since") and r.get("since") == latest_by_mkt.get(m):
                fresh_turns.append({
                    "symbol": r.get("chartSymbol") or r.get("symbol"),
                    "ticker": r.get("ticker") or r.get("symbol"),
                    "market": m,
                    "direction": direction,
                    "price": r.get("price"),
                    "currency": r.get("currency"),
                })

    all_alarms = load_alarms()
    fired_alarms = [a for a in all_alarms if a.get("fired")]
    armed_alarms = [a for a in all_alarms if not a.get("fired")]
    pse = pse_session_status()
    markets = rec.get("markets") or []
    market_lines = []
    for m in markets:
        if not isinstance(m, dict):
            continue
        state = m.get("state") or "?"
        market_lines.append({
            "market": m.get("market"),
            "state": state,
            "detail": m.get("detail"),
        })

    # Alarm levels that are PHP-priced, for peso desk checklists.
    peso_alarms = []
    for a in all_alarms:
        if a.get("currency") == "PHP" or str(a.get("symbol") or "").upper().startswith("PSE:"):
            peso_alarms.append({
                "symbol": a.get("symbol"),
                "target": a.get("target"),
                "fired": bool(a.get("fired")),
                "needLabel": a.get("needLabel") or None,
            })

    health_bits = [f"{m['market']}: {m['bullish']}▲ {m['bearish']}▼" for m in health[:4]]
    watch_bull = sum(1 for w in watch_out if w["label"] == "bullish")
    watch_bear = sum(1 for w in watch_out if w["label"] == "bearish")
    parts = []
    parts.append(f"PSE {pse['state']} ({pse['localTime']} Manila)")
    if health_bits:
        parts.append(" · ".join(health_bits))
    if watch_out:
        parts.append(f"Watchlist ({len(watch_out)}): {watch_bull}▲ {watch_bear}▼")
    if fresh_turns:
        parts.append(f"{len(fresh_turns)} fresh turn{'s' if len(fresh_turns) != 1 else ''}")
    if fired_alarms:
        parts.append(f"{len(fired_alarms)} alarm{'s' if len(fired_alarms) != 1 else ''} fired")
    degraded = [m for m in market_lines if m.get("state") in ("offline", "partial", "fallback")]
    if degraded:
        parts.append(
            "degraded: " + ", ".join(f"{m['market']} {m['state']}" for m in degraded[:4])
        )

    digest = {
        "ok": True,
        "generatedAt": int(time.time()),
        "online": netwatch_mod._watch_online,
        "summary": " | ".join(parts) if parts else "No sweep data yet",
        "pseSession": pse,
        "markets": market_lines,
        "marketHealth": health,
        "watchlist": watch_out,
        "freshTurns": fresh_turns[:25],
        "alarms": {
            "armed": len(armed_alarms),
            "fired": fired_alarms,
            "peso": peso_alarms,
        },
    }
    try:
        import deskpack
        deskpack.enrich_digest(digest, server_mod)
    except Exception as exc:
        faults.note("notify.build_digest.deskpack", exc)
    return digest


def digest_text(digest: dict) -> str:
    """Plain-text rendering for `/api/digest?format=text`."""
    lines = [digest.get("summary") or "No sweep data yet"]
    pse = digest.get("pseSession") or {}
    if pse:
        lines.append(
            f"PSE session: {pse.get('state')} at {pse.get('localTime')} Manila"
            f" ({pse.get('date')})"
        )
    markets = digest.get("markets") or []
    if markets:
        lines.append(
            "Markets: "
            + ", ".join(f"{m.get('market')}={m.get('state')}" for m in markets)
        )
    if digest.get("freshTurns"):
        top = ", ".join(
            f"{t['ticker']} ({'▲' if t['direction'] == 'bullish' else '▼'} {t['market']})"
            for t in digest["freshTurns"][:8]
        )
        lines.append("Fresh turns: " + top)
    if digest.get("watchlist"):
        wl = ", ".join(
            f"{w['symbol']} {w['phrase'] or '—'}"
            for w in digest["watchlist"][:10]
        )
        lines.append("Watchlist: " + wl)
    peso = (digest.get("alarms") or {}).get("peso") or []
    if peso:
        lines.append(
            "Peso alarms: "
            + ", ".join(
                f"{a['symbol']} @ {a['target']}"
                + (" (fired)" if a.get("fired") else "")
                for a in peso[:8]
            )
        )
    if digest.get("alarms", {}).get("fired"):
        al = ", ".join(f"{a['symbol']} @ {a['target']}" for a in digest["alarms"]["fired"])
        lines.append("Fired alarms: " + al)
    return "\n".join(lines) + "\n"


def build_packet(server_mod, netwatch_mod) -> dict:
    """Disk-only morning bundle for `/api/packet` — never triggers a fetch."""
    digest = build_digest(server_mod, netwatch_mod)
    rec = server_mod.recent_state()
    rows = list(rec.get("rows") or [])[:40]
    lean = list(rec.get("leaning") or [])[:20]
    bear = list(rec.get("bearish") or [])[:20]
    # Strip heavy sparks from the packet copy.
    slim = []
    for r in rows + lean + bear:
        if not isinstance(r, dict):
            continue
        slim.append({
            "symbol": r.get("chartSymbol") or r.get("symbol"),
            "ticker": r.get("ticker") or r.get("symbol"),
            "market": r.get("market"),
            "label": (r.get("trend") or {}).get("label") if isinstance(r.get("trend"), dict)
                     else r.get("label"),
            "since": r.get("since"),
            "price": r.get("price"),
            "currency": r.get("currency"),
            "direction": r.get("direction"),
        })
    return {
        "ok": True,
        "fromDisk": True,
        "generatedAt": int(time.time()),
        "online": netwatch_mod._watch_online,
        "digest": digest,
        "recentSample": slim,
        "note": "Assembled from the last sweep and disk chart copies. No upstream read.",
    }
