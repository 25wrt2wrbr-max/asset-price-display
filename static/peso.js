"use strict";

/* ---- peso view ----
   A switch that redraws a US-dollar chart in pesos: each bar's close times
   the USD/PHP close of the same day (or the latest day before it -- never a
   later rate). Only what is drawn changes: the price, the window's move, the
   chart, the bar table and its CSV. The trend label, the quick stats, the
   profit odds, the alarms and the comparison panel stay on the dollar price,
   so a table row and its chart still carry one verdict (invariant 1). */

const PESO_KEY = "apd-peso-view";
const PESO_FX = "USDPHP=X";
let pesoOn = (() => { try { return typeof window !== "undefined" && localStorage.getItem(PESO_KEY) === "1"; } catch { return false; } })();
let pesoFx = null;          // the USD/PHP chart payload
let pesoFxError = null;
let pesoFxAt = 0;          // when the rate was last read
const PESO_FX_TTL = 15 * 60 * 1000;
let pesoMemo = { from: null, fx: null, price: null, out: null };

function pesoEligible(d) {
  if (!d || d.currency !== "USD" || d.yieldSeries || d.unit === "%") return false;
  const sym = String(d.symbol || "");
  return !sym.startsWith("^") && !/=X$/i.test(sym);
}

const sessionDayFormats = new Map();
function sessionDay(t, zone) {
  const timeZone = zone || "UTC";
  let fmt = sessionDayFormats.get(timeZone);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat("en-CA", {
      timeZone, year: "numeric", month: "2-digit", day: "2-digit",
    });
    if (sessionDayFormats.size >= 16) sessionDayFormats.delete(sessionDayFormats.keys().next().value);
    sessionDayFormats.set(timeZone, fmt);
  }
  const parts = Object.fromEntries(fmt.formatToParts(new Date(t * 1000)).map((v) => [v.type, v.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

/* [{day, c}] oldest first, one per FX session day, from the bars behind the
   window and the window itself, weekdays only (see below). */
function pesoRates(fx) {
  const zone = fx.timezone || "UTC";
  const byDay = new Map();
  // Weekend bars on the peso chart are Coins.ph's USDC/PHP, not the FX close;
  // they are left out, so a weekend carries Friday's rate.
  const proxy = new Set((fx.weekendProxy && fx.weekendProxy.stamps) || []);
  for (const p of [...(fx.historyTail || []), ...(fx.points || [])]) {
    if (!p || !Number.isFinite(p.t) || !(p.c > 0) || proxy.has(p.t)) continue;
    const day = sessionDay(p.t, zone);
    if (!byDay.has(day) || byDay.get(day).t <= p.t) byDay.set(day, { t: p.t, c: p.c });
  }
  return [...byDay.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([day, v]) => ({ day, c: v.c }));
}

/* A copy of `d` with every drawn price in pesos, or null when some bar has no
   rate on or before its day. */
function convertToPeso(d, fx) {
  const rates = pesoRates(fx);
  if (!rates.length) return null;
  const zone = d.timezone || "UTC";
  let j = -1;
  const points = [];
  for (const p of d.points || []) {
    const day = sessionDay(p.t, zone);
    while (j + 1 < rates.length && rates[j + 1].day <= day) j++;
    if (j < 0) return null;                       // no rate yet: never borrow a later one
    points.push({ ...p, c: p.c * rates[j].c });
  }
  if (!points.length) return null;
  const lastRate = rates[j];
  const out = { ...d, points, currency: "PHP", priceHint: Math.max(2, Number(d.priceHint) || 2) };
  if (Number.isFinite(d.marketPrice)) out.marketPrice = d.marketPrice * lastRate.c;
  out.peso = { rate: lastRate.c, day: lastRate.day };
  return out;
}

/* What the hero, chart and bar table draw: the payload, or its peso copy. */
function shownData() {
  const d = state.data;
  if (!pesoOn || !pesoEligible(d) || !pesoFx) return d;
  // The live quote moves the newest bar in place (main.js), so the newest
  // close is part of the key, not only the payload object.
  const pts = d.points || [];
  const price = pts.length ? pts[pts.length - 1].c : null;
  if (pesoMemo.from === d && pesoMemo.fx === pesoFx && pesoMemo.price === price) return pesoMemo.out || d;
  const out = convertToPeso(d, pesoFx);
  pesoMemo = { from: d, fx: pesoFx, price, out };
  return out || d;
}

async function ensurePesoFx() {
  try {
    pesoFx = await getChart(PESO_FX, { fresh: Boolean(pesoFx) });
    pesoFxAt = Date.now();
    pesoFxError = null;
  } catch (err) {
    pesoFxError = err.message || "the USD/PHP rate did not load";
  }
  if (pesoOn && pesoEligible(state.data)) renderAll();
}

function drawPesoToggle() {
  const btn = document.getElementById("pesoToggle");
  if (!btn) return;
  const d = state.data;
  btn.hidden = !pesoEligible(d);
  if (btn.hidden) return;
  // Remember last choice; default stays whatever the reader last set.
  btn.setAttribute("aria-pressed", String(pesoOn));
  btn.textContent = pesoOn ? "Show in dollars" : "Show in pesos";
  if (pesoOn && !pesoFx && !pesoFxError) ensurePesoFx();
  else if (pesoOn && pesoFx && Date.now() - pesoFxAt > PESO_FX_TTL) { pesoFxAt = Date.now(); ensurePesoFx(); }
}

/* The meta-line words for a chart shown in pesos, or for one that could not be. */
function pesoNote() {
  if (!pesoOn || !pesoEligible(state.data)) return "";
  const shown = shownData();
  if (shown && shown.peso) {
    return `shown in pesos at each day's USD/PHP close (latest ₱${shown.peso.rate.toFixed(4)}, ${shown.peso.day}); ` +
      "trend label, quick stats and alarms use the dollar price";
  }
  if (pesoFxError) return `peso view unavailable (${pesoFxError}); shown in dollars`;
  return pesoFx ? "peso view unavailable for these dates; shown in dollars" : "loading the USD/PHP rate";
}

(function wirePesoToggle() {
  if (typeof document === "undefined") return;
  const btn = document.getElementById("pesoToggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    pesoOn = !pesoOn;
    try { localStorage.setItem(PESO_KEY, pesoOn ? "1" : "0"); } catch {}
    if (pesoOn && !pesoFx) ensurePesoFx();
    renderAll();
  });
})();

if (typeof module !== "undefined") module.exports = { pesoEligible, pesoRates, convertToPeso, sessionDay };
