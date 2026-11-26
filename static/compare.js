"use strict";

/* Compare up to six assets: the chart on screen plus up to five more.

   Every line starts at 100 on the first trading date all of them share, and
   only dates every series has are drawn (never a forward-filled holiday). One
   asset can be made the baseline: each line is then divided by it, so 105
   means "5% ahead of the baseline since the start", and the baseline itself
   is the flat 100 line. Lines differ by colour AND dash pattern, so identity
   never rests on colour alone; the legend names each one, and the table view
   lists every value. Colours: the page's categorical slots 1-5 and 7 (green
   and red are skipped: on this page they mean up and down), validated for
   light and dark surfaces 2026-11-23. */

const COMPARE_MAX = 6;
const COMPARE_DASH = ["", "7 4", "2 3", "10 3 2 3", "4 2", "12 4"];
const COMPARE_PRESETS = [
  ["PSE:PSEI", "PSEi"],
  ["PSE:FMETF", "FMETF"],
  ["SPY", "SPY"],
  ["BTC-USD", "BTC"],
  ["USDPHP=X", "USD/PHP"],
  ["GC=F", "Gold"],
  ["BZ=F", "Brent"],
  ["^STI", "STI"],
  ["^JKSE", "Jakarta"],
];

// Match session dates, not instants: Tokyo, New York and crypto markets do
// not start their daily bars at the same hour. Never forward-fill a holiday.
function comparisonCloses(data) {
  const zone = data.timezone || (data.yieldSeries ? "Asia/Manila" : "UTC");
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
  });
  const days = new Map();
  for (const p of data.points || []) {
    if (!p || !Number.isFinite(p.t) || !Number.isFinite(p.c)) continue;
    const parts = Object.fromEntries(fmt.formatToParts(toDate(p.t)).map(v => [v.type, v.value]));
    const day = `${parts.year}-${parts.month}-${parts.day}`;
    if (!days.has(day) || days.get(day).t <= p.t) days.set(day, p);
  }
  return days;
}

/* Rows of {day, values: [...]} over the dates every series shares, each
   series rebased to 100 on the first of them. With `base` (an index into
   `series`), every value is then divided by that series' value. */
function comparisonTable(series, base = null) {
  const maps = series.map(comparisonCloses);
  const days = [...maps[0].keys()].filter(day => maps.every(m => m.has(day))).sort();
  if (days.length < 2) throw new Error("At least two shared trading dates are needed to compare these assets.");
  const starts = maps.map(m => m.get(days[0]).c);
  if (starts.some(v => !(v > 0))) throw new Error("Every starting value must be positive to compare from 100.");
  return days.map(day => {
    const values = maps.map((m, i) => m.get(day).c / starts[i] * 100);
    if (base === null) return { day, values };
    if (!(values[base] > 0)) throw new Error("Baseline value must be positive on every shared date.");
    return { day, values: values.map(v => v / values[base] * 100) };
  });
}

// The two-series form the first version shipped; kept for its callers.
function comparisonRows(primary, peer) {
  return comparisonTable([primary, peer]).map(r => ({ day: r.day, a: r.values[0], b: r.values[1] }));
}

const compareUI = Object.fromEntries(["panel", "form", "symbol", "clear", "csv", "presets", "status", "output",
  "plot", "table", "legend"].map(key =>
  [key, document.getElementById("compare" + key[0].toUpperCase() + key.slice(1))]));
let comparePrimary = null;
let comparePeers = [];          // [{wanted, data, error, request, asBase}]
let compareBase = null;         // a symbol, or null for "all start at 100"
let compareLastExport = null;   // {names, rows, baseName}

