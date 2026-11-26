"use strict";

/* Desk pack (2026-11-25): cash planner, T+2 settle, morning pulse, overnight gap,
   commodity shelf, holdings ledger, named watchlists, scan/focus modes, share
   brief, chart in words, ASEAN presets, filings strip, BSP/BTr chips.
   Pure helpers first; never a second classifier. */

/* v2: the old key was written on every load with the "scan" default, so every
   browser had scan saved without choosing it. Only a click writes this one. */
const MODE_KEY = "apd-desk-mode-v2";
const HOLDINGS_KEY = "apd-holdings";
const WATCH_LISTS_KEY = "apd-watch-lists";
const CASH_PLANNER_KEY = "apd-cash-planner";

const COMMO_SYMBOLS = [
  ["GC=F", "Gold"],
  ["SI=F", "Silver"],
  ["CL=F", "WTI"],
  ["BZ=F", "Brent"],
  ["HG=F", "Copper"],
  ["NG=F", "Nat gas"],
];

const ASEAN_PRESETS = [
  ["PSE:PSEI", "PSEi"],
  ["^STI", "STI"],
  ["^JKSE", "Jakarta"],
  ["^KLSE", "KLCI"],
  ["D05.SI", "DBS"],
  ["TLKM.JK", "Telkom"],
];

let packDigestCache = null;

/* ---- pure helpers ------------------------------------------------------ */

function parseYmd(ymd) {
  if (!ymd || typeof ymd !== "string") return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd.trim());
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12, 0, 0);
}

function formatYmd(d) {
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const da = String(d.getDate()).padStart(2, "0");
  return `${y}-${mo}-${da}`;
}

function addCalendarDays(d, n) {
  const out = new Date(d.getTime());
  out.setDate(out.getDate() + n);
  return out;
}

/* T+2 PSE settlement: skip weekends and optional holiday YYYY-MM-DD strings. */
function pseSettleDate(tradeDayYmd, holidaysSet) {
  const start = parseYmd(tradeDayYmd);
  if (!start) return null;
  const hol = holidaysSet || new Set();
  let cur = start;
  let counted = 0;
  while (counted < 2) {
    cur = addCalendarDays(cur, 1);
    const dow = cur.getDay();
    const ymd = formatYmd(cur);
    if (dow === 0 || dow === 6) continue;
    if (hol.has(ymd)) continue;
    counted += 1;
  }
  return formatYmd(cur);
}

function morningPulseLines(digest) {
  if (!digest) return ["No digest yet — waiting for the first scan."];
  const lines = [];
  const fired = (digest.alarms && digest.alarms.fired) || [];
  if (fired.length) {
    const bits = fired.slice(0, 3).map((a) => `${a.symbol || "?"}`);
    lines.push(`${fired.length} alarm${fired.length === 1 ? "" : "s"} fired: ${bits.join(", ")}`);
  }
  const turns = digest.freshTurns || [];
  if (turns.length) {
    const top = turns.slice(0, 3).map((t) => t.ticker || t.symbol).join(", ");
    lines.push(`${turns.length} fresh turn${turns.length === 1 ? "" : "s"}${top ? ` (${top})` : ""}`);
  }
  const markets = digest.markets || [];
  const bad = markets.filter((m) => ["offline", "partial", "fallback"].includes(m.state));
  if (bad.length) {
    lines.push("Stale markets: " + bad.slice(0, 4).map((m) => `${m.market} (${m.state})`).join(", "));
  }
  const armed = digest.alarms && digest.alarms.armed;
  if (Number.isFinite(armed) && armed > 0 && !fired.length) {
    lines.push(`${armed} price alarm${armed === 1 ? "" : "s"} armed`);
  }
  if (!lines.length) lines.push("Quiet day — nothing urgent in the last digest.");
  return lines.slice(0, 6);
}

function overnightGapText(moves) {
  if (!Array.isArray(moves) || !moves.length) return null;
  return moves.slice(0, 5).map((m) => {
    const name = m.label || m.ticker || m.symbol || "?";
    const pct = Number(m.gapPct ?? m.pct ?? m.gap);
    if (!Number.isFinite(pct)) return name;
    const sign = pct >= 0 ? "+" : "−";
    return `${name} ${sign}${Math.abs(pct).toFixed(2)}%`;
  }).join(" · ");
}

