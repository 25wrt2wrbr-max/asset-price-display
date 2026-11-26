"use strict";

/* ------------------------------------------------------------------ *
 * Config
 * ------------------------------------------------------------------ */
let RANGE = "3mo";
const INTERVAL = "1d";
const ALLOWED_RANGES_CLIENT = ["1mo", "3mo", "6mo", "1y", "2y", "5y"];
function setRangeBinding(span) {
  if (!ALLOWED_RANGES_CLIENT.includes(span)) return;
  RANGE = span;
}
/* The watchlist row names its move by this span ("Three-month change"), so the
   label is derived from the one window every chart here draws rather than
   repeating the words in a second place. */
const SPAN_WORDS = {
  "1d": "One-day", "5d": "Five-day", "1mo": "One-month", "3mo": "Three-month",
  "6mo": "Six-month", "ytd": "Year-to-date", "1y": "One-year",
  "2y": "Two-year", "5y": "Five-year", "10y": "Ten-year",
};
const PLOT_W = 980, PLOT_H = 420;
const M = { top: 26, right: 104, bottom: 36, left: 66 };
const IW = PLOT_W - M.left - M.right;
const IH = PLOT_H - M.top - M.bottom;
const NS = "http://www.w3.org/2000/svg";

const state = {
  data: null,
  activeIndex: null,   // crosshair position
  loading: false,
  watch: [],           // [{symbol, name}] — the saved list, in display order
  watchQuotes: {},     // symbol -> {data} | {error} | {loading:true}
  chartSymbol: null,   // the symbol the plot is showing, for the refresh timer
  chartSeq: 0,         // guards a late answer from overwriting a newer one
  chartLoadedAt: 0,    // when the chart on screen was last answered
};

const el = {
  form: document.getElementById("form"),
  input: document.getElementById("symbol"),
  go: document.getElementById("go"),
  status: document.getElementById("status"),
  suggestions: document.getElementById("suggestions"),
  assetName: document.getElementById("assetName"),
  assetMeta: document.getElementById("assetMeta"),
  assetAbout: document.getElementById("assetAbout"),
  assetAboutBody: document.getElementById("assetAboutBody"),
  hero: document.getElementById("hero"),
  heroDelta: document.getElementById("heroDelta"),
  quickStats: document.getElementById("quickStats"),
  haltNote: document.getElementById("haltNote"),
  minInvest: document.getElementById("minInvest"),
  minInvestValue: document.getElementById("minInvestValue"),
  minInvestNote: document.getElementById("minInvestNote"),
  heroFees: document.getElementById("heroFees"),
  pseFees: document.getElementById("pseFees"),
  pseFeesValue: document.getElementById("pseFeesValue"),
  pseFeesNote: document.getElementById("pseFeesNote"),
  lastVolume: document.getElementById("lastVolume"),
  lastVolumeValue: document.getElementById("lastVolumeValue"),
  lastVolumeNote: document.getElementById("lastVolumeNote"),
  profitOdds: document.getElementById("profitOdds"),
  profitOddsValue: document.getElementById("profitOddsValue"),
  profitOddsNote: document.getElementById("profitOddsNote"),
  trendBadge: document.getElementById("trendBadge"),
  trendGlyph: document.getElementById("trendGlyph"),
  trendLabel: document.getElementById("trendLabel"),
  trendScore: document.getElementById("trendScore"),
  trendNote: document.getElementById("trendNote"),
  plot: document.getElementById("plot"),
  emptyPlot: document.getElementById("emptyPlot"),
  tableWrap: document.getElementById("tableWrap"),
  tableToggle: document.getElementById("tableToggle"),
  csvExport: document.getElementById("csvExport"),
  theme: document.getElementById("theme"),
  watchToggle: document.getElementById("watchToggle"),
  watchGlyph: document.getElementById("watchGlyph"),
  watchToggleLabel: document.getElementById("watchToggleLabel"),
  watchList: document.getElementById("watchList"),
  watchCount: document.getElementById("watchCount"),
  watchHint: document.getElementById("watchHint"),
  watchExport: document.getElementById("watchExport"),
  watchImport: document.getElementById("watchImport"),
  watchImportFile: document.getElementById("watchImportFile"),
  recentGrid: document.getElementById("recentGrid"),
  recentNote: document.getElementById("recentNote"),
  recentStatus: document.getElementById("recentStatus"),
  recentHealth: document.getElementById("recentHealth"),
  sectorGrid: document.getElementById("sectorGrid"),
  sectorNote: document.getElementById("sectorNote"),
  bearishGrid: document.getElementById("bearishGrid"),
  bearishNote: document.getElementById("bearishNote"),
  qualityNote: document.getElementById("qualityNote"),
  leaningGrid: document.getElementById("leaningGrid"),
  leaningNote: document.getElementById("leaningNote"),
};