function renderComparePresets() {
  if (!compareUI.presets || !comparePrimary) return;
  const primarySym = String(comparePrimary.symbol || "").toUpperCase();
  const label = document.createElement("span");
  label.className = "compare-presets-label";
  label.textContent = "Relative to:";
  const nodes = [label];
  for (const [sym, title] of COMPARE_PRESETS) {
    const btn = document.createElement("button");
    btn.type = "button";
    const key = sym.toUpperCase();
    const isPrimary = key === primarySym;
    const isBase = compareBase && String(compareBase).toUpperCase() === key;
    const inPeers = comparePeers.some(p =>
      p.wanted.toUpperCase() === key || (p.data && String(p.data.symbol).toUpperCase() === key));
    btn.className = "compare-preset" + (isBase ? " is-base" : inPeers ? " is-added" : "");
    btn.textContent = title;
    btn.disabled = isPrimary;
    btn.setAttribute("aria-pressed", String(Boolean(isBase)));
    btn.title = isPrimary
      ? `${title} is the main chart`
      : isBase
        ? `Comparing relative to ${title}. Click to show all from 100.`
        : `Compare ${comparePrimary.symbol} divided by ${title} (relative strength)`;
    btn.addEventListener("click", () => {
      if (isBase) {
        compareBase = null;
        renderComparison();
        return;
      }
      const existing = comparePeers.find(p =>
        p.wanted.toUpperCase() === key || (p.data && String(p.data.symbol).toUpperCase() === key));
      if (existing) {
        if (existing.data) {
          compareBase = existing.data.symbol;
          renderComparison();
        } else {
          existing.asBase = true;
        }
        return;
      }
      loadComparison(sym, { asBase: true });
    });
    nodes.push(btn);
  }
  compareUI.presets.replaceChildren(...nodes);
}

function ratioTrendCall(values) {
  if (typeof Trend === "undefined" || typeof Trend.classify !== "function") return null;
  if (!Array.isArray(values) || values.length < 4) return null;
  try {
    return Trend.classify(values);
  } catch {
    return null;
  }
}

function seriesName(d) {
  return d.symbol + (d.yieldSeries ? " (yield)" : "");
}

