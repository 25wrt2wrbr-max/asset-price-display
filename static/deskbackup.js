"use strict";

const deskRecords = {
  watch: "apd-watchlist", lists: "apd-watch-lists",
  holdings: "apd-holdings", alarms: "apd-alarms",
};

function validateDesk(backup) {
  const text = (v) => typeof v === "string" && v.trim().length > 0;
  const valid = {
    watch: (w) => text(w.symbol),
    lists: (w) => text(w.name) && Array.isArray(w.symbols) && w.symbols.every(text),
    holdings: (h) => text(h.symbol) && Number.isFinite(h.shares) && h.shares > 0 &&
      Number.isFinite(h.avgCost) && h.avgCost > 0,
    alarms: (a) => text(a.id) && text(a.symbol) && Number.isFinite(a.target),
  };
  if (backup?.format !== "asset-price-display" || backup.version !== 1) {
    throw new Error("Choose an Asset Price Display desk backup.");
  }
  for (const [name, check] of Object.entries(valid)) {
    if (!Array.isArray(backup[name]) || !backup[name].every((r) => r && check(r))) {
      throw new Error("Invalid " + name + " in backup.");
    }
  }
  return backup;
}

function restoreDeskRecords(storage, desk) {
  const previous = [];
  try {
    for (const [name, key] of Object.entries(deskRecords)) {
      const value = storage.getItem(key);
      storage.setItem(key, JSON.stringify(desk[name]));
      previous.push([key, value]);
    }
  } catch (error) {
    for (const [key, value] of previous.reverse()) {
      if (value === null) storage.removeItem(key);
      else storage.setItem(key, value);
    }
    throw error;
  }
}

if (typeof document !== "undefined") {
  const file = document.getElementById("deskFile");
  const status = document.getElementById("deskBackupStatus");
  document.getElementById("deskBackup").onclick = () => {
    try {
      const desk = { format: "asset-price-display", version: 1 };
      for (const [name, key] of Object.entries(deskRecords)) {
        desk[name] = JSON.parse(localStorage.getItem(key) || "[]");
      }
      downloadBlob("asset-price-desk.json", JSON.stringify(validateDesk(desk), null, 2), "application/json");
      status.textContent = "Desk backup downloaded.";
    } catch (e) { status.textContent = e.message; }
  };
  document.getElementById("deskRestore").onclick = () => file.click();
  file.onchange = async () => {
    const selected = file.files[0];
    file.value = "";
    if (!selected) return;
    try {
      const desk = validateDesk(JSON.parse(await selected.text()));
      if (!window.confirm(`Replace your active watchlist, named lists, holdings and alarms with ${desk.watch.length} watched assets, ${desk.lists.length} lists, ${desk.holdings.length} holdings and ${desk.alarms.length} alarms?`)) return;
      restoreDeskRecords(localStorage, desk);
      loadWatch();
      loadAlarms();
      declareWatch();
      syncAlarmsToServer();
      drawWatchList();
      refreshWatchQuotes();
      drawHoldingsBox();
      drawWatchListsBox();
      drawAlarms();
      redrawChartForAlarm();
      syncAlarmBadge();
      status.textContent = "Desk restored.";
    } catch (e) { status.textContent = e.message; }
  };
}

if (typeof module !== "undefined") module.exports = { validateDesk, restoreDeskRecords };
