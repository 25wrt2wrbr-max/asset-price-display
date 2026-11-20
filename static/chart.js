"use strict";

/* Component keys in the order they are weighted, with readable names. Every
   bar the chart draws is scored; a component that cannot be measured is
   missing and filtered out. */
const TREND_PARTS = [
  ["momentum", "momentum"],
  ["trend", "trend"],
  ["efficiency", "efficiency"],
  ["range", "range"],
];

function drawTrend() {
  const t = state.data && state.data.trend;
  const badge = el.trendBadge;
  // A series whose source has stopped printing carries no verdict (the server
  // withholds it, see `staleDays`), and the note has to say why: a badge that
  // simply vanished would read as "nothing to report" on a line that ends
  // weeks ago, and an "Neutral · leaning bullish" over a frozen price is what
  // the reader objected to in the first place.
  const stopped = state.data && Number.isFinite(state.data.staleDays)
    ? `The source has not printed since ${state.data.staleBar || "the newest bar"} — ` +
      `the newest bar is ${state.data.staleDays === 1 ? "1 day" : state.data.staleDays + " days"} old. ` +
      `No three-month verdict and no profit odds are shown: a label read off a ` +
      `price that stopped moving is a label about that month, not about now. `
    : "";

  if (!t || !TREND_GLYPH[t.label]) {
    badge.hidden = true;
    // Cleared, not merely hidden -- the rule the odds line already follows. A
    // "Neutral · leaning bullish +0.26" left in the DOM behind a hidden badge is
    // one inspector away from being read as a claim about the chart on screen,
    // and for a stopped series it is a claim the chart explicitly refuses.
    badge.className = "trend";
    el.trendGlyph.textContent = "";
    el.trendLabel.textContent = "";
    el.trendScore.textContent = "";
    el.trendNote.textContent = stopped;
    el.trendNote.hidden = !stopped;
    document.getElementById("outlookNote").hidden = true;
    return;
  }

  badge.className = "trend " + t.label;
  el.trendGlyph.textContent = TREND_GLYPH[t.label];
  // A neutral window in a side's hold band says which way it leans; the
  // label itself stays Neutral (trend.py's `lean`, never a second verdict).
  // A label whose last two weeks ran against it says so (trend.py's
  // `pullback`). The label is unchanged; the tag only names the newest bars.
  el.trendLabel.textContent = badgePhrase(t);
  const pullWord = t.pullback && t.label !== "neutral";
  el.trendScore.textContent = (t.score >= 0 ? "+" : "−") + Math.abs(t.score).toFixed(3);
  badge.hidden = false;

  // Name the horizon and the inputs, so the verdict is auditable rather than
  // a number the reader has to trust.
  const parts = TREND_PARTS
    .filter(([key]) => t.components && Number.isFinite(t.components[key]))
    .map(([key, name]) => `${name} ${t.components[key] >= 0 ? "+" : "−"}${Math.abs(t.components[key]).toFixed(2)}`);
  const fit = t.components && Number.isFinite(t.components.r2)
    ? ` · fit R² ${t.components.r2.toFixed(2)}` : "";
  // The evidence behind the call, in words: a label needs the drift to clear
  // t 1.96 and holds while it stays above t 1.0 (see trend.py).
  const sig = Number.isFinite(t.significance)
    ? (Math.abs(t.significance) >= 99 ? "every bar moved the same way"
       : `drift t ${t.significance >= 0 ? "+" : "−"}${Math.abs(t.significance).toFixed(2)}`)
    : "";
  const evidence = t.label === "neutral"
    ? neutralExplanation(t) + " "
    : t.held
      ? `This ${TREND_WORD[t.label].toLowerCase()} trend has weakened but is holding: it stays until the drift falls below the hold band. `
      : "";
  const pullNote = pullWord ? pullNoteSentence(t.label) + " " : "";
  const liveNote = state.data.lastBarBasis && state.data.lastBarBasis !== "close"
    ? "The verdict includes the newest price and updates as it moves. " : "";
  // A bond chart needs one extra sentence, or the plot contradicts the badge
  // at a glance: the line is the yield, and the label is its bond-price
  // reading. The classifier's own call rides along as `yieldTrend`, so the
  // reader can see which of the two they are looking at.
  const raw = state.data.yieldTrend;
  const yieldNote = state.data.yieldSeries
    ? "This line plots the yield in percent" +
      (raw && TREND_WORD[raw.label]
        ? `; the classifier reads the yield itself as ${TREND_WORD[raw.label].toLowerCase()}` : "") +
      ". " + bondBadgeClause() + " "
    : "";
  // A fund's line is a net asset value, struck once a business day by its
  // manager -- not a traded price. Saying so keeps the hero figure and the
  // window's move from reading as an exchange quote.
  const fundNote = state.data.fundSeries
    ? "This line plots the fund's net asset value per unit (NAVPU), set once a business day; "
      + "there is no volume and no intraday price. "
    : "";
  el.trendNote.textContent = yieldNote + fundNote +
    `Past-${state.data.yieldSeries ? "yield" : "price"} trend over all ${t.bars} bars drawn; not a prediction or guarantee for the next three months. ` +
    evidence + pullNote + liveNote +
    (parts.length ? `Signals: ${parts.join(", ")}${fit}${sig ? " · " + sig : ""}. Score strength is not a probability.` : "");
  el.trendNote.hidden = !el.trendNote.textContent;
  const outlook = document.getElementById("outlookNote");
  const c = state.data.longTermContext;
  outlook.hidden = !c;
  if (c) {
    if (c.status !== "available") {
      outlook.textContent = `Longer-term context unavailable: ${c.reason}. No three-month forecast.`;
    } else {
      const comparisons = c.comparisons.map(x =>
        `${x.months}-month ${x.returnPct >= 0 ? "+" : "−"}${Math.abs(x.returnPct).toFixed(2)}%`).join(" · ");
      outlook.textContent = `Completed prices as of ${c.asOf}: ${comparisons}. ` +
        (c.confirmed ? "Both comparisons are positive. " : "Longer-term confirmation is mixed or absent. ") +
        "In a PSE historical holdout, bullish signals with both comparisons positive finished higher after three months in 47.9% of cases; 6.3% remained bullish throughout. Overlapping cases, surviving listings only; costs excluded. Not a forecast or guarantee.";
    }
  }
}

