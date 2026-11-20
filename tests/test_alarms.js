// Price alarm: crossing rules, persistence, and staying armed across charts.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const saved = new Map();
const localStorage = { getItem: k => saved.get(k) ?? null, setItem: (k, v) => saved.set(k, v), removeItem: k => saved.delete(k) };
const rung = [];
function open() {
  const ctx = vm.createContext({ localStorage, document: { getElementById: () => null, title: 't', addEventListener() {} },
    state: { data: null }, setInterval() {} });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/alarms.js'), 'utf8'), ctx);
  vm.runInContext('ringAlarm = (a) => rung.push(a.symbol + ":" + a.fired.dir); loadAlarms();', Object.assign(ctx, { rung }));
  return ctx;
}
const bar = (symbol, c, extra = {}) => ({ symbol, name: symbol, points: [{ t: 1, c: 1 }, { t: 2, c }], ...extra });

let app = open();
assert.equal(app.alarmCrossed(99, 100, 100), 'up');
assert.equal(app.alarmCrossed(101, 100, 100), 'down');
assert.equal(app.alarmCrossed(100, 101, 100), null);   // starting on the level is not a cross
assert.equal(app.alarmCrossed(98, 99, 100), null);

app.addAlarm(bar('BTC-USD', 90), 100);    // above: wait for a rise
app.addAlarm(bar('AAPL', 200), 180);      // below: wait for a fall
app.checkAlarms(bar('AAPL', 210));        // another asset charted: BTC alarm still armed
assert.deepEqual(rung, []);

app = open();                              // reload the page: alarms survive
app.checkAlarms(bar('BTC-USD', 150, { cached: true }));  // a disk copy never fires
app.checkAlarms(bar('btc-usd', 99));
assert.deepEqual(rung, []);
app.checkAlarms(bar('BTC-USD', 101));
assert.deepEqual(rung, ['BTC-USD:up']);
app.checkAlarms(bar('BTC-USD', 80));
app.checkAlarms(bar('BTC-USD', 120));
assert.deepEqual(rung, ['BTC-USD:up']);     // fires once
app.checkAlarms(bar('AAPL', 179.5));
assert.deepEqual(rung, ['BTC-USD:up', 'AAPL:down']);
assert.equal(vm.runInContext('alarms.filter(a => a.fired).length', open()), 2);
console.log('Price alarm crossing, reload and one-shot checks passed.');
