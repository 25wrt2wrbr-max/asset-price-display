"use strict";

/* Desk extras (2026-11-25): compare-set health, staleness strip, sweep
   presets, yield-curve chip, against-market watch strip, morning ribbon,
   UITF peer drift, offline packet, turnover helper. Pure helpers first so
   tests can call them. Labels always come from existing chart payloads —
   never a second classifier. */

const DESK_PACKET_KEY = "apd-last-packet";
const DESK_PAGE_KEY = "apd-six-page";

/* ---- pure helpers ------------------------------------------------------ */

/* Mean close×volume over the last `sessions` finished bars (client mirror
   of turnover.average without a cutoff — watchlist charts are already
   settled or live; a forming last bar is still useful liquidity context). */
function watchTurnover(data, sessions) {
  const n = sessions || 5;
  if (!data || data.currency !== "PHP") return null;
  const sym = String(data.symbol || "").toUpperCase();
  if (!(sym.startsWith("PSE:") || sym.startsWith("EDGE:") || sym.endsWith(".PS"))) return null;
  const pts = data.points || [];
  const vols = typeof chartVolumes === "function" ? chartVolumes(data)
    : (data.volumes || data.barVolumes || null);
  if (!vols || !pts.length) return null;
  const picked = [];
  for (let i = Math.min(pts.length, vols.length) - 1; i >= 0; i--) {
    const c = pts[i] && pts[i].c;
    const v = vols[i];
    if (!(c > 0) || v == null || !Number.isFinite(Number(v))) continue;
    picked.push(c * Number(v));
    if (picked.length === n) break;
  }
  if (!picked.length || !picked.some((x) => x > 0)) return null;
  return picked.reduce((a, b) => a + b, 0) / picked.length;
}

/* PH02Y / PH05Y / PH10Y shape from recent-table bond rows (yield levels). */
function yieldCurveShape(rows) {
  const find = (tenor) => {
    const hit = (rows || []).find((r) => {
      const s = String(r.chartSymbol || r.symbol || "").toUpperCase();
      return s.includes(tenor);
    });
    return hit && Number.isFinite(hit.price) ? hit.price : null;
  };
  const y2 = find("PH02Y"), y5 = find("PH05Y"), y10 = find("PH10Y");
  if (y2 == null || y10 == null) return null;
  const spread = y10 - y2;
  let word = "flat";
  if (spread > 0.15) word = "steep";
  else if (spread < -0.05) word = "inverted";
  else if (spread > 0.05) word = "gently steep";
  else if (spread < 0) word = "gently inverted";
  const mid = y5 != null ? `; 5Y ${y5.toFixed(2)}%` : "";
  return {
    word,
    text: `PH curve ${word}: 2Y ${y2.toFixed(2)}% → 10Y ${y10.toFixed(2)}%${mid}`,
    spread,
    y2, y5, y10,
  };
}

/* Among watched funds sharing a category, flag top/bottom 1M movers. */
function fundPeerDrift(symbol, watch, quotes) {
  const q = quotes && quotes[symbol];
  const d = q && q.data;
  if (!d || !d.fundSeries || !d.category) return null;
  const peers = [];
  for (const item of watch || []) {
    const qd = quotes[item.symbol] && quotes[item.symbol].data;
    if (!qd || !qd.fundSeries || qd.category !== d.category) continue;
    const pts = (qd.points || []).filter((p) => p && Number.isFinite(p.c));
    if (pts.length < 2) continue;
    const found = typeof periodChanges === "function" ? periodChanges(pts) : null;
    const hit = found && found.periods.find((p) => p.name === "1M");
    if (!hit || !Number.isFinite(hit.pct)) continue;
    peers.push({ symbol: item.symbol, pct: hit.pct });
  }
  if (peers.length < 3) return null;
  peers.sort((a, b) => a.pct - b.pct);
  const me = peers.find((p) => String(p.symbol).toUpperCase() === String(symbol).toUpperCase());
  if (!me) return null;
  if (me.symbol === peers[peers.length - 1].symbol) {
    return { kind: "top", text: "top of peers (1M)", peers: peers.length, category: d.category };
  }
  if (me.symbol === peers[0].symbol) {
    return { kind: "bottom", text: "bottom of peers (1M)", peers: peers.length, category: d.category };
  }
  return null;
}

/* Markets payload → one short staleness sentence, or null when healthy. */
function marketStaleness(markets) {
  const bad = (markets || []).filter((m) =>
    m && (m.state === "offline" || m.state === "partial" || m.state === "fallback"));
  if (!bad.length) return null;
  const bits = bad.map((m) => {
    const word = m.state === "offline" ? "offline"
      : m.state === "partial" ? "partial" : "fallback";
    return `${m.market} ${word}`;
  });
  return {
    text: "Sources degraded: " + bits.join(" · ") + ". Some rows may be saved copies.",
    markets: bad,
  };
}

