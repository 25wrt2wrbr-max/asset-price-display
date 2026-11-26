"use strict";

/* ------------------------------------------------------------------ *
 * Suggestions
 * ------------------------------------------------------------------ */
const closeSuggestions = bindAssetSearch(el.input, el.suggestions, el.form, loadChart);

/* ------------------------------------------------------------------ *
 * Render
 * ------------------------------------------------------------------ */
function setStatus(msg, isError = false) {
  el.status.textContent = msg || "";
  el.status.classList.toggle("error", Boolean(isError));
}

function setBusy(busy) {
  state.loading = busy;
  el.go.disabled = busy;
  el.go.textContent = busy ? "Loading…" : "Show chart";
}

// `live`: a price tick on the chart already open. It must not close the
// search list the reader is typing in, drop the hovered bar, or rebuild a
// bar table nobody is looking at.
function fillAssetMeta(d) {
  el.assetName.textContent = d.name;
  // Short line under the title; longer source notes sit in "About this price".
  const shortBits = [d.symbol, d.exchange, d.type ? d.type.toLowerCase() : ""].filter(Boolean);
  if (Number.isFinite(d.coinRank)) shortBits.splice(2, 0, `rank ${d.coinRank}`);
  el.assetMeta.textContent = shortBits.join(" · ") || "—";

  const more = [];
  // Crypto rows carry the coin's market-cap rank, which is what tells the coin
  // you meant from a same-ticker collision, and always name the source, so a
  // symbol rerouted away from Yahoo is never mistaken for Yahoo's answer.
  if (d.source) more.push(`via ${d.source}`);
  // The bars before the listing are not the exchange's: they come from a
  // pre-IPO market, rescaled by the server so the last one closes at the IPO
  // price. Named here, so the earlier stretch is never read as Nasdaq history
  // and the level looked up as if it were.
  if (d.preipo && d.preipo.bars) {
    const price = Number(d.preipo.ipoPrice);
    more.push(`bars before ${d.preipo.anchor} via ${d.preipo.venue},`
      + (Number.isFinite(price) ? ` scaled to the $${price.toFixed(2)} IPO price` : " rescaled"));
  }
  // The newest bar is not always a closing price: it can be the price trading
  // now or the last extended-hours print. Name which, so the hero figure is
  // never read as a settled close it is not. A payload from before this field
  // existed still says what it could (`extendedLastBar`); once the server has
  // spoken, its word is the only one -- "close" needs no note, and the fold
  // having *run* is not the same as the bar carrying an after-hours price.
  const basisNote = {
    live: "last bar is a live price",
    pre: "last bar is a pre-market price",
    after: "last bar is the after-hours price",
    weekend: "last bar is Coins.ph's USDC/PHP weekend price",
  }[d.lastBarBasis];
  if (basisNote) more.push(basisNote);
  else if (!d.lastBarBasis && d.extendedLastBar) more.push("last bar includes after-hours");
  // A series the source has stopped printing: the hero figure above is that old
  // bar's close, not a price now, and the line has to say so before the reader
  // reads it as today's. The server decides it (`staleDays`), by the same rule
  // the recent table uses to leave such a name off the table.
  if (Number.isFinite(d.staleDays)) {
    more.push(`newest bar is ${d.staleDays === 1 ? "1 day" : d.staleDays + " days"} old`
      + (d.staleBar ? ` (${d.staleBar})` : ""));
  }
  // The peso pair's Saturdays and Sundays come from Coins.ph's USDC/PHP book,
  // because the FX week is shut. Say it whenever such bars are on screen, not
  // only when the newest one is: a weekend point in the middle of a three-month
  // chart is still the stablecoin's price.
  if (d.weekendProxy) {
    const n = (d.weekendProxy.stamps || []).length;
    more.push(n === 1
      ? "1 weekend bar is Coins.ph USDC/PHP"
      : `${n} weekend bars are Coins.ph USDC/PHP`);
  }
  // A disk fallback is the same shape as a live answer with a date attached:
  // the chart draws, and the meta line says when the bars were really fetched.
  if (d.cached && d.fetchedAt) more.push("last retrieved " + retrievedAt(d.fetchedAt));
  const pesoWords = typeof pesoNote === "function" ? pesoNote() : "";
  if (pesoWords) more.push(pesoWords);
  if (d.halt && d.halt.action) {
    more.push(d.halt.active ? `PSE ${d.halt.action.toLowerCase()} active` : `PSE ${d.halt.action.toLowerCase()} today`);
  }
  if (el.assetAbout && el.assetAboutBody) {
    if (more.length) {
      el.assetAboutBody.textContent = more.join(" · ");
      el.assetAbout.hidden = false;
    } else {
      el.assetAboutBody.textContent = "";
      el.assetAbout.hidden = true;
    }
  }
}

