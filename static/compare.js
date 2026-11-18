"use strict";

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

function comparisonRows(primary, peer) {
  const a = comparisonCloses(primary), b = comparisonCloses(peer);
  const days = [...a.keys()].filter(day => b.has(day)).sort();
  if (days.length < 2) throw new Error("At least two shared trading dates are needed to compare these assets.");
  const baseA = a.get(days[0]).c, baseB = b.get(days[0]).c;
  if (baseA <= 0 || baseB <= 0) throw new Error("Both starting values must be positive to compare from 100.");
  return days.map(day => ({ day, a: a.get(day).c / baseA * 100, b: b.get(day).c / baseB * 100 }));
}

function renderComparison(primary, peer) {
  const rows = comparisonRows(primary, peer);
  const first = rows[0], last = rows[rows.length - 1];
  const names = [primary, peer].map(d => d.symbol + (d.yieldSeries ? " (yield)" : ""));
  const fixed = n => n.toFixed(2);
  const note = `Both start at 100 on ${first.day}. Only shared trading dates are shown. ` +
    `On ${last.day}: ${names[0]} ${fixed(last.a)} (solid), ${names[1]} ${fixed(last.b)} (dashed).`;
  const warnings = [primary, peer].flatMap(d => {
    const notes = [];
    if (d.cached || d.stale > 0) notes.push(`${d.symbol} uses cached data.`);
    if (d.lastBarBasis && BASIS_WORDS[d.lastBarBasis]) notes.push(`${d.symbol}'s newest bar is ${BASIS_WORDS[d.lastBarBasis]}.`);
    return notes;
  });
  const svg = svgEl("svg", { viewBox: "0 0 680 250", role: "img", "aria-label": note });
  const values = rows.flatMap(r => [r.a, r.b]);
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
  for (const key of ["a", "b"]) {
    const d = rows.map((r, i) => `${i ? "L" : "M"}${x(r.day).toFixed(2)} ${y(r[key]).toFixed(2)}`).join(" ");
    svg.append(svgEl("path", { d, class: key === "a" ? "series-line" : "series-line compare-peer" }));
  }
  const table = document.createElement("table");
  const caption = table.createCaption();
  caption.textContent = `Relative values, ${first.day} = 100`;
  const header = table.createTHead().insertRow();
  for (const text of ["Date", ...names]) {
    const th = document.createElement("th"); th.scope = "col"; th.textContent = text; header.append(th);
  }
  const body = table.createTBody();
  for (const r of rows) {
    const tr = body.insertRow();
    for (const text of [r.day, fixed(r.a), fixed(r.b)]) tr.insertCell().textContent = text;
  }
  compareUI.plot.replaceChildren(svg);
  compareUI.table.replaceChildren(table);
  compareUI.status.textContent = [note, ...warnings].join(" ");
  compareUI.output.hidden = false;
}

const compareUI = Object.fromEntries(["panel", "form", "symbol", "clear", "status", "output", "plot", "table"].map(key =>
  [key, document.getElementById("compare" + key[0].toUpperCase() + key.slice(1))]));
let comparePrimary = null, compareWanted = "", compareRequest = null;

function clearComparison() {
  closeCompareSuggestions();
  if (compareRequest) compareRequest.abort();
  compareRequest = null;
  compareWanted = compareUI.symbol.value = compareUI.status.textContent = "";
  compareUI.plot.replaceChildren();
  compareUI.table.replaceChildren();
  compareUI.clear.hidden = compareUI.output.hidden = true;
}

async function loadComparison(wanted) {
  if (!wanted || !comparePrimary) return;
  if (compareRequest) compareRequest.abort();
  const request = compareRequest = new AbortController();
  compareWanted = wanted;
  compareUI.output.hidden = true;
  compareUI.clear.hidden = false;
  compareUI.status.textContent = `Loading ${wanted}…`;
  try {
    const peer = await requestJSON(`/api/chart?symbol=${encodeURIComponent(wanted)}&range=${RANGE}&interval=${INTERVAL}`, request.signal);
    if (request !== compareRequest) return;
    if (!peer || !peer.symbol) throw new Error("No comparison data received.");
    if (peer.symbol === comparePrimary.symbol) throw new Error("Choose a different second symbol.");
    renderComparison(comparePrimary, peer);
  } catch (err) {
    if (request === compareRequest) compareUI.status.textContent = `Comparison unavailable: ${err.message}`;
  }
}

function comparisonPrimaryChanged(data) {
  if (comparePrimary === data) return;
  const sameSymbol = comparePrimary && comparePrimary.symbol === data.symbol;
  comparePrimary = data;
  compareUI.panel.hidden = false;
  if (!sameSymbol) clearComparison();
  else if (compareWanted) loadComparison(compareWanted);
}

const closeCompareSuggestions = bindAssetSearch(compareUI.symbol, document.getElementById('compareSuggestions'), compareUI.form, loadComparison);
compareUI.clear.addEventListener("click", () => { clearComparison(); compareUI.symbol.focus(); });
