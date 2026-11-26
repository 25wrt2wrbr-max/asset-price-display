"use strict";

/* Morning desk extras (2026-11-24): triage band, freshness chips, watch notes/
   flags/groups, label-flip rings, saved compare sets, journal line, six-pack,
   pullback/volume inbox, watchlist 1W/1M stats. Pure helpers sit at the top so
   tests can call them; UI wiring is at the bottom. Nothing here changes
   trend.classify — every tag still describes the same bars. */

const DESK_META_KEY = "apd-watch-meta";
const DESK_SETS_KEY = "apd-compare-sets";
const DESK_PACK_KEY = "apd-six-pack";
const DESK_FLIP_KEY = "apd-label-flip";
const DESK_INBOX_KEY = "apd-watch-inbox";
const DESK_GROUP_KEY = "apd-watch-group";
const FLAG_COLORS = ["", "red", "amber", "green", "blue"];

/* ---- pure helpers ------------------------------------------------------ */

function quoteFreshness(data) {
  if (!data) return { kind: "unknown", text: "—", title: "No reading yet" };
  if (data.cached) {
    return {
      kind: "disk",
      text: "saved copy",
      title: data.fetchedAt
        ? "Stored copy from " + (typeof retrievedAt === "function" ? retrievedAt(data.fetchedAt) : data.fetchedAt)
        : "Stored copy — source did not answer this read",
    };
  }
  if (Number.isFinite(data.staleDays)) {
    return {
      kind: "stale",
      text: "not updating",
      title: `Newest bar is ${data.staleDays === 1 ? "1 day" : data.staleDays + " days"} old`
        + (data.staleBar ? ` (${data.staleBar})` : ""),
    };
  }
  const basis = data.lastBarBasis;
  if (basis === "live" || basis === "pre" || basis === "after") {
    const word = basis === "live" ? "live" : basis === "pre" ? "pre-market" : "after-hours";
    return {
      kind: "live",
      text: word,
      title: (data.source ? "via " + data.source + " · " : "") + "Newest bar is still moving (" + word + ")",
    };
  }
  if (basis === "close" || !basis) {
    return {
      kind: "settled",
      text: data.source === "PSE Edge" ? "delayed" : "settled",
      title: (data.source ? "via " + data.source + " · " : "")
        + (data.source === "PSE Edge"
          ? "PSE Edge backup — about a day behind, unadjusted"
          : "Session close on the chart"),
    };
  }
  return {
    kind: "settled",
    text: String(basis),
    title: data.source ? "via " + data.source : "Chart reading",
  };
}

// Parsed once and kept: every rail row asked for it 2-3 times per redraw,
// and each ask re-read and re-parsed the whole blob from storage. A save
// here or in another tab (the storage event) replaces the kept copy.
let watchMetaMemo = null;

function loadWatchMeta() {
  if (watchMetaMemo) return watchMetaMemo;
  try {
    const raw = JSON.parse(localStorage.getItem(DESK_META_KEY) || "{}");
    watchMetaMemo = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  } catch { watchMetaMemo = {}; }
  return watchMetaMemo;
}

function saveWatchMeta(map) {
  watchMetaMemo = map;
  try { localStorage.setItem(DESK_META_KEY, JSON.stringify(map)); } catch {}
}

if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("storage", (e) => { if (!e.key || e.key === DESK_META_KEY) watchMetaMemo = null; });
}

function metaKey(symbol) {
  return String(symbol || "").trim().toUpperCase();
}

function getWatchMeta(symbol) {
  const all = loadWatchMeta();
  const row = all[metaKey(symbol)] || {};
  return {
    note: typeof row.note === "string" ? row.note : "",
    flag: FLAG_COLORS.includes(row.flag) ? row.flag : "",
    group: typeof row.group === "string" ? row.group.slice(0, 24) : "",
  };
}

function setWatchMeta(symbol, patch) {
  const all = loadWatchMeta();
  const key = metaKey(symbol);
  const cur = getWatchMeta(symbol);
  const next = {
    note: patch.note != null ? String(patch.note).slice(0, 280) : cur.note,
    flag: patch.flag != null ? (FLAG_COLORS.includes(patch.flag) ? patch.flag : "") : cur.flag,
    group: patch.group != null ? String(patch.group).slice(0, 24) : cur.group,
  };
  if (!next.note && !next.flag && !next.group) delete all[key];
  else all[key] = next;
  saveWatchMeta(all);
  return next;
}

function periodStats(values) {
  const nums = (values || []).filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (!nums.length) return null;
  const mid = Math.floor(nums.length / 2);
  const median = nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
  return { min: nums[0], max: nums[nums.length - 1], median, n: nums.length };
}