/* ------------------------------------------------------------------ *
 * Formatting
 * ------------------------------------------------------------------ */
// Tables and chart readouts share a small set of locale formats.
const priceFormats = new Map();
function nf(digits, opts = {}) {
  const key = JSON.stringify([digits, opts]);
  let format = priceFormats.get(key);
  if (!format) {
    format = new Intl.NumberFormat(undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
      ...opts,
    });
    if (priceFormats.size >= 64) priceFormats.delete(priceFormats.keys().next().value);
    priceFormats.set(key, format);
  }
  return format;
}

function digitsFor(data) {
  const hint = Number(data && data.priceHint);
  return Number.isFinite(hint) ? Math.min(Math.max(hint, 0), 8) : 2;
}

/* Indices like ^GSPC or ^TNX are not dollar amounts, so no currency symbol. */
function showsCurrency(data) {
  return Boolean(data.currency) && !String(data.symbol).startsWith("^");
}

function formatPrice(value, data) {
  if (!Number.isFinite(value)) return "—";
  const digits = digitsFor(data);
  // A yield is a percentage, not an amount of money: it carries its unit in
  // `unit` rather than in `currency`, so no currency symbol is invented and
  // the number reads as the rate it is (6.234%).
  if (data && data.unit === "%") return nf(digits).format(value) + "%";
  if (showsCurrency(data)) {
    try {
      return nf(digits, { style: "currency", currency: data.currency }).format(value);
    } catch { /* unknown currency code — fall through to a plain number */ }
  }
  return nf(digits).format(value);
}

function formatDelta(value, data) {
  const digits = digitsFor(data);
  return (value >= 0 ? "+" : "−") + formatPrice(Math.abs(value), data).replace(/^[-−]/, "");
}

/* What a point on the chart *is*, in words. The server decides it
   (`lastBarBasis`) because the answer needs the exchange's own session clock --
   only the newest bar can be anything but a settled close, and which of the
   other three it is depends on the time of day the chart was read. This end
   only spells the answer out, the same way it spells out a trend label. */
const BASIS_WORDS = {
  live: "live",
  pre: "pre-market",
  after: "after-hours",
  // The peso pair does not trade at the weekend, so its Saturday and Sunday
  // points are Coins.ph's USDC/PHP price -- named, never spelled "close".
  weekend: "USDC/PHP",
};

function basisWord(basis, data) {
  if (BASIS_WORDS[basis]) return BASIS_WORDS[basis];
  // A fund has no session and no exchange: its one value a business day is a
  // net asset value the manager strikes, and calling that a "close" would name
  // a trade that never happened.
  return data && data.fundSeries ? "NAV" : "close";
}

/* Axis ticks are rounded numbers, so drop trailing zeros (300, 302.5, 305).
   Below $1 the fraction cap is useless -- it prints a PEPE tick of $0.0000035
   as "0" -- so micro ticks keep three significant digits instead. */
const axisFmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 });
const axisFmtMicro = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 3 });
const axisTickFmt = (tick) =>
  Math.abs(tick) >= 1 ? axisFmt.format(tick) : axisFmtMicro.format(tick);

const dayFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const fullFmt = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" });
const toDate = (ts) => new Date(ts * 1000);

/* A trading day, read in UTC. PSE bars are stamped at the Manila session open,
   which is 01:30 UTC, so the UTC date *is* the exchange's trading day whatever
   zone the reader is in -- the same reason `sessionDate` below reads stamps as
   UTC. Read in local time instead, a reader west of Manila would see the
   previous day named beside a session that has not happened yet. */
const utcDayFmt = new Intl.DateTimeFormat(undefined, {
  month: "short", day: "numeric", timeZone: "UTC",
});

/* A share count, abbreviated: nobody reads six digits at 21 px, and the exact
   figures live in the readout's tooltip. */
const shareFmt = new Intl.NumberFormat(undefined, {
  notation: "compact", maximumFractionDigits: 1,
});

/* When a payload was last retrieved live. A fresh answer only needs a clock
 * time ("Checked 3:14pm" — it was just now); a disk fallback can be days old,
 * so it names the date as well, and "today at 9:41pm" beats "Oct 3, 2026" for
 * a copy from this afternoon. `ts` is the server's `fetchedAt` epoch second. */