function chartInWords(d) {
  if (!d) return "";
  const t = d.trend || {};
  const label = t.label || "not labelled";
  const name = d.name || d.symbol || "This asset";
  const pts = d.points || [];
  let tail = "";
  if (pts.length >= 2) {
    const a = pts[0].c;
    const b = pts[pts.length - 1].c;
    if (a > 0 && Number.isFinite(b)) {
      const pct = (b / a - 1) * 100;
      tail = ` Over the drawn window the close moved ${pct >= 0 ? "+" : "−"}${Math.abs(pct).toFixed(2)}%.`;
    }
  }
  const score = Number.isFinite(t.score) ? ` Score ${t.score.toFixed(2)}.` : "";
  const pull = t.pullback ? " Price is pulling back within the label." : "";
  return `${name} looks ${label}.${score}${pull}${tail}`;
}

function isPseChart(d) {
  const sym = String((d && d.symbol) || "").toUpperCase();
  return sym.startsWith("PSE:") || sym.startsWith("EDGE:") || sym.endsWith(".PS");
}

function chartPhpPrice(d) {
  if (!d) return null;
  if (d.currency === "PHP" && Number.isFinite(d.marketPrice)) return d.marketPrice;
  const pts = d.points || [];
  const last = pts.length ? pts[pts.length - 1].c : null;
  if (d.currency === "PHP" && Number.isFinite(last)) return last;
  if (typeof shownData === "function") {
    const shown = shownData();
    if (shown && shown.currency === "PHP") {
      const p2 = shown.points || [];
      const c = p2.length ? p2[p2.length - 1].c : shown.marketPrice;
      if (Number.isFinite(c)) return c;
    }
  }
  return d.currency === "PHP" && Number.isFinite(last) ? last : null;
}

function loadHoldings() {
  try {
    const raw = JSON.parse(localStorage.getItem(HOLDINGS_KEY) || "[]");
    return Array.isArray(raw) ? raw.filter((h) => h && h.symbol) : [];
  } catch { return []; }
}

function saveHoldings(list) {
  try { localStorage.setItem(HOLDINGS_KEY, JSON.stringify(list.slice(0, 80))); } catch {}
}

function loadNamedWatchLists() {
  try {
    const raw = JSON.parse(localStorage.getItem(WATCH_LISTS_KEY) || "[]");
    return Array.isArray(raw) ? raw.filter((w) => w && w.name) : [];
  } catch { return []; }
}

function saveNamedWatchLists(list) {
  try { localStorage.setItem(WATCH_LISTS_KEY, JSON.stringify(list.slice(0, 12))); } catch {}
}

function holdingsPnL(holding, quote) {
  const d = quote && quote.data;
  const pts = d && d.points;
  const last = pts && pts.length ? pts[pts.length - 1].c : null;
  const cost = Number(holding.avgCost);
  const sh = Number(holding.shares);
  if (!(last > 0) || !(cost > 0) || !(sh > 0)) return null;
  const mv = last * sh;
  const basis = cost * sh;
  return { last, mv, basis, pnl: mv - basis, pct: (last / cost - 1) * 100 };
}

function dayMoverPct(data) {
  const pts = data && data.points;
  if (!pts || pts.length < 2) return null;
  const a = pts[pts.length - 2].c;
  const b = pts[pts.length - 1].c;
  if (!(a > 0) || !Number.isFinite(b)) return null;
  return (b / a - 1) * 100;
}

/* "focus" is the full view (every chart fold-out shown) and the default;
   "scan" hides the fold-outs to skim tables. The button is a plain toggle:
   it always reads "Scan", pressed while scan is on. `save` is set only by a
   click, so a page load never records a choice the reader did not make. */
function applyDeskMode(mode, { save = false } = {}) {
  const body = document.body;
  if (!body) return;
  const scan = mode === "scan";
  body.classList.remove("desk-scan", "desk-focus");
  body.classList.add(scan ? "desk-scan" : "desk-focus");
  if (save) {
    try { localStorage.setItem(MODE_KEY, scan ? "scan" : "focus"); } catch {}
  }
  const btn = document.getElementById("modeToggle");
  if (btn) {
    btn.textContent = "Scan";
    btn.setAttribute("aria-pressed", String(scan));
    btn.title = scan
      ? "Scan mode is on: chart fold-outs are hidden so you can skim tables. Press to show them."
      : "Scan mode hides chart fold-outs so you can skim tables";
  }
}

