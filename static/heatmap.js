"use strict";

/* The watchlist as tiles: each asset one tile, coloured by its move over the
   period picked (1D, 1W, 1M, 3M), grouped by market. Read off the same
   quotes the list draws (`state.watchQuotes`), so a tile and its row agree;
   a click opens the chart. The list stays the place to reorder.

   Colour: the page's own up/down pair, deeper for a bigger move, scaled to
   the largest move on screen. Every tile also carries a ▲/▼ and the signed
   figure, so the direction never rests on colour alone, and the text stays in
   the page's ink, never the tile colour. A tile that has no figure yet (still
   loading, failed, or too short for the period) is plain and says so. */

const HEAT_KEY = "apd-watch-view";
const HEAT_PERIOD_KEY = "apd-heat-period";
const HEAT_MODE_KEY = "apd-heat-mode";
const DENSITY_KEY = "apd-watch-density";
const HEAT_PERIOD_WORDS = { "1D": "1 day", "1W": "1 week", "1M": "1 month", "3M": "3 months", "TO": "5-day turnover" };
const heatUI = {
  toggle: document.getElementById("watchView"),
  density: document.getElementById("watchDensity"),
  box: document.getElementById("watchHeat"),
  grid: document.getElementById("watchHeatGrid"),
  note: document.getElementById("watchHeatNote"),
  periods: [...document.querySelectorAll("#watchHeat .heat-period")],
};
let heatOn = false, heatPeriod = "1D", watchCompact = false, heatMode = "move";
try {
  heatOn = localStorage.getItem(HEAT_KEY) === "tiles";
  const saved = localStorage.getItem(HEAT_PERIOD_KEY);
  if (HEAT_PERIOD_WORDS[saved]) heatPeriod = saved;
  watchCompact = localStorage.getItem(DENSITY_KEY) === "compact";
  heatMode = localStorage.getItem(HEAT_MODE_KEY) === "turnover" ? "turnover" : "move";
} catch {}

function applyWatchDensity() {
  const list = document.getElementById("watchList");
  if (list) list.classList.toggle("is-compact", watchCompact && !heatOn);
  if (heatUI.density) {
    heatUI.density.setAttribute("aria-pressed", String(watchCompact));
    heatUI.density.textContent = watchCompact ? "Comfortable" : "Compact";
    heatUI.density.title = watchCompact
      ? "Show full watchlist rows" : "Show price and change only";
    heatUI.density.hidden = heatOn;
  }
}

/* Which group a watched asset sits in, from what its chart payload says. */
function heatMarket(symbol, data) {
  const s = String(symbol || "").toUpperCase();
  const d = data || {};
  if (d.yieldSeries) return "Bond yields";
  if (s.startsWith("FUND:")) return "Philippine funds";
  if (s.startsWith("PSE:") || s.startsWith("EDGE:") || s.endsWith(".PS")) return "Philippines";
  const type = String(d.type || "").toUpperCase();
  if (type === "CRYPTOCURRENCY" || /-USDT?$/.test(s)) return "Crypto";
  if (type === "CURRENCY" || s.endsWith("=X")) return "Currencies";
  if (type === "FUTURE" || s.endsWith("=F")) return "Futures";
  if (s.startsWith("^") || type === "INDEX") return "Indexes";
  return "Stocks & funds";
}

/* The move over `period` from the drawn closes, in percent, or null. */
function heatMove(quote, period) {
  if (!quote || !quote.data) return null;
  const pts = (quote.data.points || []).filter((p) => p && Number.isFinite(p.c));
  if (pts.length < 2) return null;
  const last = pts[pts.length - 1];
  if (period === "3M") return Number.isFinite(quote.pct) ? quote.pct : null;
  if (period === "1D") {
    const prev = pts[pts.length - 2];
    return prev.c > 0 ? (last.c / prev.c - 1) * 100 : null;
  }
  const found = periodChanges(pts);
  const hit = found && found.periods.find((p) => p.name === period);
  return hit ? hit.pct : null;
}

/* 0..1 depth for a move, against the biggest move on screen (at least 2%,
   so a quiet day is not painted as a dramatic one). */
function heatDepth(pct, scale) {
  if (!Number.isFinite(pct)) return 0;
  return Math.min(1, Math.abs(pct) / Math.max(2, scale));
}

