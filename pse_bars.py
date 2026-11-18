"""PSE daily bars and charts: the TradingView chart socket, driven from a browser.

Split out of \`pse.py\` on 2026-11-18. \`pse.py\` keeps the listing universe,
search, the shared constants and the browser runners; this module holds the
socket scripts, the batched history reader and the chart builders.

Every name here is re-exported by \`pse.py\`, and every function body reads the
other module's names as \`P.x\`, so \`pse.<name>\` and
\`mock.patch.object(pse, ...)\` keep working for the moved names too.
"""

from __future__ import annotations

import datetime
import json
import math
import time

import crypto
import faults
import market_days
import onset
import pse_outlook
import trend

import pse as P



# The socket protocol, in one script. Every frame is `~m~<len>~m~<json>`; the
# length is authoritative, so frames are drained on it -- the resolved-symbol
# frame carries a session_holidays string of several kilobytes and slicing on
# braces loses the socket's place. Heartbeats (`~h~` frames) must be echoed or
# the server drops a multi-thousand-bar dump mid-flight.
#
# The sends must be in this order, and the symbol descriptor must begin with
# `=`: without it the reply to `resolve_symbol` is `symbol_error` and no bars
# ever arrive.
WS_SCRIPT = """(async () => {
  const bars = new Map();
  const out = { kind: null, error: null, meta: null, bars: null, holidays: null };
  return await new Promise((resolve) => {
    let ws, settled = false, gotSeries = false, quiet = null;
    const finish = (kind, error) => {
      if (settled) return;
      settled = true;
      clearTimeout(hard); clearTimeout(quiet);
      try { ws.close(); } catch (e) {}
      out.kind = kind || "error";
      if (error) out.error = error;
      out.bars = [...bars.values()].sort((a, b) => a[0] - b[0]);
      resolve(JSON.stringify(out));
    };
    const hard = setTimeout(() => finish("timeout", "no data before the deadline"), %(deadline)d);
    try {
      const day = new Date().toISOString().slice(0, 10);
      ws = new WebSocket(%(socket)s + "?from=chart%%2F&date=" + day);
    } catch (e) {
      out.kind = "error"; out.error = "socket could not be opened"; out.bars = [];
      return resolve(JSON.stringify(out));
    }
    const pack = (m, p) => { const s = JSON.stringify({ m, p }); return "~m~" + s.length + "~m~" + s; };
    ws.onopen = () => {
      const rnd = "cs" + Math.random().toString(36).slice(2, 8);
      ws.send(pack("set_auth_token", ["unauthorized_user_token"]));
      ws.send(pack("chart_create_session", [rnd, ""]));
      ws.send(pack("resolve_symbol", [rnd, "sds_sym_1",
        "={\\"adjustment\\":\\"splits\\",\\"symbol\\":\\"" + %(symbol)s + "\\"}"]));
      ws.send(pack("create_series", [rnd, "sds_1", "s1", "sds_sym_1", %(tf)s, %(count)d, ""]));
    };
    ws.onerror = () => finish("error", "socket error");
    ws.onclose = () => { if (!settled) finish("error", "socket closed before any data"); };
    ws.onmessage = (e) => {
      const text = String(e.data);
      const re = /~m~(\\d+)~m~/g;
      let m;
      while ((m = re.exec(text)) !== null) {
        const len = parseInt(m[1], 10);
        const whole = text.substr(m.index, m[0].length + len);
        const body = text.substr(m.index + m[0].length, len);
        if (body.indexOf("~h~") === 0) { try { ws.send(whole); } catch (err) {} continue; }
        let j;
        try { j = JSON.parse(body); } catch (err) { continue; }
        const name = j.m || j.p;
        if (name === "symbol_error") return finish("notfound", "symbol_error");
        if (name === "critical_error" || name === "protocol_error") return finish("error", String(name));
        if (name === "symbol_resolved") {
          const src = j.p[2] || {};
          // The exchange's holiday list rides on every resolved frame; kept
          // once per run, outside `meta`, for `market_days.remember_pse`.
          if (!out.holidays && typeof src.session_holidays === "string") out.holidays = src.session_holidays;
          out.meta = {
            name: src.description || src.short_description || null,
            currency: src.currency_code || null,
            exchange: (src.source2 && src.source2.description) || src.exchange || null,
            type: src.type || null,
            pricescale: src.pricescale || null
          };
        }
        if (name === "timescale_update" || name === "du") {
          const node = (j.p && j.p[1] && j.p[1].sds_1) || {};
          for (const x of (node.s || [])) {
            if (x && Array.isArray(x.v) && typeof x.v[0] === "number") bars.set(x.i, x.v);
          }
          if (name === "timescale_update" || gotSeries) {
            gotSeries = true;
            clearTimeout(quiet);
            quiet = setTimeout(() => finish("ok"), %(settle)d);
          }
        }
        if (name === "series_completed" && gotSeries) {
          clearTimeout(quiet);
          quiet = setTimeout(() => finish("ok"), 300);
        }
      }
    };
  });
})()"""


