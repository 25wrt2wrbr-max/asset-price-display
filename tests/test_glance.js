"use strict";
/* Today's overview pictures: every number the old sentences carried survives. */
const assert = require("node:assert/strict");
const g = require("../static/glance.js");

const digest = {
  pseSession: { state: "open", localTime: "14:50" },
  marketHealth: [{ market: "US", bullish: 2, bearish: 51, neutral: 426, judged: 479 }],
  watchlist: [{ label: "bullish" }, { label: "neutral" }, { label: "bearish" }],
  freshTurns: [{ ticker: "WLCON" }, { ticker: "SNDK" }],
  alarms: { fired: [{ symbol: "AAPL" }] },
  markets: [{ market: "Crypto", state: "offline" }],
};
const pills = g.summaryPills(digest);
const flat = pills.map((p) => p.parts.map((x) => x.text).join(" ")).join(" | ");
assert.match(flat, /PSE open 14:50/);
assert.match(flat, /★ 3 ▲1 ▼1/);
assert.match(flat, /2 fresh turns/);
assert.match(flat, /🔔 1/);
assert.match(flat, /Crypto offline/);
assert.doesNotMatch(flat, /US ▲2/);
assert.match(g.summaryPills(digest, { withMarkets: true }).map((p) => p.title).join(), /US: 2 bullish, 51 bearish/);
assert.deepEqual(g.summaryPills(null), []);

const h = g.healthPieces(digest.marketHealth[0]);
assert.deepEqual(h.parts.map((p) => p.text), ["▲2", "▼51", "●426"]);
assert.equal(h.of, 479);

const chips = g.overnightChips([{ symbol: "CL=F", gapPct: 2 }, { symbol: "INRPHP=X", gapPct: -0.47 }]);
assert.equal(chips[0].name, "WTI oil");
assert.equal(chips[0].text, "+2.00%");
assert.equal(chips[1].name, "INR/PHP");
assert.equal(chips[1].tone, "down");

const r = g.ratesTiles({
  policy: { rate: 5.5, previous: 5.0, since: "2026-10-22" },
  bills: [{ tenor: "1M", yield: 6.09, changeWeek: 0.16, asOf: "2026-11-26" },
          { tenor: "1Y", yield: 6.92, unchangedSince: "2026-11-24" }],
});
assert.equal(r.tiles[0].value, "5.50%");
assert.match(r.tiles[0].sub, /▲ from 5\.00%/);
assert.match(r.tiles[1].sub, /▲ 0\.16 this week/);
assert.equal(r.tiles[2].share, 1);
assert.match(r.note, /not auction results/);
assert.equal(g.ratesTiles({}), null);

assert.deepEqual(g.watchChipParts({ label: "neutral", lean: "bullish" }), { tone: "neutral", lean: "↗", mark: "●" });
assert.equal(g.watchChipParts({ label: "bearish" }).mark, "▼");
assert.equal(g.watchChipParts(null).mark, "○");
const noWeek = g.ratesTiles({ bills: [{ tenor: "3M", yield: 6.5, changeWeek: null }] });
assert.equal(noWeek.tiles[0].sub, "");
assert.equal(g.glanceWhen(0), "");
console.log("glance: ok");