function retrievedAt(ts) {
  const d = new Date(ts * 1000);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString()
    ? "today at " + time
    : fullFmt.format(d) + " at " + time;
}

function csvCell(v) {
  if (v === null || v === undefined) return "";
  let s = String(v);
  if (/^[=+\-@\t\r]/.test(s) && !/^[+-]?\d+(?:\.\d+)?%?$/.test(s)) s = "'" + s;
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function downloadBlob(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadCsv(filename, headers, rows) {
  const lines = [headers.map(csvCell).join(",")];
  for (const row of rows) lines.push(row.map(csvCell).join(","));
  downloadBlob(filename, "\uFEFF" + lines.join("\r\n") + "\r\n", "text/csv;charset=utf-8");
}

/* ------------------------------------------------------------------ *
 * Data access
 * ------------------------------------------------------------------ */
/* "smooth" unless the reader asked the system for less motion. */
function scrollBehavior() {
  return window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

/* Plain words for the failures a reader can meet. The raw text still goes to
   the console, and an abort is passed through untouched (callers test it). */
function friendlyError(err, status) {
  const raw = err && err.message || "";
  let text = null;
  if (status === undefined) text = "Can't reach the app's server. Is it still running?";
  else if (status === 404 || /not found|unknown symbol|no chart|no data/i.test(raw)) {
    text = "Couldn't find that — try a company name or ticker (examples sit under the chart).";
  } else if (/^[A-Z]\w*(Error|Exception)\b/.test(raw)) text = "Something went wrong on the app's server. Try again in a minute.";
  else if (/^Request failed \(HTTP 5\d\d\)$/.test(raw)) text = "The price source didn't answer. Try again in a minute.";
  if (!text) return err;
  console.warn("request failed:", raw);
  // A network failure stays a TypeError: the server-down banner tests for it.
  const nice = status === undefined ? new TypeError(text) : new Error(text);
  nice.detail = raw;
  return nice;
}

/* Remember the last good GET body per URL so an unchanged answer can come
   back as HTTP 304 (server already sends ETag). Cap keeps memory flat. */
const etagMemo = new Map(); // url -> { etag, payload }
const ETAG_MEMO_MAX = 48;

async function requestJSON(url, signal, { etag = true } = {}) {
  const headers = {};
  const prior = etag ? etagMemo.get(url) : null;
  if (prior && prior.etag) headers["If-None-Match"] = prior.etag;
  let res;
  // no-store: the browser must not answer 304 from its own disk cache while
  // our in-memory memo is empty (a reload would then throw on an empty body).
  try { res = await fetch(url, { signal, headers, cache: "no-store" }); }
  catch (err) { throw err && err.name === "AbortError" ? err : friendlyError(err); }
  // 304 is not res.ok; reuse the last payload and skip JSON parse.
  if (res.status === 304) {
    if (prior) return prior.payload;
    // Unexpected 304 with nothing to reuse — ask once with no ETag header.
    if (etag) return requestJSON(url, signal, { etag: false });
    throw friendlyError(new Error("Request failed (HTTP 304)"), 304);
  }
  let payload = null;
  try { payload = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    throw friendlyError(new Error((payload && payload.error) || `Request failed (HTTP ${res.status})`), res.status);
  }
  const tag = res.headers.get("ETag");
  if (tag) {
    etagMemo.delete(url);
    etagMemo.set(url, { etag: tag, payload });
    while (etagMemo.size > ETAG_MEMO_MAX) etagMemo.delete(etagMemo.keys().next().value);
  }
  return payload;
}

/* `requestJSON` can only ask; the watchlist declaration is the one thing this
   page *tells* the server, so it needs a body and a POST. Same parse-and-throw
   rules as its sibling. */
async function postJSON(url, value) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  });
  let payload = null;
  try { payload = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    throw new Error((payload && payload.error) || `Request failed (HTTP ${res.status})`);
  }
  return payload;
}

/* ---- Chart memory and prefetch ----
   A chart payload the page already holds is drawn at once. Payloads come
   from three places: a chart load, a watchlist quote, and a *prefetch*,
   started when the pointer rests on a row or presses it -- so by the time
   the click lands the answer is usually already here. Entries are short
   lived (CHART_MEMO_MS), so a click never shows a reading older than the
   chart's own one-minute re-read would; a background refresh always asks
   the server. Capped, oldest dropped first. */