# The same protocol as WS_SCRIPT, widened to a chunk. Two differences that matter:
#
# * One `chart_create_session` **per symbol**. The free token refuses a second
#   `create_series` in an existing session -- `critical_error: exceed limit of
#   series in the session` -- so batching is many sessions on one socket, not one
#   session with many series. Therefore the series name is always `sds_1`: it is
#   only ambiguous within a session, and there is one series in each.
# * Completion is tracked per symbol, and the result is not trusted until every
#   session has reported `series_completed`. Otherwise the settle timer fires on
#   the first quiet moment and the chunk comes back with whatever had arrived --
#   which is how a 60-symbol chunk returned nothing at all.
BATCH_SCRIPT = """(async () => {
  const SYMS = %(symbols)s;
  // `meta` is keyed by symbol the way `bars` is: the `symbol_resolved` frame
  // arrives on the session that asked for it, and `sidOf` maps that session
  // back to the symbol. WS_SCRIPT captures the same fields for one symbol;
  // this is the same capture, widened to a chunk, so a batched chart can name
  // and price-scale its instrument exactly as the single-symbol one does.
  const out = { kind: "error", error: null, bars: {}, meta: {}, holidays: null };
  return await new Promise((resolve) => {
    const store = {}; const sessOf = {}; const done = {};
    let ws = null, settled = false, quiet = null;
    const finish = (kind, error) => {
      if (settled) return;
      settled = true;
      clearTimeout(hard); clearTimeout(quiet);
      try { ws.close(); } catch (e) {}
      out.kind = kind || "error";
      if (error) out.error = error;
      for (const s of SYMS) {
        const m = store[s];
        out.bars[s] = m ? [...m.values()].sort((a, b) => a[0] - b[0]) : [];
      }
      resolve(JSON.stringify(out));
    };
    // Every session must report before the answer is trusted -- see the header.
    const maybeDone = () => {
      if (Object.keys(done).length >= SYMS.length) finish("ok", null);
    };
    const hard = setTimeout(() => finish("timeout", "deadline"), %(deadline)d);
    const touch = () => {
      clearTimeout(quiet);
      quiet = setTimeout(() => finish("partial", "settled early"), %(settle)d);
    };
    try {
      const day = new Date().toISOString().slice(0, 10);
      ws = new WebSocket(%(socket)s + "?from=chart%%2F&date=" + day);
    } catch (e) {
      out.error = "socket could not be opened";
      return resolve(JSON.stringify(out));
    }
    const pack = (m, p) => { const s = JSON.stringify({ m, p }); return "~m~" + s.length + "~m~" + s; };
    const sidOf = {};
    ws.onopen = () => {
      ws.send(pack("set_auth_token", ["unauthorized_user_token"]));
      SYMS.forEach((s, i) => {
        const rnd = "cs" + i + Math.random().toString(36).slice(2, 6);
        sidOf[rnd] = s;
        ws.send(pack("chart_create_session", [rnd, ""]));
        ws.send(pack("resolve_symbol", [rnd, "sds_sym_1",
          "={\\"adjustment\\":\\"splits\\",\\"symbol\\":\\"" + s + "\\"}"]));
        ws.send(pack("create_series", [rnd, "sds_1", "s1", "sds_sym_1", %(tf)s, %(count)d, ""]));
      });
    };
    ws.onerror = () => finish("error", "socket error");
    ws.onclose = () => { if (!settled) finish("error", "closed before data"); };
    ws.onmessage = (e) => {
      const text = String(e.data);
      const re = /~m~(\\d+)~m~/g;
      let m;
      while ((m = re.exec(text)) !== null) {
        const len = parseInt(m[1], 10);
        const whole = text.substr(m.index, m[0].length + len);
        const body = text.substr(m.index + m[0].length, len);
        if (body.indexOf("~h~") === 0) { try { ws.send(whole); } catch (err) {} continue; }
        let j;
        try { j = JSON.parse(body); } catch (err) { continue; }
        const name = j.m || j.p;
        const sid = (j.p && typeof j.p[0] === "string") ? j.p[0] : null;
        const sym = sid ? sidOf[sid] : null;
        // A symbol the venue does not know still counts as answered, or the
        // chunk would wait out its deadline for a name that was never coming.
        if (name === "symbol_error") { if (sym) done[sym] = 1; maybeDone(); continue; }
        if (name === "symbol_resolved") {
          if (!sym) continue;
          const src = (j.p && j.p[2]) || {};
          // Only a PSE listing speaks for the exchange (the bond yields share
          // this socket, and their venue keeps its own calendar).
          if (!out.holidays && sym.indexOf("PSE:") === 0 && typeof src.session_holidays === "string") out.holidays = src.session_holidays;
          out.meta[sym] = {
            name: src.description || src.short_description || null,
            currency: src.currency_code || null,
            exchange: (src.source2 && src.source2.description) || src.exchange || null,
            type: src.type || null,
            pricescale: src.pricescale || null
          };
          continue;
        }
        if (name === "critical_error" || name === "protocol_error") {
          return finish("error", String(name));
        }
        if (name === "timescale_update" || name === "du") {
          if (!sym) continue;
          const node = (j.p && j.p[1]) || {};
          const sds = node["sds_1"] || {};
          if (!store[sym]) { store[sym] = new Map(); sessOf[sym] = sid; }
          for (const x of (sds.s || [])) {
            if (x && Array.isArray(x.v) && typeof x.v[0] === "number") store[sym].set(x.i, x.v);
          }
          touch();
        }
        if (name === "series_completed" && sym) { done[sym] = 1; maybeDone(); }
      }
    };
  });
})()"""