function renderComparison() {
  const ready = comparePeers.filter(p => p.data);
  const pending = comparePeers.filter(p => !p.data && !p.error);
  const failed = comparePeers.filter(p => p.error);
  const notes = [
    ...pending.map(p => `Loading ${p.wanted}…`),
    ...failed.map(p => `${p.wanted} unavailable: ${p.error}`),
  ];
  compareUI.clear.hidden = !comparePeers.length;
  renderComparePresets();
  if (!comparePrimary || !ready.length) {
    compareLastExport = null;
    if (compareUI.csv) compareUI.csv.hidden = true;
    compareUI.output.hidden = true;
    compareUI.plot.replaceChildren();
    compareUI.table.replaceChildren();
    if (compareUI.legend) compareUI.legend.replaceChildren();
    compareUI.status.textContent = notes.join(" ");
    return;
  }
  const series = [comparePrimary, ...ready.map(p => p.data)];
  const names = series.map(seriesName);
  let baseIndex = series.findIndex(d => d.symbol === compareBase);
  if (baseIndex < 0) { baseIndex = null; compareBase = null; }
  let rows;
  try {
    rows = comparisonTable(series, baseIndex);
  } catch (err) {
    compareUI.output.hidden = true;
    compareUI.status.textContent = [`Comparison unavailable: ${err.message}`, ...notes].join(" ");
    return;
  }
  const first = rows[0], last = rows[rows.length - 1];
  const fixed = n => n.toFixed(2);
  const lead = baseIndex === null
    ? `All start at 100 on ${first.day}. Only dates every asset traded are shown.`
    : `Each line divided by ${names[baseIndex]}, so 100 means level with it since ${first.day}.`;
  const latest = names.map((n, i) => `${n} ${fixed(last.values[i])}`).join(", ");
  const note = `${lead} On ${last.day}: ${latest}.`;
  const warnings = series.flatMap(d => {
    const out = [];
    if (d.cached || d.stale > 0) out.push(`${d.symbol} uses cached data.`);
    if (d.lastBarBasis && BASIS_WORDS[d.lastBarBasis]) out.push(`${d.symbol}'s newest bar is ${BASIS_WORDS[d.lastBarBasis]}.`);
    return out;
  });

  // ---- the plot
  const svg = svgEl("svg", { viewBox: "0 0 680 250", role: "img", tabindex: "0", "aria-label": note });
  const values = rows.flatMap(r => r.values);
  let lo = Math.min(...values), hi = Math.max(...values);
  const pad = (hi - lo) * 0.08 || 1;
  lo -= pad; hi += pad;
  const stamp = day => Date.parse(day + "T00:00:00Z");
  const start = stamp(first.day), span = stamp(last.day) - start;
  const x = day => 65 + (stamp(day) - start) / span * 600;
  const y = v => 214 - (v - lo) / (hi - lo) * 194;
  const label = (text, xpos, ypos, anchor) => {
    const t = svgEl("text", { class: "tick-text", x: xpos, y: ypos, "text-anchor": anchor });
    t.textContent = text; svg.append(t);
  };
  for (const tick of niceTicks(lo, hi, 4)) {
    svg.append(svgEl("line", { class: "grid-line", x1: 65, x2: 665, y1: y(tick), y2: y(tick) }));
    label(axisTickFmt(tick), 59, y(tick) + 4, "end");
  }
  label(first.day, 65, 239, "start");
  label(last.day, 665, 239, "end");
  series.forEach((_, i) => {
    const d = rows.map((r, j) => `${j ? "L" : "M"}${x(r.day).toFixed(2)} ${y(r.values[i]).toFixed(2)}`).join(" ");
    const attrs = { d, class: `series-line compare-s${i + 1}` };
    if (COMPARE_DASH[i]) attrs["stroke-dasharray"] = COMPARE_DASH[i];
    svg.append(svgEl("path", attrs));
  });
  // Hover: a crosshair at the nearest shared date and every value there.
  const cross = svgEl("line", { class: "compare-cross", x1: 0, x2: 0, y1: 20, y2: 214, visibility: "hidden" });
  const hit = svgEl("rect", { x: 65, y: 20, width: 600, height: 194, fill: "transparent" });
  svg.append(cross, hit);
  const tip = document.createElement("div");
  tip.className = "compare-tip";
  tip.hidden = true;
  const showIndex = (idx) => {
    const r = rows[idx];
    cross.setAttribute("x1", x(r.day)); cross.setAttribute("x2", x(r.day));
    cross.setAttribute("visibility", "visible");
    tip.textContent = `${r.day}: ` + names.map((n, i) => `${n} ${fixed(r.values[i])}`).join(" · ");
    tip.hidden = false;
  };
  let activeIdx = null;
  const showAt = (clientX) => {
    const box = svg.getBoundingClientRect ? svg.getBoundingClientRect() : null;
    if (!box || !box.width) return;
    const vx = (clientX - box.left) / box.width * 680;
    let best = 0;
    rows.forEach((r, j) => { if (Math.abs(x(r.day) - vx) < Math.abs(x(rows[best].day) - vx)) best = j; });
    activeIdx = best;
    showIndex(best);
  };
  const hideTip = () => { activeIdx = null; cross.setAttribute("visibility", "hidden"); tip.hidden = true; };
  // One update per frame: pointermove alone (it covers the mouse too).
  let hoverX = null, hoverFrame = 0;
  hit.addEventListener("pointermove", ev => {
    hoverX = ev.clientX;
    if (!hoverFrame) hoverFrame = requestAnimationFrame(() => { hoverFrame = 0; if (hoverX !== null) showAt(hoverX); });
  });
  hit.addEventListener("pointerdown", ev => showAt(ev.clientX));  // a tap on a phone
  hit.addEventListener("pointerleave", ev => {
    if (ev.pointerType === "touch") return;  // a lifted finger keeps the tip up
    hoverX = null; hideTip();
  });
  svg.addEventListener("blur", hideTip);
  svg.addEventListener("keydown", ev => {
    const cur = activeIdx === null ? rows.length - 1 : activeIdx;
    let next = null;
    const step = ev.shiftKey ? 5 : 1;
    if (ev.key === "ArrowRight") next = Math.min(rows.length - 1, cur + step);
    else if (ev.key === "ArrowLeft") next = Math.max(0, cur - step);
    else if (ev.key === "Home") next = 0;
    else if (ev.key === "End") next = rows.length - 1;
    else if (ev.key === "Escape") { hideTip(); return; }
    if (next === null) return;
    ev.preventDefault();
    activeIdx = next;
    showIndex(next);
  });

  // ---- the legend: name, line sample, newest value; click sets the baseline
  if (compareUI.legend) {
    const items = series.map((d, i) => {
      const li = document.createElement("li");
      const pick = document.createElement("button");
      pick.type = "button";
      pick.className = "compare-key" + (i === baseIndex ? " is-base" : "");
      pick.setAttribute("aria-pressed", String(i === baseIndex));
      pick.title = i === baseIndex ? "Baseline. Click to show all from 100 again."
        : `Make ${names[i]} the baseline`;
      const swatch = svgEl("svg", { class: "compare-swatch", viewBox: "0 0 24 8", width: 24, height: 8, "aria-hidden": "true" });
      const sample = { x1: 0, x2: 24, y1: 4, y2: 4, class: `series-line compare-s${i + 1}` };
      if (COMPARE_DASH[i]) sample["stroke-dasharray"] = COMPARE_DASH[i];
      swatch.append(svgEl("line", sample));
      const text = document.createElement("span");
      text.textContent = `${names[i]} ${fixed(last.values[i])}${i === baseIndex ? " (baseline)" : ""}`;
      const pickKids = [swatch, text];
      // When a baseline is active, classify the shared-date ratio line with
      // the project's exact Trend.classify so relative strength uses the same bar.
      if (baseIndex !== null && i !== baseIndex) {
        const rel = ratioTrendCall(rows.map(r => r.values[i]));
        if (rel && rel.label) {
          const pill = document.createElement("span");
          pill.className = "compare-rel " + rel.label;
          const phrase = typeof badgePhrase === "function" ? badgePhrase(rel) : rel.label;
          const glyph = (typeof TREND_GLYPH !== "undefined" && TREND_GLYPH[rel.label]) || "";
          pill.textContent = `${glyph} ${phrase}`.trim();
          pill.title = `${names[i]} ÷ ${names[baseIndex]} over ${rows.length} shared sessions ` +
            `(score ${rel.score >= 0 ? "+" : "−"}${Math.abs(rel.score).toFixed(2)}, drift t ${rel.significance >= 0 ? "+" : "−"}${Math.abs(rel.significance).toFixed(2)}). Descriptive only.`;
          pickKids.push(pill);
        }
      }
      pick.replaceChildren(...pickKids);
      pick.addEventListener("click", () => {
        compareBase = i === baseIndex ? null : d.symbol;
        renderComparison();
      });
      li.append(pick);
      if (i > 0) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "compare-remove";
        remove.textContent = "×";
        remove.setAttribute("aria-label", `Remove ${names[i]} from the comparison`);
        remove.addEventListener("click", () => removeComparison(ready[i - 1].wanted));
        li.append(remove);
      }
      return li;
    });
    compareUI.legend.replaceChildren(...items);
  }

  // ---- the table view
  const table = document.createElement("table");
  const caption = table.createCaption();
  caption.textContent = baseIndex === null ? `Relative values, ${first.day} = 100`
    : `Relative to ${names[baseIndex]}, ${first.day} = 100`;
  const header = table.createTHead().insertRow();
  for (const text of ["Date", ...names]) {
    const th = document.createElement("th"); th.scope = "col"; th.textContent = text; header.append(th);
  }
  const body = table.createTBody();
  for (const r of rows) {
    const tr = body.insertRow();
    for (const text of [r.day, ...r.values.map(fixed)]) tr.insertCell().textContent = text;
  }
  compareLastExport = { names, rows, baseName: baseIndex === null ? null : names[baseIndex] };
  if (compareUI.csv) compareUI.csv.hidden = false;
  compareUI.plot.replaceChildren(svg, tip);
  compareUI.table.replaceChildren(table);
  compareUI.status.textContent = [note, ...warnings, ...notes].join(" ");
  compareUI.output.hidden = false;
}

