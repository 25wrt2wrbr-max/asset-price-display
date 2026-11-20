"use strict";

/* ------------------------------------------------------------------ *
 * Config
 * ------------------------------------------------------------------ */
const RANGE = "3mo";
const INTERVAL = "1d";
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
  hero: document.getElementById("hero"),
  heroDelta: document.getElementById("heroDelta"),
  minInvest: document.getElementById("minInvest"),
  minInvestValue: document.getElementById("minInvestValue"),
  minInvestNote: document.getElementById("minInvestNote"),
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
  bearishGrid: document.getElementById("bearishGrid"),
  bearishNote: document.getElementById("bearishNote"),
  qualityNote: document.getElementById("qualityNote"),
  leaningGrid: document.getElementById("leaningGrid"),
  leaningNote: document.getElementById("leaningNote"),
};

/* ------------------------------------------------------------------ *
 * Formatting
 * ------------------------------------------------------------------ */
const nf = (digits, opts = {}) =>
  new Intl.NumberFormat(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    ...opts,
  });

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
async function requestJSON(url, signal) {
  const res = await fetch(url, { signal });
  let payload = null;
  try { payload = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    throw new Error((payload && payload.error) || `Request failed (HTTP ${res.status})`);
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

async function loadChart(symbol, { quiet = false, pushHistory = true } = {}) {
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
    const data = await requestJSON(
      `/api/chart?symbol=${encodeURIComponent(wanted)}&range=${RANGE}&interval=${INTERVAL}`
    );
    // A slow answer that a newer request has already replaced must not land:
    // the reader asked for something else while this was in flight.
    if (seq !== state.chartSeq) return;
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
    if (data.cached && data.fetchedAt) {
      setStatus(`Source unreachable — showing data last retrieved ${retrievedAt(data.fetchedAt)}.`);
    } else if (!quiet) {
      setStatus("");
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