function renderAll(opts = {}) {
  const d = state.data;
  if (!d) return;
  const live = Boolean(opts.live);
  if (!live) closeSuggestions();

  // A live quote tick only moves the newest close: skip meta, badge, fees and
  // fold-outs so the 30 s clock does not rebuild work that cannot change.
  if (!live) fillAssetMeta(d);

  // What is drawn: the payload, or its peso copy (static/peso.js). The meta
  // line above and everything after the chart keep the payload itself.
  const v = typeof shownData === "function" ? shownData() : d;
  const pts = v.points;
  const last = pts[pts.length - 1];
  // The first bar the plot draws: the other end of the window the badge and
  // every table row are judged on.
  const first = pts.length > 1 ? pts[0] : null;

  // hero figure — proportional figures, never tabular-nums at display size
  el.hero.hidden = false;
  el.hero.textContent = formatPrice(last.c, v);

  // The delta is the *window's* move -- the first drawn close to the latest --
  // not the last session's. It is the same pair the watchlist row and the
  // recent table measure, so the headline figure and the rows cannot disagree
  // about the three months. The label names the starting bar, because a bare
  // "+4.12%" beside a price otherwise reads as today.
  if (first && first.c !== 0) {
    const diff = last.c - first.c;
    const pct = (diff / first.c) * 100;
    const up = diff >= 0;
    const from = dayFmt.format(toDate(first.t));
    // A yield is a rate in percent, so its change is a move in percentage
    // points, not a percentage of money -- "+0.583%" would read as a relative
    // change of an already-relative figure. The number is the plotted line's
    // move (the yield), while the badge reads a bond price; the trend note says
    // why a rising yield is bearish.
    const isYield = Boolean(d.yieldSeries || d.unit === "%");
    el.heroDelta.hidden = false;
    el.heroDelta.textContent = "";
    el.heroDelta.title = isYield
      ? `${SPAN_WORDS[RANGE] || "Window"} move in the plotted yield, ${from} to the latest bar`
      : `${SPAN_WORDS[RANGE] || "Window"} change, ${from} to the latest close`;

    const glyph = document.createElement("span");
    glyph.setAttribute("aria-hidden", "true");
    glyph.textContent = up ? "▲" : "▼";

    const val = document.createElement("span");
    val.className = "delta-val " + (up ? "up" : "down");
    const amount = isYield
      ? `${up ? "+" : "−"}${nf(digitsFor(d)).format(Math.abs(diff))} pt`
      : formatDelta(diff, v);
    val.textContent = `${amount} (${up ? "+" : "−"}${Math.abs(pct).toFixed(2)}%)`;

    const label = document.createElement("span");
    const words = SPAN_WORDS[RANGE];
    label.textContent =
      `${isYield ? "yield move" : words ? words.toLowerCase() + " move" : "window move"}, since ${from}`;

    el.heroDelta.append(glyph, val, label);
  } else {
    el.heroDelta.hidden = true;
  }

  if (!live) {
    if (typeof drawPesoToggle === "function") drawPesoToggle();
    drawQuickStats();
    drawProfitOdds();
    drawMinInvest();
    drawLastVolume();
    drawTrend();
    drawHalt();
    drawQuality();
  }
  // Fee / break-even lines follow the newest close on live ticks too.
  drawPseFees();
  // Sell-net / board-lot hero lines track the live price.
  if (typeof desksuggestOnChart === "function") desksuggestOnChart(d);
  drawChart({ keep: live });
  if (!live && typeof loadLabelStrip === "function") loadLabelStrip(d.symbol);
  if (!live && typeof loadDividends === "function") loadDividends(d.symbol);
  if (!live && typeof loadBenchmarkLine === "function") loadBenchmarkLine(d);
  if (!live && typeof loadBeatCash === "function") loadBeatCash(d);
  if (!live || !el.tableWrap.hidden) drawTable();
  if (!live) comparisonPrimaryChanged(d);
  const journal = document.getElementById("journalBtn");
  const pin = document.getElementById("sixPackPin");
  if (journal) journal.hidden = !d;
  if (pin) pin.hidden = !d;
  if (typeof deskOnChartDrawn === "function") deskOnChartDrawn(live);
}

/* Compact pure-price strip right under the 3M delta: 1D / 1W / 1M moves,
   max 3-month drawdown, distance off the 3M high, typical daily swing, and
   when the current trend run started. Omitted for yield % series except onset. */
