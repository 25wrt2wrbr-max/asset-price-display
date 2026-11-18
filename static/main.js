"use strict";

/* Open on a well-known symbol so the page is never a blank slate. */
loadWatch();
drawWatchList();
refreshWatchQuotes();
// Declares the list to the server and files the reconnect baseline. This is
// the *load-time* declaration: `saveWatch` only fires on a change, so without
// this a page that merely opens and reads never tells the server anything.
pollHealth();

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
// A tab brought back to the front re-reads at once rather than showing a
// verdict up to fifteen minutes old.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && state.chartSymbol && !state.loading) {
    loadChart(state.chartSymbol, { quiet: true });
  }
});
