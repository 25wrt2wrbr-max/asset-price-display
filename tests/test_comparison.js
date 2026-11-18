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
  const expected = [{day: "2026-11-09", a: 100, b: 100}, {day: "2026-11-10", a: 150, b: 50}];
  assert.deepEqual(JSON.parse(JSON.stringify(app.comparisonRows(a,b))), expected);
  assert.throws(() => app.comparisonRows(a, { points: [] }), /shared trading dates/);
  assert.throws(() => app.comparisonRows(a, { points: b.points.map(p => ({...p, c: 0})) }), /positive/);
  app.comparisonPrimaryChanged(a);
  const old = app.loadComparison("OLD"), current = app.loadComparison("B");
  assert.equal(requests[0].signal.aborted, true);
  requests[1].resolve(b); await current;
  requests[0].resolve({ ...b, symbol: "OLD" }); await old;
  assert.equal(nodes.compareOutput.hidden, false);
  assert.match(nodes.compareStatus.textContent, /A \(yield\) 150\.00 \(solid\), B 50\.00 \(dashed\)/);
  assert.equal(nodes.comparePlot.children[0].attrs.role, "img");
  const tableRows = nodes.compareTable.children[0].children[2].children;
  assert.deepEqual(tableRows[1].children.map(td => td.textContent), ["2026-11-10", "150.00", "50.00"]);
  const obsolete = app.loadComparison("B");
  app.comparisonPrimaryChanged({ ...a, symbol: "NEW" });
  requests[2].resolve(b); await obsolete;
  assert.equal(nodes.compareOutput.hidden, true);
  assert.equal(nodes.compareStatus.textContent, "");
  nodes.compareSymbol.value = 'chf/php';
  nodes.compareSymbol.listeners.input();
  assert.equal(nodes.compareSuggestions.children[0].children[0].textContent, 'CHFPHP=X');
  nodes.compareSuggestions.children[0].listeners.click();
  assert.equal(nodes.compareSymbol.value, 'CHFPHP=X');
  assert.match(requests[3].url, /symbol=CHFPHP%3DX/);
  assert.equal(nodes.compareSuggestions.hidden, true);
}
run().catch(error => { console.error(error); process.exitCode = 1; });