function watchlistPeriodStats(watch, quotes) {
  const buckets = { "1W": [], "1M": [] };
  for (const item of watch || []) {
    const q = quotes && quotes[item.symbol];
    const pts = q && q.data && q.data.points;
    if (!pts || typeof periodChanges !== "function") continue;
    const periods = periodChanges(pts);
    if (!periods) continue;
    for (const p of periods.periods) {
      if (p.pct != null && buckets[p.name]) buckets[p.name].push(p.pct);
    }
  }
  return {
    "1W": periodStats(buckets["1W"]),
    "1M": periodStats(buckets["1M"]),
  };
}

function journalText(data, nowIso) {
  if (!data) return "";
  const t = data.trend || {};
  const phrase = typeof badgePhrase === "function" ? badgePhrase(t)
    : (t.label ? String(t.label).charAt(0).toUpperCase() + String(t.label).slice(1) : "—");
  const plain = typeof plainReading === "function" ? (plainReading(t) || "") : "";
  const since = t.since || "";
  const run = t.run;
  const last = data.points && data.points.length ? data.points[data.points.length - 1] : null;
  const lastC = last && Number.isFinite(last.c) ? last.c : null;
  const when = nowIso || new Date().toISOString().replace(/\.\d+Z$/, "Z");
  const note = typeof getWatchMeta === "function" ? (getWatchMeta(data.symbol).note || "") : "";
  const conf = t.held ? "holding" : (t.confidence || t.strength || "");
  const lines = [
    data.symbol + (data.name ? " — " + data.name : ""),
    "Trend: " + phrase + (conf ? ` (${conf})` : ""),
    plain ? "Reading: " + plain : "",
    since ? "Since: " + since + (Number.isFinite(run) ? ` (${run} bars)` : "") : "",
    lastC != null
      ? "Last: " + (typeof formatPrice === "function" ? formatPrice(lastC, data) : String(lastC))
      : "",
    note ? "Note: " + note : "",
    "As of: " + when,
    "Chart read only — not investment advice.",
  ];
  return lines.filter(Boolean).join("\n");
}

function labelFlipArmed() {
  try { return localStorage.getItem(DESK_FLIP_KEY) !== "0"; } catch { return true; }
}

function setLabelFlipArmed(on) {
  try { localStorage.setItem(DESK_FLIP_KEY, on ? "1" : "0"); } catch {}
}

function watchInboxMode() {
  try { return localStorage.getItem(DESK_INBOX_KEY) === "1"; } catch { return false; }
}

function setWatchInboxMode(on) {
  try { localStorage.setItem(DESK_INBOX_KEY, on ? "1" : "0"); } catch {}
}

function watchGroupFilter() {
  try { return localStorage.getItem(DESK_GROUP_KEY) || ""; } catch { return ""; }
}

function setWatchGroupFilter(g) {
  try { localStorage.setItem(DESK_GROUP_KEY, g || ""); } catch {}
}

function rowInInbox(data) {
  if (!data || !data.trend) return false;
  const t = data.trend;
  if (t.pullback && (t.label === "bullish" || t.label === "bearish")) return true;
  if (typeof volumeSpike === "function" && volumeSpike(typeof chartVolumes === "function"
    ? chartVolumes(data) : (data.volumes || data.barVolumes || []))) return true;
  if (typeof windowExtreme === "function"
      && windowExtreme((data.points || []).map((p) => p.c))) return true;
  return false;
}

function loadCompareSets() {
  try {
    const raw = JSON.parse(localStorage.getItem(DESK_SETS_KEY) || "[]");
    return Array.isArray(raw) ? raw.filter((s) => s && typeof s.name === "string"
      && Array.isArray(s.symbols) && s.symbols.length) : [];
  } catch { return []; }
}

function saveCompareSets(list) {
  try { localStorage.setItem(DESK_SETS_KEY, JSON.stringify(list.slice(0, 20))); } catch {}
}

const SIX_PACK_CAP = 24;
const SIX_PACK_PAGE = 6;

function loadSixPack() {
  try {
    const raw = JSON.parse(localStorage.getItem(DESK_PACK_KEY) || "[]");
    return Array.isArray(raw)
      ? raw.map((s) => String(s || "").trim()).filter(Boolean).slice(0, SIX_PACK_CAP)
      : [];
  } catch { return []; }
}

function saveSixPack(syms) {
  const clean = [...new Set((syms || []).map((s) => String(s || "").trim()).filter(Boolean))]
    .slice(0, SIX_PACK_CAP);
  try { localStorage.setItem(DESK_PACK_KEY, JSON.stringify(clean)); } catch {}
  return clean;
}

/* ---- morning triage ---------------------------------------------------- */

let deskDigest = null;

let deskPacket = null;
let deskSectors = null;

let deskInView = true;   // section sits at the top; IO may clear this after scroll

