"use strict";

/* ---- against its market ----
   One line under the chart: the charted asset divided by its market's
   benchmark (PSEi for a Philippine share, SPY for a US share or ETF, Bitcoin
   for a coin), labelled by the same classifier the compare panel already uses
   for a baseline (`comparisonTable` + `ratioTrendCall`, static/compare.js).
   It describes how the asset did against its market over the shared days of
   the window. It is not the asset's badge and never replaces it (invariant 1):
   a table row still carries the asset's own label. */

const BENCHMARKS = {
  pse: { symbol: "PSE:PSEI", name: "PSEi" },
  us: { symbol: "SPY", name: "SPY" },
  crypto: { symbol: "BTC-USD", name: "Bitcoin" },
};

/* The benchmark for a chart payload, or null when it has none here. */
function benchmarkFor(d) {
  if (!d || !d.symbol || d.yieldSeries || d.unit === "%") return null;
  const sym = String(d.symbol).toUpperCase();
  const type = String(d.type || "").toUpperCase();
  let pick = null;
  if (sym.startsWith("PSE:") && type !== "INDEX") pick = BENCHMARKS.pse;
  else if (type === "CRYPTOCURRENCY" || /-USD$/.test(sym)) pick = BENCHMARKS.crypto;
  else if ((type === "EQUITY" || type === "ETF") && d.currency === "USD" && !sym.includes(":")) pick = BENCHMARKS.us;
  // UITF equity / balanced / index funds: PSEi as a peer market strip (never a row label).
  else if (d.fundSeries && d.category && /equity|index|balanced|stock/i.test(d.category)
           && !/money\s*market|cash/i.test(d.category)) {
    pick = BENCHMARKS.pse;
  }
  if (!pick || pick.symbol === sym) return null;
  if (pick === BENCHMARKS.pse && /^PSE:(PSEI|ALL|FIN|IND|HDG|PRO|SVC|M_O)$/.test(sym)) return null;   // indexes
  return pick;
}

/* {label, call, move, days} for `d` against `bench`, or null. */
function benchmarkReading(d, bench) {
  const rows = comparisonTable([d, bench], 1);
  const values = rows.map((r) => r.values[0]);
  const call = ratioTrendCall(values);
  if (!call || !call.label) return null;
  return { call, move: values[values.length - 1] / 100 - 1, days: rows.length };
}

const benchMemo = new Map();    // benchmark symbol -> {at, data}

async function loadBenchmarkLine(d) {
  const line = document.getElementById("benchLine");
  if (!line) return;
  const pick = benchmarkFor(d);
  const key = String(d && d.symbol || "").toUpperCase();
  if (line.dataset.symbol !== key) line.hidden = true;     // never show another asset's line
  line.dataset.symbol = key;
  if (!pick) { line.hidden = true; return; }
  try {
    let hit = benchMemo.get(pick.symbol);
    if (!hit || Date.now() - hit.at > 15 * 60 * 1000) {
      hit = { at: Date.now(), data: await getChart(pick.symbol) };
      benchMemo.set(pick.symbol, hit);
    }
    if (state.data !== d) return;                          // the reader moved on
    const r = benchmarkReading(d, hit.data);
    if (!r) { line.hidden = true; return; }
    drawBenchmarkLine(line, d, pick, r);
  } catch {
    if (state.data === d) line.hidden = true;
  }
}

function drawBenchmarkLine(line, d, pick, r) {
  const phrase = typeof badgePhrase === "function" ? badgePhrase(r.call) : r.call.label;
  const word = r.call.label === "neutral" ? "no clear lead"
    : r.call.label === "bullish" ? "pulling ahead" : "falling behind";
  const value = line.querySelector(".stat-value");
  const note = line.querySelector(".stat-note");
  line.querySelector(".stat-label").textContent = `Against ${pick.name}`;
  value.textContent = phrase;
  value.className = "stat-value " + (r.call.label === "bullish" ? "above" : r.call.label === "bearish" ? "below" : "");
  note.textContent = `${word[0].toUpperCase()}${word.slice(1)}: ${r.move >= 0 ? "+" : "−"}${Math.abs(r.move * 100).toFixed(1)}% vs ${pick.name} ` +
    `over ${r.days} shared days · how it did against its market, not its own label`;
  line.title = `${d.symbol} ÷ ${pick.symbol}, rebased, labelled by the same classifier as the badge ` +
    `(score ${r.call.score >= 0 ? "+" : "−"}${Math.abs(r.call.score).toFixed(2)}). Descriptive only.`;
  const btn = line.querySelector("button");
  btn.onclick = () => {
    if (typeof loadComparison === "function") loadComparison(pick.symbol, { asBase: true });
    const panel = document.getElementById("comparePanel");
    if (panel) {
      try { panel.open = true; } catch (err) { /* not a <details> yet */ }
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };
  line.hidden = false;
}

if (typeof module !== "undefined") module.exports = { benchmarkFor };
