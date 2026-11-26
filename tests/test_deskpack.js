"use strict";
const assert = require("assert");
const path = require("path");
const fees = require(path.join(__dirname, "..", "static", "psefees.js"));
const pack = require(path.join(__dirname, "..", "static", "deskpack.js"));

assert.strictEqual(fees.pseBoardLot(49.95), 100);
assert.strictEqual(fees.pseBoardLot(5000), 5);

assert.strictEqual(pack.pseSettleDate("2026-11-20"), "2026-11-24"); // Fri → Tue
assert.strictEqual(pack.pseSettleDate("2026-11-24"), "2026-11-26"); // Mon → Wed
const hol = new Set(["2026-11-26"]);
assert.strictEqual(pack.pseSettleDate("2026-11-24", hol), "2026-11-27");

const quiet = pack.morningPulseLines({ freshTurns: [], alarms: { fired: [] }, markets: [] });
assert.ok(quiet[0].toLowerCase().includes("quiet"));

const busy = pack.morningPulseLines({
  freshTurns: [{ ticker: "ALI" }],
  alarms: { fired: [{ symbol: "PSE:GLO" }] },
  markets: [{ market: "crypto", state: "offline" }],
});
assert.equal(busy.length, 3);

const gap = pack.overnightGapText([
  { symbol: "ES", gapPct: 0.42 },
  { label: "NQ", pct: -0.31 },
]);
assert.match(gap, /ES/);
assert.match(gap, /NQ/);

const words = pack.chartInWords({
  name: "Apple",
  symbol: "AAPL",
  trend: { label: "bullish", score: 0.41 },
  points: [{ c: 100 }, { c: 110 }],
});
assert.match(words, /bullish/i);
assert.match(words, /10\.00%/);

assert.ok(pack.ASEAN_PRESETS.length >= 4);
assert.ok(pack.COMMO_SYMBOLS.some((row) => row[0] === "GC=F"));

// Desk mode: the full view is the default, a load never saves a choice,
// and only a click on Scan records one.
{
  const store = new Map();
  global.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
  };
  const classes = new Set();
  const btn = { dataset: {}, attrs: {}, listeners: [], textContent: "", title: "",
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(_t, fn) { this.listeners.push(fn); } };
  global.document = {
    body: { classList: { add: (c) => classes.add(c), remove: (...cs) => cs.forEach((c) => classes.delete(c)),
                         contains: (c) => classes.has(c) } },
    getElementById: (id) => (id === "modeToggle" ? btn : null),
  };
  store.set("apd-desk-mode", "scan");               // the old key, written by every load
  pack.wireModeToggle();
  assert.ok(classes.has("desk-focus") && !classes.has("desk-scan"), "full view by default");
  assert.strictEqual(store.get(pack.MODE_KEY), undefined, "loading saves nothing");
  assert.strictEqual(btn.attrs["aria-pressed"], "false");
  btn.listeners[0]();                                // click: scan on
  assert.ok(classes.has("desk-scan"));
  assert.strictEqual(store.get(pack.MODE_KEY), "scan");
  assert.strictEqual(btn.attrs["aria-pressed"], "true");
  assert.strictEqual(btn.textContent, "Scan");
  btn.listeners[0]();                                // click again: full view
  assert.ok(classes.has("desk-focus"));
  assert.strictEqual(store.get(pack.MODE_KEY), "focus");
  delete global.document;
  delete global.localStorage;
}

console.log("deskpack: ok");