async function loadMorningDesk() {
  try {
    deskDigest = await requestJSON("/api/digest");
  } catch {
    deskDigest = null;
  }
  if (typeof loadOfflinePacket === "function") {
    try { deskPacket = await loadOfflinePacket(); } catch { deskPacket = null; }
  }
  // Reuse the sectors table's last payload when the main poll already has it —
  // avoids a second /api/sectors round-trip on the same 15-minute clock.
  if (typeof loadSectors === "function" && loadSectors.last) {
    deskSectors = loadSectors.last;
  } else {
    try {
      deskSectors = await requestJSON("/api/sectors");
    } catch { /* sectors optional for the ribbon */ }
  }
  drawMorningDesk();
}

function drawMorningDesk(recentPayload) {
  const root = document.getElementById("morningDesk");
  if (!root) return;
  const healthBox = document.getElementById("triageHealth");
  const turnsBox = document.getElementById("triageTurns");
  const watchBox = document.getElementById("triageWatch");
  const summary = document.getElementById("triageSummary");
  if (!healthBox || !turnsBox || !watchBox || !summary) return;

  const health = (recentPayload && recentPayload.health)
    || (deskDigest && deskDigest.marketHealth) || [];
  healthBox.textContent = "";
  if (health.length) {
    const title = document.createElement("h3");
    title.className = "health-title";
    title.textContent = "Market health";
    const legend = document.createElement("span");
    legend.className = "health-legend";
    legend.append(glanceSpan("t-up", "▲ bullish"), glanceSpan("t-down", "▼ bearish"), glanceSpan("t-muted", "● neutral"));
    title.append(legend);
    healthBox.append(title);
    for (const m of health) {
      const row = document.createElement("div");
      row.className = "health-row";
      const name = document.createElement("span");
      name.className = "health-market";
      name.textContent = m.market;
      const bar = document.createElement("span");
      bar.className = "health-bar";
      bar.setAttribute("role", "img");
      bar.setAttribute("aria-label", typeof healthText === "function" ? healthText(m) : "");
      for (const [key] of (typeof HEALTH_PARTS !== "undefined" ? HEALTH_PARTS : [["bullish"], ["bearish"], ["neutral"]])) {
        const n = m[key] || 0;
        if (!n || !m.judged) continue;
        const seg = document.createElement("span");
        seg.className = "health-seg seg-" + key;
        seg.style.flexGrow = String(n);
        bar.append(seg);
      }
      const nums = document.createElement("span");
      nums.className = "health-nums";
      if (typeof healthPieces === "function") {
        const pieces = healthPieces(m);
        for (const p of pieces.parts) nums.append(glanceSpan("t-" + p.tone, p.text));
        nums.append(glanceSpan("health-of", "/" + pieces.of));
        nums.title = pieces.title;
        row.title = pieces.title;
      } else {
        nums.textContent = typeof healthText === "function" ? healthText(m) : `${m.bullish}▲ ${m.bearish}▼`;
      }
      row.append(name, bar, nums);
      healthBox.append(row);
    }
  } else {
    const p = document.createElement("p");
    p.className = "watch-hint";
    p.textContent = "Market health loads with the recent scan.";
    healthBox.append(p);
  }

  const turns = (deskDigest && deskDigest.freshTurns) || [];
  turnsBox.textContent = "";
  const turnsTitle = document.createElement("h3");
  turnsTitle.className = "triage-sub";
  turnsTitle.textContent = turns.length ? `Fresh turns (${turns.length})` : "Fresh turns";
  turnsBox.append(turnsTitle);
  if (!turns.length) {
    const p = document.createElement("p");
    p.className = "watch-hint";
    p.textContent = "None in the last scan.";
    p.title = "No name turned on its newest bar in the last scan.";
    turnsBox.append(p);
  } else {
    const ul = document.createElement("ul");
    ul.className = "triage-list";
    for (const t of turns.slice(0, 10)) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "triage-chip " + (t.direction || "");
      btn.textContent = `${t.ticker || t.symbol} ${t.direction === "bearish" ? "▼" : "▲"}`;
      btn.title = `${t.market || ""} · ${t.direction}`;
      const sym = t.symbol;
      btn.addEventListener("click", () => { if (sym && typeof loadChart === "function") loadChart(sym); });
      li.append(btn);
      ul.append(li);
    }
    turnsBox.append(ul);
  }

  drawTriageWatch(watchBox);
  const fullSummary = (deskDigest && deskDigest.summary)
    || (recentPayload && recentPayload.note)
    || "Waiting for the first scan…";
  const pills = typeof summaryPills === "function" ? summaryPills(deskDigest) : [];
  if (pills.length) {
    drawGlancePills(summary, pills);
    summary.classList.add("glance-pills");
    summary.setAttribute("role", "group");
  } else {
    summary.classList.remove("glance-pills");
    summary.removeAttribute("role");
    summary.textContent = fullSummary;
  }
  summary.title = fullSummary;
  summary.setAttribute("aria-label", fullSummary);
  const markets = (recentPayload && recentPayload.markets)
    || (deskDigest && deskDigest.markets) || [];
  if (typeof drawStalenessStrip === "function") drawStalenessStrip(markets);
  if (typeof drawYieldCurveChip === "function") {
    drawYieldCurveChip((recentPayload && recentPayload.rows)
      || (deskPacket && deskPacket.recentSample) || []);
  }
  if (typeof drawSweepPresets === "function") drawSweepPresets();
  if (typeof drawCompareHealthBoard === "function") drawCompareHealthBoard();
  if (typeof drawAgainstMarketStrip === "function") drawAgainstMarketStrip();
  if (typeof drawMorningRibbon === "function") {
    drawMorningRibbon(deskSectors, recentPayload || { rows: (deskPacket && deskPacket.recentSample) || [] });
  }
  if (typeof drawPacketStamp === "function") {
    drawPacketStamp(deskPacket || (deskDigest && { generatedAt: deskDigest.generatedAt, fromDisk: !deskDigest.online }));
  }
  if (typeof desksuggestOnDesk === "function") {
    const rows = (recentPayload && recentPayload.rows)
      || (deskPacket && deskPacket.recentSample) || [];
    desksuggestOnDesk(deskDigest, deskPacket, rows);
  }
  root.hidden = false;
}