/* One-line against-market read from an already-loaded asset + bench payload. */
function againstMarketLine(d, benchData, pick) {
  if (!d || !benchData || !pick || typeof benchmarkReading !== "function") return null;
  const r = benchmarkReading(d, benchData);
  if (!r) return null;
  const word = r.call.label === "neutral" ? "level with"
    : r.call.label === "bullish" ? "ahead of" : "behind";
  return {
    text: `${word} ${pick.name} (${r.move >= 0 ? "+" : "−"}${Math.abs(r.move * 100).toFixed(1)}%)`,
    label: r.call.label,
    pick,
  };
}

/* ---- UI: morning extras ------------------------------------------------ */

function drawStalenessStrip(markets) {
  const strip = document.getElementById("stalenessStrip");
  if (!strip) return;
  const hit = marketStaleness(markets);
  if (!hit) { strip.hidden = true; strip.textContent = ""; return; }
  strip.hidden = false;
  strip.textContent = "";
  const p = document.createElement("p");
  p.className = "staleness-text";
  p.textContent = hit.text + " ";
  const a = document.createElement("a");
  a.href = "status.html";
  a.textContent = "Source status";
  p.append(a);
  strip.append(p);
}

function drawYieldCurveChip(rows) {
  const chip = document.getElementById("yieldCurveChip");
  if (!chip) return;
  const shape = yieldCurveShape(rows);
  if (!shape) { chip.hidden = true; chip.textContent = ""; return; }
  chip.hidden = false;
  chip.textContent = shape.text;
  chip.title = "From the three Philippine government bond yields in the recent table. Descriptive spacing only — not a composite score.";
}