def history_many(symbols, count=P.BATCH_BARS, timeframe=P.TIMEFRAME_DAILY,
                 chunk=P.BATCH_SYMBOLS, workers=P.BATCH_WORKERS,
                 attempts=P.BATCH_ATTEMPTS) -> dict[str, list]:
    """Daily bars for many symbols at once -> {symbol: rows}.

    A symbol is present only if its series arrived; a symbol missing from the
    result is one the sweep could not get, not one without bars. The caller
    decides what a missing name means.

    Why not one socket per symbol
    -----------------------------
    A browser costs about a second to start, so 263 separate `_history` calls
    would spend almost five minutes waiting on Chrome and almost none of it
    waiting on data. Many chart sessions can share one socket -- each needs its
    own `chart_create_session`, because the free token rejects a second
    `create_series` in the same session -- so a chunk of forty resolves in about
    ten seconds: a 30x saving, and the difference between a sweep that can be
    refreshed in the background and one that cannot.

    Chunking and retry
    ------------------
    Forty sessions per socket is the reliable ceiling; above it the server
    intermittently stops delivering, which shows up as an empty chunk rather
    than an error. Even at forty a chunk occasionally comes back short, so a
    short chunk is retried rather than tolerated: a missing symbol would
    otherwise be reported as "not bullish" when it is really "not fetched", and
    the table would silently lie by omission.
    """
    pending = [str(s) for s in symbols]
    if not pending:
        return {}

    out: dict[str, list] = {}
    for attempt in range(1, max(1, attempts) + 1):
        if not pending:
            break
        chunks = [pending[i:i + chunk] for i in range(0, len(pending), chunk)]
        with P._pool(workers) as pool:
            results = list(pool.map(
                lambda c: (c, P._fetch_chunk(c, timeframe, count)), chunks))
        pending = []
        for wanted, got in results:
            out.update(got)
            pending.extend(s for s in wanted if s not in got)
    return out


def _pool(workers: int):
    """A thread pool sized for `workers` Moli subprocesses.

    Threads rather than processes because the work is almost entirely waiting on
    a subprocess; the socket frames are parsed in the browser, and the Python
    side only ever reads the finished JSON.
    """
    from concurrent.futures import ThreadPoolExecutor
    return ThreadPoolExecutor(max_workers=max(1, workers))


def _fetch_chunk(symbols: list[str], timeframe: str, count: int) -> dict[str, list]:
    """One socket, one chart session per symbol. Missing symbols are simply absent.

    A chunk that fails outright returns `{}` rather than raising, so one bad
    chunk costs its own symbols and not the sweep -- the retry pass picks them up.
    """
    bars, _meta = P._fetch_chunk_raw(symbols, timeframe, count)
    return bars


