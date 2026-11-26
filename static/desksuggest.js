"use strict";

/* Desk suggestion pack (2026-11-25): session countdown, digest under badge,
   chance yardstick on the chart, packet day-diff, layouts, column presets,
   thin-book warn, PSE Edge link, UITF ladder, PH–UST spread, reminders,
   watch CSV, range chips, print hooks. Pure helpers first for tests.
   Never a second classifier — only presents existing labels and arithmetic. */

const THIN_BOOK_PHP = 1_000_000;          // same floor as recent.MIN_TURNOVER_PHP
const LAYOUT_KEY = "apd-layouts";
const COLUMN_PRESET_KEY = "apd-watch-cols";
const REMINDER_KEY = "apd-reminders";
const PACKET_PREV_KEY = "apd-packet-prev";
const RANGE_KEY = "apd-chart-range";
const CHANCE_LINE = "Across random walks of the same length, about 3.7% of windows "
  + "look labelled bullish by chance alone (and 3.7% bearish). A real label still "
  + "needs the score and drift checks — this is a yardstick, not this chart's odds.";

const WATCH_COLUMN_PRESETS = {
  full: { label: "Full", className: "" },
  fees: { label: "PSE fees", className: "cols-fees" },
  periods: { label: "1W / 1M", className: "cols-periods" },
  market: { label: "Vs market", className: "cols-market" },
};

/* ---- pure helpers ------------------------------------------------------ */