/* ---- DOM: morning desk ------------------------------------------------- */

function drawMorningPulse(digest) {
  const fold = document.getElementById("morningPulseFold");
  const ul = document.getElementById("morningPulse");
  if (!ul) return;
  const lines = morningPulseLines(digest);
  ul.textContent = "";
  for (const line of lines) {
    const li = document.createElement("li");
    li.textContent = line;
    ul.append(li);
  }
  if (fold) fold.hidden = !lines.length;
}

function drawOvernightGap(digest) {
  const el = document.getElementById("overnightGap");
  if (!el) return;
  const text = overnightGapText(digest && digest.overnightMoves);
  if (!text) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = "";
  el.append(glanceSpan("glance-label", "Overnight"));
  for (const c of overnightChips(digest.overnightMoves)) {
    const chip = glanceSpan("glance-pill tone-" + c.tone);
    chip.append(glanceSpan("", c.name), glanceSpan("t-" + c.tone, c.arrow + " " + c.text));
    chip.title = c.title;
    el.append(chip);
  }
  el.setAttribute("role", "group");
  el.setAttribute("aria-label", "Overnight US→PH gap: " + text);
  el.title = "Overnight US→PH gap: " + text + ". Session gaps named in the morning digest — descriptive only.";
}

function formatBspChip(bsp) {
  if (!bsp || typeof bsp !== "object") return null;
  if (bsp.text) return { text: bsp.text, title: bsp.title || "BSP" };
  const bits = [];
  if (bsp.rrp) bits.push("RRP " + bsp.rrp);
  if (bsp.odf) bits.push("ODF " + bsp.odf);
  if (bsp.olf) bits.push("OLF " + bsp.olf);
  if (!bits.length) return null;
  return {
    text: "BSP " + bits.join(" · "),
    title: (bsp.source || "BSP") + (bsp.cached ? " (cached)" : ""),
  };
}

function formatBtrChip(btr) {
  if (!btr) return null;
  if (typeof btr === "object" && !Array.isArray(btr) && btr.text) {
    return { text: btr.text, title: btr.title || "BTr" };
  }
  const rows = Array.isArray(btr) ? btr : [];
  if (!rows.length) return null;
  const top = rows[0];
  const y = top.yield || (top.yields && top.yields[0]) || "";
  const title = (top.title || "Auction").slice(0, 48);
  return {
    text: "BTr " + (y ? y + " · " : "") + title,
    title: "Latest Treasury auction scrape — descriptive only",
  };
}

function drawMacroChips(digest) {
  const bsp = document.getElementById("bspChip");
  const btr = document.getElementById("btrChip");
  const wrap = document.getElementById("macroChips");
  let any = false;
  if (bsp) {
    const row = formatBspChip(digest && digest.bsp);
    if (row) {
      bsp.hidden = false;
      bsp.textContent = row.text;
      bsp.title = row.title;
      any = true;
    } else {
      bsp.hidden = true;
      bsp.textContent = "";
    }
  }
  if (btr) {
    const row = formatBtrChip(digest && digest.btr);
    if (row) {
      btr.hidden = false;
      btr.textContent = row.text;
      btr.title = row.title;
      any = true;
    } else {
      btr.hidden = true;
      btr.textContent = "";
    }
  }
  if (wrap) wrap.hidden = !any;
}

function drawCommodityShelf() {
  const box = document.getElementById("commodityShelf");
  if (!box) return;
  if (!box.dataset.bound) {
    box.dataset.bound = "1";
    box.textContent = "";
    for (const [sym, title] of COMMO_SYMBOLS) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ghost-btn commodity-chip";
      b.textContent = title;
      b.title = sym;
      b.addEventListener("click", () => {
        if (typeof loadChart === "function") loadChart(sym);
      });
      box.append(b);
    }
  }
  box.hidden = false;
}

/* ---- DOM: chart card --------------------------------------------------- */

