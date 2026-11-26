"use strict";

/* ---- PSE trading costs (pure functions, no DOM) ----
   COL Financial's published online schedule, the common retail one
   (checked 2026-11-24, colfinancial.com FAQ and pse.com.ph/investing-at-pse):
     commission 0.25% of the trade, at least PHP 20, plus 12% VAT on it;
     PSE transaction fee 0.005%; SCCP clearing fee 0.01%;
     stock transaction tax 0.1% on sales only (cut from 0.6% on 2025-07-01, CMEPA).
   Other brokers may charge a different commission, and some also pass on the
   0.005% SRC fee and VAT on the PSE fee shown in the PSE's own example (about
   PHP 0.56 per PHP 10,000), which COL's schedule does not list. */
const PSE_FEES = {
  commission: 0.0025,
  minCommission: 20,
  vat: 0.12,
  exchange: 0.00005,
  clearing: 0.0001,
  salesTax: 0.001,
  source: "COL Financial online rates",
};

/* PSE tick sizes by price (pse.com.ph Board Lot Table): [upper bound, tick]. */
const PSE_TICKS = [
  [0.0099, 0.0001], [0.0490, 0.001], [0.2490, 0.001], [0.4950, 0.005],
  [4.99, 0.01], [9.99, 0.01], [19.98, 0.02], [49.95, 0.05], [99.95, 0.05],
  [199.90, 0.1], [499.80, 0.2], [999.50, 0.5], [1999, 1], [4998, 2],
];

/* PSE board lot table (markets.py BOARD_LOTS), half-open on the upper bound. */
const PSE_BOARD_LOTS = [
  [0.0099, 1_000_000], [0.0490, 100_000], [0.2490, 10_000], [0.4950, 10_000],
  [4.99, 1_000], [9.99, 100], [19.98, 100], [49.95, 100], [99.95, 10],
  [199.90, 10], [499.80, 10], [999.50, 10], [1_999, 5], [4_998, 5],
];
const ABOVE_TOP_LOT = 5;

function pseTick(price) {
  for (const [upper, tick] of PSE_TICKS) if (price <= upper + 1e-9) return tick;
  return 5;
}

/* Snap `price` to a valid PSE tick. `mode` is "nearest" (default), "up", or "down". */
function pseRoundToTick(price, mode) {
  if (!(price > 0)) return null;
  const tick = pseTick(price);
  const n = price / tick;
  let steps;
  if (mode === "up") steps = Math.ceil(n - 1e-9);
  else if (mode === "down") steps = Math.floor(n + 1e-9);
  else steps = Math.round(n);
  return Number((steps * tick).toFixed(4));
}

const round2 = (x) => Math.round(x * 100 + 1e-9) / 100;

/* Pesos left after selling `shares` at `price` (gross − sell-side fees). */
function pseSellNet(price, shares) {
  if (!(price > 0) || !(shares > 0)) return null;
  const value = price * shares;
  return round2(value - pseTradeFees(value, "sell").total);
}

/* Fees on one trade of `value` pesos, each item rounded to the centavo the
   way a broker's confirmation prints it. */
function pseTradeFees(value, side) {
  const f = PSE_FEES;
  const commission = round2(Math.max(value * f.commission, f.minCommission));
  const vat = round2(commission * f.vat);
  const exchange = round2(value * f.exchange);
  const clearing = round2(value * f.clearing);
  const tax = side === "sell" ? round2(value * f.salesTax) : 0;
  const total = round2(commission + vat + exchange + clearing + tax);
  return { commission, vat, exchange, clearing, tax, total };
}

/* The lowest price, on a valid tick, at which selling `shares` bought at
   `price` gets back at least what the purchase cost with its fees. */
function pseBoardLot(price) {
  if (!(price > 0)) return null;
  for (const [upper, lot] of PSE_BOARD_LOTS) {
    if (price <= upper + 1e-9) return lot;
  }
  return ABOVE_TOP_LOT;
}

/* Largest whole board lots affordable with `cash` at `price`, including buy fees. */
function pseCashPlan(cash, price) {
  if (!(cash > 0) || !(price > 0)) return null;
  const lot = pseBoardLot(price);
  if (!lot) return null;
  let lots = Math.floor(cash / (price * lot));
  if (lots < 1) return null;
  while (lots > 0) {
    const shares = lots * lot;
    const gross = price * shares;
    const fees = pseTradeFees(gross, "buy");
    const outlay = round2(gross + fees.total);
    if (outlay <= cash + 1e-9) {
      return {
        lot,
        shares,
        lots,
        buyFees: fees.total,
        outlay,
        leftover: round2(cash - outlay),
        breakEven: pseBreakEven(price, shares),
        sellNet: pseSellNet(price, shares),
      };
    }
    lots -= 1;
  }
  return null;
}

function pseBreakEven(price, shares) {
  if (!(price > 0) || !(shares > 0)) return null;
  const buyValue = price * shares;
  const outlay = buyValue + pseTradeFees(buyValue, "buy").total;
  // Start at the first tick at or above the buy price and walk up.
  let tick = pseTick(price);
  let s = Math.ceil(price / tick - 1e-9) * tick;
  for (let i = 0; i < 100000; i++) {
    const v = s * shares;
    if (v - pseTradeFees(v, "sell").total >= outlay - 1e-9) {
      return Number(s.toFixed(4));
    }
    tick = pseTick(s + 1e-9);
    s = Math.round((s + tick) / tick) * tick;
  }
  return null;
}

if (typeof module !== "undefined") {
  module.exports = {
    PSE_FEES, pseTick, pseRoundToTick, pseTradeFees, pseBreakEven, pseSellNet,
    pseBoardLot, pseCashPlan, PSE_BOARD_LOTS, ABOVE_TOP_LOT,
  };
}
