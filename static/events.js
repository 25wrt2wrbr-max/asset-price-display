"use strict";

/* ------------------------------------------------------------------ *
 * Wiring
 * ------------------------------------------------------------------ */
el.tableToggle.addEventListener("click", () => {
  const show = el.tableWrap.hidden;
  // Live price ticks skip the hidden table, so bring it up to date on open.
  // Unfolded first: `drawTable` skips a folded table.
  el.tableWrap.hidden = !show;
  if (show && state.data && state.data.points) drawTable();
  el.tableToggle.setAttribute("aria-pressed", show ? "true" : "false");
  el.tableToggle.textContent = show ? "Hide table" : "Table view";
});

el.csvExport.addEventListener("click", () => exportChartCsv());

el.watchExport.addEventListener("click", () => exportWatch());
(function wireWatchCsv() {
  const btn = document.getElementById("watchExportCsv");
  if (!btn) return;
  btn.addEventListener("click", () => {
    if (typeof exportWatchCsv === "function") exportWatchCsv();
  });
})();
el.watchImport.addEventListener("click", () => el.watchImportFile.click());
el.watchImportFile.addEventListener("change", () => {
  const file = el.watchImportFile.files && el.watchImportFile.files[0];
  el.watchImportFile.value = "";
  if (file) importWatchFile(file);
});

/* theme: "system" follows the computer's light/dark setting; "light" and
   "dark" stamp data-theme so the pick wins over the OS setting both ways.
   The saved key holds only a manual pick; "system" removes it, so the
   pre-paint script in index.html reads the same rule.
   `repaint` redraws chart/sparklines after a change; skipped on the first
   paint so startup does not double-fetch the ranking tables. */
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

function savedTheme() {
  let saved = null;
  try { saved = localStorage.getItem("apd-theme"); } catch {}
  return saved === "light" || saved === "dark" ? saved : "system";
}

function applyTheme(choice, { repaint = false } = {}) {
  const mode = choice === "system" ? (darkQuery.matches ? "dark" : "light") : choice;
  const before = document.documentElement.getAttribute("data-theme");
  document.documentElement.setAttribute("data-theme", mode);
  el.theme.value = choice;
  try {
    if (choice === "system") localStorage.removeItem("apd-theme");
    else localStorage.setItem("apd-theme", choice);
  } catch {}
  if (!repaint || before === mode) return;
  if (state.data) drawChart();   // re-render so SVG fills resolve the new tokens
  // Sparklines are canvas bitmaps (colour baked in); redraw so dark/light
  // tokens apply. Tables follow once the next poll sees a cleared signature.
  if (typeof resetSparkInk === "function") resetSparkInk();
  if (typeof drawWatchList === "function") drawWatchList();
  if (typeof loadRecent === "function") {
    delete loadRecent.sig;
    loadRecent();
  }
  if (typeof loadSectors === "function") {
    delete loadSectors.sig;
    loadSectors();
  }
}

el.theme.addEventListener("change", () => {
  applyTheme(el.theme.value, { repaint: true });
});

applyTheme(savedTheme());

// While following the system, a change on the computer (or its automatic
// day/night switch) flips the page at once.
darkQuery.addEventListener("change", () => {
  if (savedTheme() === "system") applyTheme("system", { repaint: true });
});

/* ---- watchlist wiring ---- */

/* Reordering is wired on the list, not on each row: rows are rebuilt by every
   drawWatchList() — including on each quote arriving — so per-row handlers
   would be dropped mid-drag. Events from a grip bubble up to here, and once a
   drag is live the bubbling target is the grip regardless of the row under it. */
el.watchList.addEventListener("dragover", (ev) => {
  if (dragSymbol === null) return;
  dragPlaceAt(ev.clientY);
  if (dragSymbol === null) return;           // the symbol went away mid-drag
  dragPointY = ev.clientY;
  startDragScroll();                         // and keep scrolling if it holds still
  ev.preventDefault();                       // required to allow a drop
  ev.dataTransfer.dropEffect = "move";
});