/* Only the "Watched" column: used when the rail redraws so health and
   fresh-turns are not rebuilt from scratch every quote tick. */
function drawTriageWatch(watchBox) {
  const box = watchBox || document.getElementById("triageWatch");
  if (!box) return;
  box.textContent = "";
  const wTitle = document.createElement("h3");
  wTitle.className = "triage-sub";
  box.append(wTitle);
  const changeList = document.getElementById("watchChangeList");
  const flips = changeList ? changeList.querySelectorAll("li").length : 0;
  const n = (typeof state !== "undefined" && state.watch) ? state.watch.length : 0;
  wTitle.textContent = n ? `Watched (${n})` : "Watched";
  if (flips) {
    const badge = glanceSpan("glance-badge", `${flips} changed`);
    badge.title = `${flips} badge change${flips === 1 ? "" : "s"} since last visit`;
    wTitle.append(" ", badge);
  }
  if (!n) {
    const p = document.createElement("p");
    p.className = "watch-hint";
    p.textContent = "Add symbols from a chart to fill this strip.";
    box.append(p);
  }
  if (typeof state !== "undefined" && state.watch && state.watch.length) {
    const ul = document.createElement("ul");
    ul.className = "triage-list";
    for (const item of state.watch.slice(0, 8)) {
      const q = state.watchQuotes[item.symbol];
      const t = q && q.data && q.data.trend;
      const phrase = t && typeof badgePhrase === "function" ? badgePhrase(t) : (t && t.label) || "…";
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      const look = typeof watchChipParts === "function" ? watchChipParts(t) : { tone: "none", lean: "" };
      btn.className = "triage-chip watch-chip tone-" + look.tone;
      const pct = q && Number.isFinite(q.pct) ? q.pct : null;
      // Shape as well as colour, so the label reads without colour vision.
      btn.append(glanceSpan("watch-chip-mark", look.mark), glanceSpan("watch-chip-sym", item.symbol.split(":").pop()));
      if (look.lean) btn.append(glanceSpan("watch-chip-lean", look.lean));
      if (pct != null) btn.append(glanceSpan("watch-chip-pct " + (pct >= 0 ? "t-up" : "t-down"), glanceSigned(pct, 1)));
      btn.title = `${item.symbol} · ${phrase}` + (pct != null ? ` · ${glanceSigned(pct, 1)}` : "");
      btn.setAttribute("aria-label", btn.title);
      btn.addEventListener("click", () => loadChart(item.symbol));
      li.append(btn);
      ul.append(li);
    }
    box.append(ul);
  }
}

/* ---- label-flip ring (browser) ----------------------------------------- */

function ringLabelFlip(symbol, prior, current) {
  if (!labelFlipArmed()) return;
  const text = `${symbol}: ${prior} → ${current}`;
  try {
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      const n = new Notification("Trend change: " + symbol, { body: text, tag: "apd-flip-" + symbol });
      n.onclick = () => { window.focus(); loadChart(symbol); n.close(); };
    }
  } catch {}
  const banner = document.getElementById("alarmBanner");
  if (banner) {
    const p = document.createElement("p");
    p.className = "alarm-ring";
    p.textContent = "↻ " + text + " ";
    const ok = document.createElement("button");
    ok.type = "button"; ok.className = "ghost-btn"; ok.textContent = "Dismiss";
    ok.addEventListener("click", () => { p.remove(); banner.hidden = !banner.children.length; });
    p.append(ok);
    banner.append(p);
    banner.hidden = false;
  }
  try {
    if (typeof alarmAudio !== "undefined" && alarmAudio) {
      if (alarmAudio.state === "suspended") alarmAudio.resume();
      const osc = alarmAudio.createOscillator(), gain = alarmAudio.createGain();
      osc.frequency.value = 660;
      gain.gain.value = 0.1;
      osc.connect(gain).connect(alarmAudio.destination);
      osc.start(); osc.stop(alarmAudio.currentTime + 0.15);
    }
  } catch {}
}