function drawBuyPlanner(d) {
  const root = document.getElementById("buyPlanner");
  const body = document.getElementById("buyPlannerBody");
  if (!root || !body) return;
  const price = chartPhpPrice(d);
  const show = isPseChart(d) && Number.isFinite(price);
  root.hidden = !show;
  if (!show) {
    body.textContent = "";
    return;
  }
  if (!root.dataset.bound) {
    root.dataset.bound = "1";
    const form = document.createElement("form");
    form.className = "buy-planner-form";
    form.innerHTML = '<label for="buyPlannerCash">Cash (₱)</label>'
      + '<input id="buyPlannerCash" type="text" inputmode="decimal" autocomplete="off" spellcheck="false">'
      + '<button class="ghost-btn" type="submit">Plan</button>'
      + '<p class="buy-planner-out" id="buyPlannerOut"></p>';
    body.append(form);
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      redrawBuyPlannerOut();
    });
    const inp = document.getElementById("buyPlannerCash");
    if (inp) {
      try {
        const saved = localStorage.getItem(CASH_PLANNER_KEY);
        if (saved) inp.value = saved;
      } catch {}
      inp.addEventListener("change", () => {
        try { localStorage.setItem(CASH_PLANNER_KEY, inp.value); } catch {}
        redrawBuyPlannerOut();
      });
    }
  }
  redrawBuyPlannerOut();
}

function redrawBuyPlannerOut() {
  const out = document.getElementById("buyPlannerOut");
  const inp = document.getElementById("buyPlannerCash");
  const d = typeof state !== "undefined" && state.data;
  const price = chartPhpPrice(d);
  if (!out || !(price > 0) || typeof pseCashPlan !== "function") return;
  const cash = inp ? Number(String(inp.value || "").replace(/,/g, "")) : NaN;
  if (!(cash > 0)) {
    out.textContent = "Enter cash in pesos to see how many whole lots fit.";
    return;
  }
  const plan = pseCashPlan(cash, price);
  if (!plan) {
    out.textContent = "Not enough cash for one board lot at this price, including fees.";
    return;
  }
  const nf = typeof Intl !== "undefined"
    ? new Intl.NumberFormat("en-PH", { style: "currency", currency: "PHP" })
    : null;
  const peso = (x) => (nf ? nf.format(x) : `₱${x.toFixed(2)}`);
  out.textContent = `${plan.lots} lot${plan.lots === 1 ? "" : "s"} (${plan.shares} shares) · `
    + `outlay ${peso(plan.outlay)} · leftover ${peso(plan.leftover)} · `
    + `break-even ${plan.breakEven != null ? peso(plan.breakEven) : "—"} · `
    + `sell net ${plan.sellNet != null ? peso(plan.sellNet) : "—"}`;
  out.title = `${plan.lot}-share board lot at ${peso(price)}; COL-style buy fees included.`;
}

function drawT2Calendar(d) {
  const el = document.getElementById("t2Calendar");
  if (!el) return;
  if (!isPseChart(d)) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  const pts = d.points || [];
  const last = pts.length ? pts[pts.length - 1] : null;
  let tradeYmd = null;
  if (last && Number.isFinite(last.t) && typeof sessionDay === "function") {
    tradeYmd = sessionDay(last.t, d.timezone || "Asia/Manila");
  } else if (d.staleBar) {
    tradeYmd = String(d.staleBar).slice(0, 10);
  }
  const settle = tradeYmd ? pseSettleDate(tradeYmd) : null;
  if (!settle) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.textContent = `T+2 settlement: trade ${tradeYmd} → cash freed ${settle} (weekends skipped).`;
  el.title = "Settlement calendar days for PSE cash equities — holidays not included unless digest lists them.";
}

function drawChartInWords(d) {
  const el = document.getElementById("chartInWords");
  if (!el) return;
  if (!d) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = chartInWords(d);
}

function ensureHeroDeltaArrow() {
  const el = document.getElementById("heroDelta");
  if (!el || el.hidden) return;
  const text = el.textContent || "";
  if (text.includes("▲") || text.includes("▼")) return;
  if (el.querySelector("[aria-hidden]")) return;
  const val = el.querySelector(".delta-val");
  if (!val) return;
  const up = val.classList.contains("up");
  const glyph = document.createElement("span");
  glyph.setAttribute("aria-hidden", "true");
  glyph.textContent = up ? "↑" : "↓";
  el.prepend(glyph);
}

