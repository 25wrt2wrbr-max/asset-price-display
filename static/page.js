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

function renderAll() {
  const d = state.data;
  if (!d) return;
  closeSuggestions();

  el.assetName.textContent = d.name;
  const bits = [d.symbol, d.exchange, d.type ? d.type.toLowerCase() : ""].filter(Boolean);
  // Crypto rows carry the coin's market-cap rank, which is what tells the coin
  // you meant from a same-ticker collision, and always name the source, so a
  // symbol rerouted away from Yahoo is never mistaken for Yahoo's answer.
  if (Number.isFinite(d.coinRank)) bits.splice(2, 0, `rank ${d.coinRank}`);
  if (d.source) bits.push(`via ${d.source}`);
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
  if (basisNote) bits.push(basisNote);
  else if (!d.lastBarBasis && d.extendedLastBar) bits.push("last bar includes after-hours");
  // A series the source has stopped printing: the hero figure above is that old
  // bar's close, not a price now, and the line has to say so before the reader
  // reads it as today's. The server decides it (`staleDays`), by the same rule
  // the recent table uses to leave such a name off the table.
  if (Number.isFinite(d.staleDays)) {
    bits.push(`newest bar is ${d.staleDays === 1 ? "1 day" : d.staleDays + " days"} old`
      + (d.staleBar ? ` (${d.staleBar})` : ""));
  }
  // The peso pair's Saturdays and Sundays come from Coins.ph's USDC/PHP book,
  // because the FX week is shut. Say it whenever such bars are on screen, not
  // only when the newest one is: a weekend point in the middle of a three-month
  // chart is still the stablecoin's price.
  if (d.weekendProxy) {
    const n = (d.weekendProxy.stamps || []).length;
    bits.push(n === 1
      ? "1 weekend bar is Coins.ph USDC/PHP"
      : `${n} weekend bars are Coins.ph USDC/PHP`);
  }
  // A disk fallback is the same shape as a live answer with a date attached:
  // the chart draws, and the meta line says when the bars were really fetched.
  if (d.cached && d.fetchedAt) bits.push("last retrieved " + retrievedAt(d.fetchedAt));
  el.assetMeta.textContent = bits.join(" · ");

  const pts = d.points;
  const last = pts[pts.length - 1];
  // The first bar the plot draws: the other end of the window the badge and
  // every table row are judged on.
  const first = pts.length > 1 ? pts[0] : null;

  // hero figure — proportional figures, never tabular-nums at display size
  el.hero.hidden = false;
  el.hero.textContent = formatPrice(last.c, d);

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
      : formatDelta(diff, d);
    val.textContent = `${amount} (${up ? "+" : "−"}${Math.abs(pct).toFixed(2)}%)`;

    const label = document.createElement("span");
    const words = SPAN_WORDS[RANGE];
    label.textContent =
      `${isYield ? "yield move" : words ? words.toLowerCase() + " move" : "window move"}, since ${from}`;

    el.heroDelta.append(glyph, val, label);
  } else {
    el.heroDelta.hidden = true;
  }

  drawProfitOdds();
  drawMinInvest();
  drawLastVolume();
  drawTrend();
  drawQuality();
  drawChart();
  drawTable();
  comparisonPrimaryChanged(d);
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
  if (!Number.isFinite(p)) {
    el.profitOdds.hidden = true;
    el.profitOdds.removeAttribute("title");
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
  el.profitOddsValue.textContent = p.toFixed(2);
  el.profitOddsValue.className = "stat-value " + (p >= 0.5 ? "above" : "below");
  el.profitOddsNote.textContent =
    `chart-based estimate, net of ${cost}% costs`;

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
