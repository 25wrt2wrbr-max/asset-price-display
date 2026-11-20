"use strict";

/* ------------------------------------------------------------------ *
 * Wiring
 * ------------------------------------------------------------------ */
el.tableToggle.addEventListener("click", () => {
  const show = el.tableWrap.hidden;
  el.tableWrap.hidden = !show;
  el.tableToggle.setAttribute("aria-pressed", show ? "true" : "false");
  el.tableToggle.textContent = show ? "Hide table" : "Table view";
});

el.csvExport.addEventListener("click", () => exportChartCsv());

el.watchExport.addEventListener("click", () => exportWatch());
el.watchImport.addEventListener("click", () => el.watchImportFile.click());
el.watchImportFile.addEventListener("change", () => {
  const file = el.watchImportFile.files && el.watchImportFile.files[0];
  el.watchImportFile.value = "";
  if (file) importWatchFile(file);
});

/* theme toggle: stamp data-theme so it wins over the OS setting both ways */
function applyTheme(mode) {
  document.documentElement.setAttribute("data-theme", mode);
  el.theme.textContent = mode === "dark" ? "Light mode" : "Dark mode";
  el.theme.setAttribute("aria-pressed", mode === "dark" ? "true" : "false");
  try { localStorage.setItem("apd-theme", mode); } catch {}
  if (state.data) drawChart();   // re-render so SVG fills resolve the new tokens
}

el.theme.addEventListener("click", () => {
  applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
});

(function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("apd-theme"); } catch {}
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (prefersDark ? "dark" : "light"));
})();

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (ev) => {
  let saved = null;
  try { saved = localStorage.getItem("apd-theme"); } catch {}
  if (!saved) applyTheme(ev.matches ? "dark" : "light");
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
el.watchToggle.addEventListener("click", () => {
  const d = state.data;
  if (!d) return;
  if (isWatched(d.symbol)) {
    removeFromWatch(d.symbol);
    setStatus(`Removed ${d.symbol} from the watchlist.`);
  } else {
    addToWatch(d.symbol, d.name);
  }
});
