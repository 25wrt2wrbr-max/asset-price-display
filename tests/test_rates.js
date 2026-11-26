// Peso cash rates strip words (static/rates.js): pure formatter checks.
const assert = require("assert");
const { ratesStripText, ratesDay } = require("../static/rates.js");

assert.strictEqual(ratesDay("2026-10-22"), "Oct 22");
assert.strictEqual(ratesDay("bad"), "");
assert.strictEqual(ratesStripText(null), null);
assert.strictEqual(ratesStripText({ policy: null, bills: [] }), null);

const t = ratesStripText({
  policy: { rate: 5.5, since: "2026-10-22", previous: 5.0 },
  bills: [
    { tenor: "3 months", yield: 6.525, asOf: "2026-11-26", changeWeek: 0.15, unchangedSince: null },
    { tenor: "1 year", yield: 6.92, asOf: "2026-11-26", changeWeek: 0, unchangedSince: "2026-11-23" },
    { tenor: "6 months", yield: null, asOf: "2026-11-26" },
  ],
  source: "TradingView",
});
assert.strictEqual(t.line, "BSP policy rate 5.50% since Oct 22 (was 5.00%)");
assert.deepStrictEqual(t.bills.map((b) => b.tenor), ["3 months", "1 year"]);  // no null yield
assert.strictEqual(t.bills[0].text, "6.53%");
assert.strictEqual(t.bills[0].move, "up 0.15 this week");
assert.strictEqual(t.bills[1].move, "no change since Nov 23");
assert.ok(t.note.includes("(Nov 26)"));
assert.ok(t.note.includes("not Treasury auction results"));
assert.ok(!/bullish|bearish/i.test(JSON.stringify(t)));

const saved = ratesStripText({ policy: { rate: 5.5 }, bills: [], cached: true });
assert.strictEqual(saved.line, "BSP policy rate 5.50%");
assert.ok(saved.note.includes("Saved copy"));
const refreshing = ratesStripText({ policy: { rate: 5.5 }, bills: [], cached: true, revalidate: true });
assert.ok(!refreshing.note.includes("Saved copy"));   // refreshing behind a saved copy is not an outage

console.log("rates strip: ok");

// ---- "Against cash" line ----
const { beatCash, beatCashText, manilaDay } = require("../static/rates.js");
const DAY = 86400;
const T0 = Date.UTC(2026, 7, 26, 1, 30) / 1000;     // Aug 26 2026, 09:30 Manila
assert.strictEqual(manilaDay(T0), "2026-08-26");
function series(n, from, to) {
  return Array.from({ length: n }, (_, i) => ({ t: T0 + i * DAY * 1.4, c: from + (to - from) * i / (n - 1) }));
}
const hist = [["2026-08-20", 5.0], ["2026-08-25", 5.9], ["2026-08-27", 6.1]];
const php = { currency: "PHP", points: series(64, 100, 104) };
const r = beatCash(php, hist);
assert.ok(r, "peso chart compares");
assert.strictEqual(r.rate, 5.9);                      // last yield on or before the start day
assert.strictEqual(r.start, "2026-08-26");
assert.ok(Math.abs(r.price - 4) < 1e-9);
assert.ok(Math.abs(r.cash - 5.9 * ((63 * 1.4 * DAY) / DAY) / 365) < 1e-9);
assert.strictEqual(r.verdict, "the price did better than cash");
const words = beatCashText(r);
assert.ok(words.value.startsWith("+4.0% vs cash +1."));
assert.ok(words.note.includes("Aug 26") && words.note.includes("before 20% tax"));
assert.ok(!/bullish|bearish/i.test(JSON.stringify(words)));
assert.strictEqual(beatCash({ ...php, points: series(64, 100, 99) }, hist).verdict,
  "cash did better than the price");
assert.strictEqual(beatCash({ ...php, currency: "USD" }, hist), null);     // dollars: no peso cash
assert.strictEqual(beatCash({ ...php, unit: "%" }, hist), null);           // a yield chart
assert.strictEqual(beatCash({ ...php, points: series(10, 100, 104) }, hist), null);
assert.strictEqual(beatCash(php, [["2026-08-01", 5.0]]), null);            // bill yield too stale
assert.strictEqual(beatCash(php, [["2026-09-01", 6.0]]), null);            // none before the start
console.log("against cash: ok");
