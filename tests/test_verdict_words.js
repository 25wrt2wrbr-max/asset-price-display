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

if (failed) {
  console.error(failed + " verdict phrase check(s) failed");
  process.exit(1);
}
console.log("verdict phrases ok");
