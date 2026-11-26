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
  // Ring when a fresh reading flips the badge vs the last successful one this
  // session (or the prior visit, once we have a current). Server notify.py also
  // posts macOS banners; this is the in-page / Notification path.
  const baseline = row.current || row.prior;
  if (baseline && baseline !== current && typeof noteWatchLabelFlip === "function") {
    noteWatchLabelFlip(symbol, baseline, current);
  }
  row.current = current;
  // Storage already holds the baseline; write only when the badge moved.
  if (current === baseline) return;
  try { localStorage.setItem(visitKey(symbol), current); } catch {}
}

function drawWatchChanges() {
  const panel = document.getElementById('watchChanges');
  panel.hidden = !state.watch.length;
  const list = document.getElementById('watchChangeList');
  if (panel.hidden) {
    list.textContent = '';
    drawWatchChanges.sig = '';
    return;
  }
  // Quote ticks redraw the rail often; skip wiping the change list when the
  // visit readings have not moved.
  const lines = [];
  let checked = 0, compared = 0, flips = 0;
  for (const item of state.watch) {
    const { prior, current } = openWatchVisit(item.symbol);
    if (!current) continue;
    checked++;
    if (!prior) continue;
    compared++;
    if (prior === current) continue;
    flips++;
    lines.push(`${item.symbol}: ${prior} → ${current}`);
  }
  const parts = [];
  if (compared && !flips) parts.push(`No trend changes among ${compared} compared.`);
  if (checked > compared) parts.push(`First reading for ${checked - compared}.`);
  if (checked < state.watch.length) parts.push(`Waiting for fresh readings: ${state.watch.length - checked}.`);
  const noteText = parts.join(' ');
  const sig = lines.join('\n') + '\0' + noteText + '\0' + state.watch.length;
  if (sig === drawWatchChanges.sig) return;
  drawWatchChanges.sig = sig;
  list.textContent = '';
  for (const text of lines) {
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'watch-change-btn';
    const symbol = text.split(':')[0];
    btn.dataset.chart = symbol;
    btn.textContent = text;
    btn.addEventListener('click', () => {
      if (typeof loadChart === 'function') loadChart(symbol);
    });
    li.append(btn);
    list.append(li);
  }
  document.getElementById('watchChangeNote').textContent = noteText;
}
