"use strict";
// Quiet-refresh signature: same draw-facing fields → equal; a price tick → not.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const src = fs.readFileSync(path.join(__dirname, "../static/core.js"), "utf8");
const start = src.indexOf("function chartQuietSig");
const end = src.indexOf("async function loadChart");
assert.ok(start >= 0 && end > start, "chartQuietSig located");
const sandbox = { console };
vm.createContext(sandbox);
vm.runInContext(src.slice(start, end), sandbox);

const base = {
  symbol: "AAPL",
  name: "Apple",
  currency: "USD",
  lastBarBasis: "live",
  fetchedAt: 1,
  cached: false,
  points: [{ t: 1, c: 100, v: 10 }, { t: 2, c: 101, v: 11 }],
  trend: { label: "bullish", score: 0.4, held: false, significance: 2.1, pullback: false },
  profitProbability: { probability: 0.55, cost: 0.01 },
};
assert.equal(sandbox.chartQuietSig(base), sandbox.chartQuietSig({ ...base, historyTail: [{ t: 0, c: 90 }] }));
const tick = {
  ...base,
  points: [{ t: 1, c: 100, v: 10 }, { t: 2, c: 102, v: 11 }],
};
assert.notEqual(sandbox.chartQuietSig(base), sandbox.chartQuietSig(tick));
const labelFlip = {
  ...base,
  trend: { ...base.trend, label: "neutral" },
};
assert.notEqual(sandbox.chartQuietSig(base), sandbox.chartQuietSig(labelFlip));
const stale = { ...base, staleDays: 4, staleBar: "2026-11-20" };
assert.notEqual(sandbox.chartQuietSig(base), sandbox.chartQuietSig(stale));
const quality = { ...base, quality: [{ code: "gap", text: "missing bar" }] };
assert.notEqual(sandbox.chartQuietSig(base), sandbox.chartQuietSig(quality));
console.log("chart quiet sig: ok");
