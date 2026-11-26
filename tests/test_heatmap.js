"use strict";
// The watchlist tiles: which move, which group, how deep. No browser.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const stub = () => ({
  addEventListener() {}, setAttribute() {}, style: { setProperty() {} },
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  append() {}, closest() { return null; }, dataset: {}, textContent: "",
});
const ctx = vm.createContext({
  localStorage: { getItem: () => null, setItem() {} },
  document: { getElementById: stub, querySelectorAll: () => [], createElement: stub },
  setInterval() {},
});
for (const f of ["verdict", "watchlist", "heatmap"]) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static", f + ".js"), "utf8"), ctx);
}
const day = 86400, t0 = 1_700_000_000;
const pts = Array.from({ length: 40 }, (_, i) => ({ t: t0 + i * day, c: 100 + i }));
const quote = { data: { points: pts }, pct: 39 };
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);
near(ctx.heatMove(quote, "1D"), (139 / 138 - 1) * 100);
near(ctx.heatMove(quote, "1W"), (139 / 132 - 1) * 100);
near(ctx.heatMove(quote, "1M"), (139 / 109 - 1) * 100);
assert.equal(ctx.heatMove(quote, "3M"), 39);
assert.equal(ctx.heatMove({ loading: true }, "1D"), null);
assert.equal(ctx.heatMove({ data: { points: pts.slice(0, 5) } }, "1M"), null);

assert.equal(ctx.heatMarket("PSE:GLO", {}), "Philippines");
assert.equal(ctx.heatMarket("EDGE:GLO", {}), "Philippines");
assert.equal(ctx.heatMarket("FUND:ALFM-PESO", {}), "Philippine funds");
assert.equal(ctx.heatMarket("BTC-USD", { type: "CRYPTOCURRENCY" }), "Crypto");
assert.equal(ctx.heatMarket("PHP=X", {}), "Currencies");
assert.equal(ctx.heatMarket("GC=F", {}), "Futures");
assert.equal(ctx.heatMarket("^GSPC", {}), "Indexes");
assert.equal(ctx.heatMarket("TVC:PH10Y", { yieldSeries: true }), "Bond yields");
assert.equal(ctx.heatMarket("COST", { type: "EQUITY" }), "Stocks & funds");

assert.equal(ctx.heatDepth(1, 0.5), 0.5);          // a quiet day scales against 2%, not itself
assert.equal(ctx.heatDepth(-10, 10), 1);
assert.equal(ctx.heatDepth(null, 10), 0);
console.log("Heatmap move, group and depth checks passed.");
