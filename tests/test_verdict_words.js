"use strict";

/* The sentences the badge, the tables and the watchlist show.
   Loads static/verdict.js in a sandbox. No packages, no browser. */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const file = path.join(__dirname, "..", "static", "verdict.js");
const context = {};
vm.createContext(context);
vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: file });

let failed = 0;
function eq(name, actual, expected) {
  if (actual !== expected) {
    failed += 1;
    console.error(name);
    console.error("  expected: " + JSON.stringify(expected));
    console.error("  actual:   " + JSON.stringify(actual));
  }
}

eq("bullish pullback badge",
  context.badgePhrase({ label: "bullish", pullback: true, score: 0.4 }),
  "Bullish, pulling back");
eq("bearish bounce badge",
  context.badgePhrase({ label: "bearish", pullback: true, score: -0.4 }),
  "Bearish, bouncing");
eq("plain bullish badge",
  context.badgePhrase({ label: "bullish", pullback: false }),
  "Bullish");
eq("leaning badge",
  context.badgePhrase({ label: "neutral", lean: "bullish" }),
  "Neutral · leaning bullish");
eq("neutral badge hides an unconfirmed lean",
  context.badgePhrase({ label: "neutral", lean: null, leanRaw: "bearish" }),
  "Neutral");

eq("pullback note",
  context.pullNoteSentence("bullish"),
  "Pulling back: the last 10 bars moved against this trend and the newest one is on the wrong side of its 20-bar average. The label stays, because the whole window still shows the trend.");
eq("bounce note",
  context.pullNoteSentence("bearish"),
  "Bouncing: the last 10 bars moved against this trend and the newest one is on the wrong side of its 20-bar average. The label stays, because the whole window still shows the trend.");

const withheld = context.withheldLeanSentence({
  label: "neutral", lean: null, leanRaw: "bullish", progress: 0.42, held: 2, holdBars: 5,
});
eq("withheld lean names the bar",
  withheld,
  "The badge does not show a bullish lean because this lean appeared on only 2 of the last 5 readings (it takes 4).");
eq("a persistent lean can still be too weak today", context.withheldLeanSentence({
  label: "neutral", leanRaw: "bearish", held: 5, holdBars: 5, significance: -1.06,
}), "The badge does not show a bearish lean because the move is too weak today.");

function why(fields) { return context.neutralExplanation({ label: "neutral", ...fields }); }
eq("short series is not called choppy", why({bars: 3, significance: null}).includes("too few"), true);
eq("flat series is not called noisy", why({bars: 8, components: {range: null}}).includes("same"), true);
eq("opposing measures", why({score: 0.18, significance: -0.4}).includes("other way"), true);
eq("score alone does not earn bearish", why({score: -0.3, significance: -1.2, lean: "bearish"}).includes("signals point down"), true);
eq("drift alone does not earn bullish", why({score: 0.2, significance: 2.3}).includes("signals taken together are too weak"), true);
eq("rounded numbers must not override the verdict", why({score: 0.25, significance: 1.96}),
  "The chart does not show a clear enough move in either direction.");
eq("a shown lean has no withheld sentence",
  context.withheldLeanSentence({ label: "neutral", lean: "bullish", leanRaw: "bullish" }),
  "");

eq("bond badge",
  context.bondBadgeClause(),
  "The badge reads it as a bond price, so a rising yield is Bearish and a falling yield is Bullish.");

const bull = context.rowDirectionPhrase({ direction: "bullish", pullback: true });
eq("table bullish", bull.text, "▲ Bullish");
eq("table pulling back", bull.pull, "pulling back");
const bear = context.rowDirectionPhrase({ direction: "bearish", pullback: true });
eq("table bearish", bear.text, "▼ Bearish");
eq("table bouncing", bear.pull, "bouncing");
const yieldRow = context.rowDirectionPhrase({ direction: "bullish", note: "yield falling" });
eq("falling yield", yieldRow.text, "Bullish (yield falling)");
eq("a yield has no pull line from the note alone", yieldRow.pull, "");

const leanTag = context.watchTagPhrase({ label: "neutral", lean: "bullish", progress: 0.5 });
eq("watch lean text", leanTag.text, "leaning bullish");
eq("watch lean stays neutral",
  leanTag.title,
  "Neutral on the chart, leaning bullish: inside the band that keeps a bullish label, 50% of the way to earning one — not confirmed. The label stays Neutral.");
