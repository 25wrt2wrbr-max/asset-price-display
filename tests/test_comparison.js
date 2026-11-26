"use strict";

// Exercise the page's own script with deterministic chart replies, including
// a late response that arrives after cancellation. No network or server.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
class Element {
  constructor() { this.children = []; this.listeners = {}; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  setAttribute(k, v) { this[k] = v; }
  removeAttribute(k) { delete this[k]; }
  append(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children = nodes; }
  child() { const node = new Element(); this.append(node); return node; }
  createCaption() { return this.child(); }
  createTHead() { return this.child(); }
  createTBody() { return this.child(); }
  insertRow() { return this.child(); }
  insertCell() { return this.child(); }
}
const nodes = {}, requests = [];
const app = vm.createContext({
  document: { getElementById(id) { return nodes[id] ||= new Element(); }, createElement: () => new Element() },
  toDate: t => new Date(t * 1000), AbortController, setTimeout, clearTimeout, RANGE: "3mo", INTERVAL: "1d", BASIS_WORDS: {},
  requestJSON: (url, signal) => new Promise(resolve => requests.push({resolve, url, signal})),
  svgEl: (tag, attrs) => Object.assign(new Element(), { tag, attrs }), niceTicks: () => [100], axisTickFmt: String,
});
for (const file of ['asset-search', 'compare']) vm.runInContext(fs.readFileSync(path.join(__dirname, `../static/${file}.js`), "utf8"), app);
const pt = (iso, c) => ({ t: Date.parse(iso) / 1000, c });
const a = { symbol: "A", yieldSeries: true, points: [
  pt("2026-11-09T21:00Z", 6), pt("2026-11-08T21:00Z", 4), pt("2026-11-05T21:00Z", 3),
] };
const b = { symbol: "B", points: [
  pt("2026-11-08T00:00Z", 20), pt("2026-11-09T00:00Z", 30), pt("2026-11-10T00:00Z", 15),
] };
async function run() {
  // Two series: the original contract.
  const expected = [{day: "2026-11-09", a: 100, b: 100}, {day: "2026-11-10", a: 150, b: 50}];
  assert.deepEqual(JSON.parse(JSON.stringify(app.comparisonRows(a,b))), expected);
  assert.throws(() => app.comparisonRows(a, { points: [] }), /shared trading dates/);
  assert.throws(() => app.comparisonRows(a, { points: b.points.map(p => ({...p, c: 0})) }), /positive/);

  // Three series, only dates all three share; then B as the baseline.
  const c = { symbol: "C", points: [pt("2026-11-09T00:00Z", 10), pt("2026-11-10T00:00Z", 12),
                                     pt("2026-11-11T00:00Z", 13)] };
  const three = app.comparisonTable([a, b, c]);
  assert.deepEqual(JSON.parse(JSON.stringify(three.map(r => r.day))), ["2026-11-09", "2026-11-10"]);
  assert.deepEqual(JSON.parse(JSON.stringify(three[1].values)), [150, 50, 120]);
  const vsB = app.comparisonTable([a, b, c], 1);
  assert.deepEqual(JSON.parse(JSON.stringify(vsB[1].values)), [300, 100, 240]);

  // Adding peers: each is its own request; neither cancels the other.
  app.comparisonPrimaryChanged(a);
  const first = app.loadComparison("B"), second = app.loadComparison("C");
  assert.equal(requests.length, 2);
  assert.equal(requests[0].signal.aborted, false);
  requests[1].resolve(c); await second;
  requests[0].resolve(b); await first;
  assert.equal(nodes.compareOutput.hidden, false);
  assert.match(nodes.compareStatus.textContent,
    /On 2026-11-10: A \(yield\) 150\.00, B 50\.00, C 120\.00\./);
  assert.equal(nodes.comparePlot.children[0].attrs.role, "img");
  const tableRows = nodes.compareTable.children[0].children[2].children;
  assert.deepEqual(tableRows[1].children.map(td => td.textContent), ["2026-11-10", "150.00", "50.00", "120.00"]);

  // A duplicate is refused without a request.
  await app.loadComparison("b");
  assert.equal(requests.length, 2);
  assert.match(nodes.compareStatus.textContent, /already on the chart/);

  // Baseline: click B's legend key, then click it again to undo.
  const keys = () => nodes.compareLegend.children.map(li => li.children[0]);
  assert.equal(keys().length, 3);
  keys()[1].listeners.click();
  assert.match(nodes.compareStatus.textContent, /divided by B/);
  assert.deepEqual(nodes.compareTable.children[0].children[2].children[1].children.map(td => td.textContent),
    ["2026-11-10", "300.00", "100.00", "240.00"]);
  keys()[1].listeners.click();
  assert.match(nodes.compareStatus.textContent, /All start at 100/);

  // Remove C: its line and column go.
  nodes.compareLegend.children[2].children[1].listeners.click();
  assert.equal(nodes.compareTable.children[0].children[2].children[1].children.length, 3);

  // At most six: the chart on screen plus five.
  for (const s of ["D", "E", "F", "G"]) app.loadComparison(s);   // B + these = 5
  assert.equal(requests.length, 6);
  await app.loadComparison("H");
  assert.equal(requests.length, 6);
  assert.match(nodes.compareStatus.textContent, /Up to 6 assets/);

  // A new chart clears the comparison and cancels what is in flight.
  app.comparisonPrimaryChanged({ ...a, symbol: "NEW" });
  assert.equal(requests[2].signal.aborted, true);
  requests[2].resolve(b);
  assert.equal(nodes.compareOutput.hidden, true);
  assert.equal(nodes.compareStatus.textContent, "");

  // The search box still adds through the same path.
  nodes.compareSymbol.value = 'chf/php';
  nodes.compareSymbol.listeners.input();
  assert.equal(nodes.compareSuggestions.children[0].children[0].textContent, 'CHFPHP=X');
  nodes.compareSuggestions.children[0].listeners.click();
  assert.match(requests[requests.length - 1].url, /symbol=CHFPHP%3DX/);
  assert.equal(nodes.compareSuggestions.hidden, true);
}
run().catch(error => { console.error(error); process.exitCode = 1; });