function noteWatchLabelFlip(symbol, prior, current) {
  if (!prior || !current || prior === current) return;
  ringLabelFlip(symbol, prior, current);
}

/* ---- watchlist chrome: freshness, flags, inbox, stats ------------------ */

function appendFreshnessChip(parent, data, symbol) {
  const f = quoteFreshness(data);
  const chip = document.createElement("span");
  chip.className = "fresh-chip kind-" + f.kind;
  chip.textContent = f.text;
  chip.title = f.title + (data && data.source ? "" : "");
  if (data && data.source) chip.title = f.title;
  // Stale / disk chips open that chart and force a fresh read.
  if ((f.kind === "stale" || f.kind === "disk") && symbol && typeof loadChart === "function") {
    chip.classList.add("is-clickable");
    chip.title = (chip.title || f.title) + " · Click to open and refresh.";
    chip.setAttribute("role", "button");
    chip.tabIndex = 0;
    const go = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      loadChart(symbol);
    };
    chip.addEventListener("click", go);
    chip.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") go(ev);
    });
  }
  parent.append(chip);
  return chip;
}

function appendFlagDot(parent, symbol) {
  const meta = getWatchMeta(symbol);
  if (!meta.flag) return null;
  const dot = document.createElement("span");
  dot.className = "flag-dot flag-" + meta.flag;
  dot.title = "Flag: " + meta.flag;
  dot.setAttribute("aria-hidden", "true");
  parent.append(dot);
  return dot;
}

function drawWatchMetaEditor(symbol) {
  const box = document.getElementById("watchMetaBox");
  if (!box) return;
  if (!symbol) { box.hidden = true; box.textContent = ""; return; }
  // A quiet chart re-read must not wipe a note being typed: the text is
  // saved on "change", which never fires for a field that was removed.
  if (box.dataset.symbol === symbol && box.contains(document.activeElement)) return;
  box.dataset.symbol = symbol;
  const meta = getWatchMeta(symbol);
  box.hidden = false;
  box.textContent = "";
  const head = document.createElement("div");
  head.className = "watch-meta-head";
  head.textContent = "Note & flag · " + symbol;
  const flags = document.createElement("div");
  flags.className = "flag-row";
  flags.setAttribute("role", "group");
  flags.setAttribute("aria-label", "Color flag");
  for (const c of FLAG_COLORS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "flag-btn" + (c ? " flag-" + c : " flag-none") + (meta.flag === c ? " is-on" : "");
    b.title = c || "No flag";
    b.setAttribute("aria-pressed", String(meta.flag === c));
    b.addEventListener("click", () => {
      setWatchMeta(symbol, { flag: c });
      drawWatchMetaEditor(symbol);
      if (typeof drawWatchList === "function") drawWatchList();
    });
    flags.append(b);
  }
  const group = document.createElement("input");
  group.type = "text";
  group.className = "watch-group-input";
  group.placeholder = "Group (e.g. PH, US, crypto)";
  group.value = meta.group;
  group.maxLength = 24;
  group.addEventListener("change", () => {
    setWatchMeta(symbol, { group: group.value.trim() });
    fillGroupFilter();
    if (typeof drawWatchList === "function") drawWatchList();
  });
  const note = document.createElement("textarea");
  note.className = "watch-note-input";
  note.rows = 2;
  note.placeholder = "Why is this on the list?";
  note.value = meta.note;
  note.maxLength = 280;
  note.addEventListener("change", () => {
    setWatchMeta(symbol, { note: note.value.trim() });
  });
  box.append(head, flags, group, note);
}

function fillGroupFilter() {
  const sel = document.getElementById("watchGroupFilter");
  if (!sel) return;
  // Quote ticks call this often; leave an open <select> alone, and skip a
  // rebuild when the group set has not changed.
  if (document.activeElement === sel) return;
  const cur = watchGroupFilter();
  const groups = new Set();
  for (const item of (state.watch || [])) {
    const g = getWatchMeta(item.symbol).group;
    if (g) groups.add(g);
  }
  const sorted = [...groups].sort();
  const sig = sorted.join("\0") + "\0" + cur;
  if (sig === fillGroupFilter.sig && sel.options.length === sorted.length + 1) return;
  fillGroupFilter.sig = sig;
  sel.textContent = "";
  sel.append(new Option("All groups", ""));
  for (const g of sorted) sel.append(new Option(g, g));
  sel.value = groups.has(cur) || cur === "" ? cur : "";
}

function watchItemVisible(item, quote) {
  const g = watchGroupFilter();
  if (g && getWatchMeta(item.symbol).group !== g) return false;
  if (watchInboxMode()) {
    const data = quote && quote.data;
    if (!data || !rowInInbox(data)) return false;
  }
  return true;
}

