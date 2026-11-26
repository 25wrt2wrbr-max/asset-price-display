"use strict";
// The server-down banner: two unreachable polls raise it, one answer lowers it.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const stub = () => ({ addEventListener() {}, setAttribute() {}, style: { setProperty() {} },
  classList: { add() {} }, append() {}, dataset: {} });
const banner = { hidden: true, textContent: "" };
const ctx = vm.createContext({
  localStorage: { getItem: () => null, setItem() {} },
  document: { getElementById: (id) => (id === "serverBanner" ? banner : stub()),
    querySelectorAll: () => [], createElement: stub },
  setInterval() {},
});
for (const f of ["verdict", "watchlist"]) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static", f + ".js"), "utf8"), ctx);
}
const t = new Date(2026, 10, 24, 9, 5);
assert.equal(ctx.noteHealthResult(false, t), false);
assert.equal(banner.hidden, true, "one miss is not an outage");
ctx.noteHealthResult(false, new Date(2026, 10, 24, 9, 6));
assert.equal(banner.hidden, false, "two misses raise the banner");
assert.match(banner.textContent, /stopped answering/);
assert.ok(banner.textContent.includes(t.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })),
  "the time is the first miss");
assert.equal(ctx.noteHealthResult(true), true, "recovery after an outage says so");
assert.equal(banner.hidden, true);
assert.equal(ctx.noteHealthResult(true), false, "a normal answer is not a recovery");
ctx.noteHealthResult(false);
assert.equal(ctx.noteHealthResult(true), false, "one miss then an answer is not a recovery");
assert.equal(banner.hidden, true);
console.log("server banner: ok");