eq("watch bearish tag",
  context.watchTagPhrase({ label: "bearish", score: -0.3 }).text,
  "Bearish");
eq("no tag without a label", context.watchTagPhrase(null), null);

// The score's parts in plain words.
eq("plain steady",
  context.plainReading({ components: { efficiency: -0.33 }, significance: -1.98, agreement: "4/4" }),
  "In plain words: a steady path (about 33% of all the daily ups and downs added up to the net move); "
  + "the move stands out clearly from the usual daily swings; 4 of 4 signals point the same way.");
eq("plain choppy",
  context.plainReading({ components: { efficiency: 0.04 }, significance: 0.5, agreement: null }),
  "In plain words: a choppy path (about 4% of all the daily ups and downs added up to the net move); "
  + "the move does not stand out from the usual daily swings.");
eq("plain uneven, partly",
  context.plainReading({ components: { efficiency: 0.1 }, significance: 1.2 }).slice(0, 27),
  "In plain words: an uneven p");
eq("plain one-way", context.plainReading({ components: {}, significance: 99 }),
  "In plain words: every bar moved the same way.");
eq("plain nothing", context.plainReading({}), "");

// Volume tag: newest bar against the median earlier bar, 2x or more.
const flatVol = Array(30).fill(100);
eq("spike", context.volumeSpike(flatVol.concat([250])), 2.5);
eq("no spike", context.volumeSpike(flatVol.concat([150])), null);
eq("zero history", context.volumeSpike(Array(30).fill(0).concat([5])), null);
eq("too short", context.volumeSpike(Array(10).fill(100).concat([500])), null);
eq("no volume", context.volumeSpike(undefined), null);
eq("missing points", context.volumeSpike(Array(30).fill(undefined)), null);
eq("volume words", context.volumePhrase(2.46), "volume 2.5× usual");
const pts3 = [{t: 1, c: 1}, {t: 2, c: 2}, {t: 3, c: 3}];
eq("yahoo volumes", context.chartVolumes({points: pts3, barVolumes: [1, 2, 3]}).length, 3);
eq("venue volumes win", context.chartVolumes({points: pts3, volumes: [4, 5, 6], barVolumes: [1, 2, 3]})[0], 4);
eq("misaligned", context.chartVolumes({points: pts3.concat([{t: 4, c: 4}]), barVolumes: [1, 2, 3]}), null);
eq("none", context.chartVolumes({points: pts3}), null);

// New 3-month high or low: the newest close against every earlier one.
const ramp = Array.from({ length: 30 }, (_, i) => 100 + i);
eq("newest is the high", context.windowExtreme(ramp), "high");
eq("newest is the low", context.windowExtreme(ramp.slice().reverse()), "low");
eq("equal to the old high counts", context.windowExtreme(ramp.concat([129])), "high");
eq("inside the range", context.windowExtreme(ramp.concat([110])), null);
eq("too short", context.windowExtreme(ramp.slice(0, 19)), null);
eq("flat series", context.windowExtreme(Array(30).fill(5)), null);
eq("missing series", context.windowExtreme(undefined), null);
eq("price words", context.extremePhrase("high", false), "at 3-month high");
eq("yield words", context.extremePhrase("low", true), "yield at 3-month low");
eq("no words", context.extremePhrase(null, false), "");

// Volume median, window drawdown & PSE halt phrase.
eq("volume median odd", context.volumeMedian([10, 50, 20]), 20);
eq("volume median even", context.volumeMedian([10, 50, 20, 40]), 30);
const dd = context.windowDrawdown([100, 120, 90, 108]);
eq("max drawdown", Math.round(dd.maxDrawdown * 10) / 10, -25);
eq("off 3m high", Math.round(dd.fromHigh * 10) / 10, -10);
eq("daily vol positive", dd.dailyVol > 0, true);
eq("halt active phrase",
  context.haltPhrase({ action: "Suspension", date: "Nov 4, 2026", time: "9:00 AM", active: true, circular: "C07712-2026" }),
  "PSE Trading suspended (Nov 4, 2026 9:00 AM) — lifting TBA · C07712-2026");

if (failed) {
  console.error(failed + " verdict phrase check(s) failed");
  process.exit(1);
}
console.log("verdict phrases ok");