const CHART_MEMO_MS = 45 * 1000;
const CHART_MEMO_MAX = 40;
const chartMemo = new Map();      // KEY -> { data, at } or { promise }

function chartUrl(symbol) {
  return `/api/chart?symbol=${encodeURIComponent(symbol)}&range=${RANGE}&interval=${INTERVAL}`;
}
function memoKey(symbol) { return String(symbol || "").trim().toUpperCase(); }

function rememberChart(asked, data) {
  if (!data) return;
  const entry = { data, at: Date.now() };
  for (const key of new Set([memoKey(asked), memoKey(data.symbol)])) {
    if (!key) continue;
    chartMemo.delete(key);          // re-insert: Map order is the age order
    chartMemo.set(key, entry);
  }
  while (chartMemo.size > CHART_MEMO_MAX) chartMemo.delete(chartMemo.keys().next().value);
}

/* The chart payload for `symbol`: from memory when fresh, else one request
   shared by everyone asking at the same moment. `fresh` skips memory. */
function getChart(symbol, { fresh = false } = {}) {
  const key = memoKey(symbol);
  const hit = chartMemo.get(key);
  if (hit && hit.promise) return hit.promise;
  if (!fresh && hit && Date.now() - hit.at < CHART_MEMO_MS) return Promise.resolve(hit.data);
  const promise = requestJSON(chartUrl(symbol)).then(
    (data) => { rememberChart(symbol, data); return data; },
    (err) => { if (chartMemo.get(key) && chartMemo.get(key).promise === promise) chartMemo.delete(key); throw err; });
  chartMemo.set(key, { promise });
  return promise;
}

let prefetchBusy = false;   // one hover prefetch at a time

function prefetchChart(symbol, force) {
  if (navigator.connection?.saveData || !symbol || memoKey(symbol) === memoKey(state.chartSymbol)) return;
  if (prefetchBusy && !force) return;
  prefetchBusy = true;
  getChart(symbol).catch(() => {})    // a failed prefetch is retried by the click
    .finally(() => { prefetchBusy = false; });
}

/* Any element carrying `data-chart` prefetches on hover (after a short rest,
   so sweeping the pointer across a table does not fetch every row), at once
   on keyboard focus, and at once on press -- a click lands ~100 ms after
   the button goes down, which is time the request gets for free. */
(function wirePrefetch() {
  let timer = null, pending = null;
  const target = (ev) => ev.target && ev.target.closest && ev.target.closest("[data-chart]");
  document.addEventListener("pointerover", (ev) => {
    const t = target(ev);
    if (!t || ev.pointerType === "touch" || t === pending) return;
    clearTimeout(timer);
    pending = t;
    // 200 ms: a slow sweep down a table used to fetch row after row, each
    // a possible browser launch on the server.
    timer = setTimeout(() => {
      if (t.isConnected && t.matches(":hover") && !document.hidden) prefetchChart(t.dataset.chart);
      pending = null;
    }, 200);
  });
  document.addEventListener("pointerout", (ev) => {
    const t = target(ev);
    if (t && !t.contains(ev.relatedTarget)) { clearTimeout(timer); pending = null; }
  });
  document.addEventListener("pointerdown", (ev) => {
    const t = target(ev);
    if (t) prefetchChart(t.dataset.chart, true);
  }, { capture: true });
  document.addEventListener("focusin", (ev) => {
    const t = target(ev);
    if (t) prefetchChart(t.dataset.chart, true);
  });
})();

/* Fields that can move the badge, hero, odds or alarm — enough to decide a
   quiet refresh can skip the redraw without stringifying the whole payload. */
function chartQuietSig(d) {
  if (!d) return "";
  const t = d.trend || {};
  const pts = d.points || [];
  const last = pts.length ? pts[pts.length - 1] : null;
  const pp = d.profitProbability || {};
  const h = d.halt || {};
  const quality = Array.isArray(d.quality)
    ? d.quality.map((f) => (f && f.code) || "").join(",")
    : "";
  return [
    d.symbol, d.name, d.currency, d.lastBarBasis, d.fetchedAt, d.cached,
    pts.length, last && last.t, last && last.c, last && last.v,
    t.label, t.score, t.held, t.significance, t.pullback, t.lean, t.agreement,
    pp.probability, pp.cost,
    h.action, quality,
    d.livePrice, d.prePrice, d.afterPrice,
    d.minInvestment, d.boardLot, d.marketPrice,
    d.staleDays, d.staleBar,
  ].join("\0");
}