async function drawFilingsStrip(d) {
  const el = document.getElementById("filingsStrip");
  if (!el) return;
  if (!isPseChart(d)) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  const sym = d.symbol;
  if (el.dataset.sym === sym && el.dataset.loaded === "1") {
    el.hidden = el.textContent === "";
    return;
  }
  el.dataset.sym = sym;
  el.dataset.loaded = "0";
  el.hidden = false;
  el.textContent = "Loading filings…";
  try {
    const raw = await requestJSON("/api/filings?symbol=" + encodeURIComponent(sym));
    const items = (raw && raw.rows) || (raw && raw.items) || (raw && raw.filings) || [];
    if (!items.length) {
      el.textContent = "No recent filings returned for this symbol.";
      el.dataset.loaded = "1";
      return;
    }
    el.textContent = "";
    const ul = document.createElement("ul");
    ul.className = "filings-list";
    for (const row of items.slice(0, 6)) {
      const li = document.createElement("li");
      const date = row.time || row.date || row.filed || "";
      const title = row.title || row.kind || row.type || "Filing";
      if (row.url) {
        const a = document.createElement("a");
        a.href = row.url;
        a.textContent = (date ? `${date} · ` : "") + title;
        a.rel = "noopener";
        li.append(a);
      } else {
        li.textContent = (date ? `${date} · ` : "") + title;
      }
      ul.append(li);
    }
    el.replaceChildren(ul);
    el.dataset.loaded = "1";
  } catch {
    el.textContent = "Filings unavailable (source offline or route not ready).";
    el.dataset.loaded = "1";
  }
}

function drawAseanPresets(d) {
  if (!d || typeof loadComparison !== "function") return;
  const box = document.getElementById("comparePresets");
  if (!box || box.querySelector(".asean-pack-label")) return;
  const label = document.createElement("span");
  label.className = "compare-presets-label asean-pack-label";
  label.textContent = "ASEAN:";
  box.append(label);
  for (const [sym, title] of ASEAN_PRESETS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "compare-preset";
    b.textContent = title;
    b.title = `Compare with ${title}`;
    b.addEventListener("click", () => loadComparison(sym));
    box.append(b);
  }
}

/* ---- DOM: rail --------------------------------------------------------- */

function drawHoldingsBox() {
  const root = document.getElementById("holdingsBox");
  const list = document.getElementById("holdingsList");
  if (!root || !list) return;
  const holdings = loadHoldings();
  root.hidden = false;
  list.textContent = "";
  if (!holdings.length) {
    const p = document.createElement("p");
    p.className = "watch-hint";
    p.textContent = "No holdings saved — add one below.";
    list.append(p);
  } else {
    const ul = document.createElement("ul");
    ul.className = "holdings-list";
    for (const h of holdings) {
      const q = typeof state !== "undefined" && state.watchQuotes && state.watchQuotes[h.symbol];
      const row = holdingsPnL(h, q);
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ghost-btn";
      btn.textContent = h.symbol.split(":").pop();
      btn.addEventListener("click", () => {
        if (typeof loadChart === "function") loadChart(h.symbol);
      });
      li.append(btn, document.createTextNode(
        ` ${h.shares} @ ${h.avgCost} ${h.currency || ""}`
        + (row ? ` · P&L ${row.pnl >= 0 ? "+" : "−"}${Math.abs(row.pnl).toFixed(2)} (${row.pct >= 0 ? "+" : "−"}${Math.abs(row.pct).toFixed(2)}%)` : " · —")));
      ul.append(li);
    }
    list.append(ul);
  }
  if (!root.dataset.bound) {
    root.dataset.bound = "1";
    const form = document.getElementById("holdingsForm");
    if (form) {
      form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        const symIn = document.getElementById("holdingsSymbol");
        const shIn = document.getElementById("holdingsShares");
        const costIn = document.getElementById("holdingsCost");
        const sym = (symIn && symIn.value.trim()) || (state.data && state.data.symbol);
        const shares = Number(shIn && shIn.value);
        const avgCost = Number(costIn && costIn.value);
        const cur = state.data && state.data.currency;
        if (!sym || !(shares > 0) || !(avgCost > 0)) return;
        const next = loadHoldings().filter((h) => h.symbol !== sym);
        next.unshift({ symbol: sym, shares, avgCost, currency: cur || "PHP" });
        saveHoldings(next);
        if (shIn) shIn.value = "";
        if (costIn) costIn.value = "";
        drawHoldingsBox();
      });
    }
  }
}

