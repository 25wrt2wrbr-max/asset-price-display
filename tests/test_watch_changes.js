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
// 1W / 1M moves: calendar days back, from the drawn closes only.
{
  const day = 86400, t0 = 1_700_000_000;
  // 40 daily bars, close = 100 + i; newest is i=39 -> 139.
  const pts = Array.from({length: 40}, (_, i) => ({t: t0 + i * day, c: 100 + i}));
  const got = open().periodChanges(pts);
  const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);
  near(got.periods[0].pct, (139 / 132 - 1) * 100);   // 7 days back: i=32
  near(got.periods[1].pct, (139 / 109 - 1) * 100);   // 30 days back: i=9
  assert.equal(got.fromHigh, 0);
  near(got.fromLow, 39);
  // Weekday-only bars: the week reaches back to the last bar on or before the cutoff.
  const gap = [{t: t0, c: 50}, {t: t0 + 3 * day, c: 60}, {t: t0 + 10 * day, c: 66}];
  const g = open().periodChanges(gap);
  near(g.periods[0].pct, 10);          // 66 vs 60 (the bar 7 days back)
  assert.equal(g.periods[1].pct, null); // the series does not reach 30 days
  assert.equal(open().periodChanges([{t: t0, c: 1}]), null);
}
console.log('Watchlist visit, outage, ordering and rename checks passed.');
