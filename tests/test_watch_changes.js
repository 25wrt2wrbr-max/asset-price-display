// Simulate closing and reopening the page, keeping only browser storage.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const saved = new Map();
const localStorage = { getItem: k => saved.get(k) || null, setItem: (k,v) => saved.set(k,v), removeItem: k => saved.delete(k) };
function open() {
  const ctx = vm.createContext({localStorage, setInterval: () => {}});
  for (const file of ['verdict', 'watchlist', 'watch-changes']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../static', file + '.js'), 'utf8'), ctx);
  }
  return ctx;
}
let app = open();
const rising = { trend: { label: 'bullish' } };
app.recordWatchVisit('X', 'X', rising);
assert.equal(app.openWatchVisit('x').prior, null);
app = open();
vm.runInContext("const state = {watch:[{symbol:'X',name:'X'}],watchQuotes:{}};", app);
for (const stale of [{cached:true}, {staleDays:15}, {stale:100}]) {
  app.setWatchQuote('X', {}, {trend:{label:'neutral'}, ...stale}, 1);
  assert.equal(app.openWatchVisit('x').current, null);
}
app.setWatchQuote('X', {}, {trend:{label:'bullish',pullback:true}}, 4);
app.setWatchQuote('X', {}, {trend:{label:'neutral'}}, 2);
app.setWatchQuote('X', {error:'offline'}, null, 5);
assert.equal(app.openWatchVisit('x').prior, 'Bullish');
assert.equal(app.openWatchVisit('x').current, 'Bullish, pulling back');
app = open();
app.recordWatchVisit('X', 'X-USD', {cached:true});
assert.equal(open().openWatchVisit('X-USD').prior, 'Bullish, pulling back');
app.forgetWatchVisit('X-USD');
assert.equal(open().openWatchVisit('X-USD').prior, null);
console.log('Watchlist visit, outage, ordering and rename checks passed.');
