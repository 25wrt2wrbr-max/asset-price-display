"use strict";
// Ex-dividend markers: which bar each ex-date lands on, and the wording.
const assert = require("assert");
const path = require("path");
const D = require(path.join(__dirname, "..", "static", "dividends.js"));

// Bars stamped 09:30 Manila (01:30 UTC): Nov 19, 20, 23 (Mon), 24 2026.
const at = (y, m, d) => Date.UTC(y, m - 1, d, 1, 30) / 1000;
const stamps = [at(2026, 11, 19), at(2026, 11, 20), at(2026, 11, 23), at(2026, 11, 24)];
assert.strictEqual(D.manilaDay(stamps[2]), "2026-11-23");

const cash = { kind: "Cash", amount: 0.6, currency: "PHP", rate: "Php0.60", ex: "2026-11-23" };
const special = { kind: "Cash", amount: 0.32, currency: "PHP", rate: "Php0.32", ex: "2026-11-23" };
const weekend = { kind: "Cash", amount: 1, currency: "PHP", ex: "2026-11-21" };   // a Saturday
const before = { kind: "Cash", amount: 1, currency: "PHP", ex: "2026-11-01" };
const after = { kind: "Cash", amount: 1, currency: "PHP", ex: "2026-12-04" };
const marks = D.dividendMarks([cash, special, weekend, before, after], stamps);
assert.strictEqual(marks.length, 1, "one bar, three dividends, outside dates dropped");
assert.strictEqual(marks[0].i, 2);
assert.strictEqual(marks[0].events.length, 3);
assert.deepStrictEqual(D.dividendMarks([cash], []), []);

assert.strictEqual(D.dividendAmountText(cash), "₱0.60 cash");
assert.strictEqual(D.dividendAmountText({ kind: "Cash", amount: 0.0114, currency: "USD" }), "$0.0114 cash");
assert.strictEqual(D.dividendAmountText({ kind: "Stock", rate: "10%" }), "stock dividend (10%)");
assert.strictEqual(D.dividendAmountText({ kind: "Cash", amount: null, rate: "see circular" }), "cash (see circular)");

assert.ok(D.isPseChartSymbol("PSE:BDO") && D.isPseChartSymbol("edge:tel") && D.isPseChartSymbol("bdo.ps"));
assert.ok(!D.isPseChartSymbol("AAPL") && !D.isPseChartSymbol("BTC-USD"));

const line = D.dividendSentence({ source: "PSE Edge", next: { ...after, pay: "2026-12-18" } }, marks);
assert.ok(line.startsWith("Ex-dividend in this window: "), line);
assert.ok(line.includes("not a sign of weakness"), line);
assert.ok(line.includes("Next ex-date: ") && line.includes("paid "), line);
assert.ok(line.endsWith("Source: PSE Edge."), line);
assert.strictEqual(D.dividendSentence({ next: null }, []), "");
// A chart reaching back past the list's oldest date says where dates start.
const partial = D.dividendSentence({ coverFrom: "2025-12-02" }, marks, "2024-11-26");
assert.ok(partial.startsWith("Ex-dividend dates known from "), partial);
const none = D.dividendSentence({ coverFrom: "2025-12-02" }, [], "2024-11-26");
assert.ok(none.startsWith("No ex-dividend date since ") && none.includes("not in the list"), none);
assert.strictEqual(D.dividendSentence({ coverFrom: "2025-12-02" }, [], "2026-08-28"), "");
// Without the company list, no "none" sentence (an outage is not a fact).
assert.strictEqual(D.dividendSentence({ coverFrom: "2025-12-02", complete: false }, [], "2024-11-26"), "");
console.log("dividends: ok");