function drawWatchStats() {
  const box = document.getElementById("watchStats");
  if (!box) return;
  const stats = watchlistPeriodStats(state.watch, state.watchQuotes);
  box.textContent = "";
  const parts = [];
  for (const name of ["1W", "1M"]) {
    const s = stats[name];
    if (!s) continue;
    parts.push(`${name} min ${signedPct(s.min)} · med ${signedPct(s.median)} · max ${signedPct(s.max)} (n=${s.n})`);
  }
  if (typeof watchLabelCounts === "function") {
    const { counts, median, n } = watchLabelCounts(state.watch, state.watchQuotes);
    if (n) {
      parts.push(`▲${counts.bullish} ▼${counts.bearish} ·${counts.neutral}`
        + (Number.isFinite(median) ? ` · day med ${signedPct(median)}` : ""));
    }
  }
  if (!parts.length) { box.hidden = true; return; }
  box.hidden = false;
  box.textContent = parts.join(" · ");
  box.title = "Across watchlist rows with a fresh reading — describes the list now, predicts nothing.";
}

/* ---- six-pack ---------------------------------------------------------- */

function drawSixPack() {
  const wrap = document.getElementById("sixPackWrap");
  const grid = document.getElementById("sixPack");
  const nav = document.getElementById("sixPackNav");
  const pageLabel = document.getElementById("sixPackPageLabel");
  if (!grid) return;
  const syms = loadSixPack();
  grid.textContent = "";
  if (!syms.length) {
    if (wrap) wrap.hidden = true;
    grid.hidden = true;
    if (nav) nav.hidden = true;
    return;
  }
  if (wrap) wrap.hidden = false;
  grid.hidden = false;
  const pages = Math.max(1, Math.ceil(syms.length / SIX_PACK_PAGE));
  let page = typeof sixPackPage === "function" ? sixPackPage() : 0;
  if (page >= pages) page = pages - 1;
  if (typeof setSixPackPage === "function") setSixPackPage(page);
  const start = page * SIX_PACK_PAGE;
  const slice = syms.slice(start, start + SIX_PACK_PAGE);
  for (let i = 0; i < SIX_PACK_PAGE; i++) {
    const slot = document.createElement("div");
    slot.className = "six-slot";
    const sym = slice[i];
    if (!sym) {
      slot.classList.add("is-empty");
      slot.textContent = "Empty";
      grid.append(slot);
      continue;
    }
    const q = state.watchQuotes[sym] || (state.data && state.data.symbol === sym ? { data: state.data, ...quoteSummary(state.data) } : null);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "six-open";
    const top = document.createElement("span");
    top.className = "six-sym";
    top.textContent = sym;
    const mid = document.createElement("span");
    mid.className = "six-price";
    if (q && q.data) mid.textContent = formatPrice(q.price != null ? q.price : q.data.points[q.data.points.length - 1].c, q.data);
    else mid.textContent = "…";
    const tag = document.createElement("span");
    tag.className = "six-tag";
    const t = q && q.data && q.data.trend;
    tag.textContent = t && typeof badgePhrase === "function" ? badgePhrase(t) : "—";
    if (t && t.label) tag.classList.add(t.label);
    btn.append(top, mid, tag);
    btn.addEventListener("click", () => loadChart(sym));
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "six-rm";
    rm.textContent = "×";
    rm.setAttribute("aria-label", "Remove " + sym + " from six-pack");
    rm.addEventListener("click", (ev) => {
      ev.stopPropagation();
      saveSixPack(loadSixPack().filter((s) => s.toUpperCase() !== sym.toUpperCase()));
      drawSixPack();
    });
    slot.append(btn, rm);
    grid.append(slot);
  }
  if (nav && pageLabel) {
    nav.hidden = pages <= 1;
    pageLabel.textContent = `Page ${page + 1} of ${pages}`;
  }
}

function pinToSixPack(symbol) {
  if (!symbol) return;
  const list = loadSixPack();
  const key = symbol.trim().toUpperCase();
  if (list.some((s) => s.toUpperCase() === key)) return;
  if (list.length >= SIX_PACK_CAP) list.shift();
  list.push(symbol.trim());
  saveSixPack(list);
  // Jump to the page that holds the new pin.
  if (typeof setSixPackPage === "function") {
    setSixPackPage(Math.floor((list.length - 1) / SIX_PACK_PAGE));
  }
  drawSixPack();
  if (typeof setStatus === "function") setStatus("Pinned " + symbol + " to the six-pack strip.");
}

/* ---- compare sets + journal -------------------------------------------- */

