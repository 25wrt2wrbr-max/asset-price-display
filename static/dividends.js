"use strict";

/* ---- ex-dividend markers (PSE names only) ----
   On its ex-dividend date a PSE stock opens lower by about the dividend.
   That drop is in the chart's bars, so a small "D" tick marks each ex-date
   inside the window, and a line under the chart names the dates and the next
   one coming. Dates come from PSE Edge (`/api/dividends`, pse_dividends.py),
   asked after the chart draws, so the chart never waits. Information only:
   the label is scored on the same bars as before. */

const dividendMemo = new Map();          // symbol -> {at, data}
const DIVIDEND_TTL = 6 * 60 * 60 * 1000;
const dividendState = { symbol: null, data: null };
let dividendTimer = null;

function isPseChartSymbol(symbol) {
  return /^(PSE:|EDGE:)/i.test(String(symbol || "")) || /\.PS$/i.test(String(symbol || ""));
}

const DIVIDEND_CURRENCY = { PHP: "₱", USD: "$", CAD: "CA$" };

/* "₱0.60 cash" / "stock dividend" / the source's own words when unreadable. */
function dividendAmountText(e) {
  if (!e) return "";
  const kind = String(e.kind || "").toLowerCase();
  if (kind !== "cash") return (kind ? kind + " dividend" : "dividend") + (e.rate ? ` (${e.rate})` : "");
  if (Number.isFinite(e.amount)) {
    // At least centavos (₱0.60), up to the six places PSE writes (₱1.30593750).
    const amount = e.amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 6 });
    return `${DIVIDEND_CURRENCY[e.currency] || (e.currency ? e.currency + " " : "")}${amount} cash`;
  }
  return "cash" + (e.rate ? ` (${e.rate})` : "");
}

/* 'YYYY-MM-DD' of a bar stamp in Manila, the day PSE dates its ex-dates in. */
const manilaDayFmt = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Manila", year: "numeric", month: "2-digit", day: "2-digit" });
function manilaDay(t) { return manilaDayFmt.format(new Date(t * 1000)); }

/* Each ex-date inside the drawn bars -> the first bar on or after it.
   Returns [{i, events}] (two dividends on one day share a marker). Dates
   before the first bar or after the last are not drawn. */
function dividendMarks(events, stamps) {
  const days = (stamps || []).map(manilaDay);
  const n = days.length;
  if (!n) return [];
  const byIndex = new Map();
  for (const e of events || []) {
    if (!e || !e.ex || e.ex < days[0] || e.ex > days[n - 1]) continue;
    const i = days.findIndex((day) => day >= e.ex);
    if (i < 0) continue;
    if (!byIndex.has(i)) byIndex.set(i, []);
    byIndex.get(i).push(e);
  }
  return [...byIndex.entries()].sort((a, b) => a[0] - b[0]).map(([i, evs]) => ({ i, events: evs }));
}

