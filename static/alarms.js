"use strict";

/* ---- price alarms ----
   An alarm is a level on one asset's plotted price. It fires once, when a
   fresh reading lands on the other side of the level from the reading before
   it (or on it). Alarms are saved in this browser and outlive the chart:
   opening another asset does not disarm them. Every armed symbol is re-read
   on its own clock, whichever asset the chart is showing, and also whenever
   the chart or a watchlist row happens to load that symbol.

   A disk copy (`cached`) or a series the source stopped printing is not a
   live price, so it is never used to fire or to move the reference. */
const ALARM_KEY = "apd-alarms";
const ALARM_POLL = 60 * 1000;

let alarms = [];
let alarmAudio = null;

function loadAlarms() {
  try {
    const raw = JSON.parse(localStorage.getItem(ALARM_KEY) || "[]");
    alarms = Array.isArray(raw) ? raw.filter((a) =>
      a && typeof a.symbol === "string" && Number.isFinite(a.target)) : [];
  } catch { alarms = []; }
}

function saveAlarms() {
  try { localStorage.setItem(ALARM_KEY, JSON.stringify(alarms)); } catch {}
  syncAlarmsToServer();
}

function syncAlarmBadge() {
  const fired = alarms.filter((a) => a.fired).length;
  try {
    if (typeof navigator === "undefined") return;
    if (fired > 0 && typeof navigator.setAppBadge === "function") {
      Promise.resolve(navigator.setAppBadge(fired)).catch(() => {});
    } else if (fired === 0 && typeof navigator.clearAppBadge === "function") {
      Promise.resolve(navigator.clearAppBadge()).catch(() => {});
    }
  } catch {}
}

function syncAlarmsToServer() {
  if (typeof postJSON !== "function") return;
  postJSON("/api/alarms", alarms).catch(() => {});
}

async function restoreAlarmsFromServer() {
  if (typeof requestJSON !== "function") return;
  try {
    const res = await requestJSON("/api/alarms");
    const remote = Array.isArray(res && res.alarms) ? res.alarms : [];
    if (!remote.length) {
      if (alarms.length) syncAlarmsToServer();
      return;
    }
    if (!alarms.length) {
      alarms = remote;
      try { localStorage.setItem(ALARM_KEY, JSON.stringify(alarms)); } catch {}
      drawAlarms();
      redrawChartForAlarm();
      return;
    }
    // Merge any alarm fired on the server while Safari was closed.
    const byId = new Map(remote.map((a) => [a.id, a]));
    let changed = false;
    for (const local of alarms) {
      const srv = byId.get(local.id);
      if (srv && srv.fired && !local.fired) {
        local.fired = srv.fired;
        local.last = srv.last;
        changed = true;
        ringAlarm(local);
      }
    }
    if (changed) {
      try { localStorage.setItem(ALARM_KEY, JSON.stringify(alarms)); } catch {}
      drawAlarms();
    } else {
      syncAlarmsToServer();
    }
  } catch {}
}

function redrawChartForAlarm(symbol) {
  if (typeof state === "undefined" || !state.data || typeof drawChart !== "function") return;
  if (!symbol || alarmSym(state.data.symbol) === alarmSym(symbol)) {
    drawChart({ keep: true });
  }
}

const alarmSym = (s) => String(s || "").trim().toUpperCase();

/* The price an alarm reads: the newest bar's close, the same figure the hero
   number shows. Null when the payload is not a live reading. */
function alarmPrice(data) {
  if (!data || data.cached || data.staleDays != null) return null;
  const pts = data.points || [];
  const last = pts[pts.length - 1];
  return last && Number.isFinite(last.c) ? last.c : null;
}

/* Did the move from `prev` to `now` cross `target`? Touching counts. A
   reading that sits exactly on the level is not a side, so it never arms a
   cross by itself. Pure, so the test can call it. */
function alarmCrossed(prev, now, target) {
  if (!Number.isFinite(prev) || !Number.isFinite(now)) return null;
  if (prev < target && now >= target) return "up";
  if (prev > target && now <= target) return "down";
  return null;
}

function snapAlarmTarget(data, target) {
  let t = Number(target);
  if (!Number.isFinite(t)) return null;
  // PSE names: snap to a valid tick so the alert matches what can be traded.
  const sym = String(data && data.symbol || "").toUpperCase();
  const pse = data && data.currency === "PHP"
    && (sym.startsWith("PSE:") || sym.startsWith("EDGE:") || sym.endsWith(".PS")
      || Number.isFinite(data.boardLot));
  if (pse && typeof pseRoundToTick === "function") {
    const snapped = pseRoundToTick(t, "nearest");
    if (Number.isFinite(snapped)) t = snapped;
  }
  return t;
}

