"use strict";

/* Open on a well-known symbol so the page is never a blank slate. */
loadWatch();
drawWatchList();
refreshWatchQuotes();
// Restore from the local server first when this browser has no saved list yet,
// then declare and file the reconnect baseline so a fresh browser does not wipe
// the server's copy.
restoreWatchFromServer().finally(() => pollHealth());

function symbolFromUrl() {
  const hash = location.hash.replace(/^#/, "");
  if (hash.startsWith("symbol=")) {
    const s = decodeURIComponent(hash.slice(7)).trim();
    if (s) return s;
  }
  const q = new URLSearchParams(location.search).get("symbol");
  return (q && q.trim()) || "USDPHP=X";
}

const initialSymbol = symbolFromUrl();
el.input.value = initialSymbol;
loadChart(initialSymbol, { pushHistory: false });

window.addEventListener("popstate", () => {
  const sym = symbolFromUrl();
  if (sym && sym !== state.chartSymbol) {
    el.input.value = sym;
    loadChart(sym, { pushHistory: false });
  }
});
loadAlarms();
bindAlarmForm();
drawAlarms();
// Alarms are checked whether or not the tab is visible: they exist to speak up
// while the reader is looking elsewhere.
setInterval(pollAlarms, ALARM_POLL);
loadRecent();
// Kept current while the tab is open, but only while it is visible -- a
// background tab polling upstream every fifteen minutes is waste, and the
// sweep behind this one is slower still: it reads a browser-backed Yahoo
// fetch for the whole Ondo shelf.
setInterval(() => { if (!document.hidden) loadRecent(); }, RECENT_TTL);
// The chart on screen re-reads itself without being clicked, quietly, so the
// last bar (which carries live and extended-hours trading) and the trend
// badge scored on it do not sit frozen at whatever they said when the asset
// was opened. Skipped while a request of the reader's own is in flight: that
// one is about to land, and racing it would only make the newer answer lose.
//
// The clock ticks every minute and asks whether a read is due: one minute
// after the last answer while the newest bar is moving, fifteen once it has
// settled. Asking every minute means opening a live coin from a settled
// chart starts the fast clock at once instead of after the slow wait.
function chartIsLive() {
  const basis = state.data && state.data.lastBarBasis;
  return basis === "live" || basis === "pre" || basis === "after";
}
setInterval(() => {
  if (document.hidden || !state.chartSymbol || state.loading) return;
  const age = Date.now() - (state.chartLoadedAt || 0);
  if (age >= (chartIsLive() ? CHART_LIVE_TTL : CHART_TTL) - 1000) {
    loadChart(state.chartSymbol, { quiet: true });
  }
}, CHART_LIVE_TTL);
// The fast clock. The chart above is re-read once a minute and the server
// keeps it for a minute, so the headline price could trail the market by two.
// While a Yahoo price is moving, ask `/api/quote` (one-minute bars, a 3 s
// server memo) every two seconds and move only the newest point and the
// figures read from it. The badge is not re-scored here: it changes with the
// next full re-read, which also replaces this patched point.
const QUOTE_POLL = 2 * 1000;
let quoteBusy = false;
setInterval(async () => {
  const d = state.data;
  if (quoteBusy || document.hidden || !d || state.loading || !chartIsLive()) return;
  if (d.source !== "Yahoo" || d.cached || !d.points || !d.points.length) return;
  const seq = state.chartSeq, sym = state.chartSymbol;
  quoteBusy = true;
  try {
    const q = await requestJSON("/api/quote?symbol=" + encodeURIComponent(sym));
    if (seq !== state.chartSeq || sym !== state.chartSymbol || state.data !== d) return;
    const last = d.points[d.points.length - 1];
    if (!Number.isFinite(q.price) || q.price <= 0 || q.price === last.c) return;
    last.c = q.price;
    renderAll();
    if (typeof checkAlarms === "function") { checkAlarms(d); drawAlarmForm(); }
  } catch {} finally { quoteBusy = false; }
}, QUOTE_POLL);
// A tab brought back to the front re-reads at once rather than showing a
// verdict up to fifteen minutes old.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && state.chartSymbol && !state.loading) {
    loadChart(state.chartSymbol, { quiet: true });
  }
});