/* ---- SVG scaffolding ---- */
function svgEl(name, attrs = {}) {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

/* Round tick values to clean numbers. */
function niceTicks(min, max, count) {
  const span = max - min;
  if (!(span > 0)) return [min];
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) out.push(v);
  return out;
}

function drawChart() {
  const d = state.data;
  const pts = d.points;
  const n = pts.length;

  el.plot.textContent = "";
  el.plot.classList.remove("is-stale");

  const closes = pts.map((p) => p.c);
  let lo = Math.min(...closes);
  let hi = Math.max(...closes);
  if (hi === lo) {                       // flat series still needs a band
    const pad = Math.abs(lo || 1) * 0.01;
    lo -= pad; hi += pad;
  }
  const pad = (hi - lo) * 0.06;
  lo -= pad; hi += pad;

  const yOf = (v) => M.top + IH - ((v - lo) / (hi - lo)) * IH;
  const xOf = (i) => M.left + (n === 1 ? IW / 2 : (i / (n - 1)) * IW);

  const svg = svgEl("svg", {
    viewBox: `0 0 ${PLOT_W} ${PLOT_H}`,
    role: "img",
    tabindex: "0",
    "aria-label": `${d.name} (${d.symbol}) daily closing ` +
                  (d.yieldSeries ? "yield in percent" : "price") +
                  ", last three months. Use the table view for exact values. " +
                  "Arrow keys move between bars, Shift or Page Up and Page Down jump five, Home and End go to the ends.",
  });

  // --- gridlines + y ticks (hairline, solid, recessive) ---
  for (const tick of niceTicks(lo, hi, 5)) {
    const y = yOf(tick);
    if (y < M.top - 1 || y > M.top + IH + 1) continue;
    svg.append(svgEl("line", { class: "grid-line", x1: M.left, x2: M.left + IW, y1: y, y2: y }));
    const label = svgEl("text", {
      class: "tick-text", x: M.left - 10, y, "text-anchor": "end", "dominant-baseline": "middle",
    });
    label.textContent = axisTickFmt(tick);   // clean numbers, no trailing zeros
    svg.append(label);
  }

  // --- x ticks: five evenly spaced dates, always ending on the last point ---
  const tickCount = 5;
  const idxSet = new Set();
  for (let k = 0; k < tickCount; k++) {
    idxSet.add(Math.round((k / (tickCount - 1)) * (n - 1)));
  }
  idxSet.add(n - 1);
  for (const i of [...idxSet].sort((a, b) => a - b)) {
    const x = xOf(i);
    const anchor = i === 0 ? "start" : i === n - 1 ? "end" : "middle";
    const label = svgEl("text", {
      class: "tick-text", x, y: M.top + IH + 20, "text-anchor": anchor,
    });
    label.textContent = dayFmt.format(toDate(pts[i].t));
    svg.append(label);
  }

  // --- baseline ---
  svg.append(svgEl("line", {
    class: "axis-line", x1: M.left, x2: M.left + IW, y1: M.top + IH, y2: M.top + IH,
  }));

  // --- axis titles ---
  const yTitle = svgEl("text", { class: "axis-title", x: M.left - 10, y: M.top - 12, "text-anchor": "end" });
  // A bond chart's axis is a rate, not a price, and saying so is the only
  // place on the plot that names the unit: the line is the yield in percent.
  yTitle.textContent = d.yieldSeries
    ? "YIELD %"
    : showsCurrency(d) ? String(d.currency).toUpperCase() : "PRICE";
  svg.append(yTitle);

  // --- geometry ---
  const coords = pts.map((p, i) => ({ x: xOf(i), y: yOf(p.c), point: p }));
  const linePath = coords.map((c, i) => `${i ? "L" : "M"}${c.x.toFixed(2)} ${c.y.toFixed(2)}`).join(" ");

  // area wash at ~10% under the line (single series -> no legend needed)
  svg.append(svgEl("path", {
    class: "series-area",
    d: `${linePath} L ${coords[coords.length - 1].x.toFixed(2)} ${M.top + IH} ` +
       `L ${coords[0].x.toFixed(2)} ${M.top + IH} Z`,
  }));
  svg.append(svgEl("path", { class: "series-line", d: linePath }));

  // --- end marker + a single direct label (the endpoint) ---
  const lastC = coords[coords.length - 1];
  svg.append(svgEl("circle", { class: "end-dot", cx: lastC.x, cy: lastC.y, r: 4.5 }));

  // --- hover layer: crosshair, dot, tooltip, keyboard focus target ---
  const crosshair = svgEl("line", {
    class: "crosshair", y1: M.top, y2: M.top + IH, x1: 0, x2: 0, visibility: "hidden",
  });
  const hoverDot = svgEl("circle", { class: "hover-dot", r: 4.5, cx: 0, cy: 0, visibility: "hidden" });
  svg.append(crosshair, hoverDot);

  // one transparent target spanning the plot so the pointer only has to be close
  const capture = svgEl("rect", {
    x: M.left, y: M.top, width: IW, height: IH, fill: "transparent", style: "cursor:crosshair",
  });
  svg.append(capture);

  el.plot.append(svg);

  const tooltip = document.createElement("div");
  tooltip.className = "tooltip";
  tooltip.hidden = true;
  el.plot.append(tooltip);

  // endpoint label lives in the SVG so it tracks the plot's own scale
  const endLabel = svgEl("text", {
    class: "end-label", x: lastC.x + 14, y: lastC.y, "dominant-baseline": "middle",
  });
  endLabel.textContent = formatPrice(lastC.point.c, d);
  svg.append(endLabel);

  /* ---- interaction ---- */
  // The peso pair's Saturday and Sunday points are Coins.ph's USDC/PHP price
  // (`weekendProxy.stamps`), not an interbank close. The server names them so
  // this readout can say whose number each one is.
  const proxyStamps = new Set((d.weekendProxy && d.weekendProxy.stamps) || []);
  const indexFromEvent = (ev) => {
    const box = svg.getBoundingClientRect();
    const mx = ((ev.clientX - box.left) / box.width) * PLOT_W;
    const ratio = (mx - M.left) / IW;
    return Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1))));
  };

  const showAt = (i) => {
    const c = coords[i];
    state.activeIndex = i;

    crosshair.setAttribute("x1", c.x);
    crosshair.setAttribute("x2", c.x);
    crosshair.setAttribute("visibility", "visible");
    hoverDot.setAttribute("cx", c.x);
    hoverDot.setAttribute("cy", c.y);
    hoverDot.setAttribute("visibility", "visible");

    tooltip.textContent = "";
    const dateLine = document.createElement("div");
    dateLine.className = "tt-date";
    dateLine.textContent = fullFmt.format(toDate(c.point.t));

    const row = document.createElement("div");
    row.className = "tt-row";
    const key = document.createElement("span");
    key.className = "tt-key";
    const value = document.createElement("span");
    value.className = "tt-value";
    value.textContent = formatPrice(c.point.c, d);   // value leads
    const label = document.createElement("span");
    label.className = "tt-label";
    // Every bar but the newest is the session's own close. The newest may not
    // be -- it can be the price trading now or the last extended-hours print --
    // and `lastBarBasis` is the server's call on which, so a post-market print
    // never reads as the official close. A weekend bar is neither: it is the
    // stablecoin's price for a day the FX week did not trade.
    label.textContent = proxyStamps.has(c.point.t)
      ? basisWord("weekend", d)
      : i === n - 1 ? basisWord(d.lastBarBasis, d) : basisWord(null, d);
    row.append(key, value, label);

    tooltip.append(dateLine, row);
    tooltip.hidden = false;

    const box = svg.getBoundingClientRect();
    const scale = box.width / PLOT_W;
    let left = c.x * scale;
    const halfTip = tooltip.offsetWidth / 2;
    left = Math.max(halfTip + 4, Math.min(box.width - halfTip - 4, left));
    tooltip.style.left = left + "px";
    tooltip.style.top = (c.y * (box.height / PLOT_H)) + "px";
  };

  const clear = () => {
    state.activeIndex = null;
    crosshair.setAttribute("visibility", "hidden");
    hoverDot.setAttribute("visibility", "hidden");
    tooltip.hidden = true;
  };

  capture.addEventListener("pointermove", (ev) => showAt(indexFromEvent(ev)));
  capture.addEventListener("pointerleave", clear);
  svg.addEventListener("blur", clear);

  // keyboard: the same readout as hover, reachable without a pointer
  svg.addEventListener("keydown", (ev) => {
    const cur = state.activeIndex === null ? n - 1 : state.activeIndex;
    let next = null;
    const step = ev.shiftKey ? 5 : 1;
    if (ev.key === "ArrowRight") next = Math.min(n - 1, cur + step);
    else if (ev.key === "ArrowLeft") next = Math.max(0, cur - step);
    else if (ev.key === "PageDown") next = Math.max(0, cur - 5);
    else if (ev.key === "PageUp") next = Math.min(n - 1, cur + 5);
    else if (ev.key === "Home") next = 0;
    else if (ev.key === "End") next = n - 1;
    else if (ev.key === "Escape") { clear(); return; }
    if (next === null) return;
    ev.preventDefault();
    showAt(next);
  });
}