function renderSavedCompareSets() {
  const box = document.getElementById("compareSets");
  if (!box) return;
  box.textContent = "";
  const sets = loadCompareSets();
  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "ghost-btn";
  saveBtn.textContent = "Save this compare";
  saveBtn.title = "Store the chart plus peers as a named set in this browser";
  saveBtn.addEventListener("click", () => {
    if (typeof comparePrimary === "undefined" || !comparePrimary) {
      if (typeof setStatus === "function") setStatus("Open a chart first.", true);
      return;
    }
    const name = window.prompt("Name for this compare set:", comparePrimary.symbol + " set");
    if (!name || !name.trim()) return;
    const symbols = [comparePrimary.symbol];
    if (typeof comparePeers !== "undefined") {
      for (const p of comparePeers) {
        const s = (p.data && p.data.symbol) || p.wanted;
        if (s) symbols.push(s);
      }
    }
    const list = loadCompareSets().filter((s) => s.name !== name.trim());
    list.unshift({ name: name.trim().slice(0, 40), symbols: symbols.slice(0, 6), base: compareBase || null });
    saveCompareSets(list);
    renderSavedCompareSets();
  });
  box.append(saveBtn);
  for (const set of sets) {
    const row = document.createElement("span");
    row.className = "compare-set-row";
    const go = document.createElement("button");
    go.type = "button";
    go.className = "compare-preset";
    go.textContent = set.name;
    go.title = set.symbols.join(", ");
    go.addEventListener("click", async () => {
      const [primary, ...peers] = set.symbols;
      if (!primary) return;
      await loadChart(primary);
      if (typeof comparePeers !== "undefined") {
        comparePeers = [];
        compareBase = set.base || null;
      }
      for (const peer of peers) {
        if (typeof loadComparison === "function") await loadComparison(peer, {
          asBase: set.base && String(set.base).toUpperCase() === String(peer).toUpperCase(),
        });
      }
    });
    const del = document.createElement("button");
    del.type = "button";
    del.className = "watch-io-btn";
    del.textContent = "×";
    del.setAttribute("aria-label", "Delete compare set " + set.name);
    del.addEventListener("click", () => {
      saveCompareSets(loadCompareSets().filter((s) => s.name !== set.name));
      renderSavedCompareSets();
    });
    row.append(go, del);
    box.append(row);
  }
}

async function copyJournal() {
  const text = journalText(state.data);
  if (!text) {
    if (typeof setStatus === "function") setStatus("Load a chart first.", true);
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    if (typeof setStatus === "function") setStatus("Copied journal line to the clipboard.");
  } catch {
    // Fallback: select a hidden textarea
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.append(ta);
    ta.select();
    try { document.execCommand("copy"); setStatus("Copied journal line to the clipboard."); }
    catch { setStatus("Could not copy — select and copy from the console.", true); console.log(text); }
    ta.remove();
  }
}

/* ---- alarm shortcuts --------------------------------------------------- */

function alarmShortcutTargets(data) {
  if (!data || !data.points || data.points.length < 2) return [];
  const pts = data.points.filter((p) => p && Number.isFinite(p.c));
  if (pts.length < 2) return [];
  const last = pts[pts.length - 1].c;
  const closes = pts.map((p) => p.c);
  const hi = Math.max(...closes), lo = Math.min(...closes);
  const mean20 = closes.slice(-20).reduce((a, b) => a + b, 0) / Math.min(20, closes.length);
  return [
    { label: "Last", value: last },
    { label: "3M high", value: hi },
    { label: "3M low", value: lo },
    { label: "20-bar mean", value: mean20 },
  ].filter((t) => Number.isFinite(t.value) && t.value > 0);
}

function drawAlarmShortcuts() {
  const row = document.getElementById("alarmShortcuts");
  if (!row) return;
  row.textContent = "";
  const targets = alarmShortcutTargets(state.data);
  row.hidden = !targets.length;
  for (const t of targets) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ghost-btn alarm-shortcut";
    b.textContent = t.label;
    b.title = "Set price alarm at " + (typeof formatPrice === "function" ? formatPrice(t.value, state.data) : t.value);
    b.addEventListener("click", () => {
      const input = document.getElementById("alarmPrice");
      if (input) input.value = t.value.toFixed(typeof digitsFor === "function" ? digitsFor(state.data) : 2);
      if (typeof addAlarm === "function" && state.data) {
        try {
          if (typeof Notification !== "undefined" && Notification.permission === "default") Notification.requestPermission();
        } catch {}
        try { if (typeof alarmAudio !== "undefined" && !alarmAudio) alarmAudio = new (window.AudioContext || window.webkitAudioContext)(); } catch {}
        addAlarm(state.data, t.value);
        drawAlarms();
        document.getElementById("alarmNote").textContent = `Alarm set at ${formatPrice(t.value, state.data)}.`;
      }
    });
    row.append(b);
  }
}

/* ---- bind UI ----------------------------------------------------------- */

