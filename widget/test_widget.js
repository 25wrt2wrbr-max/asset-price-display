// Node tests for trend-widget.js (no browser needed): node widget/test_widget.js
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const here = __dirname;
const box = {};
box.self = box;
vm.runInNewContext(fs.readFileSync(path.join(here, "trend-widget.js"), "utf8"), box);
const { Trend, TrendWidget: W } = box;

let passed = 0;
function test(name, fn) {
  try { fn(); passed++; } catch (e) { console.error("FAIL", name, "\n ", e.message); process.exitCode = 1; }
}

// The scorer inside the bundle is the exported one, unchanged.
test("bundle carries export/trend.js unchanged", () => {
  const bundle = fs.readFileSync(path.join(here, "trend-widget.js"), "utf8");
  const scorer = fs.readFileSync(path.join(here, "..", "export", "trend.js"), "utf8").trimEnd();
  assert.ok(bundle.includes(scorer));
});

function walk(seed, drift, n) {
  let x = seed, p = 100;
  const out = [];
  for (let i = 0; i < n; i++) {
    x = (x * 1103515245 + 12345) % 2147483648;
    p *= Math.exp(drift + 0.01 * ((x / 2147483648) - 0.5) * 3.4);
    out.push(+p.toFixed(4));
  }
  return out;
}

test("judge scores the last 63 closes with Trend.classify", () => {
  for (const [seed, drift] of [[1, 0.004], [2, -0.004], [3, 0], [4, 0.002], [5, -0.001]]) {
    const closes = walk(seed, drift, 120);
    const v = W.judge(closes);
    const r = Trend.classify(closes.slice(-63));
    assert.strictEqual(v.bars, 63);
    assert.strictEqual(v.label, r.label);
    assert.strictEqual(v.result.score, r.score);
  }
});

test("bars option and 'all'", () => {
  const closes = walk(9, 0.003, 100);
  assert.strictEqual(W.judge(closes, { bars: 30 }).bars, 30);
  assert.strictEqual(W.judge(closes, { bars: "all" }).bars, 100);
  assert.strictEqual(W.judge(closes, { bars: "all" }).result.score, Trend.classify(closes).score);
});

test("every input shape gives the same verdict", () => {
  const closes = walk(4, 0.004, 63);
  const dates = closes.map((_, i) => new Date(Date.UTC(2026, 0, 1) + i * 864e5).toISOString().slice(0, 10));
  const want = W.judge(closes).result.score;
  const shapes = [
    closes,
    closes.map((c, i) => [dates[i], c]),
    closes.map((c, i) => ({ date: dates[i], close: c })),
    { dates, closes },
    "date,close\n" + closes.map((c, i) => dates[i] + "," + c).join("\n"),
    "Date,Open,High,Low,Close,Volume\n" + closes.map((c, i) => `${dates[i]},1,1,1,${c},5`).join("\n"),
    closes.join(", "),
    JSON.stringify(closes.map((c, i) => ({ date: dates[i], close: c }))),
  ];
  shapes.forEach((s, k) => assert.strictEqual(W.judge(s).result.score, want, "shape " + k));
});

test("newest-first input is turned around", () => {
  const closes = walk(6, 0.004, 63);
  const dates = closes.map((_, i) => new Date(Date.UTC(2026, 0, 1) + i * 864e5).toISOString().slice(0, 10));
  const rev = closes.map((c, i) => ({ date: dates[i], close: c })).reverse();
  const v = W.judge(rev);
  assert.strictEqual(v.result.score, W.judge(closes).result.score);
  assert.strictEqual(v.last, closes[closes.length - 1]);
});

test("unix seconds and milliseconds dates", () => {
  const s = W.normalize([[1767225600, 10], [1767312000, 11]]);
  const ms = W.normalize([[1767225600000, 10], [1767312000000, 11]]);
  assert.strictEqual(s.dates[0].toISOString().slice(0, 10), "2026-01-01");
  assert.strictEqual(ms.dates[1].toISOString().slice(0, 10), "2026-01-02");
});

test("bad rows are dropped and counted", () => {
  const v = W.normalize([1, 2, null, "x", 0, -3, "4.5", "$1,200.50"]);
  assert.strictEqual(JSON.stringify(v.closes), "[1,2,4.5,1200.5]");
  assert.strictEqual(v.dropped, 4);
});

test("fewer than 3 prices is not a verdict", () => {
  assert.strictEqual(W.judge([1, 2]).result, null);
  assert.strictEqual(W.judge([1, 2]).label, null);
  assert.strictEqual(W.judge([]).words, "Not enough data");
});

test("words", () => {
  assert.strictEqual(W.words({ label: "bullish", pullback: true }).text, "Bullish");
  assert.strictEqual(W.words({ label: "bullish", pullback: true }).tag, "pulling back");
  assert.strictEqual(W.words({ label: "bearish", pullback: true }).tag, "bouncing");
  assert.strictEqual(W.words({ label: "neutral", lean: "bullish" }).tag, "leaning bullish");
  assert.strictEqual(W.words({ label: "neutral", lean: null }).tag, "");
});

test("demo prices read as their names say", () => {
  const read = (f) => fs.readFileSync(path.join(here, "demo-data", f), "utf8");
  assert.strictEqual(W.judge(W.parseText(read("rising.json"))).label, "bullish");
  assert.strictEqual(W.judge(W.parseText(read("falling.csv"))).label, "bearish");
  assert.strictEqual(W.judge(W.parseText(read("sideways.json"))).label, "neutral");
});

console.log(`${passed} widget tests passed` + (process.exitCode ? " (some FAILED)" : ""));
