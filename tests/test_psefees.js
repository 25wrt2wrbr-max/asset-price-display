"use strict";
// PSE fee and break-even checks against published worked examples.
const assert = require("assert");
const path = require("path");
const {
  pseTick, pseRoundToTick, pseTradeFees, pseBreakEven, pseSellNet,
  pseBoardLot, pseCashPlan,
} = require(path.join(__dirname, "..", "static", "psefees.js"));

// COL Financial's FAQ: buy 20,000 ALI at 5.00 -> 295.00; sell at 5.20 -> 410.80.
assert.strictEqual(pseTradeFees(100000, "buy").total, 295.00);
assert.strictEqual(pseTradeFees(104000, "sell").total, 410.80);
// The 20-peso floor: a 1,000-peso buy pays 20 + 2.40 VAT + 0.05 + 0.10.
const small = pseTradeFees(1000, "buy");
assert.strictEqual(small.commission, 20);
assert.strictEqual(small.total, 22.55);   // calculate.ph's ₱10 x 100 example
assert.strictEqual(pseTradeFees(1000, "sell").total, 23.55);

// Ticks from the PSE board lot table, including bracket edges.
assert.strictEqual(pseTick(4.99), 0.01);
assert.strictEqual(pseTick(10), 0.02);
assert.strictEqual(pseTick(19.98), 0.02);
assert.strictEqual(pseTick(20), 0.05);
assert.strictEqual(pseTick(199.9), 0.1);
assert.strictEqual(pseTick(6000), 5);

// Break-even is on a valid tick, and the tick before it falls short.
function check(price, shares) {
  const be = pseBreakEven(price, shares);
  const outlay = price * shares + pseTradeFees(price * shares, "buy").total;
  const net = (s) => s * shares - pseTradeFees(s * shares, "sell").total;
  assert.ok(net(be) >= outlay - 1e-9, `${price}x${shares}: ${be} does not cover`);
  const tick = pseTick(be - 1e-9);
  const before = Number((be - tick).toFixed(4));
  if (before >= price) assert.ok(net(before) < outlay, `${price}x${shares}: ${before} already covers`);
  const steps = be / pseTick(be);
  assert.ok(Math.abs(steps - Math.round(steps)) < 1e-6, `${be} is not on a tick`);
  return be;
}
assert.strictEqual(check(10, 100), 10.48);      // floor-heavy one-lot trade
check(5, 20000);
check(19.9, 100);                                // crosses the 19.98 -> 20.00 edge
check(0.33, 10000);
check(1500, 5);
check(115.5, 10);

// Sell net: gross − sell fees on COL's ALI sell example (20,000 × 5.20).
assert.strictEqual(pseSellNet(5.20, 20000), round2ish(104000 - 410.80));
function round2ish(x) { return Math.round(x * 100 + 1e-9) / 100; }
assert.strictEqual(pseRoundToTick(10.01, "nearest"), 10.02);  // tick 0.02 above 10
assert.strictEqual(pseRoundToTick(10.004, "nearest"), 10.00);
assert.strictEqual(pseRoundToTick(19.99, "up"), 20.00);

assert.strictEqual(pseBoardLot(4.99), 1000);
assert.strictEqual(pseBoardLot(10), 100);
assert.strictEqual(pseBoardLot(6000), 5);
assert.strictEqual(pseBoardLot(null), null);

const plan = pseCashPlan(100_000, 5);
assert.ok(plan);
assert.strictEqual(plan.lot, 100);
assert.ok(plan.lots >= 1);
assert.ok(plan.outlay <= 100_000 + 1e-9);
assert.ok(plan.leftover >= 0);
assert.strictEqual(pseCashPlan(100, 500), null);

console.log("pse fees: ok");