/* ---- table view: the WCAG-clean twin of the chart ---- */
function drawTable() {
  const d = state.data;
  const pts = d.points;
  const proxyStamps = new Set((d.weekendProxy && d.weekendProxy.stamps) || []);
  const hasPts = Boolean(pts && pts.length);
  el.tableToggle.hidden = !hasPts;
  el.csvExport.hidden = !hasPts;

  el.tableWrap.textContent = "";
  const table = document.createElement("table");

  const caption = document.createElement("caption");
  // The newest row can be a price that has not settled (live, or the last
  // extended-hours print). Say so here too: the table is the keyboard- and
  // screen-reader-clean twin of the chart, and its "Close" heading would
  // otherwise be the only thing that column ever said.
  const basis = BASIS_WORDS[d.lastBarBasis];
  caption.textContent = `${d.name} (${d.symbol}) — daily closes, last three months.` +
    (basis
      ? ` The newest row is ${basis === "after-hours" ? "an" : "a"} ${basis} price, not a settled close.`
      : "") +
    (d.weekendProxy
      ? ` Saturday and Sunday rows are Coins.ph's USDC/PHP price: the peso pair does not trade at the weekend.`
      : "");
  table.append(caption);

  const thead = document.createElement("thead");
  const hrow = document.createElement("tr");
  for (const heading of ["Date", "Close", "Change"]) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = heading;
    hrow.append(th);
  }
  thead.append(hrow);
  table.append(thead);

  const tbody = document.createElement("tbody");
  pts.forEach((p, i) => {
    const tr = document.createElement("tr");
    const date = document.createElement("td");
    date.textContent = fullFmt.format(toDate(p.t));

    const close = document.createElement("td");
    close.textContent = formatPrice(p.c, d);
    // The newest row is the point the chart's tooltip labels: when that figure
    // is live or an extended-hours print, the cell says so on hover instead of
    // passing under a "Close" heading it does not answer to. A weekend row of
    // the peso pair is the stablecoin's price, and says that instead.
    if (proxyStamps.has(p.t)) {
      close.title = basisWord("weekend", d);
    } else if (i === pts.length - 1 && BASIS_WORDS[d.lastBarBasis]) {
      close.title = basisWord(d.lastBarBasis, d);
    }

    const change = document.createElement("td");
    change.textContent = i === 0 ? "—" : formatDelta(p.c - pts[i - 1].c, d);

    tr.append(date, close, change);
    tbody.append(tr);
  });
  table.append(tbody);

  el.tableWrap.append(table);
}

function exportChartCsv() {
  const d = state.data;
  if (!d || !d.points || !d.points.length) return;
  const pts = d.points;
  const proxyStamps = new Set((d.weekendProxy && d.weekendProxy.stamps) || []);
  const unit = d.unit || d.currency || "";
  const rows = pts.map((p, i) => {
    const change = i === 0 ? "" : Number((p.c - pts[i - 1].c).toFixed(8));
    let note = "";
    if (proxyStamps.has(p.t)) note = basisWord("weekend", d);
    else if (i === pts.length - 1 && BASIS_WORDS[d.lastBarBasis]) note = basisWord(d.lastBarBasis, d);
    return [sessionDate(p.t), p.c, change, unit, note];
  });
  const slug = String(d.symbol || "chart").replace(/[^A-Za-z0-9._-]+/g, "_");
  downloadCsv(`${slug}-${RANGE}.csv`, ["Date", "Close", "Change", "Unit", "Note"], rows);
}