function addAlarm(data, target, needLabel) {
  const price = alarmPrice(data);
  const want = needLabel === "bullish" || needLabel === "bearish" ? needLabel : null;
  const snapped = snapAlarmTarget(data, target);
  if (!Number.isFinite(snapped)) return null;
  const a = {
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    symbol: data.symbol,
    name: data.name || data.symbol,
    target: snapped,
    last: price,                 // the reading the next one is compared with
    unit: data.unit || null,
    currency: data.currency || null,
    priceHint: Number.isFinite(Number(data.priceHint)) ? Number(data.priceHint) : null,
    // Optional filter: fire only while the chart's current label matches.
    // Descriptive gate on today's badge — not a forecast that it will stay.
    needLabel: want,
    created: Date.now(),
    fired: null,                 // {at, price, dir} once it has gone off
  };
  alarms.push(a);
  saveAlarms();
  redrawChartForAlarm(a.symbol);
  return a;
}

function removeAlarm(id) {
  const gone = alarms.find((a) => a.id === id);
  alarms = alarms.filter((a) => a.id !== id);
  saveAlarms();
  drawAlarms();
  redrawChartForAlarm(gone && gone.symbol);
}

/* Every fresh payload for a symbol goes through here: the chart's own loads,
   the watchlist's row reads, and the alarm clock below. */
function checkAlarms(data) {
  const price = alarmPrice(data);
  if (price === null) return;
  const key = alarmSym(data.symbol);
  const labelNow = data.trend && data.trend.label;
  let changed = false;
  for (const a of alarms) {
    if (a.fired || alarmSym(a.symbol) !== key) continue;
    const dir = alarmCrossed(a.last, price, a.target);
    if (dir) {
      // Label gate: a filter on the chart's current label, not a forecast.
      // When the label does not match, leave `last` alone so a later reading
      // with the right label can still count as a cross.
      if (a.needLabel && labelNow !== a.needLabel) continue;
      changed = true;
      a.last = price;
      a.fired = { at: Date.now(), price, dir };
      ringAlarm(a);
      continue;
    }
    // Stored and redrawn only when the price moved: the minute poll runs in
    // hidden tabs too, and most minutes nothing moves.
    if (a.last !== price) { a.last = price; changed = true; }
  }
  if (changed) { saveAlarms(); drawAlarms(); }
}

function alarmFmt(value, a) {
  return typeof formatPrice === "function"
    ? formatPrice(value, { unit: a.unit, currency: a.currency, symbol: a.symbol, priceHint: a.priceHint })
    : String(value);
}

function alarmMessage(a) {
  const f = a.fired;
  return `${a.symbol} ${f.dir === "up" ? "rose to" : "fell to"} ${alarmFmt(f.price, a)}, ` +
    `crossing your alarm at ${alarmFmt(a.target, a)}.`;
}

function ringAlarm(a) {
  const text = alarmMessage(a);
  // 1. a system notification, so it is seen with the tab in the background
  try {
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      const n = new Notification("Price alarm: " + a.symbol, { body: text, tag: "apd-alarm-" + a.id, requireInteraction: true });
      n.onclick = () => { window.focus(); loadChart(a.symbol); n.close(); };
    }
  } catch {}
  // 2. a banner on the page that stays until dismissed
  const banner = document.getElementById("alarmBanner");
  if (banner) {
    const p = document.createElement("p");
    p.className = "alarm-ring";
    p.textContent = "🔔 " + text + " ";
    const ok = document.createElement("button");
    ok.type = "button"; ok.className = "ghost-btn"; ok.textContent = "Dismiss";
    ok.addEventListener("click", () => { p.remove(); banner.hidden = !banner.children.length; });
    p.append(ok);
    banner.append(p);
    banner.hidden = false;
  }
  // 3. a short beep
  try {
    if (alarmAudio) {
      if (alarmAudio.state === "suspended") alarmAudio.resume();
      const t0 = alarmAudio.currentTime;
      for (let i = 0; i < 3; i++) {
        const osc = alarmAudio.createOscillator(), gain = alarmAudio.createGain();
        osc.frequency.value = 880;
        gain.gain.value = 0.15;
        osc.connect(gain).connect(alarmAudio.destination);
        osc.start(t0 + i * 0.35); osc.stop(t0 + i * 0.35 + 0.2);
      }
    }
  } catch {}
  // 4. the tab title & Safari Dock badge, for a tab the reader is not looking at
  if (!document.title.startsWith("🔔")) document.title = "🔔 " + document.title;
  syncAlarmBadge();
}

