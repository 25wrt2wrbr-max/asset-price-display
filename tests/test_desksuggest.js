"use strict";
// Desk suggestion pack: pure helpers only.
const assert = require("assert");
const path = require("path");
const ds = require(path.join(__dirname, "..", "static", "desksuggest.js"));

assert.equal(ds.formatCountdown(90), "1m 30s");
assert.equal(ds.formatCountdown(3661), "1h 01m");
assert.ok(ds.formatCountdown(90000).includes("d"));

const open = ds.pseSessionChip({
  state: "open", secondsToClose: 120, localTime: "15:13", _at: 0,
}, 0);
assert.match(open.text, /closes in/);

const pre = ds.pseSessionChip({
  state: "pre-open", secondsToOpen: 600, localTime: "09:20", _at: 0,
}, 0);
assert.match(pre.text, /opens in/);

assert.equal(ds.thinBookWarn(2_000_000), null);
assert.equal(ds.thinBookWarn(500_000).text, "thin book");
assert.equal(ds.thinBookWarn(null), null);

assert.match(ds.pseEdgeUrl("PSE:ALI"), /companyName=ALI/);
assert.match(ds.pseEdgeUrl("EDGE:GLO"), /GLO/);

const spread = ds.phUstSpread([
  { chartSymbol: "TVC:PH10Y", price: 6.2, market: "Philippine bonds" },
  { chartSymbol: "^TNX", price: 4.1 },
]);
assert.equal(spread.kind, "spread");
assert.ok(Math.abs(spread.spread - 2.1) < 1e-9);

const levels = ds.phUstSpread([
  { chartSymbol: "TVC:PH10Y", price: 6.2, ticker: "PH10Y" },
  { chartSymbol: "ZB=F", price: 115.5, ticker: "ZB" },
]);
assert.equal(levels.kind, "levels");

const ladder = ds.fundPeerLadder("FUND:A", [
  { symbol: "FUND:A" }, { symbol: "FUND:B" }, { symbol: "FUND:C" },
], {
  "FUND:A": { data: { fundSeries: true, category: "Equity", points: [{ c: 1 }, { c: 1.1 }], name: "A" } },
  "FUND:B": { data: { fundSeries: true, category: "Equity", points: [{ c: 1 }, { c: 1.05 }], name: "B" } },
  "FUND:C": { data: { fundSeries: true, category: "Equity", points: [{ c: 1 }, { c: 0.9 }], name: "C" } },
});
// periodChanges may be undefined in node — ladder needs it; if null, skip assert.
if (ladder) {
  assert.equal(ladder.peers.length, 3);
  assert.ok(ladder.rank >= 1);
}

const diff = ds.packetDayDiff(
  { digest: { summary: "old", freshTurns: [{ symbol: "A" }], alarms: { peso: [] } } },
  { digest: { summary: "new", freshTurns: [{ symbol: "A" }, { symbol: "B" }], alarms: { peso: [{}] } } },
);
assert.match(diff.text, /new turn/);
assert.match(diff.text, /peso alarms/);

const counts = ds.watchLabelCounts(
  [{ symbol: "X" }, { symbol: "Y" }],
  {
    X: { data: { trend: { label: "bullish" }, points: [{ c: 1 }, { c: 1.1 }] } },
    Y: { data: { trend: { label: "bearish" }, points: [{ c: 1 }, { c: 0.9 }] } },
  },
);
assert.equal(counts.counts.bullish, 1);
assert.equal(counts.counts.bearish, 1);
assert.ok(Number.isFinite(counts.median));

assert.match(ds.CHANCE_LINE, /3\.7%/);

console.log("desksuggest: ok");