function bindDesk() {
  const flip = document.getElementById("labelFlipToggle");
  if (flip) {
    flip.checked = labelFlipArmed();
    flip.addEventListener("change", () => {
      setLabelFlipArmed(flip.checked);
      try {
        if (flip.checked && typeof Notification !== "undefined" && Notification.permission === "default") {
          Notification.requestPermission();
        }
      } catch {}
    });
  }
  const inbox = document.getElementById("watchInboxToggle");
  if (inbox) {
    inbox.checked = watchInboxMode();
    inbox.addEventListener("change", () => {
      setWatchInboxMode(inbox.checked);
      if (typeof drawWatchList === "function") drawWatchList();
    });
  }
  const group = document.getElementById("watchGroupFilter");
  if (group) {
    group.addEventListener("change", () => {
      setWatchGroupFilter(group.value);
      if (typeof drawWatchList === "function") drawWatchList();
    });
  }
  const journal = document.getElementById("journalBtn");
  if (journal) journal.addEventListener("click", () => copyJournal());
  const pin = document.getElementById("sixPackPin");
  if (pin) pin.addEventListener("click", () => {
    if (state.data && state.data.symbol) pinToSixPack(state.data.symbol);
  });
  fillGroupFilter();
  renderSavedCompareSets();
  drawSixPack();
  const prev = document.getElementById("sixPackPrev");
  const next = document.getElementById("sixPackNext");
  if (prev) prev.addEventListener("click", () => {
    if (typeof setSixPackPage === "function" && typeof sixPackPage === "function") {
      setSixPackPage(Math.max(0, sixPackPage() - 1));
      drawSixPack();
    }
  });
  if (next) next.addEventListener("click", () => {
    if (typeof setSixPackPage === "function" && typeof sixPackPage === "function") {
      setSixPackPage(sixPackPage() + 1);
      drawSixPack();
    }
  });
  const deskRoot = document.getElementById("morningDesk");
  if (deskRoot && typeof IntersectionObserver === "function") {
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        // While the section is still hidden (before first draw), keep polling —
        // a hidden node reports not intersecting and would starve the refresh.
        if (deskRoot.hidden) { deskInView = true; continue; }
        deskInView = e.isIntersecting;
      }
    }, { rootMargin: "160px 0px" });
    io.observe(deskRoot);
  }
  loadMorningDesk();
  setInterval(() => {
    if (!document.hidden && deskInView) loadMorningDesk();
  }, 15 * 60 * 1000);
}

function deskOnChartDrawn(live) {
  // A live tick (every 30 s while the market trades) only moves the price.
  // The note editor, pinned strip and saved compares do not change with it,
  // and rebuilding the editor mid-tick also threw away what was being typed.
  const sym = state.data && state.data.symbol;
  if (!live) {
    drawWatchMetaEditor(sym);
    renderSavedCompareSets();
  }
  // The pinned strip shows the open chart's price when it is pinned.
  if (!live || (sym && loadSixPack().some((s) => memoKey(s) === memoKey(sym)))) drawSixPack();
  drawAlarmShortcuts();
}

function deskExtrasSig() {
  const parts = [];
  for (const it of (state.watch || [])) {
    const q = state.watchQuotes[it.symbol];
    const d = q && q.data;
    const t = d && d.trend;
    const pts = d && d.points;
    const last = pts && pts.length ? pts[pts.length - 1] : null;
    parts.push([
      it.symbol,
      d && d.fetchedAt,
      t && t.label, t && t.score, t && t.pullback,
      last && last.c,
    ].join(":"));
  }
  if (state.data) {
    const t = state.data.trend || {};
    parts.push(["open", state.data.symbol, t.label, t.score].join(":"));
  }
  try {
    if (typeof loadCompareSets === "function") {
      parts.push("sets:" + loadCompareSets().map((s) => s.name + "/" + (s.symbols || []).join(",")).join("|"));
    }
  } catch (err) { /* localStorage may be blocked */ }
  // Ribbon reads deskSectors; include a light stamp so a sector refresh redraws it.
  if (typeof deskSectors !== "undefined" && deskSectors && deskSectors.rows) {
    parts.push("sec:" + deskSectors.rows.length + ":" + (deskSectors.fetchedAt || deskSectors.note || ""));
  }
  return parts.join("|");
}

function deskOnWatchDrawn() {
  fillGroupFilter();
  drawWatchStats();
  // Rail quote ticks used to rebuild the whole morning desk (health + turns
  // too). The watched strip always refreshes; six-pack / compare / against /
  // ribbon skip when their inputs have not moved.
  drawTriageWatch();
  const sig = deskExtrasSig();
  if (sig === deskOnWatchDrawn.extrasSig) return;
  deskOnWatchDrawn.extrasSig = sig;
  drawSixPack();
  if (typeof drawCompareHealthBoard === "function") drawCompareHealthBoard();
  if (typeof drawAgainstMarketStrip === "function") drawAgainstMarketStrip();
  if (typeof drawMorningRibbon === "function") {
    drawMorningRibbon(deskSectors, { rows: (deskPacket && deskPacket.recentSample) || [] });
  }
}

function deskOnRecent(payload) {
  drawMorningDesk(payload);
}