def _fetch_chunk_raw(symbols: list[str], timeframe: str,
                     count: int) -> tuple[dict[str, list], dict[str, dict]]:
    """`_fetch_chunk`, plus the `symbol_resolved` meta it now captures.

    The sweep only wants bars, but a batched *chart* also needs each
    instrument's name, currency and tick size, and those arrive on the same
    frames the bars do -- re-running the socket to collect them would double
    the browser spend for data that was already in the room. Returns
    `(bars, meta)`; both carry only the symbols that answered.
    """
    script = P.BATCH_SCRIPT % {
        "symbols": json.dumps([str(s) for s in symbols]),
        "tf": json.dumps(timeframe),
        "count": int(count),
        "deadline": P.BATCH_DEADLINE_MS,
        "settle": P.BATCH_SETTLE_MS,
        "socket": json.dumps(P.SOCKET_URL),
    }
    try:
        raw = P._run_batch(P.SOCKET_PAGE, script)
        envelope = json.loads(raw)
    except (P.PseError, ValueError):
        return {}, {}
    if envelope.get("kind") != "ok":
        return {}, {}
    _remember_holidays(envelope)
    bars = envelope.get("bars") or {}
    out: dict[str, list] = {}
    for symbol, rows in bars.items():
        # An empty list is the socket's way of saying "this session produced
        # nothing", which is a failure to fetch rather than a verdict.
        if rows:
            out[str(symbol)] = rows
    meta = {str(k): v for k, v in (envelope.get("meta") or {}).items()
            if isinstance(v, dict)}
    return out, meta


def _remember_holidays(envelope) -> None:
    """Hand the exchange's holiday list (if the run saw one) to `market_days`.

    Only the sweep's pace reads it; a failure here costs nothing but that.
    """
    try:
        market_days.remember_pse((envelope or {}).get("holidays"))
    except Exception as exc:
        faults.note("PSE holiday list", exc)


def _history(symbol: str, timeframe: str, count: int) -> dict:
    """Drive one websocket call and return the parsed envelope."""
    script = P.WS_SCRIPT % {
        # The venue prefix is part of the symbol, not our own encoding of it:
        # TradingView resolves the bare "TEL" to TE Connectivity on another
        # exchange, and only "PSE:TEL" is the Manila listing.
        "symbol": json.dumps(symbol),
        "tf": json.dumps(timeframe),
        "count": int(count),
        "deadline": P.DEADLINE_MS,
        "settle": P.SETTLE_MS,
        "socket": json.dumps(P.SOCKET_URL),
    }
    raw = P._run(P.SOCKET_PAGE, script)
    try:
        envelope = json.loads(raw)
    except ValueError:
        raise P.PseError(f"unusable socket reply: {str(raw)[:200]}")
    kind = envelope.get("kind")
    if str(symbol).upper().startswith("PSE:"):
        _remember_holidays(envelope)
    if kind == "notfound":
        raise P.PseNotFound(f"TradingView has no symbol {symbol!r}.")
    if kind != "ok":
        raise P.PseError(f"socket {kind}: {envelope.get('error') or 'no detail'}")
    return envelope


def price_hint(pricescale, price: float) -> int:
    """Decimals to show, taken from the instrument's own tick size.

    PSE quotes to the tick, so `pricescale` is a better answer than magnitude:
    a ₱0.31 stock ticks at 1/1000 (0.310), which a magnitude rule would round to
    0.3100. The floor of two decimals is the exchange's own convention -- the
    scale for a large-cap like PLDT is 1, but it is quoted in centavos, and
    `₱1,119` reads as a rounded price where `₱1,119.00` does not. Falls back to
    the crypto path's magnitude rule when the scale is missing.
    """
    try:
        scale = float(pricescale)
        if scale > 0:
            return max(2, min(6, int(round(math.log10(scale)))))
    except (TypeError, ValueError):
        pass
    return max(2, crypto.price_hint(price))


