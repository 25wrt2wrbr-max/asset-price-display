"use strict";

/* ------------------------------------------------------------------ *
 * Watchlist
 *
 * The list is a set of symbols the user curates. Picking one is just a
 * chart load (same code path as the search box); the rail additionally
 * shows each saved symbol's last close, so the list is worth glancing at
 * without selecting anything. Persisted to localStorage, best-effort.
 * ------------------------------------------------------------------ */
const WATCH_KEY = "apd-watchlist";
const watchQuoteSeq = new WeakMap();
let watchHadLocal = false;

/* The page only ever draws daily closes over three months, so a watchlist
   quote is the same `/api/chart` payload the main chart uses.

   The percentage a row carries is the *window's* move -- the first close the
   chart draws to the latest -- not the day's. A row and the chart a click opens
   are then the same verdict about the same bars, which is the rule the recent
   table already follows, and the chart's own hero delta now measures the same
   pair, so the headline figure and the row cannot disagree about the three
   months. */
function quoteSummary(data) {
  const pts = data.points;
  const last = pts[pts.length - 1];
  const first = pts.length > 1 ? pts[0] : null;
  const diff = first ? last.c - first.c : null;
  // A zero first close has no percentage to report, but still has a direction.
  const pct = first && first.c !== 0 ? (diff / first.c) * 100 : null;
  const from = first ? dayFmt.format(toDate(first.t)) : "";
  return {
    data,
    price: last.c,
    diff,
    pct,
    up: diff === null ? null : diff >= 0,
    moveTitle: from
      ? `${SPAN_WORDS[RANGE] || "Window"} change, ${from} to the latest close`
      : "Change over the charted window",
  };
}

/* Shorter moves inside the same bars the chart draws: the newest close
   against the last close at least 7 and 30 calendar days earlier (calendar,
   so a coin's weekend bars and a stock's weekday bars mean the same week),
   and how far the newest close sits from the window's highest and lowest.
   Plain arithmetic on drawn closes -- it describes, it never predicts. A
   period the series does not reach is null, never a guess. */
const PERIODS = [["1W", 7], ["1M", 30]];
function periodChanges(points) {
  const pts = (points || []).filter((p) => p && Number.isFinite(p.c) && Number.isFinite(p.t));
  if (pts.length < 2) return null;
  const last = pts[pts.length - 1];
  const pct = (from) => (from && from.c !== 0 ? (last.c / from.c - 1) * 100 : null);
  const out = { periods: [] };
  for (const [name, days] of PERIODS) {
    const cutoff = last.t - days * 86400;
    let base = null;
    for (let i = pts.length - 2; i >= 0; i--) {
      if (pts[i].t <= cutoff) { base = pts[i]; break; }
    }
    out.periods.push({ name, pct: pct(base) });
  }
  const closes = pts.map((p) => p.c);
  const hi = Math.max(...closes), lo = Math.min(...closes);
  out.fromHigh = hi !== 0 ? (last.c / hi - 1) * 100 : null;
  out.fromLow = lo !== 0 ? (last.c / lo - 1) * 100 : null;
  return out;
}
function signedPct(v) {
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;
}

/* A tiny line of the same closes the chart draws, so a row shows the shape of
   its three months at a glance. Decoration only (aria-hidden): the figure
   beside it and the chart a click opens carry the numbers. Coloured with the
   row's own move, so line and percentage always agree.
   Canvas, not SVG: hundreds of table rows each used to build a polyline DOM
   tree; one bitmap per spark keeps scroll and first paint cheaper. */
const SPARK_H = 18;
let sparkInk = null;   // cached theme strokes; cleared on theme change
function sparkStroke(up) {
  if (!sparkInk) {
    const css = getComputedStyle(document.documentElement);
    sparkInk = {
      muted: css.getPropertyValue("--text-muted").trim() || "#6b6a65",
      up: css.getPropertyValue("--delta-up").trim() || "#006300",
      down: css.getPropertyValue("--delta-down").trim() || "#c02f2f",
    };
  }
  return up == null ? sparkInk.muted : up ? sparkInk.up : sparkInk.down;
}
function resetSparkInk() { sparkInk = null; }
function watchSparkline(points, up) {
  return sparkline((points || []).map((p) => p.c), up, 60);
}
/* Shared with the recent tables (`tables.js`), which pass the row's own
   window closes. `up` null draws the line uncoloured. */
