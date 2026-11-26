"use strict";

/* Open on a well-known symbol so the page is never a blank slate. */
loadWatch();
drawWatchList();
refreshWatchQuotes();
// Tell the warmer about this browser's list once at start (saveWatch also
// posts on every edit). Without this, a steady health poll never declares.
if (state.watch.length) declareWatch();
// Restore from the local server first when this browser has no saved list yet,
// then declare and file the reconnect baseline so a fresh browser does not wipe
// the server's copy.
restoreWatchFromServer().finally(() => pollHealth());

function symbolFromUrl() {
  const hash = location.hash.replace(/^#/, "");
  if (hash.startsWith("symbol=")) {
    try {
      const s = decodeURIComponent(hash.slice(7)).trim();
      if (s) return s;
    } catch {}
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
if (typeof restoreAlarmsFromServer === "function") restoreAlarmsFromServer();
if (typeof bindDesk === "function") bindDesk();
// Alarms are checked whether or not the tab is visible: they exist to speak up
// while the reader is looking elsewhere.
setInterval(pollAlarms, ALARM_POLL);
loadRecent();
loadSectors();
// Kept current while the tab is open, but only while it is visible -- a
// background tab polling upstream every fifteen minutes is waste, and the
// sweep behind this one is slower still: it reads a browser-backed Yahoo
// fetch for the whole Ondo shelf.
setInterval(() => { if (!document.hidden) loadRecent(); }, RECENT_TTL);
setInterval(() => { if (!document.hidden) loadSectors(); }, RECENT_TTL);
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
// While a Yahoo price is moving, ask `/api/quote` (one-minute bars, a 25 s
// server memo) every thirty seconds and move only the newest point and the
// figures read from it. The badge is not re-scored here: it changes with the
// next full re-read, which also replaces this patched point.
// Each miss starts a browser run upstream, so thirty seconds, not two: about
// 120 runs an hour for an open live chart instead of 1,800.
const QUOTE_POLL = 30 * 1000;  // was 10 s: 120 browser runs an hour, not 360
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
    // A move too small to change any printed figure redraws nothing: the
    // point is still updated, so the next real move draws from it.
    const sameText = typeof formatPrice === "function" &&
      formatPrice(q.price, d) === formatPrice(last.c, d);
    last.c = q.price;
    if (sameText) {  // nothing to redraw, but an alarm level may sit in between
      if (typeof checkAlarms === "function") checkAlarms(d);
      return;
    }
    renderAll({ live: true });
    // The same payload object was patched in place, so the comparison does not
    // see it as new: redraw it with the moved point.
    if (typeof renderComparison === "function" && typeof comparePrimary !== "undefined" &&
        comparePrimary === d && comparePeers.length) renderComparison();
    if (typeof checkAlarms === "function") { checkAlarms(d); drawAlarmForm(); }
  } catch {} finally { quoteBusy = false; }
}, QUOTE_POLL);
// A tab brought back to the front re-reads at once rather than showing a
// verdict up to fifteen minutes old.
document.addEventListener("visibilitychange", () => {
  // Skipped when the chart answered under a minute ago: quick tab switching
  // would otherwise re-read and redraw it on every switch.
  if (!document.hidden && state.chartSymbol && !state.loading &&
      Date.now() - (state.chartLoadedAt || 0) >= CHART_LIVE_TTL) {
    loadChart(state.chartSymbol, { quiet: true });
  }
});

/* ---- first-visit examples: a click charts the asset ---- */
document.addEventListener("click", (ev) => {
  const chip = ev.target.closest && ev.target.closest(".example-chip");
  if (!chip) return;
  el.input.value = chip.dataset.example;
  loadChart(chip.dataset.example);
});

/* ---- one-time welcome tip (localStorage) ---- */
(function wireWelcomeTip() {
  const tip = document.getElementById("welcomeTip");
  const dismiss = document.getElementById("welcomeDismiss");
  if (!tip || !dismiss) return;
  let seen = false;
  try { seen = localStorage.getItem("apd-welcome-v1") === "1"; } catch {}
  if (seen) return;
  tip.hidden = false;
  dismiss.addEventListener("click", () => {
    tip.hidden = true;
    try { localStorage.setItem("apd-welcome-v1", "1"); } catch {}
  });
})();

/* ---- section nav highlight + back-to-top ---- */
(function wireChrome() {
  const nav = document.getElementById("sectionNav");
  const toTop = document.getElementById("toTop");
  const links = nav ? Array.from(nav.querySelectorAll("a[href^='#']")) : [];
  const targets = links.map((a) => {
    const id = a.getAttribute("href").slice(1);
    return { a, el: document.getElementById(id) || document.getElementById(id.replace(/Heading$/, "")) };
  }).filter((t) => t.el);
  // Morning desk starts hidden; still watch its heading once it appears.
  if (typeof IntersectionObserver === "function" && targets.length) {
    const io = new IntersectionObserver((entries) => {
      let best = null;
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        if (!best || e.intersectionRatio > best.intersectionRatio) best = e;
      }
      // Clear when nothing is in the band (e.g. the footer gap), so a stale
      // highlight does not stick.
      for (const t of targets) {
        t.a.classList.toggle("is-active", Boolean(best) && t.el === best.target);
      }
    }, { rootMargin: "-20% 0px -55% 0px", threshold: [0.1, 0.35, 0.6] });
    for (const t of targets) io.observe(t.el);
  }
  if (toTop) {
    const syncTop = () => { toTop.hidden = window.scrollY < 480; };
    window.addEventListener("scroll", syncTop, { passive: true });
    syncTop();
    toTop.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: scrollBehavior() });
    });
  }
})();

/* ---- long section notes: two lines, with a button for the rest ----
   The note text is still the server's own sentence, whole; only its display
   is shortened. */
for (const id of ["recentNote", "leaningNote", "bearishNote"]) {
  const note = document.getElementById(id);
  if (!note) continue;
  note.classList.add("is-clamped");
  const more = document.createElement("button");
  more.type = "button";
  more.className = "note-more";
  more.textContent = "Show details";
  more.setAttribute("aria-expanded", "false");
  more.hidden = true;
  note.after(more);
  more.addEventListener("click", () => {
    const open = note.classList.toggle("is-clamped") === false;
    more.textContent = open ? "Show less" : "Show details";
    more.setAttribute("aria-expanded", String(open));
  });
  // Shown whenever the two-line cut really hides text (a short note on a
  // phone wraps too), and kept while the note is open.
  const sync = () => {
    more.hidden = note.classList.contains("is-clamped") && note.scrollHeight <= note.clientHeight + 1;
  };
  new MutationObserver(sync).observe(note, { childList: true, characterData: true, subtree: true });
  if (window.ResizeObserver) new ResizeObserver(sync).observe(note);
  sync();
}