function clearComparison() {
  closeCompareSuggestions();
  for (const p of comparePeers) if (p.request) p.request.abort();
  comparePeers = [];
  compareBase = null;
  compareLastExport = null;
  compareUI.symbol.value = compareUI.status.textContent = "";
  compareUI.plot.replaceChildren();
  compareUI.table.replaceChildren();
  if (compareUI.legend) compareUI.legend.replaceChildren();
  if (compareUI.csv) compareUI.csv.hidden = true;
  compareUI.clear.hidden = compareUI.output.hidden = true;
  renderComparePresets();
}

function removeComparison(wanted) {
  const peer = comparePeers.find(p => p.wanted === wanted);
  if (!peer) return;
  if (peer.request) peer.request.abort();
  comparePeers = comparePeers.filter(p => p !== peer);
  if (peer.data && peer.data.symbol === compareBase) compareBase = null;
  renderComparison();
}

async function fetchPeer(peer) {
  if (peer.request) peer.request.abort();
  const request = peer.request = new AbortController();
  peer.data = null; peer.error = null;
  try {
    const data = await requestJSON(`/api/chart?symbol=${encodeURIComponent(peer.wanted)}&range=${RANGE}&interval=${INTERVAL}`, request.signal);
    if (request !== peer.request || !comparePeers.includes(peer)) return;
    if (!data || !data.symbol) throw new Error("No comparison data received.");
    const taken = [comparePrimary, ...comparePeers.filter(p => p !== peer).map(p => p.data)]
      .some(d => d && d.symbol === data.symbol);
    if (taken) throw new Error(`${data.symbol} is already on the chart.`);
    peer.data = data;
    if (peer.asBase) {
      compareBase = data.symbol;
      peer.asBase = false;
    }
  } catch (err) {
    if (request !== peer.request || !comparePeers.includes(peer)) return;
    if (err && err.name === "AbortError") return;
    peer.error = err.message;
  }
  peer.request = null;
  renderComparison();
}

