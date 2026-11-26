"use strict";
/* Friendlier + lighter III: copy, live fast path, and 404 wording stay wired. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(root, rel), "utf8");

const html = read("index.html");
assert.match(html, /Today’s overview|Today's overview/);
assert.match(html, /id="welcomeTip"/);
assert.match(html, /id="kbdHelp"/);
assert.match(html, /id="assetAbout"/);
assert.match(html, /Skip to search/);
assert.match(html, /Only if trend still looks/);
assert.match(html, /profitOddsAside/);

const page = read("static/page.js");
assert.match(page, /function fillAssetMeta/);
assert.match(page, /if \(!live\) fillAssetMeta/);
assert.match(page, /A live quote tick only moves the newest close/);

const tables = read("static/tables.js");
assert.match(tables, /Turn began/);
assert.match(tables, /Days in trend/);
assert.match(tables, /3-mo change/);
assert.doesNotMatch(tables, /\["Market", "Asset", "Direction", "Since", "Run"/);

const desk = read("static/desk.js");
assert.match(desk, /deskInView/);
assert.match(desk, /loadSectors\.last/);

const core = read("static/core.js");
const sandbox = { console, Map, TypeError, Error, document: { getElementById: () => null } };
vm.createContext(sandbox);
const start = core.indexOf("function friendlyError");
const end = core.indexOf("/* Remember the last good GET");
assert.ok(start >= 0 && end > start);
vm.runInContext(core.slice(start, end), sandbox);

const miss = sandbox.friendlyError(new Error("unknown symbol"), 404);
assert.match(miss.message, /Couldn't find that/);
assert.equal(miss.detail, "unknown symbol");

const label = read("static/labelstrip.js");
assert.match(label, /labelStripVisible/);
assert.match(label, /getElementById\("plot"\)/);

const css = read("static/app.css");
assert.match(css, /\.section-nav a\.is-active/);
assert.match(css, /\.welcome-tip/);
assert.match(css, /mask-image: linear-gradient/);

console.log("friendly ux: ok");
