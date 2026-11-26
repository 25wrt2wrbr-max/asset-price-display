// Desk extras: turnover, yield curve, peer drift, staleness.
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

const ctx = vm.createContext({
  chartVolumes: (d) => d.volumes,
  periodChanges: (pts) => {
    if (!pts || pts.length < 2) return null;
    const a = pts[0].c, b = pts[pts.length - 1].c;
    return { periods: [{ name: "1M", pct: (b / a - 1) * 100 }] };
  },
  benchmarkReading: () => null,
  module: { exports: {} },
});
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "../static/deskextras.js"), "utf8"),
  ctx,
);

const turn = ctx.watchTurnover({
  currency: "PHP",
  symbol: "PSE:ALI",
  points: [
    { t: 1, c: 10 }, { t: 2, c: 10 }, { t: 3, c: 10 },
    { t: 4, c: 10 }, { t: 5, c: 10 }, { t: 6, c: 10 },
  ],
  volumes: [100, 100, 100, 100, 100, 100],
}, 5);
assert.equal(turn, 1000);

assert.equal(ctx.watchTurnover({ currency: "USD", symbol: "AAPL", points: [], volumes: [] }), null);

const shape = ctx.yieldCurveShape([
  { chartSymbol: "TVC:PH02Y", price: 5.0 },
  { chartSymbol: "TVC:PH05Y", price: 5.5 },
  { chartSymbol: "TVC:PH10Y", price: 6.0 },
]);
assert.equal(shape.word, "steep");
assert.match(shape.text, /PH curve steep/);

const flat = ctx.yieldCurveShape([
  { chartSymbol: "TVC:PH02Y", price: 5.0 },
  { chartSymbol: "TVC:PH10Y", price: 5.02 },
]);
assert.equal(flat.word, "flat");

const watch = [
  { symbol: "FUND:A" }, { symbol: "FUND:B" }, { symbol: "FUND:C" },
];
const quotes = {
  "FUND:A": { data: { fundSeries: true, category: "equity", points: [{ c: 1 }, { c: 1.2 }] } },
  "FUND:B": { data: { fundSeries: true, category: "equity", points: [{ c: 1 }, { c: 1.05 }] } },
  "FUND:C": { data: { fundSeries: true, category: "equity", points: [{ c: 1 }, { c: 0.9 }] } },
};
assert.equal(ctx.fundPeerDrift("FUND:A", watch, quotes).kind, "top");
assert.equal(ctx.fundPeerDrift("FUND:C", watch, quotes).kind, "bottom");
assert.equal(ctx.fundPeerDrift("FUND:B", watch, quotes), null);

assert.equal(ctx.marketStaleness([{ market: "US", state: "live" }]), null);
const stale = ctx.marketStaleness([
  { market: "US", state: "partial" },
  { market: "PSE", state: "offline" },
]);
assert.match(stale.text, /US partial/);
assert.match(stale.text, /PSE offline/);

console.log("Desk extras helpers passed.");
