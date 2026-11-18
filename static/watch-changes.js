"use strict";

// One saved reading per symbol. The previous visit's copy stays fixed in
// memory while successful reads update the copy the next visit will open.
const watchVisit = new Map();
let watchReadSeq = 0;
const visitKey = symbol => 'apd-last-trend:' + symbol.trim().toUpperCase();

function visitReading(data) {
  const t = data && data.trend;
  if (!t || data.cached || data.stale || data.staleDays != null ||
      !['neutral', 'bullish', 'bearish'].includes(t.label)) return null;
  return badgePhrase(t);
}

function openWatchVisit(symbol) {
  const key = visitKey(symbol);
  if (!watchVisit.has(key)) {
    let prior = null;
    try { prior = localStorage.getItem(key); } catch {}
    watchVisit.set(key, { prior, current: null });
  }
  return watchVisit.get(key);
}

function forgetWatchVisit(symbol) {
  const key = visitKey(symbol);
  watchVisit.delete(key);
  try { localStorage.removeItem(key); } catch {}
}

function recordWatchVisit(was, symbol, data) {
  const row = openWatchVisit(symbol);
  if (visitKey(was) !== visitKey(symbol)) {
    const old = openWatchVisit(was);
    if (!row.prior && old.prior) {
      row.prior = old.prior;
      try { localStorage.setItem(visitKey(symbol), row.current || row.prior); } catch {}
    }
    forgetWatchVisit(was);
  }
  const current = visitReading(data);
  if (!current) return;
  row.current = current;
  try { localStorage.setItem(visitKey(symbol), current); } catch {}
}

function drawWatchChanges() {
  const panel = document.getElementById('watchChanges');
  panel.hidden = !state.watch.length;
  const list = document.getElementById('watchChangeList');
  list.textContent = '';
  if (panel.hidden) return;
  let checked = 0, compared = 0;
  for (const item of state.watch) {
    const { prior, current } = openWatchVisit(item.symbol);
    if (!current) continue;
    checked++;
    if (!prior) continue;
    compared++;
    if (prior === current) continue;
    const li = document.createElement('li');
    li.textContent = `${item.symbol}: ${prior} → ${current}`;
    list.append(li);
  }
  const note = document.getElementById('watchChangeNote');
  const parts = [];
  if (compared && !list.children.length) parts.push(`No trend changes among ${compared} compared.`);
  if (checked > compared) parts.push(`First reading for ${checked - compared}.`);
  if (checked < state.watch.length) parts.push(`Waiting for fresh readings: ${state.watch.length - checked}.`);
  note.textContent = parts.join(' ');
}