function drawQuickStats() {
  const box = el.quickStats;
  if (!box) return;
  const d = state.data;
  const pts = (d && d.points) || [];
  if (pts.length < 2) {
    box.hidden = true;
    box.textContent = "";
    return;
  }
  const isYield = Boolean(d.yieldSeries || d.unit === "%");
  const chips = [];
  if (!isYield) {
    const last = pts[pts.length - 1], prev = pts[pts.length - 2];
    if (prev && prev.c > 0 && Number.isFinite(last.c)) {
      const d1 = (last.c / prev.c - 1) * 100;
      chips.push({ label: "1D", text: signedPct(d1), cls: d1 >= 0 ? "up" : "down" });
    }
    if (typeof periodChanges === "function") {
      const pc = periodChanges(pts);
      if (pc && pc.periods) {
        for (const p of pc.periods) {
          if (Number.isFinite(p.pct)) {
            chips.push({ label: p.name, text: signedPct(p.pct), cls: p.pct >= 0 ? "up" : "down" });
          }
        }
      }
    }
    const dd = typeof windowDrawdown === "function" ? windowDrawdown(pts.map((p) => p.c)) : null;
    if (dd) {
      chips.push({
        label: "Max drawdown",
        text: dd.maxDrawdown < -0.05 ? `−${Math.abs(dd.maxDrawdown).toFixed(1)}%` : "0.0%",
        cls: dd.maxDrawdown <= -10 ? "down" : "",
        title: "Largest peak-to-trough drop inside the drawn 3-month window.",
      });
      if (Number.isFinite(dd.fromHigh)) {
        chips.push({
          label: "Off 3M high",
          text: dd.fromHigh < -0.05 ? `−${Math.abs(dd.fromHigh).toFixed(1)}%` : "at high",
          cls: "",
        });
      }
      if (Number.isFinite(dd.dailyVol)) {
        chips.push({
          label: "Daily swing",
          text: `±${dd.dailyVol.toFixed(1)}%`,
          cls: "",
          title: "Standard deviation of daily log returns over the drawn window.",
        });
      }
    }
  }
  if (d.onset && Number.isFinite(d.onset.since)) {
    const when = dayFmt.format(toDate(d.onset.since));
    const run = Number.isFinite(d.onset.run) ? ` (${d.onset.run} bars)` : "";
    chips.push({
      label: d.onset.censored ? "Trend since at least" : "Trend started",
      text: when + run,
      cls: "",
      title: d.onset.censored
        ? "This run began before the oldest bar fetched."
        : "The bar where the current trend label started (hollow ring on the chart).",
    });
  }
  box.textContent = "";
  if (!chips.length) {
    box.hidden = true;
    return;
  }
  chips.forEach((c, idx) => {
    if (idx > 0) {
      const sep = document.createElement("span");
      sep.className = "qs-sep";
      sep.setAttribute("aria-hidden", "true");
      sep.textContent = "·";
      box.append(sep);
    }
    const item = document.createElement("span");
    item.className = "qs-item";
    if (c.title) item.title = c.title;
    const lbl = document.createElement("span");
    lbl.className = "qs-lbl";
    lbl.textContent = c.label + " ";
    const val = document.createElement("span");
    val.className = "qs-val" + (c.cls ? " " + c.cls : "");
    val.textContent = c.text;
    item.append(lbl, val);
    box.append(item);
  });
  box.hidden = false;
}

function drawHalt() {
  const box = el.haltNote;
  if (!box) return;
  const h = state.data && state.data.halt;
  if (!h || !h.action) {
    box.hidden = true;
    box.textContent = "";
    return;
  }
  box.hidden = false;
  box.textContent = (h.active ? "⛔ " : "⚠ ") + haltPhrase(h) + " (via PSE Edge).";
}

/* ---- three-month profit odds ----
   One number, 0-1, from the server (`probability.estimate`): the displayed
   daily log returns' mean and volatility projected three months, including
   mean-estimation uncertainty and assumed costs. Independent of the badge.
   This is an uncalibrated model estimate, not a historical class frequency.
   A payload without a usable estimate hides the readout. Invariant 3 in spirit: a
   missing number is missing, never a defaulted 0.5. */
/* The whole claim behind the odds figure, kept in one place: the chart's
   stat-line and the watchlist row's own readout both show this in a tooltip,
   and two copies of a paragraph this specific are two paragraphs that would
   eventually disagree. The figure alone would read as a forecast for *this*
   asset, so the tooltip names the measurement, the assumed costs and the bias
   that runs through it. */
