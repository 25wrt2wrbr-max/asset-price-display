"use strict";

/* The words the badge, the tables and the watchlist agree on.
   Plain functions, no DOM, so a Node test can lock the sentences. */

const TREND_GLYPH = { bullish: "▲", bearish: "▼", neutral: "◆" };
const TREND_WORD = { bullish: "Bullish", bearish: "Bearish", neutral: "Neutral" };

// For explaining the server's verdict, never for setting a label.
const ENTRY_SCORE = 0.25;
const ENTRY_DRIFT = 1.96;
const LEAN_MARGIN = 1.15;
const LEAN_HOLD_NEED = 4;

function badgePhrase(trend) {
  if (!trend || !TREND_WORD[trend.label]) return "";
  const lean = trend.label === "neutral" && TREND_WORD[trend.lean]
    ? ` · leaning ${trend.lean}` : "";
  const pull = trend.pullback && trend.label !== "neutral"
    ? (trend.label === "bullish" ? ", pulling back" : ", bouncing") : "";
  return TREND_WORD[trend.label] + lean + pull;
}

function pullNoteSentence(label) {
  const name = label === "bullish" ? "Pulling back" : "Bouncing";
  return `${name}: the last 10 bars moved against this trend and the newest one is on the wrong side of its 20-bar average. The label stays, because the whole window still shows the trend.`;
}

function withheldLeanSentence(trend) {
  if (!trend || trend.label !== "neutral" || trend.lean || !TREND_WORD[trend.leanRaw]) {
    return "";
  }
  const reasons = [];
  if (Number.isFinite(trend.significance) && Math.abs(trend.significance) < LEAN_MARGIN) {
    reasons.push("the move is too weak today");
  }
  if (Number.isInteger(trend.held) && Number.isInteger(trend.holdBars) && trend.held < LEAN_HOLD_NEED) {
    reasons.push(`this lean appeared on only ${trend.held} of the last ${trend.holdBars} readings (it takes ${LEAN_HOLD_NEED})`);
  }
  return `The badge does not show a ${trend.leanRaw} lean because ${reasons.join(" and ") || "the lean has not met the steadiness checks"}.`;
}

function neutralExplanation(t) {
  if (!t || t.label !== "neutral") return "";
  if (Number.isInteger(t.bars) && t.bars < 4) {
    return "There are too few closing values to judge a trend. At least four are needed.";
  }
  if (t.components && t.components.range === null) return "Every closing value on this chart is the same.";
  const s = t.score, d = t.significance;
  const generic = "The chart does not show a clear enough move in either direction.";
  if (!Number.isFinite(s) || !Number.isFinite(d)) return generic;
  let why = generic;
  if (s * d < 0) {
    why = "The combined chart signals point one way, but the average move between closes points the other way.";
  } else if (Math.abs(d) < ENTRY_DRIFT && Math.abs(s) >= ENTRY_SCORE) {
    why = "The chart signals point " + (s > 0 ? "up" : "down") + ", but the move is too small compared with the usual swings between closes to confirm a trend.";
  } else if (Math.abs(s) < ENTRY_SCORE && Math.abs(d) >= ENTRY_DRIFT) {
    why = "The average move between closes points " + (d > 0 ? "up" : "down") + ", but the chart signals taken together are too weak to confirm that trend.";
  } else if (Math.abs(s) < ENTRY_SCORE && Math.abs(d) < ENTRY_DRIFT) {
    why = "The chart signals are weak overall, and the average move does not stand out from the swings between closes.";
  }
  const lean = t.lean ? `It leans ${t.lean}, but that is short of a confirmed trend.` : withheldLeanSentence(t);
  return lean ? `${why} ${lean}` : why;
}

function bondBadgeClause() {
  return "The badge reads it as a bond price, so a rising yield is Bearish and a falling yield is Bullish.";
}

/* The direction cell. A yield names the yield move in parentheses. A pullback
   is a second line, not part of the label. */
function rowDirectionPhrase(row) {
  const note = row && row.note;
  const isYield = note === "yield rising" || note === "yield falling" || note === "yield flat";
  const word = (row && TREND_WORD[row.direction]) || (row && row.direction) || "—";
  const glyph = row && TREND_GLYPH[row.direction] || "";
  const pull = row && row.pullback && (row.direction === "bullish" || row.direction === "bearish")
    ? (row.direction === "bullish" ? "pulling back" : "bouncing")
    : "";
  return {
    text: isYield ? `${word} (${note})` : `${glyph} ${word}`,
    pull,
    yield: Boolean(isYield),
  };
}

/* The watchlist pill. A lean replaces the Neutral tag. The title is the
   sentence the hover shows; the score title stays with the row, because it
   names that row's own score. */
function watchTagPhrase(trend) {
  if (!trend || !TREND_WORD[trend.label]) return null;
  if (trend.label === "neutral" && TREND_WORD[trend.lean]) {
    const pct = Number.isFinite(trend.progress) ? Math.round(trend.progress * 100) : null;
    return {
      kind: "lean",
      lean: trend.lean,
      text: `leaning ${trend.lean}`,
      title: `Neutral on the chart, leaning ${trend.lean}: inside the band that keeps a ` +
        `${trend.lean} label` +
        (pct === null ? "" : `, ${pct}% of the way to earning one`) +
        ` — not confirmed. The label stays Neutral.`,
    };
  }
  return { kind: trend.label, lean: null, text: TREND_WORD[trend.label], title: null };
}