function drawWatchListsBox() {
  const root = document.getElementById("watchListsBox");
  const list = document.getElementById("watchListsNames");
  if (!root || !list) return;
  const named = loadNamedWatchLists();
  root.hidden = false;
  list.textContent = "";
  if (!named.length) {
    const p = document.createElement("p");
    p.className = "watch-hint";
    p.textContent = "Save the current watchlist under a name.";
    list.append(p);
  } else {
    const ul = document.createElement("ul");
    ul.className = "watch-lists-names";
    for (const row of named) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ghost-btn";
      btn.textContent = row.name;
      btn.title = (row.symbols || []).join(", ");
      btn.addEventListener("click", () => applyNamedWatchList(row));
      li.append(btn);
      const movers = watchListDayMovers(row);
      if (movers) {
        const span = document.createElement("span");
        span.className = "watch-lists-mover";
        span.textContent = " · " + movers;
        li.append(span);
      }
      ul.append(li);
    }
    list.append(ul);
  }
  if (!root.dataset.bound) {
    root.dataset.bound = "1";
    const form = document.getElementById("watchListsForm");
    if (form) {
      form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        const nameIn = document.getElementById("watchListName");
        const name = nameIn && String(nameIn.value || "").trim();
        if (!name || !state.watch || !state.watch.length) return;
        const syms = state.watch.map((w) => w.symbol);
        const next = loadNamedWatchLists().filter((w) => w.name !== name);
        next.unshift({ name, symbols: syms, savedAt: Date.now() });
        saveNamedWatchLists(next);
        if (nameIn) nameIn.value = "";
        drawWatchListsBox();
      });
    }
  }
}

function applyNamedWatchList(row) {
  if (!row || !row.symbols || !row.symbols.length) return;
  if (typeof saveWatch !== "function" || typeof state === "undefined") return;
  state.watch = row.symbols.map((sym) => ({ symbol: sym, name: sym }));
  saveWatch();
  if (typeof drawWatchList === "function") drawWatchList();
  if (typeof refreshWatchQuotes === "function") refreshWatchQuotes();
  if (typeof setStatus === "function") setStatus(`Loaded watchlist “${row.name}”`);
}

function watchListDayMovers(row) {
  const quotes = typeof state !== "undefined" && state.watchQuotes;
  if (!quotes || !row.symbols) return null;
  const pcts = [];
  for (const sym of row.symbols) {
    const p = dayMoverPct(quotes[sym] && quotes[sym].data);
    if (Number.isFinite(p)) pcts.push({ sym, p });
  }
  if (!pcts.length) return null;
  pcts.sort((a, b) => b.p - a.p);
  const top = pcts[0];
  const bot = pcts[pcts.length - 1];
  return `day: ${top.sym.split(":").pop()} ${top.p >= 0 ? "+" : "−"}${Math.abs(top.p).toFixed(2)}%`
    + (bot.sym !== top.sym ? `; ${bot.sym.split(":").pop()} ${bot.p >= 0 ? "+" : "−"}${Math.abs(bot.p).toFixed(2)}%` : "");
}

function wireModeToggle() {
  const btn = document.getElementById("modeToggle");
  if (!btn || btn.dataset.bound) return;
  btn.dataset.bound = "1";
  let mode = "focus";
  try {
    if (localStorage.getItem(MODE_KEY) === "scan") mode = "scan";
  } catch {}
  applyDeskMode(mode);
  btn.addEventListener("click", () => {
    const next = document.body.classList.contains("desk-scan") ? "focus" : "scan";
    applyDeskMode(next, { save: true });
  });
}

function wireShareBrief() {
  const btn = document.getElementById("shareBriefBtn");
  if (!btn || btn.dataset.bound) return;
  btn.dataset.bound = "1";
  btn.addEventListener("click", () => {
    document.body.classList.add("desk-print-brief");
    const done = () => document.body.classList.remove("desk-print-brief");
    if (typeof window.print === "function") {
      window.print();
      setTimeout(done, 500);
    } else {
      window.open(location.href, "_blank");
      done();
    }
  });
}

/* ---- entry points ------------------------------------------------------ */

function deskpackOnChart(d) {
  drawBuyPlanner(d);
  drawT2Calendar(d);
  drawChartInWords(d);
  ensureHeroDeltaArrow();
  drawAseanPresets(d);
  drawFilingsStrip(d);
}

function deskpackOnDesk(digest, packet, rows) {
  packDigestCache = digest || packDigestCache;
  drawMorningPulse(digest);
  drawOvernightGap(digest);
  drawMacroChips(digest);
  drawCommodityShelf();
  drawHoldingsBox();
  drawWatchListsBox();
}