async function loadChart(symbol, { quiet = false, pushHistory = true, scanCall = null } = {}) {
  const wanted = symbol.trim();
  if (!wanted) return;
  const seq = ++state.chartSeq;
  const readSeq = ++watchReadSeq;

  // Refetch keeps the frame: hold the previous render at reduced opacity.
  // A background refresh is not an action the reader took, so it does not dim
  // the plot, does not say "Loading", and does not disable the button.
  if (state.data && !quiet) el.plot.classList.add("is-stale");
  if (!quiet) {
    setStatus("Loading " + wanted + "…");
    setBusy(true);
  }

  try {
    // A reader's click may draw from memory; a background refresh asks anew.
    const data = await getChart(wanted, { fresh: quiet });
    // A slow answer that a newer request has already replaced must not land:
    // the reader asked for something else while this was in flight.
    if (seq !== state.chartSeq) return;
    if (!quiet || state.chartSymbol !== data.symbol) state.scanCall = scanCall;
    const comparison = document.getElementById("scanComparison");
    if (comparison) {
      const scan = state.scanCall;
      const label = data.trend && data.trend.label;
      comparison.hidden = !(scan && label && scan.label !== label);
      if (!comparison.hidden) {
        const time = (seconds) => seconds ? " at " + new Date(seconds * 1000).toLocaleString() : "";
        const read = chartMemo.get(memoKey(wanted));
        comparison.textContent = "Scan" + time(scan.at) + " · " + scan.label +
          ". Chart " + (data.cached && data.fetchedAt ? "copy saved" + time(data.fetchedAt) :
          "read by browser" + time(read && read.at / 1000)) + " · " + label + ".";
      }
    }
    // A background re-read that came back the same changes nothing on screen.
    // A short signature of draw-facing fields avoids stringifying the whole
    // payload (points + historyTail) on every quiet poll.
    if (quiet && state.data && data && state.chartSymbol === data.symbol) {
      if (chartQuietSig(data) === chartQuietSig(state.data)) {
        state.chartLoadedAt = Date.now();
        return;
      }
    }
    state.data = data;
    state.chartSymbol = data.symbol;   // what the refresh clock re-asks for
    state.chartLoadedAt = Date.now();  // and when it last got an answer
    state.activeIndex = null;
    if (!quiet && pushHistory) {
      el.input.value = data.symbol;
      const hash = `#symbol=${encodeURIComponent(data.symbol)}`;
      if (location.hash !== hash) {
        try { history.pushState({ symbol: data.symbol }, "", hash); } catch {}
      }
    }
    // Keyed on the symbol as *asked for*, so an entry still filed under a raw
    // ticker is found; the payload then canonicalises it.
    setWatchQuote(wanted, quoteSummary(data), data, readSeq);  // selecting an asset refreshes its quote
    renderAll();
    if (typeof checkAlarms === "function") { checkAlarms(data); drawAlarmForm(); }  // armed alarms read every fresh price
    drawWatchList();                            // repaint the active-row highlight
    if (!quiet) scheduleReveal();               // and bring it into view if it is below the fold
    // A disk fallback arrives over a successful HTTP response — the server
    // answered, it just could not reach the source. Name the outage in the
    // status line (not styled as an error: the chart *did* load) so the reader
    // knows the bars they see stopped arriving at `fetchedAt`.
    // A copy served while a fresh fetch runs behind it (`revalidate`) is not
    // an outage: say nothing and ask again in a few seconds for the new bars.
    if (data.cached && data.fetchedAt && !data.revalidate) {
      setStatus(`Source unreachable — showing data last retrieved ${retrievedAt(data.fetchedAt)}.`);
      state.outageShown = true;
    } else if (!quiet || state.outageShown) {
      setStatus("");
      state.outageShown = false;
    }
    if (data.revalidate) {
      const sym = data.symbol;
      setTimeout(() => {
        if (state.chartSymbol === sym) loadChart(sym, { quiet: true, pushHistory: false });
      }, 4000);
    }
  } catch (err) {
    // A background refresh that failed changed nothing on screen, so it stays
    // quiet: it must not overwrite a message the reader is reading, and the
    // bars in front of them are still the ones that last loaded.
    if (!quiet || !state.data) setStatus(err.message, true);
  } finally {
    // Only the newest non-quiet request owns the busy state: a background
    // refresh never set it, and a superseded load hands it to its successor.
    if (!quiet && seq === state.chartSeq) {
      setBusy(false);
      el.plot.classList.remove("is-stale");
    }
  }
}
