"use strict";
const assert = require("node:assert/strict");
const {validateDesk, restoreDeskRecords} = require("../static/deskbackup.js");
const desk = {version: 1, format: "asset-price-display", watch: [{symbol: "AAPL"}],
  lists: [{name: "Daily", symbols: ["AAPL"]}], holdings: [], alarms: []};
assert.equal(validateDesk(desk), desk);
assert.throws(() => validateDesk({...desk, version: 2}));
assert.throws(() => validateDesk({...desk, lists: [{name: "Broken"}]}));
const saved = new Map([["apd-watchlist", "old"]]);
let full = true;
const storage = {
  getItem: k => saved.get(k) ?? null,
  setItem(k, v) {
    if (full && k === "apd-holdings") throw Error("Storage full");
    saved.set(k, v);
  },
  removeItem: k => saved.delete(k),
};
assert.throws(() => restoreDeskRecords(storage, desk), /Storage full/);
assert.deepEqual([...saved], [["apd-watchlist", "old"]]);
full = false;
restoreDeskRecords(storage, desk);
assert.deepEqual(JSON.parse(saved.get("apd-watch-lists")), desk.lists);
assert.deepEqual(JSON.parse(saved.get("apd-alarms")), []);