/* Arrow keys walk the bar table when the plot is focused; announce change. */
function wireChartKeyboard() {
  if (document.documentElement.dataset.chartKeys === "1") return;
  document.documentElement.dataset.chartKeys = "1";
  document.addEventListener("keydown", (ev) => {
    if (ev.altKey || ev.metaKey || ev.ctrlKey) return;
    const tag = (ev.target && ev.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    const d = typeof state !== "undefined" && state.data;
    const pts = d && d.points;
    if (!pts || pts.length < 2) return;
    if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
    ev.preventDefault();
    let i = Number.isFinite(state.activeIndex) ? state.activeIndex : pts.length - 1;
    i += ev.key === "ArrowLeft" ? -1 : 1;
    if (i < 0) i = 0;
    if (i >= pts.length) i = pts.length - 1;
    state.activeIndex = i;
    if (typeof drawCrosshair === "function") drawCrosshair();
    else if (typeof renderPlot === "function") renderPlot();
    const words = document.getElementById("chartInWords");
    if (words && !words.hidden) {
      const p = pts[i];
      const prev = i > 0 ? pts[i - 1] : null;
      let bit = "";
      if (prev && prev.c > 0 && Number.isFinite(p.c)) {
        const pct = (p.c / prev.c - 1) * 100;
        bit = ` Bar ${i + 1}/${pts.length}: ${pct >= 0 ? "up" : "down"} ${Math.abs(pct).toFixed(2)}%.`;
      }
      words.dataset.barNote = bit;
      words.textContent = chartInWords(d) + bit;
    }
  });
}

function applyMobileSheetHints() {
  const mq = window.matchMedia && window.matchMedia("(max-width: 720px)");
  const sync = () => {
    document.body.classList.toggle("desk-mobile", !!(mq && mq.matches));
  };
  sync();
  if (mq && mq.addEventListener) mq.addEventListener("change", sync);
}

function deskpackBoot() {
  wireModeToggle();
  wireShareBrief();
  drawCommodityShelf();
  drawHoldingsBox();
  drawWatchListsBox();

  // desksuggestOnDesk / desksuggestOnChart already call deskpack*; keep a
  // fallback if those hooks never ran (older page cache without the call).
  if (typeof drawMorningDesk === "function" && !drawMorningDesk._deskpack) {
    const origDesk = drawMorningDesk;
    drawMorningDesk = function (recentPayload) {
      origDesk(recentPayload);
      if (typeof desksuggestOnDesk === "function") return;
      const rows = (recentPayload && recentPayload.rows) || [];
      const dig = (typeof deskDigest !== "undefined" && deskDigest) || packDigestCache;
      deskpackOnDesk(dig, typeof deskPacket !== "undefined" ? deskPacket : null, rows);
    };
    drawMorningDesk._deskpack = true;
  }

  if (typeof renderAll === "function" && !renderAll._deskpack) {
    const origRender = renderAll;
    renderAll = function (opts) {
      origRender(opts);
      if (typeof desksuggestOnChart === "function") {
        if (!opts || !opts.live) {
          drawHoldingsBox();
          drawWatchListsBox();
        }
        return;
      }
      const d = typeof state !== "undefined" && state.data;
      if (d) deskpackOnChart(d);
      drawHoldingsBox();
      drawWatchListsBox();
    };
    renderAll._deskpack = true;
  }

  wireChartKeyboard();
  applyMobileSheetHints();

  if (typeof deskOnWatchDrawn === "function" && !deskOnWatchDrawn._deskpack) {
    const origWatch = deskOnWatchDrawn;
    deskOnWatchDrawn = function () {
      origWatch();
      drawHoldingsBox();
      drawWatchListsBox();
    };
    deskOnWatchDrawn._deskpack = true;
  }
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", deskpackBoot);
  } else {
    setTimeout(deskpackBoot, 0);
  }
}

if (typeof module !== "undefined") {
  module.exports = {
    pseSettleDate,
    morningPulseLines,
    overnightGapText,
    chartInWords,
    COMMO_SYMBOLS,
    ASEAN_PRESETS,
    parseYmd,
    formatYmd,
    applyDeskMode,
    wireModeToggle,
    MODE_KEY,
  };
}