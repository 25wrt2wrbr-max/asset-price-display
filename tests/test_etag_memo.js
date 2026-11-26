"use strict";
// Client ETag memo: a second GET with the same body reuses the payload on 304.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const calls = [];
const sandbox = {
  console,
  Map,
  TypeError,
  Error,
  fetch(url, opts) {
    calls.push({ url, headers: (opts && opts.headers) || {}, cache: opts && opts.cache });
    if (calls.length === 1) {
      return Promise.resolve({
        status: 200,
        ok: true,
        headers: { get: (n) => (n === "ETag" ? '"abc"' : null) },
        json: async () => ({ rows: [1] }),
      });
    }
    assert.equal(opts.headers["If-None-Match"], '"abc"');
    assert.equal(opts.cache, "no-store");
    return Promise.resolve({
      status: 304,
      ok: false,
      headers: { get: () => null },
      json: async () => { throw new Error("no body"); },
    });
  },
};
vm.createContext(sandbox);
const src = fs.readFileSync(path.join(__dirname, "../static/core.js"), "utf8");
const start = src.indexOf("const etagMemo");
const end = src.indexOf("async function postJSON");
assert.ok(start >= 0 && end > start, "etag helpers located");
const friendly = src.indexOf("function friendlyError");
vm.runInContext(src.slice(friendly, end), sandbox);

sandbox.requestJSON("/api/recent").then((a) => {
  assert.deepEqual(a, { rows: [1] });
  return sandbox.requestJSON("/api/recent");
}).then((b) => {
  assert.deepEqual(b, { rows: [1] });
  assert.equal(calls.length, 2);
  // Bare 304 with an empty memo must retry once without If-None-Match.
  vm.runInContext("etagMemo.clear()", sandbox);
  const realFetch = sandbox.fetch;
  let n = 0;
  sandbox.fetch = (url, opts) => {
    n += 1;
    if (n === 1) {
      assert.ok(!opts.headers["If-None-Match"]);
      return Promise.resolve({
        status: 304, ok: false,
        headers: { get: () => null },
        json: async () => { throw new Error("no body"); },
      });
    }
    assert.ok(!opts.headers["If-None-Match"], "retry drops the ETag");
    return Promise.resolve({
      status: 200, ok: true,
      headers: { get: (h) => (h === "ETag" ? '"xyz"' : null) },
      json: async () => ({ rows: [9] }),
    });
  };
  return sandbox.requestJSON("/api/recent").then((c) => {
    sandbox.fetch = realFetch;
    assert.deepEqual(c, { rows: [9] });
    console.log("etag memo: ok");
  });
}).catch((err) => {
  console.error(err);
  process.exit(1);
});