function profitOddsClaim(r) {
  const cost = (r.cost * 100).toFixed(2);
  return `Estimated chance that the price return exceeds ${cost}% assumed round-trip ` +
    `costs over the next three months (${r.horizonBars} sessions). Uses only the ` +
    `${r.observations} log returns in the displayed chart: their mean and volatility, ` +
    `including uncertainty in the estimated mean. Assumes independent normal log ` +
    `returns with unchanged mean and volatility. Weekday calendars omit exchange ` +
    `holidays. Not a calibrated success rate or guarantee; regime changes, fat tails, ` +
    `taxes and currency conversion are not modeled. For futures, this estimates a ` +
    `contract price gain, not leveraged account profitability; expiry, rolls, margin ` +
    `and broker-specific costs are not modeled. Estimates are bounded to 0.01–0.99.`;
}

function drawProfitOdds() {
  const d = state.data;
  const r = d && d.profitProbability;
  const p = r && r.probability;
  const aside = document.getElementById("profitOddsAside");
  if (!Number.isFinite(p)) {
    el.profitOdds.hidden = true;
    el.profitOdds.removeAttribute("title");
    if (aside) aside.hidden = true;
    // Cleared, not just hidden: a yield chart sitting on top of the previous
    // asset's odds would leave "0.45 PSE stock base rate" in the DOM, one
    // inspector away from being read as a claim about a bond.
    el.profitOddsValue.textContent = "—";
    el.profitOddsValue.className = "stat-value";
    el.profitOddsNote.textContent = "";
    return;
  }
  const cost = (r.cost * 100).toFixed(2);
  el.profitOdds.hidden = false;
  if (aside) aside.hidden = false;
  el.profitOddsValue.textContent = p.toFixed(2);
  el.profitOddsValue.className = "stat-value " + (p >= 0.5 ? "above" : "below");
  el.profitOddsNote.textContent =
    `based on similar past charts, after about ${cost}% in costs`;

  // The tooltip carries the whole claim, because the figure alone would read as
  // a forecast for *this* asset: the population, how it was measured, what the
  // adjustment was, and the bias that runs through it.
  el.profitOdds.title = profitOddsClaim(r);
}

/* ---- minimum investment ----
   The PSE board lot times the latest close: what it costs to buy the smallest
   order the exchange allows. Both figures are the server's, computed from the
   same board-lot table the leaderboards' "Min. investment" column uses, so the
   two cannot disagree. A payload without them -- every non-PSE symbol, since the
   board lot is a PSE rule -- hides the readout rather than showing a zero.

   The lot belongs in the note, not the headline: the cheque is what a reader is
   asking for. It is worth spelling out because a minimum investment of
   PHP 114,000.00 reads as a mistake until you can see it is 1,000 shares. */
function drawMinInvest() {
  const d = state.data;
  const figs = d && [d.minInvestment, d.boardLot];
  const usable = figs && figs.every((v) => Number.isFinite(v) && v > 0);
  el.minInvest.hidden = !usable;
  if (!usable) return;

  el.minInvestValue.textContent = leaderMoney(d.minInvestment, d.currency);
  el.minInvestNote.textContent =
    `${nf(0).format(d.boardLot)}-share board lot at ${formatPrice(d.marketPrice, d)}`;
}

/* ---- fees on one board lot ----
   Buy and sell costs for the same lot the minimum-investment line names, at
   today's price, and the lowest valid price that recovers the purchase with
   both sides' fees. A cost readout, not a target: it says nothing about where
   the price will go. Rates and their source are in static/psefees.js. */