def completed_trade(points: list[dict], volumes: list, now: float | None = None
                    ) -> tuple[int | None, float | None, float | None]:
    """The newest **finished** session's (stamp, traded shares, traded value).

    "How much money moved through this name" is `close * volume` on a bar -- the
    same product `bullish.py` and `onset.py` rank the tables on, so a chart
    readout and a table row describe one session the same way.

    Why today's bar waits for the bell
    -----------------------------------
    The reader asked for the last **completed** trading day, and the provider
    gives no way to tell a finished bar from a forming one: TradingView's daily
    payload carries today's candle from the opening bell, and nothing in the
    frame says whether it has stopped moving (the same gap `pse_outlook` works
    around by discarding today's candle outright). So the clock does the work
    instead, from the exchange's own published schedule:

        pse.com.ph, trading hours (read 2026-11-04)
        9:00 pre-open / 9:30 open / 12:00-13:00 recess / 14:45 pre-close
        15:00 closing VWAP session / **15:15 market close**

    A bar dated today is therefore the session **so far** until `SESSION_CLOSE`,
    and today's finished session from `CLOSING_PRINT_DELAY` past it (the closing
    print takes a moment to land in the daily bar). A bar dated tomorrow is
    always refused -- that is a clock disagreement, not a session.

    No holiday calendar is needed and none is invented: on a holiday there is no
    bar dated today at all, so the walk falls through to the last day that
    actually traded. A suspension behaves the same way.

    Read at **read** time, not fetch time (`server.chart_data`), for the reason
    `lastBarBasis` is: a payload fetched at 10:30 and served at 16:00, or
    tomorrow from a disk copy, must not still be answering for the day it was
    fetched on. The rule is a pure function of the bars and the clock, so nothing
    outside the drawn series is invented.

    Two refusals, neither of them a zero:

    * **No volume at all.** The PSE index carries none, and a bar whose volume
      field did not survive parsing is silence rather than a session that
      traded nothing. `onset`'s own rule ("a missing volume is not a
      zero-volume session") applies.
    * **A zero-volume bar.** The same silence inside the series: a name that did
      not trade that day has no traded value to report, and PHP 0.00 beside a
      live price would read as a claim about demand rather than absence of
      prints.

    A weekly series is refused by the caller, not here: a week's volume times
    its close is not a trading *day*'s value.
    """
    if not points or not volumes:
        return None, None, None
    now = time.time() if now is None else now
    now_manila = datetime.datetime.fromtimestamp(now, pse_outlook.MANILA)
    today = now_manila.date()
    # Today's bar is a finished session only after the exchange's own close --
    # plus the moment the closing print needs to reach the daily bar. Before
    # that it is the session so far, and reporting it would print a partial day
    # as though it were complete.
    close_at = now_manila.replace(
        hour=P.SESSION_CLOSE.hour, minute=P.SESSION_CLOSE.minute,
        second=0, microsecond=0) + P.CLOSING_PRINT_DELAY
    today_is_final = now_manila >= close_at
    for i in range(len(points) - 1, -1, -1):
        try:
            stamp = int(points[i]["t"])
            close = float(points[i]["c"])
        except (KeyError, TypeError, ValueError):
            continue
        day = datetime.datetime.fromtimestamp(stamp, pse_outlook.MANILA).date()
        if day > today:
            continue                    # a stamp ahead of the clock: not a session
        if day == today and not today_is_final:
            continue                    # today, still trading
        volume = volumes[i] if i < len(volumes) else None
        if not volume or not close > 0:
            return None, None, None
        return stamp, float(volume), close * float(volume)
    return None, None, None


def session_window(stamp: int, interval: str, now: float | None = None) -> dict | None:
    """The PSE session a newest bar belongs to, for `server.last_bar_basis`.

    TradingView's daily payload carries today's candle from the opening bell,
    so during the session the newest bar **is** the price trading now -- what
    the chart draws and what a broker screen quotes are the same reading. The
    frame does not say so, which is why the clock does: the bar is stamped at
    the session it belongs to, and 9:30-15:15 Manila is when it can move.

    Answers None for a weekly bar (a week's candle is not a trading day's
    price) and for a payload whose clock cannot be read. `formingBar` is the
    claim, `regular` is when it can be true, and the read-time test in
    `server.last_bar_basis` is what stops a payload read after today's close
    from still claiming to be live -- the window is an absolute stamp, so it
    expires on its own.
    """
    if interval != "1d":
        return None
    try:
        day = datetime.datetime.fromtimestamp(int(stamp), pse_outlook.MANILA).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    now_manila = datetime.datetime.fromtimestamp(
        time.time() if now is None else now, pse_outlook.MANILA)
    opened = datetime.datetime.combine(day, P.SESSION_OPEN, tzinfo=pse_outlook.MANILA)
    closed = datetime.datetime.combine(day, P.SESSION_CLOSE, tzinfo=pse_outlook.MANILA)
    forming = day == now_manila.date()
    return {
        "regular": [int(opened.timestamp()), int(closed.timestamp())],
        "coversLastBar": forming,
        "formingBar": forming,
    }


