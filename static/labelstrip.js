"use strict";

/* ---- past-year label strip ----
   A thin band under the chart: one slice per trading bar of the past year,
   coloured by the label that bar carried (`/api/labelhistory`, which re-reads
   the same classifier on each past three-month window -- see labelhistory.py).
   Loaded after the chart draws, as its own request, so the chart never waits
   for it. History only: how often the label happened, never odds. */

const labelStripMemo = new Map();      // symbol -> {at, data}
const LABEL_STRIP_TTL = 30 * 60 * 1000;
const LABEL_STRIP_WORD = { bullish: "Bullish", bearish: "Bearish", neutral: "Neutral" };

/* Runs of equal labels: [{label, from, to}] with bar indices, None kept as null. */
function labelRuns(labels) {
  const runs = [];
  (labels || []).forEach((x, i) => {
    const last = runs[runs.length - 1];
    if (last && last.label === x) last.to = i;
    else runs.push({ label: x, from: i, to: i });
  });
  return runs;
}

function labelStripSentence(h) {
  const s = h.summary || {};
  const c = s.counts || {};
  if (!s.bars) return "";
  const pct = (k) => Math.round((c[k] || 0) / s.bars * 100);
  const bits = [
    `Past year: bullish on ${c.bullish || 0} of ${s.bars} bars (${pct("bullish")}%), ` +
    `bearish on ${c.bearish || 0} (${pct("bearish")}%), neutral on ${c.neutral || 0}`,
    `${s.changes} label change${s.changes === 1 ? "" : "s"}`,
  ];
  const longest = s.longest || {};
  if (longest.bullish) bits.push(`longest bullish run ${longest.bullish} bars`);
  if (longest.bearish) bits.push(`longest bearish run ${longest.bearish} bars`);
  return bits.join(" · ") + ". What happened, not odds.";
}

function drawLabelStrip(h) {
  const box = document.getElementById("labelHistory");
  if (!box) return;
  const labels = h && h.labels;
  if (!labels || !labels.length || !(h.summary && h.summary.bars)) { box.hidden = true; return; }
  // The oldest bars have no three-month window behind them (no label). They
  // drew as an empty gap at the left, so the strip starts at the first label.
  let start = labels.findIndex((x) => x != null);
  if (start < 0) start = 0;
  const n = labels.length - start;
  const svg = svgEl("svg", {
    class: "label-strip", viewBox: `0 0 ${n} 10`, preserveAspectRatio: "none",
    role: "img", "aria-label": labelStripSentence(h),
  });
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: h.timezone || "UTC", year: "numeric", month: "2-digit", day: "2-digit" });
  const day = (i) => {
    const t = h.t && h.t[i + start];
    return t ? fmt.format(new Date(t * 1000)) : "";
  };
  for (const r of labelRuns(labels.slice(start))) {
    const rect = svgEl("rect", {
      x: r.from, y: 0, width: r.to - r.from + 1, height: 10,
      class: "strip-" + (r.label || "none"),
    });
    const title = svgEl("title", {});
    const bars = r.to - r.from + 1;
    title.textContent = `${r.label ? LABEL_STRIP_WORD[r.label] : "Not enough history"}: ` +
      `${day(r.from)} to ${day(r.to)} (${bars} bar${bars === 1 ? "" : "s"})`;
    rect.append(title);
    svg.append(rect);
  }
  const ends = document.createElement("div");
  ends.className = "label-strip-ends";
  const a = document.createElement("span");
  a.textContent = day(0);
  const b = document.createElement("span");
  b.textContent = day(n - 1);
  ends.append(a, b);
  const note = document.createElement("p");
  note.className = "stat-note";
  note.textContent = labelStripSentence(h) +
    (h.inverted ? " Read as the bond price, like the badge." : "") +
    " Each bar is labelled from the three months before it." +
    (h.cached && h.fetchedAt && !h.revalidate ? ` Source unreachable; bars last retrieved ${new Date(h.fetchedAt * 1000).toLocaleString()}.` : "");
  box.replaceChildren(svg, ends, note);
  if (h.windowStarts && h.closes && h.tailTimes) {
    const panel = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Inspect a historical trend call";
    const slider = document.createElement("input");
    slider.type = "range";
    slider.setAttribute("aria-label", "Historical bar");
    slider.min = start;
    slider.max = labels.length - 1;
    slider.value = box.dataset.historyAsset === h.symbol && h.t.includes(Number(box.dataset.historyTime))
      ? h.t.indexOf(Number(box.dataset.historyTime)) : slider.max;
    const caption = document.createElement("p");
    caption.setAttribute("aria-live", "polite");
    const chart = svgEl("svg", {viewBox: "0 0 400 70", preserveAspectRatio: "none",
      "aria-hidden": "true", class: "history-window"});
    function selectBar() {
      const i = Number(slider.value);
      const first = h.windowStarts[i];
      const end = h.offset + i;
      const values = first == null ? [] : h.closes.slice(first, end + 1);
      const date = day(i - start);
      slider.setAttribute("aria-valuetext", date);
      box.dataset.historyAsset = h.symbol;
      box.dataset.historyTime = h.t[i];
      chart.replaceChildren();
      if (!values.length || !labels[i]) {
        caption.textContent = date + " · Insufficient history";
        return;
      }
      let verdict = LABEL_STRIP_WORD[labels[i]];
      if (labels[i] !== "neutral") {
        if (h.held[i]) verdict += " (held in the hold band)";
        else if (labels[i-1] && labels[i-1] !== labels[i]) verdict += " (new call)";
      }
      const unit = h.inverted ? "%" : h.currency || h.unit || "";
      caption.textContent = date + " · " + verdict + " · " + (h.inverted ? "Yield " : "Close ") +
        h.closes[end] + " " + unit + " · " + values.length + " bars";
      const startTime = first < h.offset ? h.tailTimes[first] : h.t[first - h.offset];
      caption.textContent += " from " + fmt.format(new Date(startTime * 1000));
      const lo = Math.min(...values), span = Math.max(...values) - lo;
      const line = values.map((v, j) => [j * 398 / Math.max(1, values.length - 1) + 1,
        span ? 67 - 64 * (v - lo) / span : 35].join(",")).join(" ");
      chart.append(svgEl("polyline", {points: line, stroke: "currentColor", fill: "none",
        "stroke-width": 2, "vector-effect": "non-scaling-stroke"}));
    }
    panel.open = box.dataset.historyOpen === h.symbol;
    panel.ontoggle = () => { if (panel.isConnected) box.dataset.historyOpen = panel.open ? h.symbol : ""; };
    slider.oninput = selectBar;
    svg.onclick = (event) => {
      const bounds = svg.getBoundingClientRect();
      slider.value = start + Math.min(n - 1, Math.max(0, Math.floor(n * (event.clientX - bounds.left) / bounds.width)));
      panel.open = true;
      selectBar();
    };
    panel.append(summary, slider, caption, chart);
    box.append(panel);
    selectBar();
  }
  box.hidden = false;
}