function sparkline(values, up, SPARK_W) {
  const closes = (values || []).filter(Number.isFinite);
  if (closes.length < 2) return null;
  let lo = closes[0], hi = closes[0];
  for (let i = 1; i < closes.length; i++) {
    const c = closes[i];
    if (c < lo) lo = c;
    if (c > hi) hi = c;
  }
  if (hi === lo) { lo -= 1; hi += 1; }      // a flat series draws mid-height
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const canvas = document.createElement("canvas");
  canvas.className = "watch-spark " + (up == null ? "" : up ? "up" : "down");
  canvas.width = Math.round(SPARK_W * dpr);
  canvas.height = Math.round(SPARK_H * dpr);
  canvas.style.width = SPARK_W + "px";
  canvas.style.height = SPARK_H + "px";
  canvas.setAttribute("aria-hidden", "true");
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.scale(dpr, dpr);
  const pad = 1.5, span = SPARK_H - pad * 2, step = SPARK_W / (closes.length - 1);
  ctx.strokeStyle = sparkStroke(up);
  ctx.lineWidth = 1.4;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  for (let i = 0; i < closes.length; i++) {
    const x = i * step;
    const y = pad + (hi - closes[i]) / (hi - lo) * span;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
  return canvas;
}

function loadWatch() {
  try {
    const stored = localStorage.getItem(WATCH_KEY);
    watchHadLocal = stored !== null;
    const raw = JSON.parse(stored || "[]");
    if (!Array.isArray(raw)) return;
    state.watch = raw
      .filter((it) => it && typeof it.symbol === "string" && it.symbol.trim())
      .map((it) => ({ symbol: it.symbol.trim(), name: String(it.name || it.symbol).trim() }));
  } catch { state.watch = []; }
}

function saveWatch() {
  watchHadLocal = true;
  try { localStorage.setItem(WATCH_KEY, JSON.stringify(state.watch)); } catch {}
  declareWatch();
}

function parseWatchItems(raw) {
  const list = Array.isArray(raw) ? raw
    : raw && Array.isArray(raw.watchlist) ? raw.watchlist
    : raw && Array.isArray(raw.symbols) ? raw.symbols
    : null;
  if (!list) return null;
  const out = [];
  const seen = new Set();
  for (const it of list) {
    const symbol = typeof it === "string" ? it.trim()
      : it && typeof it.symbol === "string" ? it.symbol.trim() : "";
    if (!symbol || symbol.length > 32) continue;
    const key = symbol.toUpperCase();
    if (seen.has(key)) continue;
    seen.add(key);
    const name = it && typeof it === "object" && typeof it.name === "string" && it.name.trim()
      ? it.name.trim() : symbol;
    out.push({ symbol, name });
  }
  return out;
}

async function restoreWatchFromServer() {
  if (watchHadLocal || state.watch.length) return;
  let payload;
  try {
    payload = await requestJSON("/api/watch");
  } catch { return; }
  const items = parseWatchItems(payload);
  if (!items || !items.length) return;
  state.watch = items;
  saveWatch();
  drawWatchList();
  refreshWatchQuotes();
  setStatus(`Restored ${items.length} watchlist symbol${items.length === 1 ? "" : "s"} from the local server.`);
}

function exportWatch() {
  if (!state.watch.length) {
    setStatus("Watchlist is empty — nothing to export.");
    return;
  }
  downloadBlob("watchlist.json", JSON.stringify(state.watch, null, 2) + "\n", "application/json;charset=utf-8");
  setStatus(`Exported ${state.watch.length} watchlist symbol${state.watch.length === 1 ? "" : "s"}.`);
}

async function importWatchFile(file) {
  if (!file) return;
  let parsed;
  try {
    parsed = JSON.parse(await file.text());
  } catch {
    setStatus("Could not read watchlist file — expected valid JSON.", true);
    return;
  }
  const items = parseWatchItems(parsed);
  if (!items) {
    setStatus("Watchlist file must contain a JSON list of symbols.", true);
    return;
  }
  const existing = new Set(state.watch.map((it) => it.symbol.toUpperCase()));
  const added = [];
  for (const it of items) {
    const key = it.symbol.toUpperCase();
    if (existing.has(key)) continue;
    existing.add(key);
    state.watch.push(it);
    added.push(it);
  }
  if (!added.length) {
    setStatus("All symbols from that file are already on the watchlist.");
    return;
  }
  saveWatch();
  drawWatchList();
  added.forEach((it) => fetchWatchQuote(it.symbol));
  setStatus(`Imported ${added.length} symbol${added.length === 1 ? "" : "s"} to the watchlist.`);
}

/* Hand the server the list it must keep warm. Up to this page existing, the
   warmer only knew about *listed* symbols — what a source published — and the
   reader's own rows were invisible to it, so a reconnect refetched everything
   except the watchlist. The declaration is a *delivery*, not a transaction:
   fire-and-forget, swallow every failure (the next `saveWatch`, the next page
   load, or the next reconnect's health poll re-sends it), and it never touches
   the UI. An offline declaration is not a lost list — localStorage is still the
   durable one, and the union on the server is only there to warm rows. */
function declareWatch() {
  postJSON("/api/watch", state.watch).catch(() => {});
}

/* The single writer of `state.watchQuotes`, and the only place a saved symbol
   may change. Entry and quote key therefore cannot drift apart: when the server
   canonicalises a spelling (asked for `jup`, returned `JUP-USD`) the quote moves
   with the symbol and the change is persisted.

   `payload` is the chart response, or `{ error }` / `{ loading: true }` while
   there is nothing to learn from yet. Its `symbol` and `name` are what let a row
   saved under a raw ticker — by the older add box, which stored no metadata —
   settle into the same identity the chart draws.

   A quote is only stored for a symbol already on the list, so charting a random
   asset does not leak an entry into the map. */
function setWatchQuote(symbol, entry, payload, seq) {
  // Both spellings are tried: a legacy entry filed under a raw ticker (`jup`)
  // has to be found by the canonical symbol the server returned (`JUP-USD`),
  // and an entry already canonical has to be found by the raw one it was
  // requested with. One lookup cannot do both, and both paths occur.
  const item = watchEntry(symbol) || watchEntry(payload && payload.symbol);
  if (!item) return;
  if (seq < (watchQuoteSeq.get(item) || 0)) return;
  if (seq != null) watchQuoteSeq.set(item, seq);

  // Capture the old spelling *before* overwriting it — drag state is keyed on
  // the symbol as it was. (The active-row highlight needs no fix-up: it is
  // derived from the chart on screen, not stored against a spelling.)
  const was = item.symbol;
  const canonical = payload && payload.symbol ? String(payload.symbol).trim() : was;
  const realName = payload && payload.name ? String(payload.name).trim() : "";
  let changed = false;

  if (canonical && canonical.toUpperCase() !== was.toUpperCase()) {
    item.symbol = canonical;
    if (dragSymbol === was) dragSymbol = canonical;
    delete state.watchQuotes[was];
    changed = true;
  } else if (canonical && canonical !== was) {
    item.symbol = canonical;   // same ticker, server's casing
    changed = true;
  }

  // A stored name that is just the ticker was never metadata — adopt the real
  // one so a canonicalised row does not read "JUP-USD / jup".
  if (realName && (item.name === was || item.name.toUpperCase() === item.symbol.toUpperCase())) {
    item.name = realName;
    changed = true;
  }

  if (changed) saveWatch();
  state.watchQuotes[item.symbol] = entry;
  if (payload) recordWatchVisit(was, item.symbol, payload);
}

function isWatched(symbol) {
  return watchEntry(symbol) !== null;
}

/* ---- which row is the chart on screen ----

   The rail lights the row whose asset is being drawn, and *which* row that is
   is derived from the chart on screen every time the list is painted. It used
   to be a snapshot taken in `loadChart`, which was wrong the moment the reader
   did anything else: chart MSFT, press Add, and the row now holding the asset
   in front of them stayed dark — as it did for a row restored from disk, one
   renamed to the server's spelling, or one that arrived after the chart. Two
   functions, no state to keep in sync: one decides, `drawWatchList` paints. */
function activeWatchKey() {
  return state.chartSymbol ? String(state.chartSymbol).trim().toUpperCase() : null;
}

function isWatchActive(item) {
  const key = activeWatchKey();
  if (!key) return false;
  if (item.symbol.toUpperCase() === key) return true;
  // A row can be saved under a spelling the server answers separately from the
  // one on screen: `USDPHP=X` and `PHP=X` are one price line (`coinsph.SYMBOLS`
  // names both), the page opens on the first and the search box offers the
  // second. Comparing the saved letters alone would leave the row dark with its
  // own series drawn beside it, so the instrument itself is compared too.
  const quote = state.watchQuotes[item.symbol];
  const drawn = quote && quote.data;
  if (!drawn) return false;
  if (String(drawn.symbol || "").trim().toUpperCase() === key) return true;
  return sameInstrument(drawn, state.data);
}

/* Name, venue, instrument type and currency together name a listing; two
   different instruments do not share all four, and two spellings of one pair
   share them exactly (measured 2026-11-04: `USDPHP=X` and `PHP=X` both read
   "USD/PHP" / CCY / CURRENCY / PHP while their last closes differed in the
   sixth decimal, which is a fetch a minute apart, not a different asset). A
   payload missing any of the four proves nothing and matches nothing. */
function sameInstrument(a, b) {
  if (!a || !b) return false;
  const bits = (d) =>
    [d.name, d.exchange, d.type, d.currency].map((v) => String(v || "").trim().toUpperCase());
  const x = bits(a);
  const y = bits(b);
  if (x.some((v) => !v)) return false;
  return x.every((v, i) => v === y[i]);
}

/* The saved entry for the chart on screen, or null. */
function activeWatchItem() {
  return state.watch.find((item) => isWatchActive(item)) || null;
}

/* The rail scrolls its own box (`max-height: 60vh`), so a lit row below the
   fold is brought into view by moving the *list's* scrollTop — never the
   page's. A page-level reveal would push the chart off screen in the stacked
   layout, which is the opposite of helping. A live drag owns the scroll
   position, so the reveal stands down while one is running.

   It runs in a frame, never in the fetch callback: a chart answer lands before
   the rows have been laid out, and `scrollHeight`/`getBoundingClientRect` read
   0/0 there (measured 2026-11-04 — with twenty rows in the DOM and a 540 px
   rail, every cold load read 0/0). So it asks again frame by frame, for a few
   seconds at most, and gives up quietly: a rail that never gets a layout (a
   hidden tab, a collapsed box) has nothing to scroll. */
const REVEAL_PATIENCE = 4000;   // ms of frame-by-frame asking

function scheduleReveal() {
  requestAnimationFrame(() => revealActiveRow(Date.now() + REVEAL_PATIENCE));
}

function revealActiveRow(deadline = 0) {
  if (dragSymbol !== null) return;      // a live drag owns the scroll position
  const list = el.watchList;
  // Nothing measured yet: the rows are in the DOM but the frame has not been
  // laid out. Ask again next frame rather than compare zeroes and decide the row
  // is on screen; a rail that never gets a layout runs the asking out quietly.
  const again = () => {
    if (Date.now() < deadline) requestAnimationFrame(() => revealActiveRow(deadline));
  };
  if (!list.clientHeight) return again();
  if (list.scrollHeight <= list.clientHeight + 1) return;   // nothing hidden
  const row = [...list.children].find((r) => r.classList.contains("is-active"));
  if (!row) return;
  const box = list.getBoundingClientRect();
  const r = row.getBoundingClientRect();
  if (!box.height || !r.height) return again();
  if (r.top < box.top) list.scrollTop -= box.top - r.top;
  else if (r.bottom > box.bottom) list.scrollTop += r.bottom - box.bottom;
}

/* The saved entry for a symbol, under any casing, or null. */
function watchEntry(symbol) {
  const key = String(symbol || "").trim().toUpperCase();
  if (!key) return null;
  return state.watch.find((it) => it.symbol.toUpperCase() === key) || null;
}

function addToWatch(symbol, name) {
  const sym = symbol.trim();
  if (!sym) return;
  const key = sym.toUpperCase();
  const existing = state.watch.find((it) => it.symbol.toUpperCase() === key);
  if (existing) { setStatus(`${existing.symbol} is already on the watchlist.`); return; }
  // No length cap: the list is the reader's own and grows as far as they want.
  // The only bound left is the one that was never a product decision -- the
  // server's request-body ceiling, which is about not buffering junk.
  state.watch.push({ symbol: sym, name: (name || sym).trim() });
  saveWatch();
  drawWatchList();
  fetchWatchQuote(sym);
  // The asset the reader is looking at is now on the list, so its row lights up
  // at once (the highlight is derived, not remembered) and is scrolled into view
  // when the rail hides it behind its own overflow.
  scheduleReveal();
  setStatus(`Added ${sym} to the watchlist.`);
}

function removeFromWatch(symbol) {
  forgetWatchVisit(symbol);
  const key = symbol.toUpperCase();
  state.watch = state.watch.filter((it) => it.symbol.toUpperCase() !== key);
  // Delete every spelling: a quote may have been stored before the symbol was
  // canonicalised, and an exact-key delete would leave it behind.
  Object.keys(state.watchQuotes).forEach((stored) => {
    if (stored.toUpperCase() === key) delete state.watchQuotes[stored];
  });
  saveWatch();
  drawWatchList();
}

/* Many rows load at once; draw the list at most once per frame. */
// Quotes land one by one; each used to rebuild the whole rail (rows,
// sparklines, tiles, six-pack). Now quotes that land within 250 ms of each
// other share one rebuild, and a steady stream still redraws once a second.
let watchDrawTimer = 0, watchDrawFirst = 0;
function queueWatchDraw() {
  const now = Date.now();
  if (!watchDrawTimer) watchDrawFirst = now;
  clearTimeout(watchDrawTimer);
  const wait = Math.max(0, Math.min(250, 1000 - (now - watchDrawFirst)));
  watchDrawTimer = setTimeout(() => {
    watchDrawTimer = 0;
    requestAnimationFrame(drawWatchList);
  }, wait);
}

/* Quote fetches are independent of the main chart request, so one bad symbol
   never blocks the list — each row resolves on its own. */
async function fetchWatchQuote(symbol, { fresh = false } = {}) {
  if (!isWatched(symbol)) return;
  // The saved entry, held across the await: `setWatchQuote` may rename it to the
  // server's spelling, and the live object answers the question below either way.
  const item = watchEntry(symbol);
  const readSeq = ++watchReadSeq;
  // A row that already shows a price keeps it until the new one lands, so a
  // refresh costs one redraw, not two (and the row does not flash "loading").
  const prev = state.watchQuotes[item.symbol];
  if (!prev || prev.loading || prev.error) {
    setWatchQuote(symbol, { loading: true }, null, readSeq);
    queueWatchDraw();
  }
  try {
    // Prefer the short chart memo when warm (45 s): a row just charted should
    // not start a second browser run. A reconnect pass passes `fresh: true`.
    const data = await getChart(symbol, { fresh });
    if (!state.watch.includes(item)) return;      // removed while in flight
    setWatchQuote(item.symbol, quoteSummary(data), data, readSeq);
    if (typeof checkAlarms === "function") checkAlarms(data);
  } catch (err) {
    if (!state.watch.includes(item)) return;
    setWatchQuote(item.symbol, { error: err.message }, null, readSeq);
  }
  queueWatchDraw();
  // A row that has just gained its price line and its odds line is taller than
  // the row the chart revealed a second earlier, so the lit row can slide under
  // the rail's edge. Re-reveal for *that row only*: another row's quote landing
  // must never move the rail under the reader.
  if (item && isWatchActive(item)) scheduleReveal();
}

function refreshWatchQuotes({ fresh = false } = {}) {
  state.watch.forEach((it) => fetchWatchQuote(it.symbol, { fresh }));
}

/* ---- staying current without being asked ----
   The server now keeps the declared list warm on its own: on a reconnect edge
   it refetches every union symbol, whether or not a page is open. This poll is
   how an *open* page learns that happened — `/api/health`'s `reconnections`
   counter is the server's own edge count, and when it moves, the fresh copies
   are already on the server (or arriving within seconds), so the page's job is
   only to re-read them: refresh the rows, and redraw the chart if one of them
   is what the chart is showing.

   The poll also re-declares the list, which is what makes a symbol added
   *during* an outage known to the server again once the wire returns: the
   save-time declaration failed while offline, and nothing else re-sends it.
   Every 30s while visible costs one memo read server-side — `/api/health` is
   a static answer and `/api/watch` a list swap plus a small disk write. */
const HEALTH_POLL = 30 * 1000;
const WATCH_TTL = 300 * 1000;   // rows re-sync on the leaderboards' cadence

let healthEdges = null;   // last `reconnections` value seen; null until first poll

/* Server-down banner (2026-11-24). A failed poll used to be silent, so a
   stopped local server left the page showing old prices as if live. Two
   unreachable polls in a row (about a minute) raise a banner; the first poll
   that answers lowers it and re-reads the rows and the chart. Only a refused
   connection counts: an HTTP error means the server is up. */
const SERVER_DOWN_AFTER = 2;
let healthMisses = 0;
let serverDownSince = null;

function serverBannerText(since) {
  const at = since.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return `The local server stopped answering at ${at}. Prices on this page may be old. ` +
    "Start it again with python3 server.py.";
}

function noteHealthResult(reachable, now = new Date()) {
  const banner = document.getElementById("serverBanner");
  if (!reachable) {
    healthMisses += 1;
    if (healthMisses === 1) serverDownSince = now;
    if (healthMisses >= SERVER_DOWN_AFTER && banner) {
      banner.textContent = serverBannerText(serverDownSince);
      banner.hidden = false;
    }
    return false;
  }
  const wasDown = healthMisses >= SERVER_DOWN_AFTER;
  healthMisses = 0;
  serverDownSince = null;
  if (banner) banner.hidden = true;
  return wasDown;
}

async function pollHealth() {
  let payload;
  try {
    payload = await requestJSON("/api/health");
  } catch (err) {
    // `fetch` rejects with a TypeError when nothing answers; `requestJSON`
    // throws a plain Error for an HTTP status, which means the server is up.
    noteHealthResult(!(err instanceof TypeError));
    return;
  }
  if (noteHealthResult(true)) {
    // Back after an outage: whatever the counter says, the rows are old.
    // File the counter as seen so the check below does not re-read them twice.
    if (typeof payload.reconnections === "number") healthEdges = payload.reconnections;
    declareWatch();
    refreshWatchQuotes({ fresh: true });
    if (state.chartSymbol) loadChart(state.chartSymbol, { quiet: true, pushHistory: false });
    return;
  }
  const edges = payload.reconnections;
  if (typeof edges !== "number") return;   // older server: no counter to watch
  // First poll only files the baseline; the page has already fetched at load.
  // *Any* move refreshes: upward is a reconnect edge, to a smaller number is a
  // server restart, and both mean the copy behind each row just changed.
  // Declaring the watchlist every 30 s was waste: saveWatch already posts it,
  // and a reconnect (above) posts it once more.
  if (healthEdges === null) { healthEdges = edges; return; }
  if (edges === healthEdges) return;
  healthEdges = edges;
  declareWatch();
  refreshWatchQuotes({ fresh: true });
  // Re-read the chart on screen only if it is one of the rows just refreshed.
  if (state.chartSymbol && activeWatchItem()) {
    // Quiet: never wipe what the reader is typing or flash "Loading…".
    loadChart(state.chartSymbol, { quiet: true, pushHistory: false });
  }
}

/* Kept current like the tables above: visible-only, so a background tab costs
   the upstream nothing. Rows re-read every five minutes, and the reconnect
   counter is polled far faster — the latency budget on the user's own list. */
setInterval(() => { if (!document.hidden) refreshWatchQuotes(); }, WATCH_TTL);
setInterval(() => { if (!document.hidden) pollHealth(); }, HEALTH_POLL);

/* ---- reordering ----
   The user's order is the list's own order: `state.watch` is the only thing
   persisted, so a drag or a keyboard nudge is just a move within it followed by
   a save and a repaint. Both entries keep their quote, so a reorder never
   re-fetches anything. */

function moveWatch(from, to) {
  if (from === to) return false;
  const n = state.watch.length;
  if (from < 0 || from >= n || to < 0 || to >= n) return false;
  const [item] = state.watch.splice(from, 1);
  state.watch.splice(to, 0, item);
  saveWatch();
  drawWatchList();   // full repaint: row contents are unchanged, only the order
  return true;
}

function reorderWatch(symbol, to) {
  const from = state.watch.findIndex((it) => it.symbol === symbol);
  if (from < 0) return false;
  const moved = moveWatch(from, to);
  if (moved) {
    setStatus(`${symbol} moved to position ${to + 1} of ${state.watch.length}.`);
  }
  return moved;
}

/* Move one row during a live drag, without a full repaint: the row under the
   pointer must stay alive for the rest of the gesture. Returns the new index. */
function shiftWatchRow(list, dragIndex, targetIndex) {
  if (dragIndex === targetIndex) return dragIndex;
  const item = state.watch[dragIndex];
  state.watch.splice(dragIndex, 1);
  state.watch.splice(targetIndex, 0, item);
  const nodes = [...list.children];
  const before = nodes[targetIndex < dragIndex ? targetIndex : targetIndex + 1];
  list.insertBefore(nodes[dragIndex], before || null);
  return targetIndex;
}

/* Where the row goes for a pointer at `clientY`: insert above or below the
   nearest row by which half of it the pointer is in. Read by the dragover
   handler and, while the rail scrolls itself, by the scroll loop -- the row
   under a pointer that is holding still changes as the list moves, and no
   `dragover` fires to say so. */
function dragPlaceAt(clientY) {
  if (dragSymbol === null) return;
  const list = el.watchList;
  const rows = [...list.children];
  const from = state.watch.findIndex((it) => it.symbol === dragSymbol);
  if (from < 0) return endDrag();

  let target = rows.length;
  for (let i = 0; i < rows.length; i++) {
    if (i === from) continue;
    const box = rows[i].getBoundingClientRect();
    const mid = box.top + box.height / 2;
    if (clientY < mid) { target = i; break; }
  }
  if (target > from) target -= 1;            // the dragged row vacates its slot
  shiftWatchRow(list, from, target);
}

/* Pointer drag, native HTML5 flavour, with one wrinkle: a drag has no DOM
   event of its own to listen to, so the handlers live on the grips, which every
   repaint throws away. `dragRepaint` fixes that -- a quote arriving mid-drag
   repaints the list and then re-derives the drag from state, so the gesture
   survives instead of silently dying with its grip.

   The list order is mutated as rows reflow, so there is no separate commit:
   `dragFrom` only remembers where the row started. dragend then either keeps
   the change or puts it back, and "did a drop land on the rail?" is what
   decides -- a drop fires `drop` on the list, a cancelled drag (Escape, or
   releasing outside the window) does not. */
let dragSymbol = null;   // symbol being dragged, null when idle
let dragFrom = -1;       // where it was lifted from, for a cancel
let dragDropped = false; // did the gesture end in a drop on the rail?
let dragPointY = null;   // last pointer y seen during a drag, client px
let dragScrollRaf = 0;   // pending auto-scroll frame, 0 when the loop is idle
let dragScrollAt = 0;    // when the previous frame ran, ms; 0 restarts the clock
let dragScrollAcc = 0;   // fractional px carried to the next frame

function endDrag() {
  dragSymbol = null;
  dragFrom = -1;
  dragDropped = false;
  stopDragScroll();
  el.watchList.classList.remove("is-reordering");
  el.watchList.querySelectorAll(".is-dragging").forEach((li) => li.classList.remove("is-dragging"));
}

/* Called by every drawWatchList(). Re-marks the dragged row in the new DOM,
   or -- if the symbol is gone, e.g. removed mid-drag -- ends the drag. */
function dragRepaint() {
  if (dragSymbol === null) return;
  const index = state.watch.findIndex((it) => it.symbol === dragSymbol);
  const row = el.watchList.children[index];
  if (!row) return endDrag();
  row.classList.add("is-dragging");
  el.watchList.classList.add("is-reordering");
}

function finishDrag() {
  if (dragSymbol === null) return;
  const symbol = dragSymbol;
  const from = dragFrom;
  const dropped = dragDropped;
  endDrag();

  if (!dropped) {
    // Cancelled: rows reflowed live purely as preview, so put the order back.
    const at = state.watch.findIndex((it) => it.symbol === symbol);
    if (at >= 0 && at !== from) {
      const [item] = state.watch.splice(at, 1);
      state.watch.splice(from, 0, item);
      drawWatchList();
      setStatus("Reorder cancelled.");
    }
    return;
  }

  const to = state.watch.findIndex((it) => it.symbol === symbol);
  if (to === from || to < 0) return;       // nothing moved: nothing to say
  saveWatch();
  setStatus(`${symbol} moved to position ${to + 1} of ${state.watch.length}.`);
}

/* ---- dragging a row past the rail's edge scrolls the rail ----

   A drag reports where the pointer is only while it moves, so a row carried to
   the bottom of a long rail would sit there scrolling nothing, waiting for the
   hand to move another pixel -- which is exactly the manual arranging this rail
   has to make easy. The list therefore scrolls on its own clock: while the
   pointer sits inside an edge band, an rAF loop keeps pushing the rail, and each
   push re-places the row through dragPlaceAt, because the row under a pointer
   that is holding still has moved without a `dragover` to announce it. */
const DRAG_SCROLL_EDGE = 56;   // px band at either end that starts the scroll
const DRAG_SCROLL_SLOW = 120;  // px per second on entering the band
const DRAG_SCROLL_FAST = 900;  // px per second at the very edge

function stopDragScroll() {
  if (dragScrollRaf) cancelAnimationFrame(dragScrollRaf);
  dragScrollRaf = 0;
  dragPointY = null;
  dragScrollAt = 0;
  dragScrollAcc = 0;
}

/* The box that actually moves: the rail keeps its own overflow on a wide page,
   while a narrow one stacks the rail into the flow and the page scrolls instead. */
function dragScroller(list) {
  if (list.scrollHeight > list.clientHeight + 1) return list;
  return document.scrollingElement || document.documentElement;
}

function dragScrollStep(now) {
  dragScrollRaf = 0;
  if (dragSymbol === null || dragPointY === null) return;
  const list = el.watchList;

  // The band belongs to the slice of the rail that is on screen: a stacked rail
  // is taller than the window, so its own top and bottom are not the edges to aim at.
  const box = list.getBoundingClientRect();
  const top = Math.max(box.top, 0);
  const bottom = Math.min(box.bottom, window.innerHeight);
  const edge = Math.min(DRAG_SCROLL_EDGE, (bottom - top) / 3);
  if (!(edge > 0)) { dragScrollAt = 0; dragScrollAcc = 0; return; }

  const depth = dragPointY < top + edge
    ? (top + edge - dragPointY) / edge
    : dragPointY > bottom - edge
      ? -(dragPointY - (bottom - edge)) / edge
      : 0;
  if (!depth) { dragScrollAt = 0; dragScrollAcc = 0; return; }

  const scroller = dragScroller(list);
  if (scroller.scrollHeight <= scroller.clientHeight) return;   // nothing hidden

  // Pixels per *second*, not per frame: the same gesture has to travel the same
  // distance on a screen painting at 60 Hz and on one struggling at 25.
  const dt = dragScrollAt ? Math.min(50, now - dragScrollAt) : 16;
  dragScrollAt = now;
  const t = Math.min(1, Math.abs(depth));
  dragScrollAcc += (depth > 0 ? -1 : 1) *
    (DRAG_SCROLL_SLOW + (DRAG_SCROLL_FAST - DRAG_SCROLL_SLOW) * t) * dt / 1000;

  // Scroll whole pixels and carry the remainder, so a slow band cannot round to
  // nothing and stall the loop just inside the edge.
  const step = dragScrollAcc < 0 ? Math.ceil(dragScrollAcc) : Math.floor(dragScrollAcc);
  if (step) {
    const before = scroller.scrollTop;
    scroller.scrollTop = before + step;
    dragScrollAcc -= step;
    if (scroller.scrollTop === before) return;   // already at that end
    dragPlaceAt(dragPointY);
  }
  dragScrollRaf = requestAnimationFrame(dragScrollStep);
}

function startDragScroll() {
  if (dragScrollRaf) return;
  dragScrollRaf = requestAnimationFrame(dragScrollStep);
}

/* Focus and the DOM order are rebuilt by every repaint, so a keyboard nudge
   restores both by hand: move the row it acted on, then put focus back. */
function nudgeWatch(symbol, step) {
  const from = state.watch.findIndex((it) => it.symbol === symbol);
  if (from < 0) return;
  const to = Math.max(0, Math.min(state.watch.length - 1, from + step));
  if (!reorderWatch(symbol, to)) return;
  const row = el.watchList.children[to];
  const grip = row && row.querySelector(".watch-grip");
  if (grip) grip.focus();
}

function drawWatchList() {
  drawWatchChanges();
  const list = el.watchList;
  // A repaint is not a scroll. Emptying the list to rebuild it drops the
  // container's scrollTop to 0 for the length of that frame, so every quote
  // arriving yanked a long rail back to its first row — and with it undid the
  // reveal of the lit row, which is the whole point of the highlight. The rail's
  // own position is therefore captured here and put back before returning.
  const keepTop = list.scrollTop;
  list.textContent = "";                    // untrusted labels -> no innerHTML
  el.watchCount.textContent = state.watch.length ? `${state.watch.length}` : "";
  const rail = list.closest(".watch");
  if (rail) rail.classList.toggle("is-filled", state.watch.length > 0);

  if (!state.watch.length) {
    const empty = document.createElement("li");
    empty.className = "watch-empty";
    empty.textContent = "Nothing saved yet. Chart a symbol, then press Add to watchlist.";
    list.append(empty);
    el.watchHint.textContent = "";
    syncWatchToggle();
    if (typeof drawWatchHeat === "function") drawWatchHeat();
    if (typeof syncTableStars === "function") syncTableStars();
    return;
  }

  // One clause explains the pill, and only once a pill is on screen -- an
  // empty list of tags needs no key.
  const anyVerdict = state.watch.some((it) => {
    const q = state.watchQuotes[it.symbol];
    return q && q.data && q.data.trend && TREND_WORD[q.data.trend.label];
  });
  const anyOdds = state.watch.some((it) => {
    const q = state.watchQuotes[it.symbol];
    const r = q && q.data && q.data.profitProbability;
    return Boolean(r && Number.isFinite(r.probability));
  });
  // A lighter tag is a lean, not a verdict: the key sentence gains a clause
  // about it only once one is on screen.
  const anyLean = state.watch.some((it) => {
    const q = state.watchQuotes[it.symbol];
    const t = q && q.data && q.data.trend;
    return Boolean(t && t.label === "neutral" && TREND_WORD[t.lean]);
  });
  el.watchHint.textContent = (
    state.watch.length > 1
      ? "Click a symbol to chart it. Drag the grip — or focus it and press ↑/↓ — to reorder."
      : "Click a symbol to chart its last three months."
  ) + (activeWatchItem() ? " The highlighted row is the chart on screen." : "")
    + (anyVerdict ? " Each tag is that row's three-month verdict" +
        (anyLean ? ", and a lighter tag is a lean it has not confirmed — only a steady lean gets one." : ".") : "")
    + (anyOdds ? " The chance figure is each chart's own three-month estimate." : "");

  state.watch.forEach((item) => {
    const quote = state.watchQuotes[item.symbol];
    if (typeof watchItemVisible === "function" && !watchItemVisible(item, quote)) return;
    const active = isWatchActive(item);

    // The row's verdict. `quote.data` is the very payload the chart draws, so
    // this label is the chart's own badge, not a second opinion about the
    // symbol. A missing or unscoreable series shows no pill rather than
    // inventing a neutral one -- a missing fetch is not a verdict.
    const trend = quote && quote.data && quote.data.trend ? quote.data.trend : null;
    const verdict = trend && TREND_WORD[trend.label] ? trend.label : null;
    const verdictScore = verdict && Number.isFinite(trend.score)
      ? ` (score ${trend.score >= 0 ? "+" : "−"}${Math.abs(trend.score).toFixed(2)})`
      : "";
    // A neutral window inside one side's hold band says so, in the chart's own
    // terms: `trend.lean` is the classifier's own field, not a second reading.
    // Its label stays Neutral — a lean is not a verdict, so the tag it draws
    // says "leaning", never "Bullish".
    const lean = verdict === "neutral" && TREND_WORD[trend.lean] ? trend.lean : null;
    // A row whose series the source has stopped printing carries no verdict and
    // no odds either (the chart's payload says so, `staleDays`), and the row
    // says the date rather than letting an old price pass for today's. It is the
    // same rule that kept ATKR off the leaning table.
    const staleDays = quote && quote.data && Number.isFinite(quote.data.staleDays)
      ? quote.data.staleDays : null;

    // The chart's own 0-1 odds for the next three months, from the same payload
    // the chart prints. A yield, a futures contract whose chart supports no
    // estimate, or a row still loading has none, and then the line is left out
    // rather than filled with a default: a missing number is missing.
    const odds = quote && quote.data ? quote.data.profitProbability : null;
    const oddsP = odds && Number.isFinite(odds.probability) ? odds.probability : null;

    const li = document.createElement("li");
    li.className = "watch-item" + (active ? " is-active" : "");

    const pick = document.createElement("button");
    pick.type = "button";
    pick.className = "watch-pick";
    pick.setAttribute("aria-label",
      `Chart ${item.name} (${item.symbol})` +
      (verdict ? `, trend ${TREND_WORD[verdict]}` : "") +
      (lean ? `, leaning ${lean}` : "") +
      (staleDays === null ? ""
        : `, no verdict: the newest bar is ${staleDays} days old`) +
      (oddsP === null ? "" : `, three-month profit odds ${oddsP.toFixed(2)}`));
    if (active) pick.setAttribute("aria-current", "true");

    const top = document.createElement("span");
    top.className = "watch-top";
    const id = document.createElement("span");
    id.className = "watch-id";
    const sym = document.createElement("span");
    sym.className = "watch-sym";
    sym.textContent = item.symbol;
    id.append(sym);
    if (typeof appendFlagDot === "function") appendFlagDot(id, item.symbol);
    if (quote && quote.data && typeof appendFreshnessChip === "function") {
      appendFreshnessChip(id, quote.data, item.symbol);
    } else if (quote && quote.error && typeof appendFreshnessChip === "function") {
      const chip = document.createElement("span");
      chip.className = "fresh-chip kind-offline";
      chip.textContent = "offline";
      chip.title = quote.error;
      id.append(chip);
    }
    const metaNote = typeof getWatchMeta === "function" ? getWatchMeta(item.symbol).note : "";
    if (metaNote) {
      const tip = document.createElement("span");
      tip.className = "watch-note-mark";
      tip.textContent = "✎";
      tip.title = metaNote;
      id.append(tip);
    }
    const tagPhrase = watchTagPhrase(trend);
    if (tagPhrase && tagPhrase.kind === "lean") {
      // The lean replaces the plain Neutral tag rather than sitting beside it.
      // "leaning bullish" already implies the verdict is Neutral, and the second
      // pill cost the symbol 55px -- at a 340px rail that read "US…" for
      // `USDPHP=X`. The tooltip and the accessible name still say Neutral out
      // loud, so nothing is hidden, only shortened.
      const leanTag = document.createElement("span");
      leanTag.className = "watch-trend leaning " + tagPhrase.lean;
      leanTag.textContent = tagPhrase.text;
      leanTag.title = tagPhrase.title;
      id.append(leanTag);
    } else if (verdict) {
      const tag = document.createElement("span");
      tag.className = "watch-trend " + verdict;
      tag.textContent = TREND_WORD[verdict];
      tag.title = `${SPAN_WORDS[RANGE] || "Window"} trend${verdictScore}: the same ` +
        `classifier the chart's badge uses, scored on the same bars.`;
      id.append(tag);
    }

    const price = document.createElement("span");
    price.className = "watch-price";
    if (quote && quote.data) {
      price.textContent = formatPrice(quote.price, quote.data);
      // A disk fallback's price is true of `fetchedAt`, not of now; the row
      // keeps its single-line shape and puts the date where hovering finds it.
      if (quote.data.cached && quote.data.fetchedAt) {
        price.title = "Last retrieved " + retrievedAt(quote.data.fetchedAt);
      } else if (staleDays !== null) {
        // The source stopped printing: the price on this row is that last bar's
        // close, and the tooltip carries the date the same way a disk copy's
        // does -- the row keeps its shape, the fact is one hover away.
        price.title = `Newest bar is from ${quote.data.staleBar || "the last print"} — ` +
          `${staleDays === 1 ? "1 day" : staleDays + " days"} old. The source has ` +
          `not printed since, so this row has no verdict and no odds.`;
      }
    } else if (quote && quote.loading) {
      price.textContent = "…";
    } else {
      price.textContent = "";               // error -> the sub-line carries it
    }
    top.append(id, price);

    const sub = document.createElement("span");
    sub.className = "watch-sub";
    const name = document.createElement("span");
    name.className = "watch-name";
    name.textContent = item.name;

    const chg = document.createElement("span");
    if (quote && quote.data && Number.isFinite(quote.pct)) {
      const up = quote.up;
      chg.className = "watch-chg " + (up ? "up" : "down");
      // The tooltip says which move this is and which bar it starts from: a
      // bare "-9.34%" beside a price reads as today's move until told otherwise.
      chg.setAttribute("title", quote.moveTitle || "Change over the charted window");
      // Glyph carries the direction, so this never depends on color alone.
      chg.textContent =
        `${up ? "▲" : "▼"} ${up ? "+" : "−"}${Math.abs(quote.pct).toFixed(2)}%`;
    } else if (quote && quote.error) {
      chg.className = "watch-chg";
      chg.textContent = "unavailable";
      chg.title = quote.error;
    } else {
      chg.className = "watch-chg";
      chg.textContent = "";
    }
    const right = document.createElement("span");
    right.className = "watch-right";
    const spark = quote && quote.data ? watchSparkline(quote.data.points, quote.up) : null;
    if (spark) right.append(spark);
    right.append(chg);
    // PSE liquidity: 5-day peso turnover from this chart's own bars.
    if (quote && quote.data && typeof watchTurnover === "function") {
      const turn = watchTurnover(quote.data, 5);
      if (Number.isFinite(turn)) {
        const liq = document.createElement("span");
        liq.className = "watch-liq";
        liq.textContent = typeof compact === "function" ? compact(turn, "PHP") : String(Math.round(turn));
        liq.title = "Average close × volume over the last five bars with volume on this chart (pesos). Liquidity context only.";
        const warn = typeof thinBookWarn === "function" ? thinBookWarn(turn) : null;
        if (warn) {
          liq.classList.add("thin-book-warn");
          liq.textContent += " · thin";
          liq.title = warn.title;
        }
        right.append(liq);
      }
    }
    // Against-market chip when a benchmark reading is already memoised.
    if (quote && quote.data && typeof againstMarketLine === "function"
        && typeof benchmarkFor === "function") {
      const pick = benchmarkFor(quote.data);
      const memo = pick && typeof benchMemo !== "undefined" ? benchMemo.get(pick.symbol) : null;
      if (pick && memo && memo.data) {
        const line = againstMarketLine(quote.data, memo.data, pick);
        if (line) {
          const vs = document.createElement("span");
          vs.className = "watch-vs-market " + (line.label || "");
          vs.textContent = line.text;
          vs.title = `Vs ${pick.name} over shared days — context only, not this row's label.`;
          right.append(vs);
        }
      }
    }
    // UITF peer drift / ladder among watched funds in the same category.
    if (quote && quote.data && typeof fundPeerDrift === "function") {
      const drift = fundPeerDrift(item.symbol, state.watch, state.watchQuotes);
      if (drift) {
        const peer = document.createElement("span");
        peer.className = "watch-peer " + drift.kind;
        peer.textContent = drift.kind === "top" ? "↑ peers" : "↓ peers";
        peer.title = `${drift.text} among ${drift.peers} watched funds in ${drift.category}. Rank of past 1M moves only.`;
        id.append(peer);
      }
    }
    if (quote && quote.data && typeof fundPeerLadder === "function") {
      const ladder = fundPeerLadder(item.symbol, state.watch, state.watchQuotes);
      if (ladder && ladder.rank > 0) {
        const lad = document.createElement("span");
        lad.className = "watch-peer-ladder";
        lad.textContent = `#${ladder.rank}/${ladder.peers.length}`;
        lad.title = ladder.peers.map((p, i) =>
          `${i + 1}. ${p.symbol.split(":").pop()} ${p.pct >= 0 ? "+" : "−"}${Math.abs(p.pct).toFixed(1)}%`
        ).join(" · ") + ` · ${ladder.category} (1M moves among watched peers)`;
        id.append(lad);
      }
    }
    sub.append(name, right);

    pick.append(top, sub);

    // The week and the month inside the same window, one footnote line, each
    // figure with its own sign so it never depends on colour alone. The
    // distance from the window's high and low rides in the tooltip.
    const periods = quote && quote.data ? periodChanges(quote.data.points) : null;
    if (periods && periods.periods.some((p) => p.pct !== null)) {
      const line = document.createElement("span");
      line.className = "watch-periods";
      for (const p of periods.periods) {
        if (p.pct === null) continue;
        const part = document.createElement("span");
        const label = document.createElement("span");
        label.textContent = p.name;
        const val = document.createElement("span");
        val.className = "watch-period-val " + (p.pct >= 0 ? "up" : "down");
        val.textContent = signedPct(p.pct);
        part.append(label, " ", val);
        line.append(part);
      }
      const tips = ["Change from the last close at least 7 / 30 days before the newest"];
      if (Number.isFinite(periods.fromHigh) && Number.isFinite(periods.fromLow)) {
        tips.push(`${Math.abs(periods.fromHigh).toFixed(1)}% below the 3-month high, `
          + `${periods.fromLow.toFixed(1)}% above the 3-month low`);
        const off = document.createElement("span");
        off.textContent = periods.fromHigh === 0 ? "at high"
          : periods.fromLow === 0 ? "at low"
          : `${Math.abs(periods.fromHigh).toFixed(1)}% off high`;
        line.append(off);
      }
      line.title = tips.join(". ") + ".";
      pick.append(line);
    }

    // Below the name and the window's move, because it is a different kind of
    // claim: the move is what the last three months did, this is a model's odds
    // about the next three. Same figure, same tooltip and same above/below 0.5
    // colour as the stat-line under the price.
    if (oddsP !== null) {
      const oddsLine = document.createElement("span");
      oddsLine.className = "watch-odds";
      oddsLine.title = profitOddsClaim(odds);
      const oddsLabel = document.createElement("span");
      oddsLabel.textContent = "3-mo chance";
      const oddsVal = document.createElement("span");
      oddsVal.className = "watch-odds-val " + (oddsP >= 0.5 ? "above" : "below");
      oddsVal.textContent = oddsP.toFixed(2);
      oddsLine.append(oddsLabel, oddsVal);
      pick.append(oddsLine);
    }
    pick.dataset.chart = item.symbol;
    pick.addEventListener("click", () => loadChart(item.symbol));

    // The grip is the only draggable part, so the rest of the row keeps its
    // click-to-chart. Arrow keys on a focused grip move the row instead.
    const grip = document.createElement("button");
    grip.type = "button";
    grip.className = "watch-grip";
    grip.textContent = "⠿";
    grip.draggable = true;
    grip.title = "Drag to reorder";
    grip.setAttribute("aria-label",
      `Reorder ${item.symbol}. Drag, or press arrow up or down to move it.`);
    grip.addEventListener("dragstart", (ev) => {
      dragSymbol = item.symbol;
      dragFrom = state.watch.findIndex((it) => it.symbol === item.symbol);
      ev.dataTransfer.effectAllowed = "move";
      // Some browsers cancel a drag that carries no payload.
      ev.dataTransfer.setData("text/plain", item.symbol);
      li.classList.add("is-dragging");
      list.classList.add("is-reordering");
    });
    grip.addEventListener("dragend", finishDrag);
    grip.addEventListener("keydown", (ev) => {
      let step = 0;
      if (ev.key === "ArrowUp") step = -1;
      else if (ev.key === "ArrowDown") step = 1;
      else if (ev.key === "Home") step = -state.watch.length;   // clamped to 0
      else if (ev.key === "End") step = state.watch.length;     // clamped to last
      else return;
      ev.preventDefault();   // else the rail scrolls instead of the row moving
      nudgeWatch(item.symbol, step);
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-btn";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Remove ${item.symbol} from watchlist`);
    remove.addEventListener("click", (ev) => {
      ev.stopPropagation();
      removeFromWatch(item.symbol);
      setStatus(`Removed ${item.symbol} from the watchlist.`);
    });

    li.append(grip, pick, remove);
    list.append(li);
  });

  if (!list.children.length && state.watch.length) {
    const empty = document.createElement("li");
    empty.className = "watch-empty";
    empty.textContent = watchInboxMode && watchInboxMode()
      ? "No watched name has a pullback, volume spike, or window extreme right now."
      : "No rows match this group filter.";
    list.append(empty);
  }

  syncWatchToggle();
  dragRepaint();   // a drag outlives the rows it started on
  list.scrollTop = keepTop;   // the rail keeps the place the reader left it in
  if (typeof drawWatchHeat === "function") drawWatchHeat();
  if (typeof syncTableStars === "function") syncTableStars();
  if (typeof deskOnWatchDrawn === "function") deskOnWatchDrawn();
}

/* The charted asset is the only thing the toggle can add, so it mirrors
   state.data — there is no typed text to mistype. Called at the end of
   drawWatchList, which every mutation repaints through. */
function syncWatchToggle() {
  const btn = el.watchToggle;
  const d = state.data;
  btn.hidden = !d;
  if (!d) return;
  const on = isWatched(d.symbol);
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  el.watchGlyph.textContent = on ? "\u2605" : "\u2606";
  el.watchToggleLabel.textContent = on ? "On watchlist" : "Add to watchlist";
}