/* ---- the form under the chart and the list in the rail ---- */
function drawAlarmForm() {
  const box = document.getElementById("alarmBox");
  if (!box) return;
  const d = state.data;
  const price = alarmPrice(d) ?? (d && d.points && d.points.length ? d.points[d.points.length - 1].c : null);
  box.hidden = !d || !Number.isFinite(price);
  if (box.hidden) return;
  const input = document.getElementById("alarmPrice");
  if (input.dataset.symbol !== d.symbol) {      // a new asset: start from its price
    input.value = price.toFixed(digitsFor(d));
    input.dataset.symbol = d.symbol;
  }
  const own = alarms.filter((a) => !a.fired && alarmSym(a.symbol) === alarmSym(d.symbol)).length;
  document.getElementById("alarmNote").textContent =
    `Now ${formatPrice(price, d)}.` + (own ? ` ${own} alarm${own > 1 ? "s" : ""} armed on ${d.symbol}.` : "");
}

function drawAlarms() {
  const list = document.getElementById("alarmList");
  if (!list) return;
  const section = document.getElementById("alarmSection");
  section.hidden = !alarms.length;
  list.textContent = "";
  for (const a of alarms) {
    const li = document.createElement("li");
    li.className = "alarm-row" + (a.fired ? " is-fired" : "");
    const open = document.createElement("button");
    open.type = "button"; open.className = "alarm-open";
    open.textContent = a.symbol;
    open.title = "Show " + a.name;
    open.addEventListener("click", () => { el.input.value = a.symbol; loadChart(a.symbol); });
    const what = document.createElement("span");
    what.className = "alarm-what";
    if (a.fired) {
      what.textContent = `went off ${a.fired.dir === "up" ? "▲" : "▼"} at ${alarmFmt(a.fired.price, a)} (level ${alarmFmt(a.target, a)})`;
    } else {
      const side = Number.isFinite(a.last) ? (a.target >= a.last ? "▲ " : "▼ ") : "";
      const gate = a.needLabel ? ` · only while ${a.needLabel}` : "";
      what.textContent = `${side}${alarmFmt(a.target, a)}` +
        (Number.isFinite(a.last) ? ` · now ${alarmFmt(a.last, a)}` : " · waiting for a live price") +
        gate;
    }
    const del = document.createElement("button");
    del.type = "button"; del.className = "watch-io-btn";
    del.textContent = a.fired ? "Clear" : "Remove";
    del.setAttribute("aria-label", `${del.textContent} alarm on ${a.symbol} at ${alarmFmt(a.target, a)}`);
    del.addEventListener("click", () => { removeAlarm(a.id); drawAlarmForm(); });
    li.append(open, what, del);
    list.append(li);
  }
  drawAlarmForm();
  syncAlarmBadge();
}

function bindAlarmForm() {
  const form = document.getElementById("alarmBox");
  if (!form) return;
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const d = state.data;
    const input = document.getElementById("alarmPrice");
    const target = Number(String(input.value).replace(/,/g, ""));
    const note = document.getElementById("alarmNote");
    if (!d || !Number.isFinite(target) || target <= 0 && d.unit !== "%") {
      note.textContent = "Type a price to set the alarm at.";
      return;
    }
    const now = alarmPrice(d);
    if (now !== null && now === target) {
      note.textContent = "That is the price now. Pick a level above or below it.";
      return;
    }
    // Asked inside the click, the only moment a browser lets a page ask.
    try {
      if (typeof Notification !== "undefined" && Notification.permission === "default") Notification.requestPermission();
    } catch {}
    try { if (!alarmAudio) alarmAudio = new (window.AudioContext || window.webkitAudioContext)(); } catch {}
    const needSel = document.getElementById("alarmNeedLabel");
    const needLabel = needSel ? needSel.value : "";
    const a = addAlarm(d, target, needLabel);
    drawAlarms();
    const denied = typeof Notification === "undefined" || Notification.permission === "denied";
    const shown = a ? a.target : target;
    if (a && a.target !== target && typeof pseRoundToTick === "function") {
      input.value = String(a.target);
    }
    note.textContent = `Alarm set at ${formatPrice(shown, d)}` +
      (a && a.target !== target ? " (snapped to a valid PSE tick)" : "") +
      (needLabel ? ` (only while currently labelled ${needLabel})` : "") + "." +
      (denied ? " Browser notifications are off, so it will show on this page and beep." : "");
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && document.title.startsWith("🔔 ")) document.title = document.title.slice(3);
  });
}

/* Re-read every armed symbol each minute, tab visible or not: an alarm has to
   work while the reader is looking at something else. A symbol the chart
   already read within the last minute is skipped, its answer already counted. */
async function pollAlarms() {
  const due = [...new Set(alarms.filter((a) => !a.fired).map((a) => a.symbol))];
  for (const symbol of due) {
    if (state.data && alarmSym(state.data.symbol) === alarmSym(symbol) &&
        Date.now() - (state.chartLoadedAt || 0) < ALARM_POLL - 5000) continue;
    try {
      const data = await requestJSON(
        `/api/chart?symbol=${encodeURIComponent(symbol)}&range=${RANGE}&interval=${INTERVAL}`);
      checkAlarms(data);
    } catch { /* an outage is not a crossing: try again next minute */ }
  }
}