function drawSweepPresets() {
  const box = document.getElementById("sweepPresets");
  if (!box || box.dataset.bound) return;
  box.dataset.bound = "1";
  box.textContent = "";
  const presets = [
    { label: "Fresh bullish", href: "#recentHeading", prep: () => {
      if (typeof recentView !== "undefined") {
        recentView.freshOnly = true;
        recentView.volSpikeOnly = false;
      }
      if (typeof tableRenderers !== "undefined" && tableRenderers.rows) tableRenderers.rows();
    }},
    { label: "Volume spikes", href: "#recentHeading", prep: () => {
      if (typeof recentView !== "undefined") {
        recentView.volSpikeOnly = true;
        recentView.freshOnly = false;
      }
      if (typeof tableRenderers !== "undefined" && tableRenderers.rows) tableRenderers.rows();
    }},
    { label: "Leaning", href: "#leaningHeading", prep: null },
    { label: "Bearish", href: "#bearishHeading", prep: null },
    { label: "Sectors", href: "#sectorHeading", prep: null },
  ];
  for (const p of presets) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ghost-btn sweep-preset preset-" + p.label.toLowerCase().replace(/\s+/g, "-");
    b.textContent = p.label;
    b.addEventListener("click", () => {
      if (p.prep) p.prep();
      const el = document.querySelector(p.href);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    box.append(b);
  }
}

function drawCompareHealthBoard() {
  const box = document.getElementById("triageCompares");
  if (!box || typeof loadCompareSets !== "function") return;
  box.textContent = "";
  box.hidden = false;
  const sets = loadCompareSets();
  const title = document.createElement("h3");
  title.className = "triage-sub";
  title.textContent = sets.length ? `Compare sets (${sets.length})` : "Compare sets";
  box.append(title);
  if (!sets.length) {
    const p = document.createElement("p");
    p.className = "watch-hint";
    p.textContent = "Save a compare under the chart to see each set's labels here.";
    box.append(p);
    box.hidden = true;     // a how-to, not data: shown once a set exists
    return;
  }
  const ul = document.createElement("ul");
  ul.className = "triage-list compare-health";
  for (const set of sets.slice(0, 6)) {
    const li = document.createElement("li");
    li.className = "compare-health-row";
    const name = document.createElement("button");
    name.type = "button";
    name.className = "triage-chip";
    name.textContent = set.name;
    name.title = set.symbols.join(", ");
    name.addEventListener("click", async () => {
      const [primary, ...peers] = set.symbols;
      if (!primary || typeof loadChart !== "function") return;
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
    const bits = document.createElement("span");
    bits.className = "compare-health-bits";
    const parts = [];
    for (const sym of set.symbols.slice(0, 6)) {
      const q = typeof state !== "undefined" && state.watchQuotes
        ? state.watchQuotes[sym] : null;
      const open = typeof state !== "undefined" && state.data
        && String(state.data.symbol).toUpperCase() === String(sym).toUpperCase()
        ? state.data : null;
      const d = (q && q.data) || open;
      const t = d && d.trend;
      const label = t && t.label ? t.label.charAt(0).toUpperCase() : "?";
      const pull = t && t.pullback ? "↩" : "";
      const fresh = d && typeof quoteFreshness === "function" ? quoteFreshness(d).text : "";
      parts.push(`${sym.split(":").pop()} ${label}${pull}${fresh ? "·" + fresh : ""}`);
    }
    bits.textContent = parts.join(" · ");
    li.append(name, bits);
    ul.append(li);
  }
  box.append(ul);
}

function drawAgainstMarketStrip() {
  const box = document.getElementById("againstStrip");
  if (!box || typeof state === "undefined" || !state.watch) return;
  box.textContent = "";
  box.hidden = false;
  const title = document.createElement("h3");
  title.className = "triage-sub";
  title.textContent = "Against their market";
  box.append(title);
  const lines = [];
  for (const item of state.watch.slice(0, 12)) {
    const q = state.watchQuotes[item.symbol];
    const d = q && q.data;
    if (!d || typeof benchmarkFor !== "function") continue;
    const pick = benchmarkFor(d);
    if (!pick) continue;
    const memo = typeof benchMemo !== "undefined" ? benchMemo.get(pick.symbol) : null;
    if (!memo || !memo.data) continue;
    const line = againstMarketLine(d, memo.data, pick);
    if (!line) continue;
    lines.push({ symbol: item.symbol, text: line.text, label: line.label });
  }
  if (!lines.length) {
    const p = document.createElement("p");
    p.className = "watch-hint";
    p.textContent = "Opens after a watched name has a benchmark reading.";
    box.append(p);
    box.hidden = true;     // empty until a benchmark reading arrives
    return;
  }
  const ul = document.createElement("ul");
  ul.className = "triage-list";
  for (const row of lines.slice(0, 8)) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "triage-chip " + (row.label || "");
    btn.textContent = `${row.symbol} · ${row.text}`;
    btn.addEventListener("click", () => loadChart(row.symbol));
    li.append(btn);
    ul.append(li);
  }
  box.append(ul);
}

function drawMorningRibbon(sectorsPayload, recentPayload) {
  const ribbon = document.getElementById("morningRibbon");
  if (!ribbon) return;
  ribbon.textContent = "";
  const parts = [];
  // The watched tape (price move + label) lives on the Watched chips below,
  // one chip per name, so the ribbon keeps only market-wide pills.
  // Sector breadth from PSEi + sector rows when present.
  const rows = (sectorsPayload && sectorsPayload.rows) || [];
  if (rows.length) {
    let up = 0, down = 0;
    for (const r of rows) {
      if (Number.isFinite(r.changePct)) {
        if (r.changePct >= 0) up++; else down++;
      } else if (r.trend && r.trend.label === "bullish") up++;
      else if (r.trend && r.trend.label === "bearish") down++;
    }
    const breadth = document.createElement("span");
    breadth.className = "ribbon-breadth";
    breadth.append("PSE sectors ", glanceSpan("t-up", "▲" + up), " ", glanceSpan("t-down", "▼" + down));
    breadth.title = "Count of sector/index rows up vs down on the sector table.";
    parts.push(breadth);
  }
  const curve = yieldCurveShape((recentPayload && recentPayload.rows) || []);
  if (curve) {
    const c = document.createElement("span");
    c.className = "ribbon-breadth";
    c.textContent = curve.word === "steep" || curve.word === "gently steep"
      ? "Curve steep" : curve.word === "inverted" || curve.word === "gently inverted"
        ? "Curve inverted" : "Curve flat";
    c.title = curve.text;
    parts.push(c);
  }
  if (!parts.length) {
    ribbon.hidden = true;
    return;
  }
  ribbon.hidden = false;
  for (const p of parts) ribbon.append(p);
}

async function loadOfflinePacket() {
  try {
    const packet = await requestJSON("/api/packet");
    try { localStorage.setItem(DESK_PACKET_KEY, JSON.stringify(packet)); } catch {}
    return packet;
  } catch {
    try {
      const raw = JSON.parse(localStorage.getItem(DESK_PACKET_KEY) || "null");
      return raw && typeof raw === "object" ? raw : null;
    } catch { return null; }
  }
}

function drawPacketStamp(packet) {
  const el = document.getElementById("packetStamp");
  if (!el) return;
  if (!packet) { el.hidden = true; return; }
  const when = packet.generatedAt
    ? new Date(packet.generatedAt * 1000).toLocaleString()
    : "";
  el.hidden = false;
  const full = packet.fromDisk
    ? `Offline packet${when ? " · " + when : ""} — disk only, no live fetch.`
    : `Morning packet${when ? " · " + when : ""}`;
  const short = typeof glanceWhen === "function" ? glanceWhen(packet.generatedAt) : when;
  el.textContent = "🕑 " + (short || "—") + (packet.fromDisk ? " · saved copy" : "");
  el.title = full + " Assembled from the last sweep and disk cache. Does not trigger upstream reads.";
}

/* ---- six-pack paging (up to 24 pins, 6 per page) ------------------------ */

function sixPackPage() {
  try { return Math.max(0, parseInt(localStorage.getItem(DESK_PAGE_KEY) || "0", 10) || 0); }
  catch { return 0; }
}

function setSixPackPage(n) {
  try { localStorage.setItem(DESK_PAGE_KEY, String(Math.max(0, n))); } catch {}
}

if (typeof module !== "undefined") {
  module.exports = {
    watchTurnover, yieldCurveShape, fundPeerDrift, marketStaleness, againstMarketLine,
  };
}