function drawWatchHeat() {
  if (!heatUI.box) return;
  heatUI.toggle.textContent = heatOn ? "List" : "Tiles";
  heatUI.toggle.setAttribute("aria-pressed", String(heatOn));
  heatUI.toggle.title = heatOn ? "Show the watchlist as a list"
    : "Show the watchlist as tiles coloured by each asset's move";
  el.watchList.hidden = heatOn;
  heatUI.box.hidden = !heatOn;
  for (const b of heatUI.periods) {
    b.setAttribute("aria-pressed", String(b.dataset.period === heatPeriod));
  }
  if (!heatOn) return;

  const byTurnover = heatMode === "turnover" || heatPeriod === "TO";
  const items = state.watch.map((item) => {
    const quote = state.watchQuotes[item.symbol];
    const turn = byTurnover && quote && quote.data && typeof watchTurnover === "function"
      ? watchTurnover(quote.data, 5) : null;
    return {
      item, quote,
      pct: byTurnover ? null : heatMove(quote, heatPeriod === "TO" ? "1D" : heatPeriod),
      turn: Number.isFinite(turn) ? turn : null,
      market: heatMarket(item.symbol, quote && quote.data),
    };
  });
  const scale = byTurnover
    ? Math.max(0, ...items.map((t) => t.turn || 0))
    : Math.max(0, ...items.map((t) => Math.abs(t.pct || 0)));
  const groups = new Map();
  for (const t of items) {
    if (!groups.has(t.market)) groups.set(t.market, []);
    groups.get(t.market).push(t);
  }
  heatUI.grid.textContent = "";
  for (const [market, tiles] of groups) {
    if (groups.size > 1) {
      const h = document.createElement("h3");
      h.className = "heat-group";
      h.textContent = market;
      heatUI.grid.append(h);
    }
    const grid = document.createElement("div");
    grid.className = "heat-grid";
    for (const t of tiles) {
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "heat-tile";
      tile.dataset.chart = t.item.symbol;
      if (byTurnover) {
        if (t.turn != null) {
          const depth = scale > 0 ? Math.min(1, t.turn / scale) : 0;
          tile.classList.add("up");
          tile.style.setProperty("--heat", `${Math.round(10 + depth * 40)}%`);
          // Tile size tracks turnover (Fidelity-style weight cue).
          tile.style.flexGrow = String(Math.max(1, Math.round(1 + depth * 4)));
          tile.style.minWidth = `${Math.round(64 + depth * 48)}px`;
        }
      } else {
        const up = t.pct !== null && t.pct >= 0;
        if (t.pct !== null) {
          const depth = heatDepth(t.pct, scale);
          tile.classList.add(up ? "up" : "down");
          tile.style.setProperty("--heat", `${Math.round(10 + depth * 40)}%`);
        }
      }
      if (isWatchActive(t.item)) tile.classList.add("is-active");
      const sym = document.createElement("span");
      sym.className = "heat-sym";
      sym.textContent = t.item.symbol;
      const val = document.createElement("span");
      val.className = "heat-val";
      if (byTurnover) {
        if (t.turn != null) {
          val.textContent = typeof compact === "function" ? compact(t.turn, "PHP") : String(Math.round(t.turn));
        } else if (t.quote && t.quote.loading) {
          val.textContent = "…";
        } else {
          val.textContent = "—";
        }
      } else if (t.pct !== null) {
        const up = t.pct >= 0;
        val.textContent = `${up ? "▲" : "▼"} ${up ? "+" : "−"}${Math.abs(t.pct).toFixed(2)}%`;
      } else if (t.quote && t.quote.loading) {
        val.textContent = "…";
      } else {
        val.textContent = "—";
      }
      const trend = t.quote && t.quote.data && t.quote.data.trend;
      const dot = document.createElement("span");
      dot.className = "heat-dot " + (trend && trend.label ? trend.label : "unknown");
      if (trend && trend.pullback) dot.classList.add("pullback");
      dot.setAttribute("aria-hidden", "true");
      const labelWord = trend && trend.label
        ? (trend.label + (trend.pullback ? ", pullback" : ""))
        : "no label yet";
      tile.append(sym, val, dot);
      const what = byTurnover
        ? (t.turn == null
          ? (t.quote && t.quote.error ? `no figure: ${t.quote.error}` : "no turnover figure")
          : `5-day peso turnover ${Math.round(t.turn).toLocaleString("en-PH")}`)
        : (t.pct === null
          ? (t.quote && t.quote.error ? `no figure: ${t.quote.error}` : "no figure for this period")
          : `${t.pct >= 0 ? "up" : "down"} ${Math.abs(t.pct).toFixed(2)}% over ${HEAT_PERIOD_WORDS[heatPeriod]}`);
      tile.title = `${t.item.name || t.item.symbol}: ${what}; trend ${labelWord}. Click to chart it.`;
      tile.setAttribute("aria-label", `${t.item.symbol}, ${what}, ${labelWord}`);
      tile.addEventListener("click", () => loadChart(t.item.symbol));
      grid.append(tile);
    }
    heatUI.grid.append(grid);
  }
  heatUI.note.textContent = items.length
    ? (byTurnover
      ? "Tile size and colour depth follow 5-day peso turnover on PSE names. "
        + "Other markets show no turnover figure. Corner dot is the chart's own label."
      : `Move over ${HEAT_PERIOD_WORDS[heatPeriod]}, from each chart's own closes. `
        + "Deeper colour, bigger move, against the largest on screen. "
        + "The corner dot is that chart's own trend label. Past moves only, not a forecast.")
    : "Nothing saved yet. Chart a symbol, then press Add to watchlist.";
  applyWatchDensity();
}

heatUI.toggle.addEventListener("click", () => {
  heatOn = !heatOn;
  try { localStorage.setItem(HEAT_KEY, heatOn ? "tiles" : "list"); } catch {}
  drawWatchHeat();
  if (typeof drawWatchList === "function") drawWatchList();
});
if (heatUI.density) {
  heatUI.density.addEventListener("click", () => {
    watchCompact = !watchCompact;
    try { localStorage.setItem(DENSITY_KEY, watchCompact ? "compact" : "full"); } catch {}
    applyWatchDensity();
  });
}
for (const b of heatUI.periods) {
  b.addEventListener("click", () => {
    heatPeriod = b.dataset.period;
    heatMode = heatPeriod === "TO" ? "turnover" : "move";
    try {
      localStorage.setItem(HEAT_PERIOD_KEY, heatPeriod);
      localStorage.setItem(HEAT_MODE_KEY, heatMode);
    } catch {}
    drawWatchHeat();
  });
}
applyWatchDensity();
