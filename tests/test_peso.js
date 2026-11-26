"use strict";
// Peso view: same-day or earlier USD/PHP rate, never a later one.
const assert = require("assert");
const path = require("path");
const { pesoEligible, convertToPeso } = require(path.join(__dirname, "..", "static", "peso.js"));

const at = (day, hour) => Date.parse(`${day}T${String(hour).padStart(2, "0")}:00:00Z`) / 1000;
const fx = { timezone: "UTC",
  historyTail: [{ t: at("2026-11-02", 0), c: 58.0 }],
  points: [{ t: at("2026-11-03", 0), c: 58.5 }, { t: at("2026-11-05", 0), c: 59.0 }] };
// New York bars at 14:30 UTC = 09:30 local, same calendar day.
const usd = { symbol: "AAPL", currency: "USD", timezone: "America/New_York", priceHint: 2, marketPrice: 12,
  points: [{ t: at("2026-11-02", 14), c: 10 }, { t: at("2026-11-04", 14), c: 11 }, { t: at("2026-11-05", 14), c: 12 }],
  trend: { label: "bullish" } };

const out = convertToPeso(usd, fx);
assert.deepStrictEqual(out.points.map((p) => p.c), [580, 11 * 58.5, 708]);   // 11-04 carries 11-03's rate
assert.strictEqual(out.currency, "PHP");
assert.strictEqual(out.marketPrice, 12 * 59);
assert.strictEqual(out.trend, usd.trend);                                     // label untouched
assert.strictEqual(usd.points[0].c, 10);                                      // original untouched
assert.deepStrictEqual(out.peso, { rate: 59, day: "2026-11-05" });

// A bar before the first rate is not converted with a later rate.
assert.strictEqual(convertToPeso({ ...usd, points: [{ t: at("2026-11-01", 14), c: 9 }, ...usd.points] }, fx), null);

assert.ok(pesoEligible(usd));
assert.ok(pesoEligible({ symbol: "BTC-USD", currency: "USD" }));
assert.ok(!pesoEligible({ symbol: "^GSPC", currency: "USD" }));
assert.ok(!pesoEligible({ symbol: "EURUSD=X", currency: "USD" }));
assert.ok(!pesoEligible({ symbol: "PSE:ALI", currency: "PHP" }));
assert.ok(!pesoEligible({ symbol: "ZN=F", currency: "USD", unit: "%" }));
// A Coins.ph weekend bar on the rate chart is skipped: Saturday carries Friday's FX close.
const fxWeekend = { ...fx, points: [...fx.points, { t: at("2026-11-07", 0), c: 70 }],
  weekendProxy: { stamps: [at("2026-11-07", 0)] } };
const sat = convertToPeso({ ...usd, symbol: "BTC-USD", timezone: "UTC",
  points: [{ t: at("2026-11-07", 12), c: 1 }] }, fxWeekend);
assert.strictEqual(sat.points[0].c, 59);
console.log("peso view: ok");