def chart(symbol: str, span: str, interval: str) -> dict:
    """Daily/weekly bars for a PSE security, in the server's payload shape.

    Raises PseNotFound for a symbol TradingView does not know and PseError for a
    transport failure, so the caller can tell a typo from an outage.
    """
    canonical = P.canonical_symbol(symbol)
    if canonical is None:
        raise P.PseNotFound(f"{symbol!r} is not a PSE symbol.")

    days = P.RANGE_DAYS.get(span, P.RANGE_DAYS["3mo"])
    if interval == "1wk":
        timeframe = P.TIMEFRAME_WEEKLY
        count = min(P.MAX_BARS, max(60, days // 7 + 8))
    else:
        timeframe = P.TIMEFRAME_DAILY
        count = max(P.OUTLOOK_BARS, P.BAR_COUNT.get(span, P.BAR_COUNT["3mo"]))

    envelope = P._history(canonical, timeframe, count)
    meta = envelope.get("meta") or {}

    points: list[dict] = []
    volumes: list[float | None] = []
    seen: set[int] = set()
    for row in envelope.get("bars") or []:
        try:
            stamp = int(row[0])
            close = float(row[4])
        except (IndexError, TypeError, ValueError):
            continue  # tolerate a malformed row rather than lose the series
        if stamp in seen or not close > 0:
            continue
        # An index has no volume, so its bars carry only five fields. Absent
        # volume is not a malformed row -- it just means the ensemble's volume
        # signal has nothing to say.
        try:
            volume = float(row[5])
        except (IndexError, TypeError, ValueError):
            volume = None
        seen.add(stamp)
        points.append({"t": stamp, "c": round(close, 6)})
        volumes.append(volume)

    if not points:
        raise P.PseNotFound(f"No price data for {canonical}.")
    order = sorted(range(len(points)), key=lambda i: points[i]["t"])
    points = [points[i] for i in order]
    volumes = [volumes[i] for i in order]

    # Trim to the exact window. The bar count asked for is an over-estimate on
    # purpose (see BAR_COUNT); the timestamp is what makes the range honest
    # regardless of holidays. If a symbol has gone quiet for longer than the
    # window, fall back to its last bars so the chart is not blank.
    cutoff = time.time() - days * 86400
    start = next((i for i, p in enumerate(points) if p["t"] >= cutoff), None)
    if start is None or len(points) - start < 2:
        start = max(0, len(points) - max(2, trend.MIN_BARS))
    used = points[start:]
    used_volumes = volumes[start:]

    closes = [p["c"] for p in used]

    # Same contract as the Yahoo and crypto paths: every series is scored, so a
    # thinly traded PSE name -- whose 90-day window can hold only a few dozen
    # bars -- still gets its verdict, and only bad data leaves the badge off.
    trend_call = None
    try:
        trend_call = trend.classify(closes, used_volumes)
    except ValueError:
        pass

    last = used[-1]["c"]
    previous = used[-2]["c"] if len(used) > 1 else None

    # The bars behind the window, for the badge's steadiness reading
    # (`server.chart_data` -> `onset.decorate`). The socket already returned
    # `OUTLOOK_BARS` of history, so a 90-day chart has years behind it and the
    # reading is exact rather than approximate.
    tail = [{"t": point["t"], "c": point["c"], "v": volumes[i]}
            for i, point in list(enumerate(points))[:start]
            [-onset.LEAN_HOLD_BARS:]]

    # The board lot times the last close: the smallest cheque that buys this
    # stock, which the page shows under the price. Imported here rather than at
    # the top because `markets` imports this module -- for the scanner POST and
    # its browser fallback -- so a top-level import would be a cycle, and this is
    # the one place in it that needs the lot table. That table is the exchange's,
    # keyed on price, not the instrument's `pricescale`, which is the tick size.
    import markets
    # An index has no board lot: it is a reading of its members, not a
    # security, so a "5-share lot" under its price would be a cheque nobody
    # can write. Scanned with the stocks since 2026-11-09, so its chart can be
    # opened from a row; the figure is withheld rather than invented.
    lot, lot_cost = ((None, None) if meta.get("type") == "index"
                     else markets.minimum_investment(last))

    return {
        "symbol": canonical,
        "name": meta.get("name") or canonical,
        "currency": meta.get("currency") or "PHP",
        "exchange": meta.get("exchange") or "Philippine Stock Exchange",
        "type": meta.get("type") or "stock",
        "priceHint": P.price_hint(meta.get("pricescale"), last),
        "previousClose": previous,
        "marketPrice": last,
        "boardLot": lot,
        "minInvestment": lot_cost,
        "points": used,
        # Shares per bar, aligned with `points` (the shape `crypto.chart` ships),
        # so the last *completed* session's value can be read off at read time
        # instead of being frozen into this payload -- see `completed_trade`.
        "volumes": used_volumes,
        # The session the newest bar belongs to. A bar dated today is the day
        # **so far** until the exchange's close, so this is what lets the page
        # call the newest point the live price (`server.last_bar_basis`) instead
        # of a settled close -- and re-read it every minute rather than every
        # fifteen.
        "session": P.session_window(used[-1]["t"], interval),
        "longTermContext": pse_outlook.context(points) if interval == "1d" else None,
        "trend": trend_call,
        # The bars before the window, so the badge's lean can be checked over
        # the previous sessions (`server.chart_data` -> `onset.decorate`).
        "historyTail": tail,
        "source": "TradingView",
    }


def try_chart(symbol: str, span: str, interval: str) -> dict | None:
    """`chart()`, with "not ours" and "no bars" flattened to None."""
    try:
        return P.chart(symbol, span, interval)
    except P.PseNotFound:
        return None


def charts_many(symbols, span: str = "3mo", interval: str = "1d",
                chunk=P.BATCH_SYMBOLS, workers=P.BATCH_WORKERS,
                attempts=P.BATCH_ATTEMPTS) -> dict[str, dict | Exception]:
    """`chart()` for many PSE symbols at once, through the same batched socket.

    Returns `{canonical_symbol: payload}` for every symbol whose series
    arrived, and `{symbol: exception}` for the ones that did not. The split is
    the caller's whole interface to failure semantics: a bar-shaped entry is a
    finished chart, and an exception entry is either `PseNotFound` (a verdict
    about the symbol) or `PseError` (an outage about the wire) -- exactly the
    distinction `chart()` draws one symbol at a time, so a caller can treat
    them the same way it treats that one.

    Why this exists
    ---------------
    The row warmer used to warm each PSE row through `chart()` one browser run
    at a time: ~90 symbols, ~90 launches, ~90 single-symbol sockets. The sweep
    already proved that forty sessions share one socket (see `history_many`),
    so the warmer's pass can ride the same chunking -- the bars per symbol are
    identical, only the post-processing differs. That post-processing is lifted
    here verbatim from `chart()` (window trim, trend call, board-lot figure)
    rather than refactored out of it, on purpose: one copy per route is the
    price of the two routes not being able to drift, and this module already
    paid it once with `markets.minimum_investment`. A symbol whose series never
    arrives (the chunk came back short and the retry pass exhausted its
    attempts) gets a `PseError`, not silence -- "not fetched" is a transport
    verdict, not an answer about the symbol.

    The meta comes from the same socket run (`_fetch_chunk_raw`), so a batched
    chart names, scales and prices its instrument exactly as the single-symbol
    `chart()` does; a session whose `symbol_resolved` frame never arrived gets
    `chart()`'s own fallback defaults rather than a different spelling.
    """
    # Canonicalised up front, so the queue a caller built maps back to the
    # symbols the socket knows -- and so duplicates by spelling collapse.
    queue: dict[str, str] = {}
    for symbol in symbols:
        canonical = P.canonical_symbol(symbol)
        if canonical is None:
            raise P.PseNotFound(f"{symbol!r} is not a PSE symbol.")
        queue[canonical] = str(symbol)
    if not queue:
        return {}

    out: dict[str, dict | Exception] = {}
    pending = list(queue)
    for attempt in range(1, max(1, attempts) + 1):
        if not pending:
            break
        chunks = [pending[i:i + chunk] for i in range(0, len(pending), chunk)]
        with P._pool(workers) as pool:
            results = list(pool.map(
                lambda c: P._fetch_chunk_raw(c, P._timeframe_for(span, interval),
                                           P._bar_count_for(span, interval)),
                chunks))
        pending = []
        for wanted, (got, meta) in zip(chunks, results):
            for symbol in wanted:
                rows = got.get(symbol)
                if not rows:
                    pending.append(symbol)   # retry pass owns it
                    continue
                try:
                    out[symbol] = P._build_chart(symbol, rows, meta.get(symbol) or {},
                                               span, interval)
                except P.PseNotFound as exc:
                    out[symbol] = exc        # bars arrived, none usable: verdict
                except P.PseError as exc:
                    out[symbol] = exc
                    # A broken series is transport, not absence: the retry
                    # pass has another go at it like any other miss.
                    pending.append(symbol)
    # Everything still pending after the last attempt is an outage wearing one
    # row per symbol -- same exception shape `_history` would have raised.
    for symbol in pending:
        out[symbol] = P.PseError(f"no series for {symbol!r} after {attempts} attempt(s)")
    return out


def _timeframe_for(span: str, interval: str) -> str:
    """The socket timeframe `chart()` picks for this window. Shared, so the
    batched path cannot disagree with the single one about `1wk`."""
    return (P.TIMEFRAME_WEEKLY if interval == "1wk" else P.TIMEFRAME_DAILY)


def _bar_count_for(span: str, interval: str) -> int:
    days = P.RANGE_DAYS.get(span, P.RANGE_DAYS["3mo"])
    if interval == "1wk":
        return min(P.MAX_BARS, max(60, days // 7 + 8))
    return max(P.OUTLOOK_BARS, P.BAR_COUNT.get(span, P.BAR_COUNT["3mo"]))


def _build_chart(symbol: str, rows, meta: dict, span: str, interval: str) -> dict:
    """One symbol's parsed bars -> the exact payload `chart()` returns.

    Lifted from `chart()`'s body (parse, dedupe, sort, trim, score, lot) with
    the socket run factored out in front. The trim, the trend and the lot
    arithmetic are the parts that must not drift between the two routes, and
    the comment trail inside `chart()` explains each -- read there.
    """
    days = P.RANGE_DAYS.get(span, P.RANGE_DAYS["3mo"])

    points: list[dict] = []
    volumes: list[float | None] = []
    seen: set[int] = set()
    for row in rows:
        try:
            stamp = int(row[0])
            close = float(row[4])
        except (IndexError, TypeError, ValueError):
            continue
        if stamp in seen or not close > 0:
            continue
        try:
            volume = float(row[5])
        except (IndexError, TypeError, ValueError):
            volume = None
        seen.add(stamp)
        points.append({"t": stamp, "c": round(close, 6)})
        volumes.append(volume)

    if not points:
        raise P.PseNotFound(f"No price data for {symbol}.")
    order = sorted(range(len(points)), key=lambda i: points[i]["t"])
    points = [points[i] for i in order]
    volumes = [volumes[i] for i in order]

    cutoff = time.time() - days * 86400
    start = next((i for i, p in enumerate(points) if p["t"] >= cutoff), None)
    if start is None or len(points) - start < 2:
        start = max(0, len(points) - max(2, trend.MIN_BARS))
    used = points[start:]
    used_volumes = volumes[start:]

    closes = [p["c"] for p in used]
    trend_call = None
    try:
        trend_call = trend.classify(closes, used_volumes)
    except ValueError:
        pass

    last = used[-1]["c"]
    previous = used[-2]["c"] if len(used) > 1 else None

    import markets
    # Same rule as `chart()`: no board lot for an index (2026-11-09).
    lot, lot_cost = ((None, None) if meta.get("type") == "index"
                     else markets.minimum_investment(last))

    # `volumes` beside `points`, exactly as `chart()` ships them, so the
    # batched route a warmed row is stored through cannot omit what the
    # single-symbol route carries (see `completed_trade` for the read-time rule).
    return {
        "symbol": symbol,
        "name": meta.get("name") or symbol,
        "currency": meta.get("currency") or "PHP",
        "exchange": meta.get("exchange") or "Philippine Stock Exchange",
        "type": meta.get("type") or "stock",
        "priceHint": P.price_hint(meta.get("pricescale"), last),
        "previousClose": previous,
        "marketPrice": last,
        "boardLot": lot,
        "minInvestment": lot_cost,
        "points": used,
        "volumes": used_volumes,
        # The newest bar's session, so the batched route carries the same claim
        # the single-symbol route does (`chart()` -> `session_window`).
        "session": P.session_window(used[-1]["t"], interval),
        "longTermContext": pse_outlook.context(points) if interval == "1d" else None,
        "trend": trend_call,
        "source": "TradingView",
    }