let labelStripTimer = null;
let labelStripPending = null;
let labelStripVisible = true;
let labelStripIO = null;

(function wireLabelStripVisibility() {
  // Node unit tests load this file without a document.
  if (typeof document === "undefined") return;
  // Watch the plot, not #labelHistory: the strip starts hidden, and a hidden
  // box never intersects, which would starve the first fetch forever.
  const plot = document.getElementById("plot");
  if (!plot || typeof IntersectionObserver !== "function") return;
  labelStripIO = new IntersectionObserver((entries) => {
    for (const e of entries) {
      labelStripVisible = e.isIntersecting;
      if (labelStripVisible && labelStripPending) {
        const sym = labelStripPending;
        labelStripPending = null;
        loadLabelStrip(sym);
      }
    }
  }, { rootMargin: "80px 0px" });
  labelStripIO.observe(plot);
})();

/* Asked after a short rest, and only if the chart is still on that asset:
   stepping through table rows must not queue a year of bars per row.
   Deferred while the strip is scrolled off-screen (IntersectionObserver). */
function loadLabelStrip(symbol) {
  const box = document.getElementById("labelHistory");
  if (!box || !symbol) return;
  const key = String(symbol).toUpperCase();
  if (box.dataset.symbol !== key) box.hidden = true;
  if (!labelStripVisible) {
    labelStripPending = symbol;
    return;
  }
  clearTimeout(labelStripTimer);
  labelStripTimer = setTimeout(() => {
    if (String(state.chartSymbol || "").toUpperCase() === key) fetchLabelStrip(symbol);
  }, 500);
}

async function fetchLabelStrip(symbol) {
  const box = document.getElementById("labelHistory");
  if (!box || !symbol) return;
  const key = String(symbol).toUpperCase();
  if (box.dataset.symbol !== key) box.hidden = true;    // never show another asset's strip
  box.dataset.symbol = key;
  // The strip's newest slice is the badge's label. When the badge has moved
  // on since the strip was read, the strip is read again.
  const badge = state.data && state.data.trend && state.data.trend.label;
  const agrees = (h) => !badge || !h.labels || !h.labels.length || h.labels[h.labels.length - 1] === badge;
  const hit = labelStripMemo.get(key);
  // `hit.badge` is the badge a copy was fetched under: one re-read per badge
  // change, not one per redraw, if the two still differ afterwards.
  if (hit && Date.now() - hit.at < LABEL_STRIP_TTL && (agrees(hit.data) || hit.badge === badge)) {
    drawLabelStrip(hit.data);
    return;
  }
  try {
    const fresh = Boolean(hit);   // a stale or disagreeing copy: ask the server anew
    const data = await requestJSON("/api/labelhistory?symbol=" + encodeURIComponent(symbol) +
      (fresh ? "&fresh=1" : ""));
    labelStripMemo.delete(key);
    labelStripMemo.set(key, { at: Date.now(), data, badge });
    // Kept to the 40 most recent symbols, so a long session of browsing
    // does not hold every year of labels it ever opened.
    while (labelStripMemo.size > 40) labelStripMemo.delete(labelStripMemo.keys().next().value);
    if (String(state.chartSymbol || "").toUpperCase() !== key) return;   // reader moved on
    drawLabelStrip(data);
  } catch {
    if (String(state.chartSymbol || "").toUpperCase() === key) box.hidden = true;
  }
}

if (typeof module !== "undefined") module.exports = { labelRuns, labelStripSentence };