function dividendDayWords(iso) {
  const [y, m, d] = String(iso).split("-").map(Number);
  if (!y || !m || !d) return String(iso || "");
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(undefined, {
    timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
}

function dividendEventWords(e) {
  return `${dividendDayWords(e.ex)} (${dividendAmountText(e)})`;
}

/* The sentence under the chart, or "" when there is nothing to say.
   `firstDay` is the oldest drawn bar's Manila date: when the chart reaches
   back past the list's coverage, the sentence says where the dates start. */
function dividendSentence(data, marks, firstDay) {
  if (!data) return "";
  const bits = [];
  const partial = Boolean(data.coverFrom && firstDay && firstDay < data.coverFrom);
  if (marks && marks.length) {
    const evs = marks.flatMap((m) => m.events);
    const where = partial
      ? `Ex-dividend dates known from ${dividendDayWords(data.coverFrom)}`
      : "Ex-dividend in this window";
    bits.push(`${where}: ${evs.map(dividendEventWords).join(", ")}. ` +
      "On that day the price usually opens lower by about the dividend; that part of the move is the payout leaving the share, not a sign of weakness.");
  } else if (partial && data.complete !== false) {
    // Without the company list a common share's rows cannot be matched, so
    // "none" would be an outage stated as a fact: said only when complete.
    bits.push(`No ex-dividend date since ${dividendDayWords(data.coverFrom)}; earlier dates are not in the list.`);
  }
  if (data.next) {
    const pay = data.next.pay ? `, paid ${dividendDayWords(data.next.pay)}` : "";
    bits.push(`Next ex-date: ${dividendEventWords(data.next)}${pay}. Shares bought before that day get it.`);
  }
  if (!bits.length) return "";
  return bits.join(" ") + ` Source: ${data.source || "PSE Edge"}` +
    (data.cached && data.fetchedAt ? `, saved copy from ${new Date(data.fetchedAt * 1000).toLocaleString()}` : "") + ".";
}

/* Called by drawChart (static/chart.js) on every redraw. */
function drawDividendMarks(svg, d, coords) {
  const note = typeof document !== "undefined" ? document.getElementById("dividendNote") : null;
  const sym = String(d && d.symbol || "").toUpperCase();
  const data = dividendState.symbol === sym ? dividendState.data : null;
  if (!data || !coords || !coords.length) {
    if (note) note.hidden = true;
    return;
  }
  const marks = dividendMarks(data.events, coords.map((c) => c.point.t));
  const base = M.top + IH;
  for (const m of marks) {
    const x = coords[m.i].x;
    const g = svgEl("g", { class: "div-mark" });
    g.append(svgEl("line", { class: "div-mark-line", x1: x, x2: x, y1: base - 14, y2: base }));
    g.append(svgEl("circle", { class: "div-mark-dot", cx: x, cy: base - 20, r: 7 }));
    const t = svgEl("text", { class: "div-mark-text", x, y: base - 20,
      "text-anchor": "middle", "dominant-baseline": "central" });
    t.textContent = "D";
    const title = svgEl("title");
    title.textContent = "Ex-dividend " + m.events.map(dividendEventWords).join(", ");
    g.append(t, title);
    svg.append(g);
  }
  if (note) {
    const text = dividendSentence(data, marks, manilaDay(coords[0].point.t));
    note.textContent = text;
    note.hidden = !text;
  }
}

/* Asked after a short rest, and only while the chart is still on that name. */
function loadDividends(symbol) {
  const key = String(symbol || "").toUpperCase();
  clearTimeout(dividendTimer);
  if (!isPseChartSymbol(key)) {
    dividendState.symbol = key;
    dividendState.data = null;
    const note = document.getElementById("dividendNote");
    if (note) note.hidden = true;
    return;
  }
  if (dividendState.symbol !== key) { dividendState.symbol = key; dividendState.data = null; }
  const hit = dividendMemo.get(key);
  if (hit && Date.now() - hit.at < DIVIDEND_TTL) {
    if (dividendState.data !== hit.data) { dividendState.data = hit.data; redrawForDividends(key); }
    return;
  }
  dividendTimer = setTimeout(() => fetchDividends(symbol), 600);
}

function redrawForDividends(key) {
  if (String(state.chartSymbol || "").toUpperCase() !== key || !state.data) return;
  drawChart({ keep: true });
}

async function fetchDividends(symbol) {
  const key = String(symbol || "").toUpperCase();
  if (String(state.chartSymbol || "").toUpperCase() !== key) return;
  try {
    const data = await requestJSON("/api/dividends?symbol=" + encodeURIComponent(symbol));
    dividendMemo.delete(key);
    dividendMemo.set(key, { at: Date.now(), data });
    while (dividendMemo.size > 40) dividendMemo.delete(dividendMemo.keys().next().value);
    if (dividendState.symbol !== key) return;        // reader moved on
    dividendState.data = data;
    redrawForDividends(key);
  } catch {
    // No dates is no markers, never a wrong one.
  }
}

if (typeof module !== "undefined") {
  module.exports = { dividendMarks, dividendAmountText, dividendSentence, isPseChartSymbol, manilaDay };
}
