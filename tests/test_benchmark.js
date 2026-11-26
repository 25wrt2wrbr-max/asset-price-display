"use strict";
// Which benchmark a chart is read against.
const assert = require("assert");
const path = require("path");
const { benchmarkFor } = require(path.join(__dirname, "..", "static", "benchmark.js"));
const pick = (d) => (benchmarkFor(d) || {}).symbol || null;

assert.strictEqual(pick({ symbol: "PSE:ALI", type: "stock", currency: "PHP" }), "PSE:PSEI");
assert.strictEqual(pick({ symbol: "PSE:FMETF", type: "fund", currency: "PHP" }), "PSE:PSEI");
assert.strictEqual(pick({ symbol: "AAPL", type: "EQUITY", currency: "USD" }), "SPY");
assert.strictEqual(pick({ symbol: "QQQ", type: "ETF", currency: "USD" }), "SPY");
assert.strictEqual(pick({ symbol: "ETH-USD", type: "CRYPTOCURRENCY", currency: "USD" }), "BTC-USD");
for (const d of [
  { symbol: "SPY", type: "ETF", currency: "USD" },
  { symbol: "BTC-USD", type: "CRYPTOCURRENCY", currency: "USD" },
  { symbol: "PSE:PSEI", type: "index", currency: "PHP" },
  { symbol: "PSE:M_O", type: "index", currency: "PHP" },
  { symbol: "TVC:PH10Y", type: "YIELD", yieldSeries: true },
  { symbol: "^GSPC", type: "INDEX", currency: "USD" },
  { symbol: "GC=F", type: "FUTURE", currency: "USD" },
  { symbol: "EURUSD=X", type: "CURRENCY", currency: "USD" },
  { symbol: "FUND:BPI-MM", type: "Net asset value", currency: "PHP" },
  { symbol: "SAP.DE", type: "EQUITY", currency: "EUR" },
]) assert.strictEqual(pick(d), null, d.symbol);
console.log("benchmark: ok");