function drawPseFees() {
  const d = state.data;
  const lot = d && d.boardLot;
  const price = d && d.marketPrice;
  const usable = typeof pseTradeFees === "function" && d && d.currency === "PHP"
    && Number.isFinite(lot) && lot > 0 && Number.isFinite(price) && price > 0;
  el.pseFees.hidden = !usable;
  if (el.heroFees) el.heroFees.hidden = !usable;
  if (!usable) {
    if (el.heroFees) el.heroFees.textContent = "";
    return;
  }
  const value = lot * price;
  const buy = pseTradeFees(value, "buy");
  const sell = pseTradeFees(value, "sell");
  const be = pseBreakEven(price, lot);
  const pct = (buy.total + sell.total) / value * 100;
  const net = typeof pseSellNet === "function" ? pseSellNet(price, lot) : null;
  el.pseFeesValue.textContent = `${leaderMoney(buy.total + sell.total, "PHP")} round trip`;
  el.pseFeesNote.textContent =
    `${leaderMoney(buy.total, "PHP")} to buy, ${leaderMoney(sell.total, "PHP")} to sell (${pct.toFixed(2)}%)` +
    (be ? ` · gets the money back at ${formatPrice(be, d)} or higher` : "") +
    (net != null ? ` · sell clears ${leaderMoney(net, "PHP")}` : "");
  el.pseFees.title =
    `${PSE_FEES.source}: commission 0.25% (at least ₱20) plus 12% VAT, PSE fee 0.005%, ` +
    `clearing fee 0.01%, and 0.1% sales tax when selling. Your broker's fees may differ slightly. ` +
    `The break-even price is the lowest valid PSE price at which selling this lot returns ` +
    `what buying it cost, after both sides' fees. Sell clears = gross proceeds minus sell-side fees.`;
  // Hero: board lot, round trip, break-even, and sell net — same arithmetic as above.
  if (el.heroFees) {
    el.heroFees.hidden = false;
    const lotBit = Number.isFinite(d.boardLot)
      ? `${nf(0).format(d.boardLot)}-share lot · min ${leaderMoney(d.minInvestment, "PHP")}`
      : "One lot";
    el.heroFees.textContent = lotBit
      + ` · ${leaderMoney(buy.total + sell.total, "PHP")} round trip`
      + (be ? ` · break-even ${formatPrice(be, d)}` : "")
      + (net != null ? ` · sell clears ${leaderMoney(net, "PHP")}` : "");
    el.heroFees.title = el.pseFees.title;
  }
}

/* ---- traded value on the last trading day ----
   The newest *finished* session's close times its volume, in the stock's own
   currency. Computed server-side (`server.chart_data` -> `pse.completed_trade`)
   from this chart's own bars, and decided at read time, so the figure belongs
   to a completed day rather than to a bar that is still forming.

   "Finished" is the exchange's own bell, not a guess: pse.com.ph closes the
   market at 3:15pm Manila, so before that the newest bar is today's session so
   far and the readout is yesterday's; from then on it is today's closing
   figure. Nothing marks a bar as final in the payload, which is why the note
   names the day -- and why the fix lived here rather than in a default.

   A PSE readout only: an index carries no volume and no other source ships one
   in this payload, and both cases hide the line rather than printing a zero
   (invariant 3 in spirit -- a missing volume is not a session that traded
   nothing). */
function drawLastVolume() {
  const d = state.data;
  const value = d && d.tradedTurnover;
  const usable = Number.isFinite(value) && value > 0;
  el.lastVolume.hidden = !usable;
  if (!usable) {
    // Cleared, not just hidden: a peso figure left in the DOM while an index
    // or a bond is on screen is one inspector away from reading as a claim
    // about it.
    el.lastVolumeValue.textContent = "—";
    el.lastVolumeNote.textContent = "";
    el.lastVolume.removeAttribute("title");
    return;
  }

  const stamp = d.tradedDay;
  const day = Number.isFinite(stamp) ? utcDayFmt.format(toDate(stamp)) : "";
  const shares = d.tradedShares;
  const count = Number.isFinite(shares) && shares > 0 ? shares : null;

  el.lastVolumeValue.textContent = compact(value, d.currency || "PHP");
  el.lastVolumeNote.textContent = [count ? `${shareFmt.format(count)} shares` : "",
                                   day ? `${day}, last completed session` : ""]
    .filter(Boolean).join(" · ");

  // The whole claim, because a bare figure under the price reads as the
  // window's turnover: it is one finished session's close times its volume,
  // and today's bar only joins in once the exchange has closed.
  el.lastVolume.title =
    `Value traded on the last finished trading day: the bar's close times its ` +
    `volume` +
    (count ? ` (${nf(0).format(count)} shares)` : "") +
    `, ${leaderMoney(value, d.currency || "PHP")} in total. The exchange closes ` +
    `at 3:15pm Manila, so while it is trading this is the previous session's ` +
    `figure and from then on it is today's closing figure -- the source does not ` +
    `mark a bar as finished, so the exchange's own close is what decides. A stock ` +
    `that did not trade that day has no figure. Delayed like the price.`;
}

/* ---- trend badge ----
   The classifier runs server-side (see trend.py) and ships with the chart
   payload, so the call is scored on the same bars that are drawn. A missing
   or unscoreable series simply hides the badge. */

// Defects found in the bars drawn (see quality.py). They describe the data and
// never change the label: the note says so, so a flagged chart is not read as
// a different verdict.
function drawQuality() {
  const flags = (state.data && state.data.quality) || [];
  el.qualityNote.hidden = !flags.length;
  el.qualityNote.textContent = flags.length
    ? "⚠ Data check: " + flags.map((f) => f.text).join("; ") + ". The label is unchanged."
    : "";
}
