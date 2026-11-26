"use strict";
// Label strip runs and wording.
const assert = require("assert");
const path = require("path");
const { labelRuns, labelStripSentence } = require(path.join(__dirname, "..", "static", "labelstrip.js"));

assert.deepStrictEqual(labelRuns([null, "neutral", "neutral", "bullish"]), [
  { label: null, from: 0, to: 0 }, { label: "neutral", from: 1, to: 2 }, { label: "bullish", from: 3, to: 3 },
]);
const line = labelStripSentence({ summary: { bars: 252, changes: 1,
  counts: { bullish: 18, bearish: 0, neutral: 234 }, longest: { bullish: 18, bearish: 0 } } });
assert.ok(line.startsWith("Past year: bullish on 18 of 252 bars (7%), bearish on 0 (0%), neutral on 234"), line);
assert.ok(line.includes("1 label change ·"), line);
assert.ok(!line.includes("bearish run"), line);
assert.ok(line.endsWith("What happened, not odds."), line);
assert.strictEqual(labelStripSentence({ summary: { bars: 0 } }), "");
console.log("label strip: ok");