function formatCountdown(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h >= 24) {
    const d = Math.floor(h / 24);
    return `${d}d ${h % 24}h`;
  }
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}m ${String(s % 60).padStart(2, "0")}s`;
}

function pseSessionChip(session, nowMs) {
  if (!session) return null;
  const base = session._at != null ? session._at : Date.now();
  const elapsed = Math.max(0, ((nowMs != null ? nowMs : Date.now()) - base) / 1000);
  if (session.state === "open" && Number.isFinite(session.secondsToClose)) {
    const left = Math.max(0, session.secondsToClose - elapsed);
    const text = formatCountdown(left);
    return text ? { text: `PSE closes in ${text}`, title: `PSE session open · Manila ${session.localTime || ""}` } : null;
  }
  if (Number.isFinite(session.secondsToOpen)) {
    const left = Math.max(0, session.secondsToOpen - elapsed);
    const text = formatCountdown(left);
    const when = session.state === "pre-open" ? "opens" : "next open";
    return text ? { text: `PSE ${when} in ${text}`, title: `PSE ${session.state} · Manila ${session.localTime || ""}` } : null;
  }
  if (session.state === "weekend" || session.state === "holiday") {
    return { text: `PSE ${session.state}`, title: `Manila ${session.localTime || ""}` };
  }
  return { text: `PSE ${session.state}`, title: `Manila ${session.localTime || ""}` };
}

function thinBookWarn(turnover, floor) {
  const lim = floor != null ? floor : THIN_BOOK_PHP;
  if (!Number.isFinite(turnover) || turnover <= 0) return null;
  if (turnover >= lim) return null;
  return {
    text: "thin book",
    title: `5-day peso turnover ${Math.round(turnover).toLocaleString("en-PH")} is under ₱${lim.toLocaleString("en-PH")}. Liquidity context only.`,
  };
}

function pseEdgeUrl(symbol) {
  const raw = String(symbol || "").toUpperCase().trim();
  let ticker = raw;
  if (ticker.startsWith("PSE:") || ticker.startsWith("EDGE:")) ticker = ticker.slice(ticker.indexOf(":") + 1);
  if (ticker.endsWith(".PS")) ticker = ticker.slice(0, -3);
  if (!ticker || ticker === "PSEI") return "https://edge.pse.com.ph/";
  return "https://edge.pse.com.ph/companyDirectory/search.do?pageNo=1&companyName="
    + encodeURIComponent(ticker);
}

/* PH 10Y vs a US rate proxy from recent rows. Prefer ^TNX / US10Y yield minus
   PH10Y (true spread). If only Treasury futures sit on the desk, show both
   levels side by side — never subtract a futures price from a yield. */
function phUstSpread(rows) {
  const find = (needles) => {
    for (const r of rows || []) {
      const s = String(r.chartSymbol || r.symbol || r.ticker || "").toUpperCase();
      if (needles.some((n) => s.includes(n)) && Number.isFinite(r.price)) return r;
    }
    return null;
  };
  const ph = find(["PH10Y"]);
  if (!ph) return null;
  const ustYield = find(["^TNX", "US10Y", "TNX"]);
  if (ustYield) {
    const spread = ph.price - ustYield.price;
    return {
      text: `PH–UST 10Y ${spread >= 0 ? "+" : "−"}${Math.abs(spread).toFixed(2)} pp`,
      spread,
      ph: ph.price,
      ust: ustYield.price,
      kind: "spread",
    };
  }
  const zb = find(["ZB=F", "UB=F"]);
  if (!zb) return null;
  return {
    text: `PH10Y ${ph.price.toFixed(2)}% · ${String(zb.ticker || zb.symbol || "ZB").split(":").pop()} ${zb.price.toFixed(2)}`,
    spread: null,
    ph: ph.price,
    ust: zb.price,
    kind: "levels",
  };
}

/* Full UITF peer ladder (sorted 1M %), or null when fewer than 3 peers. */
function fundPeerLadder(symbol, watch, quotes) {
  const q = quotes && quotes[symbol];
  const d = q && q.data;
  if (!d || !d.fundSeries || !d.category) return null;
  const peers = [];
  for (const item of watch || []) {
    const qd = quotes[item.symbol] && quotes[item.symbol].data;
    if (!qd || !qd.fundSeries || qd.category !== d.category) continue;
    const pts = (qd.points || []).filter((p) => p && Number.isFinite(p.c));
    if (pts.length < 2) continue;
    let pct = null;
    if (typeof periodChanges === "function") {
      const found = periodChanges(pts);
      const hit = found && found.periods.find((p) => p.name === "1M");
      if (hit && Number.isFinite(hit.pct)) pct = hit.pct;
    } else {
      const a = pts[0].c, b = pts[pts.length - 1].c;
      if (a > 0) pct = (b / a - 1) * 100;
    }
    if (!Number.isFinite(pct)) continue;
    peers.push({ symbol: item.symbol, pct, name: (qd.name || item.name || item.symbol) });
  }
  if (peers.length < 3) return null;
  peers.sort((a, b) => b.pct - a.pct);
  const me = peers.findIndex((p) => String(p.symbol).toUpperCase() === String(symbol).toUpperCase());
  return { category: d.category, peers, rank: me + 1 };
}

function packetDayDiff(prev, next) {
  if (!next) return null;
  const bits = [];
  const prevSum = prev && prev.digest && prev.digest.summary;
  const nextSum = next.digest && next.digest.summary;
  if (prevSum && nextSum && prevSum !== nextSum) bits.push("digest summary changed");
  const prevTurns = (prev && prev.digest && prev.digest.freshTurns) || [];
  const nextTurns = (next.digest && next.digest.freshTurns) || [];
  const prevKeys = new Set(prevTurns.map((t) => String(t.chartSymbol || t.symbol || "")));
  const fresh = nextTurns.filter((t) => !prevKeys.has(String(t.chartSymbol || t.symbol || "")));
  if (fresh.length) bits.push(`${fresh.length} new turn${fresh.length === 1 ? "" : "s"}`);
  const prevAlarms = ((prev && prev.digest && prev.digest.alarms && prev.digest.alarms.peso) || []).length;
  const nextAlarms = ((next.digest && next.digest.alarms && next.digest.alarms.peso) || []).length;
  if (nextAlarms !== prevAlarms) bits.push(`peso alarms ${prevAlarms}→${nextAlarms}`);
  if (!bits.length && prev) bits.push("no material change vs last packet");
  if (!prev) return { text: "First packet stored this browser", bits: [] };
  return { text: "Since last packet: " + bits.join(" · "), bits };
}

function watchLabelCounts(watch, quotes) {
  const counts = { bullish: 0, bearish: 0, neutral: 0, none: 0 };
  const dayMoves = [];
  for (const item of watch || []) {
    const d = quotes && quotes[item.symbol] && quotes[item.symbol].data;
    const t = d && d.trend;
    if (!t || !t.label) counts.none++;
    else if (counts[t.label] != null) counts[t.label]++;
    else counts.none++;
    if (d && d.points && d.points.length >= 2) {
      const a = d.points[d.points.length - 2].c;
      const b = d.points[d.points.length - 1].c;
      if (a > 0 && Number.isFinite(b)) dayMoves.push((b / a - 1) * 100);
    }
  }
  dayMoves.sort((a, b) => a - b);
  const median = dayMoves.length
    ? dayMoves[Math.floor(dayMoves.length / 2)]
    : null;
  return { counts, median, n: (watch || []).length };
}

function loadLayouts() {
  try {
    const raw = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "[]");
    return Array.isArray(raw) ? raw.filter((x) => x && x.name) : [];
  } catch { return []; }
}

function saveLayouts(list) {
  try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(list.slice(0, 12))); } catch {}
}

function snapshotLayout(name) {
  const snap = {
    name: String(name || "").trim().slice(0, 40),
    at: Date.now(),
    heat: typeof heatOn !== "undefined" ? heatOn : false,
    compact: typeof watchCompact !== "undefined" ? watchCompact : false,
    columns: localStorage.getItem(COLUMN_PRESET_KEY) || "full",
    peso: typeof pesoOn !== "undefined" ? pesoOn : false,
    range: typeof RANGE !== "undefined" ? RANGE : "3mo",
    sixPack: typeof loadSixPack === "function" ? loadSixPack() : [],
    compare: typeof comparePeers !== "undefined"
      ? { peers: (comparePeers || []).map((p) => p.symbol || p), base: typeof compareBase !== "undefined" ? compareBase : null }
      : null,
  };
  if (!snap.name) return null;
  const list = loadLayouts().filter((x) => x.name !== snap.name);
  list.unshift(snap);
  saveLayouts(list);
  return snap;
}

function applyLayout(snap) {
  if (!snap) return;
  try {
    if (snap.columns) localStorage.setItem(COLUMN_PRESET_KEY, snap.columns);
    if (snap.heat != null) localStorage.setItem("apd-watch-view", snap.heat ? "tiles" : "list");
    if (snap.compact != null) localStorage.setItem("apd-watch-density", snap.compact ? "compact" : "full");
    if (snap.peso != null) localStorage.setItem("apd-peso-view", snap.peso ? "1" : "0");
    if (snap.range) localStorage.setItem(RANGE_KEY, snap.range);
  } catch {}
  if (typeof heatOn !== "undefined") heatOn = Boolean(snap.heat);
  if (typeof watchCompact !== "undefined") watchCompact = Boolean(snap.compact);
  if (typeof pesoOn !== "undefined") pesoOn = Boolean(snap.peso);
  if (typeof setChartRange === "function" && snap.range) setChartRange(snap.range, { quiet: true });
  applyWatchColumnPreset(snap.columns || "full");
  if (typeof applyWatchDensity === "function") applyWatchDensity();
  if (typeof drawWatchHeat === "function") drawWatchHeat();
  if (typeof drawWatchList === "function") drawWatchList();
  if (typeof renderAll === "function") renderAll();
}

function applyWatchColumnPreset(key) {
  const preset = WATCH_COLUMN_PRESETS[key] || WATCH_COLUMN_PRESETS.full;
  try { localStorage.setItem(COLUMN_PRESET_KEY, key in WATCH_COLUMN_PRESETS ? key : "full"); } catch {}
  const list = document.getElementById("watchList");
  if (!list) return preset;
  for (const k of Object.keys(WATCH_COLUMN_PRESETS)) {
    if (WATCH_COLUMN_PRESETS[k].className) list.classList.remove(WATCH_COLUMN_PRESETS[k].className);
  }
  if (preset.className) list.classList.add(preset.className);
  return preset;
}

function loadReminders() {
  try {
    const raw = JSON.parse(localStorage.getItem(REMINDER_KEY) || "[]");
    return Array.isArray(raw) ? raw.filter((r) => r && r.symbol && r.date) : [];
  } catch { return []; }
}

function saveReminders(list) {
  try { localStorage.setItem(REMINDER_KEY, JSON.stringify(list.slice(0, 80))); } catch {}
}

function addReminder(symbol, date, note) {
  const list = loadReminders().filter((r) =>
    !(String(r.symbol).toUpperCase() === String(symbol).toUpperCase() && r.date === date));
  list.push({
    symbol: String(symbol || "").trim(),
    date: String(date || "").slice(0, 10),
    note: String(note || "").trim().slice(0, 120),
  });
  saveReminders(list);
  return list;
}

function dueReminders(today) {
  const day = today || new Date().toISOString().slice(0, 10);
  return loadReminders().filter((r) => r.date <= day);
}

/* ---- UI drawers -------------------------------------------------------- */

let _sessionTimer = null;
let _sessionSnap = null;

function drawPseSessionChip(session) {
  const ribbon = document.getElementById("morningRibbon");
  if (!ribbon) return;
  let chip = document.getElementById("pseSessionChip");
  if (!chip) {
    chip = document.createElement("span");
    chip.id = "pseSessionChip";
    chip.className = "ribbon-breadth pse-session-chip";
    ribbon.prepend(chip);
  }
  if (session) {
    _sessionSnap = { ...session, _at: Date.now() };
  }
  const hit = pseSessionChip(_sessionSnap);
  if (!hit) { chip.hidden = true; chip.textContent = ""; return; }
  chip.hidden = false;
  ribbon.hidden = false;   // the ribbon may hold only this chip
  chip.textContent = hit.text;
  chip.title = hit.title || "";
  if (!_sessionTimer) {
    _sessionTimer = setInterval(() => drawPseSessionChip(null), 30 * 1000);
  }
}

function drawDigestUnderBadge(digest) {
  const line = document.getElementById("chartDigestLine");
  if (!line) return;
  const text = digest && digest.summary ? String(digest.summary) : "";
  if (!text) { line.hidden = true; line.textContent = ""; return; }
  line.hidden = false;
  const pills = typeof summaryPills === "function" ? summaryPills(digest, { withMarkets: true }) : [];
  if (pills.length) {
    drawGlancePills(line, pills);
    line.classList.add("glance-pills");
    line.setAttribute("role", "group");
  } else {
    line.classList.remove("glance-pills");
    line.removeAttribute("role");
    line.textContent = text;
  }
  line.title = text + " — from the morning digest, not a forecast.";
  line.setAttribute("aria-label", text);
}

function drawChanceOnChart() {
  const note = document.getElementById("chanceNote");
  if (!note) return;
  note.hidden = false;
  note.textContent = CHANCE_LINE;
  note.title = "Same yardstick the recent-table note uses (recent.CHANCE_RATE). Describes labelled windows in random walks, not this asset.";
}

function drawPseEdgeLink(d) {
  const a = document.getElementById("pseEdgeLink");
  if (!a) return;
  const sym = d && d.symbol ? String(d.symbol).toUpperCase() : "";
  const pse = sym.startsWith("PSE:") || sym.startsWith("EDGE:") || sym.endsWith(".PS")
    || (d && d.currency === "PHP" && d.boardLot);
  if (!pse) { a.hidden = true; a.removeAttribute("href"); return; }
  a.hidden = false;
  a.href = pseEdgeUrl(sym);
  a.textContent = "PSE Edge disclosures";
  a.title = "Open the exchange disclosure site for this ticker (new tab).";
  a.rel = "noopener noreferrer";
  a.target = "_blank";
}

function drawThinBookHero(d) {
  const el = document.getElementById("thinBookNote");
  if (!el) return;
  const turn = typeof watchTurnover === "function" ? watchTurnover(d, 5) : null;
  const warn = thinBookWarn(turn);
  if (!warn) { el.hidden = true; el.textContent = ""; return; }
  el.hidden = false;
  el.textContent = "Thin book · 5-day peso turnover under ₱1M";
  el.title = warn.title;
}

function drawPhUstSpreadChip(rows) {
  const chip = document.getElementById("phUstSpreadChip");
  if (!chip) return;
  const hit = phUstSpread(rows);
  if (!hit) { chip.hidden = true; chip.textContent = ""; return; }
  chip.hidden = false;
  chip.textContent = hit.text;
  chip.title = hit.kind === "spread"
    ? `PH 10Y ${hit.ph.toFixed(2)}% minus US 10Y ${hit.ust.toFixed(2)}%. Descriptive spacing only.`
    : `PH 10Y yield beside a US Treasury futures price (different units — not a spread).`;
}

function drawPacketDiff(packet) {
  const el = document.getElementById("packetDiff");
  if (!el) return;
  let prev = null;
  try { prev = JSON.parse(localStorage.getItem(PACKET_PREV_KEY) || "null"); } catch {}
  const diff = packetDayDiff(prev, packet);
  if (packet) {
    try { localStorage.setItem(PACKET_PREV_KEY, JSON.stringify(packet)); } catch {}
  }
  if (!diff) { el.hidden = true; el.textContent = ""; return; }
  el.hidden = false;
  // Short form for the status row; the full sentence stays on hover.
  el.textContent = diff.bits && diff.bits.length ? "↻ " + diff.bits.join(" · ") : "↻ " + diff.text;
  el.title = diff.text;
}

function drawWatchSummaryExtra() {
  const box = document.getElementById("watchStats");
  if (!box || typeof state === "undefined") return;
  const { counts, median, n } = watchLabelCounts(state.watch, state.watchQuotes);
  if (!n) return;
  const extra = ` · ▲${counts.bullish} ▼${counts.bearish} ·${counts.neutral}`
    + (Number.isFinite(median) ? ` · day med ${median >= 0 ? "+" : "−"}${Math.abs(median).toFixed(2)}%` : "");
  if (box.textContent && !box.textContent.includes("▲")) box.textContent += extra;
  else if (!box.textContent) {
    box.hidden = false;
    box.textContent = `${n} watched` + extra;
  }
}

function drawRemindersInbox() {
  const box = document.getElementById("remindersBox");
  if (!box) return;
  const due = dueReminders();
  box.textContent = "";
  if (!due.length) { box.hidden = true; return; }
  box.hidden = false;
  const h = document.createElement("h3");
  h.className = "triage-sub";
  h.textContent = `Reminders (${due.length})`;
  box.append(h);
  const ul = document.createElement("ul");
  ul.className = "triage-list";
  for (const r of due.slice(0, 8)) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "triage-chip";
    btn.textContent = `${r.symbol} · ${r.date}${r.note ? " · " + r.note : ""}`;
    btn.addEventListener("click", () => {
      if (typeof loadChart === "function") loadChart(r.symbol);
    });
    const x = document.createElement("button");
    x.type = "button";
    x.className = "ghost-btn";
    x.textContent = "Done";
    x.addEventListener("click", () => {
      saveReminders(loadReminders().filter((y) => !(y.symbol === r.symbol && y.date === r.date)));
      drawRemindersInbox();
    });
    li.append(btn, x);
    ul.append(li);
  }
  box.append(ul);
}

function drawLayoutControls() {
  const box = document.getElementById("layoutControls");
  if (!box || box.dataset.bound) return;
  box.dataset.bound = "1";
  box.textContent = "";
  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "ghost-btn";
  saveBtn.textContent = "Save layout";
  saveBtn.addEventListener("click", () => {
    const name = window.prompt("Name this layout", "Morning");
    if (!name) return;
    snapshotLayout(name);
    drawLayoutControls();
    if (typeof setStatus === "function") setStatus("Layout saved: " + name.trim());
  });
  box.append(saveBtn);
  for (const snap of loadLayouts().slice(0, 6)) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ghost-btn sweep-preset";
    b.textContent = snap.name;
    b.title = "Restore heat/compact/columns/peso/range";
    b.addEventListener("click", () => applyLayout(snap));
    box.append(b);
  }
}

function drawColumnPresets() {
  const box = document.getElementById("watchColPresets");
  if (!box) return;
  let cur = "full";
  try { cur = localStorage.getItem(COLUMN_PRESET_KEY) || "full"; } catch {}
  if (!box.dataset.bound) {
    box.dataset.bound = "1";
    box.textContent = "";
    for (const [key, preset] of Object.entries(WATCH_COLUMN_PRESETS)) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ghost-btn";
      b.dataset.preset = key;
      b.textContent = preset.label;
      b.addEventListener("click", () => {
        applyWatchColumnPreset(key);
        drawColumnPresets();
        if (typeof drawWatchList === "function") drawWatchList();
      });
      box.append(b);
    }
  }
  for (const b of box.querySelectorAll("button[data-preset]")) {
    b.setAttribute("aria-pressed", String(b.dataset.preset === cur));
  }
  applyWatchColumnPreset(cur);
}

function exportWatchCsv() {
  if (typeof state === "undefined" || !state.watch.length) {
    if (typeof setStatus === "function") setStatus("Watchlist is empty — nothing to export.");
    return;
  }
  const rows = [["symbol", "name", "price", "currency", "label", "score", "dayPct", "turnover5dPhp", "boardLot", "breakEven", "sellNet"]];
  for (const item of state.watch) {
    const q = state.watchQuotes[item.symbol];
    const d = q && q.data;
    const t = d && d.trend;
    const price = d && d.points && d.points.length ? d.points[d.points.length - 1].c : "";
    const turn = d && typeof watchTurnover === "function" ? watchTurnover(d, 5) : "";
    const lot = d && d.boardLot;
    let be = "", net = "";
    if (d && d.currency === "PHP" && Number.isFinite(lot) && Number.isFinite(price)
        && typeof pseBreakEven === "function") {
      be = pseBreakEven(price, lot) || "";
      if (typeof pseSellNet === "function") net = pseSellNet(price, lot) || "";
    }
    rows.push([
      item.symbol, item.name || "", price, (d && d.currency) || "",
      (t && t.label) || "", (t && Number.isFinite(t.score) ? t.score : ""),
      Number.isFinite(q && q.pct) ? q.pct : "",
      Number.isFinite(turn) ? Math.round(turn) : "",
      Number.isFinite(lot) ? lot : "", be, net,
    ]);
  }
  const body = rows.map((r) => r.map((c) => {
    const s = String(c == null ? "" : c);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }).join(",")).join("\n") + "\n";
  if (typeof downloadBlob === "function") {
    downloadBlob("watchlist.csv", body, "text/csv;charset=utf-8");
  }
  if (typeof setStatus === "function") setStatus(`Exported ${state.watch.length} rows as CSV.`);
}

/* Chart range chips — default stays 3mo; changing RANGE reloads the open chart
   so the badge matches the drawn window (invariant 1 for the chart on screen). */
const ALLOWED_CLIENT_RANGES = ["1mo", "3mo", "6mo", "1y", "2y", "5y"];

function setChartRange(span, opts) {
  if (!ALLOWED_CLIENT_RANGES.includes(span)) return;
  if (typeof RANGE !== "undefined") {
    // RANGE is declared with let in core.js after this pack lands.
    try { /* eslint-disable no-global-assign */ } catch {}
  }
  if (typeof window !== "undefined") {
    // Assign through the binding in core.js
  }
  const prev = typeof RANGE !== "undefined" ? RANGE : "3mo";
  if (span === prev && !(opts && opts.force)) {
    drawRangeChips();
    return;
  }
  // core.js exposes setRangeBinding when available
  if (typeof setRangeBinding === "function") setRangeBinding(span);
  try { localStorage.setItem(RANGE_KEY, span); } catch {}
  if (typeof chartMemo !== "undefined" && chartMemo.clear) chartMemo.clear();
  drawRangeChips();
  if (opts && opts.quiet) return;
  if (typeof state !== "undefined" && state.chartSymbol && typeof loadChart === "function") {
    loadChart(state.chartSymbol);
  }
}

function drawRangeChips() {
  const box = document.getElementById("rangeChips");
  if (!box) return;
  const cur = typeof RANGE !== "undefined" ? RANGE : "3mo";
  if (!box.dataset.bound) {
    box.dataset.bound = "1";
    box.textContent = "";
    for (const span of ALLOWED_CLIENT_RANGES) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ghost-btn";
      b.dataset.range = span;
      b.textContent = span;
      b.title = "Redraw this chart over " + (typeof SPAN_WORDS !== "undefined" && SPAN_WORDS[span] ? SPAN_WORDS[span].toLowerCase() : span)
        + ". Tables still use their own scan windows.";
      b.addEventListener("click", () => setChartRange(span));
      box.append(b);
    }
  }
  for (const b of box.querySelectorAll("button[data-range]")) {
    b.setAttribute("aria-pressed", String(b.dataset.range === cur));
  }
}

function wireReminderForm() {
  const form = document.getElementById("reminderForm");
  if (!form || form.dataset.bound) return;
  form.dataset.bound = "1";
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const date = document.getElementById("reminderDate");
    const note = document.getElementById("reminderNote");
    const sym = typeof state !== "undefined" && state.data ? state.data.symbol : null;
    if (!sym || !date || !date.value) return;
    addReminder(sym, date.value, note ? note.value : "");
    if (note) note.value = "";
    drawRemindersInbox();
    if (typeof setStatus === "function") setStatus("Reminder saved for " + sym);
  });
}

function desksuggestOnChart(d) {
  drawChanceOnChart();
  drawPseEdgeLink(d);
  drawThinBookHero(d);
  drawRangeChips();
  wireReminderForm();
  const form = document.getElementById("reminderForm");
  if (form) form.hidden = !d;
  if (typeof deskpackOnChart === "function") deskpackOnChart(d);
}

function desksuggestOnDesk(digest, packet, recentRows) {
  if (digest && digest.pseSession) drawPseSessionChip(digest.pseSession);
  drawDigestUnderBadge(digest);
  drawPacketDiff(packet);
  drawPhUstSpreadChip(recentRows || (packet && packet.recentSample) || []);
  drawRemindersInbox();
  drawLayoutControls();
  const link = document.getElementById("digestTextLink");
  if (link) {
    link.hidden = false;
    link.href = "/api/digest?format=text";
    link.download = "digest.txt";
  }
  if (typeof deskpackOnDesk === "function") {
    deskpackOnDesk(digest, packet, recentRows || []);
  }
}

function desksuggestBoot() {
  drawColumnPresets();
  drawRangeChips();
  drawLayoutControls();
  try {
    const saved = localStorage.getItem(RANGE_KEY);
    if (saved && ALLOWED_CLIENT_RANGES.includes(saved) && saved !== "3mo"
        && typeof setRangeBinding === "function") {
      setRangeBinding(saved);
      drawRangeChips();
    }
  } catch {}
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", desksuggestBoot);
  } else {
    // Scripts at end of body — DOM is ready.
    setTimeout(desksuggestBoot, 0);
  }
}

if (typeof module !== "undefined") {
  module.exports = {
    formatCountdown, pseSessionChip, thinBookWarn, pseEdgeUrl, phUstSpread,
    fundPeerLadder, packetDayDiff, watchLabelCounts, CHANCE_LINE, THIN_BOOK_PHP,
    WATCH_COLUMN_PRESETS,
  };
}
