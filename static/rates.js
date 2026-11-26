/* Peso cash rates strip (morning desk): the BSP policy rate and short
   government bill yields, from /api/rates (`phrates.py`).

   Levels only. Nothing here is a trend label, and nothing touches the badge.
   The bill numbers are market yields (what the bills trade at), not Treasury
   auction results; the note under the line says so in words, visibly, not
   only on hover. Loaded after the page's first draw; re-read hourly. */

const RATES_TTL = 60 * 60 * 1000;

/* "2026-10-22" -> "Oct 22". Read as UTC so no time zone moves the day. */
function ratesDay(iso) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return "";
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

function ratesPct(value) {
  return typeof value === "number" && isFinite(value) ? value.toFixed(2) + "%" : null;
}

/* The strip's words from a payload: { line, bills: [{tenor, text, move}],
   note } or null when there is nothing to show. Pure, so node can test it. */
function ratesStripText(payload) {
  if (!payload || typeof payload !== "object") return null;
  const policy = payload.policy || null;
  const bills = Array.isArray(payload.bills) ? payload.bills : [];
  const rate = policy ? ratesPct(policy.rate) : null;
  const rows = [];
  for (const bill of bills) {
    const level = ratesPct(bill && bill.yield);
    if (!level) continue;           // a tenor that did not arrive is left out
    let move = "";
    const ch = bill.changeWeek;
    if (typeof ch === "number" && Math.abs(ch) >= 0.005) {
      move = (ch > 0 ? "up " : "down ") + Math.abs(ch).toFixed(2) + " this week";
    }
    const still = bill.unchangedSince ? "no change since " + ratesDay(bill.unchangedSince) : "";
    rows.push({ tenor: String(bill.tenor || ""), text: level, move: still || move });
  }
  if (!rate && !rows.length) return null;

  let line = "";
  if (rate) {
    line = "BSP policy rate " + rate;
    const since = ratesDay(policy.since);
    const prev = ratesPct(policy.previous);
    if (since && prev) line += " since " + since + " (was " + prev + ")";
    else if (since) line += " since " + since;
  }

  const asOf = bills.map((b) => b && b.asOf).filter(Boolean).sort().pop();
  let note = "Bill yields are what short government bills trade at";
  note += asOf ? " (" + ratesDay(asOf) + ")" : "";
  note += ", not Treasury auction results. They show what cash earns, not where prices go.";
  note += " Source: " + (payload.source || "TradingView") + ".";
  // A copy served while a refresh runs behind it (`revalidate`) is not an
  // outage; only a copy that stands in for a failed fetch says so.
  if (payload.cached && !payload.revalidate) note += " Saved copy — the source did not answer.";
  return { line, bills: rows, note };
}

function drawRatesStrip(payload) {
  const box = document.getElementById("ratesStrip");
  if (!box) return;
  const text = ratesStripText(payload);
  if (!text) { box.hidden = true; return; }
  box.textContent = "";
  const tiles = typeof ratesTiles === "function" ? ratesTiles(payload) : null;
  if (tiles) {
    // Tiles: big number, small tenor, arrow for the week; a bar under each
    // bill draws the curve's shape. The full sentences stay on hover.
    const head = document.createElement("p");
    head.className = "rates-line";
    const title = document.createElement("strong");
    title.textContent = "Peso cash rates";
    head.append(title);
    box.append(head);
    const grid = document.createElement("div");
    grid.className = "rates-tiles";
    for (const t of tiles.tiles) {
      const tile = document.createElement("div");
      tile.className = "rates-tile kind-" + t.kind;
      tile.title = t.title;
      const lab = document.createElement("span");
      lab.className = "rates-tile-label";
      lab.textContent = t.label;
      const val = document.createElement("span");
      val.className = "rates-tile-value";
      val.textContent = t.value;
      const sub = document.createElement("span");
      sub.className = "rates-tile-sub";
      sub.textContent = t.sub;
      tile.append(lab, val, sub);
      if (t.kind === "bill") {
        const bar = document.createElement("span");
        bar.className = "rates-tile-bar";
        const fill = document.createElement("span");
        fill.style.width = Math.round(100 * t.share) + "%";
        bar.append(fill);
        tile.append(bar);
      }
      grid.append(tile);
    }
    box.append(grid);
    const note = document.createElement("p");
    note.className = "rates-note";
    note.textContent = tiles.note;
    note.title = text.note;
    box.append(note);
    box.setAttribute("aria-label", "Peso cash rates. " + (text.line || "")
      + " " + text.bills.map((b) => b.tenor + " bill " + b.text + " " + b.move).join(", ") + ". " + text.note);
    box.hidden = false;
    return;
  }

  const head = document.createElement("p");
  head.className = "rates-line";
  const title = document.createElement("strong");
  title.textContent = "Peso cash rates";
  head.append(title);
  if (text.line) head.append(" · " + text.line);
  box.append(head);

  if (text.bills.length) {
    const list = document.createElement("ul");
    list.className = "rates-bills";
    list.setAttribute("aria-label", "Government bill yields");
    for (const bill of text.bills) {
      const li = document.createElement("li");
      const tenor = document.createElement("span");
      tenor.className = "rates-tenor";
      tenor.textContent = bill.tenor + " bill";
      const level = document.createElement("span");
      level.className = "rates-level";
      level.textContent = bill.text;
      li.append(tenor, " ", level);
      if (bill.move) {
        const move = document.createElement("span");
        move.className = "rates-move";
        move.textContent = bill.move;
        li.append(" ", move);
      }
      list.append(li);
    }
    box.append(list);
  }

  const note = document.createElement("p");
  note.className = "rates-note";
  note.textContent = text.note;
  box.append(note);
  box.hidden = false;
}

