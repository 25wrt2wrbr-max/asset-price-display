"use strict";
// Canvas sparklines: a short series draws a bitmap; a flat series still draws;
// one point is skipped.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const strokes = [];
const ctx = {
  scale() {},
  beginPath() {},
  moveTo() {},
  lineTo() {},
  stroke() { strokes.push(this.strokeStyle); },
  strokeStyle: "",
  lineWidth: 0,
  lineJoin: "",
  lineCap: "",
};
const docEl = {
  style: {},
};
const fakeCss = {
  getPropertyValue(name) {
    if (name === "--text-muted") return " #898781 ";
    if (name === "--delta-up") return " #0ca30c ";
    if (name === "--delta-down") return " #e66767 ";
    return "";
  },
};
const sandbox = {
  window: { devicePixelRatio: 1 },
  document: {
    documentElement: docEl,
    createElement(tag) {
      assert.equal(tag, "canvas");
      return {
        className: "",
        width: 0,
        height: 0,
        style: {},
        setAttribute() {},
        getContext() { return ctx; },
      };
    },
  },
  getComputedStyle() { return fakeCss; },
  Number,
  Math,
  String,
  Array,
  Object,
  console,
};
vm.createContext(sandbox);
const src = fs.readFileSync(path.join(__dirname, "../static/watchlist.js"), "utf8");
// Only the spark helpers are needed; stop before setInterval / DOM wiring that
// needs a full page. The file also defines many other symbols — load a slice.
const start = src.indexOf("const SPARK_H");
const end = src.indexOf("function loadWatch");
assert.ok(start >= 0 && end > start, "spark helpers located");
vm.runInContext(src.slice(start, end), sandbox);

const up = sandbox.sparkline([1, 2, 3, 4], true, 44);
assert.ok(up, "rising series draws");
assert.match(up.className, /\bup\b/);
assert.equal(strokes.at(-1), "#0ca30c");

const flat = sandbox.sparkline([5, 5, 5], null, 44);
assert.ok(flat, "flat series draws");
assert.equal(strokes.at(-1), "#898781");

assert.equal(sandbox.sparkline([9], true, 44), null, "one point is skipped");
assert.equal(sandbox.sparkline([], true, 44), null);

sandbox.resetSparkInk();
sandbox.sparkline([1, 3], false, 20);
assert.equal(strokes.at(-1), "#e66767");

console.log("spark canvas: ok");