/* A leave bubbles out of every row the pointer crosses, so only a leave of the
   list itself ends the scroll; coming back in restarts it on the next dragover. */
el.watchList.addEventListener("dragleave", (ev) => {
  if (dragSymbol === null) return;
  if (ev.relatedTarget && el.watchList.contains(ev.relatedTarget)) return;
  stopDragScroll();
});

el.watchList.addEventListener("drop", (ev) => {
  if (dragSymbol === null) return;
  ev.preventDefault();
  dragDropped = true;      // dragend fires next, and will now commit
});

/* Adds or removes the charted asset. Symbol and name come off the payload, so
   a rerouted crypto keeps its canonical identity and its decorated meta line is
   never parsed as a ticker. */
function toggleCurrentWatch() {
  const d = state.data;
  if (!d) return;
  if (isWatched(d.symbol)) {
    removeFromWatch(d.symbol);
    setStatus(`Removed ${d.symbol} from the watchlist.`);
  } else {
    addToWatch(d.symbol, d.name);
  }
}

el.watchToggle.addEventListener("click", toggleCurrentWatch);

/* ---- keyboard-first scanning ----
   /  focus search box
   j  step to the next visible scanner row (loads its chart + prefetches next)
   k  step to the previous visible scanner row
   w  star / unstar the currently charted asset
   t  toggle table view
   ?  show shortcuts in the status line */
function scannableRows() {
  const grids = [el.recentGrid, el.leaningGrid, el.bearishGrid, el.sectorGrid];
  const rows = [];
  for (const g of grids) {
    if (!g) continue;
    for (const tr of g.querySelectorAll("tbody tr[data-chart]")) {
      if (tr.offsetParent !== null) rows.push(tr);
    }
  }
  return rows;
}

function stepScannerRow(delta) {
  const rows = scannableRows();
  if (!rows.length) return;
  const active = document.querySelector("tr.is-kbd-active");
  let idx = active ? rows.indexOf(active) : -1;
  if (idx < 0 && state.chartSymbol) {
    const cur = String(state.chartSymbol).trim().toUpperCase();
    idx = rows.findIndex((tr) => String(tr.dataset.chart || "").trim().toUpperCase() === cur);
  }
  const next = idx < 0
    ? (delta > 0 ? 0 : rows.length - 1)
    : (idx + delta + rows.length) % rows.length;
  for (const tr of document.querySelectorAll("tr.is-kbd-active")) {
    tr.classList.remove("is-kbd-active");
  }
  const picked = rows[next];
  picked.classList.add("is-kbd-active");
  picked.scrollIntoView({ block: "nearest", behavior: scrollBehavior() });
  const sym = picked.dataset.chart;
  if (sym) {
    el.input.value = sym;
    picked.click();
  }
  const ahead = rows[(next + (delta >= 0 ? 1 : -1) + rows.length) % rows.length];
  if (ahead && ahead.dataset.chart && typeof prefetchChart === "function") {
    prefetchChart(ahead.dataset.chart);
  }
}

document.addEventListener("keydown", (ev) => {
  if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
  const tag = ev.target && ev.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (ev.target && ev.target.isContentEditable)) {
    return;
  }
  if (ev.key === "/") {
    ev.preventDefault();
    el.input.focus();
    el.input.select();
  } else if (ev.key === "j") {
    ev.preventDefault();
    stepScannerRow(1);
  } else if (ev.key === "k") {
    ev.preventDefault();
    stepScannerRow(-1);
  } else if (ev.key === "w") {
    ev.preventDefault();
    toggleCurrentWatch();
  } else if (ev.key === "t") {
    if (!el.tableToggle.hidden) {
      ev.preventDefault();
      el.tableToggle.click();
    }
  } else if (ev.key === "?") {
    ev.preventDefault();
    const help = document.getElementById("kbdHelp");
    if (help) {
      help.open = true;
      help.scrollIntoView({ block: "nearest", behavior: scrollBehavior() });
    }
    setStatus("Keyboard shortcuts: / search · j/k next or previous table row · w star · t table view");
  }
});