/* Add an asset (the search box's callback). The chart on screen is the first
   line, so five can be added. */
async function loadComparison(wanted, opts = {}) {
  wanted = (wanted || "").trim();
  if (!wanted || !comparePrimary) return;
  compareUI.symbol.value = "";
  const key = wanted.toUpperCase();
  if (key === String(comparePrimary.symbol).toUpperCase()
      || comparePeers.some(p => p.wanted.toUpperCase() === key)) {
    compareUI.status.textContent = `${wanted} is already on the chart.`;
    return;
  }
  if (comparePeers.length >= COMPARE_MAX - 1) {
    compareUI.status.textContent = `Up to ${COMPARE_MAX} assets: remove one to add ${wanted}.`;
    return;
  }
  const peer = { wanted, data: null, error: null, request: null, asBase: Boolean(opts && opts.asBase) };
  comparePeers.push(peer);
  renderComparison();
  await fetchPeer(peer);
}

function comparisonPrimaryChanged(data) {
  if (comparePrimary === data) return;
  const sameSymbol = comparePrimary && comparePrimary.symbol === data.symbol;
  comparePrimary = data;
  compareUI.panel.hidden = false;
  if (!sameSymbol) clearComparison();
  else renderComparison();       // a refresh of the same chart: redraw with it
}

const closeCompareSuggestions = bindAssetSearch(compareUI.symbol, document.getElementById('compareSuggestions'), compareUI.form, loadComparison);
compareUI.clear.addEventListener("click", () => { clearComparison(); compareUI.symbol.focus(); });
if (compareUI.csv) {
  compareUI.csv.addEventListener("click", () => {
    if (!compareLastExport || typeof downloadCsv !== "function") return;
    const { names, rows } = compareLastExport;
    const slug = names.map(n => n.replace(/[^A-Za-z0-9._-]+/g, "_")).join("-vs-");
    downloadCsv(`compare-${slug}.csv`, ["Date", ...names],
      rows.map(r => [r.day, ...r.values.map(v => Number(v.toFixed(4)))]));
  });
}
