// Morning-desk helpers: freshness, journal line, period stats, meta store.
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

const saved = new Map();
const localStorage = {
  getItem: (k) => saved.get(k) ?? null,
  setItem: (k, v) => saved.set(k, String(v)),
  removeItem: (k) => saved.delete(k),
};

const ctx = vm.createContext({
  localStorage,
  document: {
    getElementById: () => null,
    createElement: () => ({ append() {}, addEventListener() {}, setAttribute() {} }),
    createElementNS: () => ({ setAttribute() {}, append() {} }),
  },
  window: { prompt: () => null },
  state: { watch: [], watchQuotes: {}, data: null },
  setInterval() {},
  Notification: undefined,
  navigator: {},
  badgePhrase: (t) => (t && t.label ? t.label.charAt(0).toUpperCase() + t.label.slice(1) : ""),
  plainReading: (t) => (t && t.label === "bullish" ? "Rising steadily." : ""),
  formatPrice: (v) => String(v),
  periodChanges: (pts) => {
    if (!pts || pts.length < 2) return null;
    return { periods: [{ name: "1W", pct: 1.5 }, { name: "1M", pct: -2 }] };
  },
  signedPct: (v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`,
  volumeSpike: () => false,
  windowExtreme: () => null,
  chartVolumes: () => [],
  console,
});

vm.runInContext(
  fs.readFileSync(path.join(__dirname, "../static/desk.js"), "utf8"),
  ctx,
);

assert.equal(ctx.quoteFreshness(null).kind, "unknown");
assert.equal(ctx.quoteFreshness({ cached: true, fetchedAt: 1 }).kind, "disk");
assert.equal(ctx.quoteFreshness({ staleDays: 3, staleBar: "2026-01-01" }).kind, "stale");
assert.equal(ctx.quoteFreshness({ lastBarBasis: "live", source: "Yahoo" }).kind, "live");
assert.equal(ctx.quoteFreshness({ lastBarBasis: "close", source: "PSE Edge" }).text, "delayed");
assert.equal(ctx.quoteFreshness({ lastBarBasis: "close", source: "TradingView" }).kind, "settled");

ctx.setWatchMeta("aapl", { note: "earnings watch", flag: "amber", group: "US" });
assert.equal(JSON.stringify(ctx.getWatchMeta("AAPL")),
  JSON.stringify({ note: "earnings watch", flag: "amber", group: "US" }));
ctx.setWatchMeta("AAPL", { note: "", flag: "", group: "" });
assert.equal(JSON.stringify(ctx.getWatchMeta("AAPL")),
  JSON.stringify({ note: "", flag: "", group: "" }));

const stats = ctx.watchlistPeriodStats(
  [{ symbol: "X" }, { symbol: "Y" }],
  {
    X: { data: { points: [{ t: 1, c: 1 }, { t: 2, c: 2 }] } },
    Y: { data: { points: [{ t: 1, c: 1 }, { t: 2, c: 2 }] } },
  },
);
assert.equal(stats["1W"].n, 2);
assert.equal(stats["1W"].median, 1.5);
assert.equal(stats["1M"].min, -2);

const journal = ctx.journalText({
  symbol: "BTC-USD",
  name: "Bitcoin",
  trend: { label: "bullish", since: "2026-10-01", run: 12 },
  points: [{ t: 1, c: 100 }, { t: 2, c: 110 }],
}, "2026-11-24T12:00:00Z");
assert.match(journal, /BTC-USD — Bitcoin/);
assert.match(journal, /Trend: Bullish/);
assert.match(journal, /Reading: Rising steadily/);
assert.match(journal, /Since: 2026-10-01 \(12 bars\)/);
assert.match(journal, /Last: 110/);
assert.match(journal, /not investment advice/);

assert.equal(JSON.stringify(ctx.alarmShortcutTargets({
  points: [
    { t: 1, c: 10 }, { t: 2, c: 12 }, { t: 3, c: 11 }, { t: 4, c: 13 },
  ],
}).map((t) => t.label)), JSON.stringify(["Last", "3M high", "3M low", "20-bar mean"]));

assert.equal(ctx.rowInInbox({ trend: { label: "bullish", pullback: true } }), true);
assert.equal(ctx.rowInInbox({ trend: { label: "neutral" }, points: [] }), false);

console.log("test_desk.js: ok");