/* ---- "Against cash": did the price beat a 3-month government bill? ----

   Looks back only: the price change over the drawn window next to what a
   3-month bill bought on the window's first day would have earned over the
   same days (simple interest, before the 20% final tax). Peso-priced charts
   only, never a yield chart, never a label. Dividends are not counted. */

const MANILA_DAY = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Manila", year: "numeric", month: "2-digit", day: "2-digit",
});
const CASH_GAP_DAYS = 7;    // the bill yield used may be at most this stale

function manilaDay(ts) {
  return MANILA_DAY.format(new Date(ts * 1000));   // "2026-08-26"
}

/* {price, cash, rate, start, verdict} or null when the comparison would not
   be fair (not pesos, a yield chart, too few bars, no bill yield that day). */
function beatCash(data, history) {
  if (!data || String(data.currency || "").toUpperCase() !== "PHP") return null;
  if (data.yieldSeries || data.unit === "%") return null;
  const pts = (data.points || []).filter((p) => p && Number.isFinite(p.c) && Number.isFinite(p.t));
  if (pts.length < 20 || !Array.isArray(history) || !history.length) return null;
  const first = pts[0], last = pts[pts.length - 1];
  if (!(first.c > 0)) return null;
  const start = manilaDay(first.t);
  let hit = null;
  for (const row of history) {
    if (Array.isArray(row) && row[0] <= start && Number.isFinite(row[1])) hit = row;
  }
  if (!hit) return null;
  const gap = (Date.parse(start + "T00:00:00Z") - Date.parse(hit[0] + "T00:00:00Z")) / 864e5;
  if (gap > CASH_GAP_DAYS) return null;
  const days = (last.t - first.t) / 86400;
  if (!(days > 0)) return null;
  const price = (last.c / first.c - 1) * 100;
  const cash = hit[1] * days / 365;
  const diff = price - cash;
  const verdict = Math.abs(diff) < 0.1 ? "about the same as cash"
    : diff > 0 ? "the price did better than cash" : "cash did better than the price";
  return { price, cash, rate: hit[1], start, days: Math.round(days), verdict };
}

function beatCashText(r) {
  if (!r) return null;
  const sign = (x) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(1) + "%";
  return {
    value: `${sign(r.price)} vs cash ${sign(r.cash)}`,
    note: `Over ${r.days} days, ${r.verdict}. Cash is a 3-month government bill bought on `
      + `${ratesDay(r.start)} at ${r.rate.toFixed(2)}% a year, before 20% tax. `
      + "Price change only; dividends not counted. Looks back, not ahead.",
  };
}

let ratesLatest = null;

async function loadBeatCash(d) {
  const line = typeof document !== "undefined" && document.getElementById("beatCash");
  if (!line) return;
  const key = String(d && d.symbol || "").toUpperCase();
  if (line.dataset.symbol !== key) line.hidden = true;     // never show another asset's line
  line.dataset.symbol = key;
  if (!d || String(d.currency || "").toUpperCase() !== "PHP") { line.hidden = true; return; }
  try {
    if (!ratesLatest) ratesLatest = await requestJSON("/api/rates");
  } catch {
    line.hidden = true;
    return;
  }
  if (line.dataset.symbol !== key) return;                  // the chart moved on meanwhile
  const text = beatCashText(beatCash(d, ratesLatest && ratesLatest.cashHistory));
  if (!text) { line.hidden = true; return; }
  document.getElementById("beatCashValue").textContent = text.value;
  document.getElementById("beatCashNote").textContent = text.note;
  line.hidden = false;
}

async function loadRates() {
  if (typeof document === "undefined" || !document.getElementById("ratesStrip")) return;
  try {
    ratesLatest = await requestJSON("/api/rates");
    drawRatesStrip(ratesLatest);
    loadRates.at = Date.now();
  } catch {
    // An outage keeps whatever the strip already shows; an empty strip stays hidden.
  }
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const start = () => {
    loadRates();
    setInterval(loadRates, RATES_TTL);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && Date.now() - (loadRates.at || 0) > RATES_TTL) loadRates();
    });
  };
  // After the first draw: the chart and tables come first.
  if ("requestIdleCallback" in window) {
    window.addEventListener("load", () => requestIdleCallback(start, { timeout: 4000 }));
  } else {
    window.addEventListener("load", () => setTimeout(start, 1500));
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { ratesStripText, ratesDay, ratesPct, beatCash, beatCashText, manilaDay };
}
