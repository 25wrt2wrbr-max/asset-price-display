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

/* Is the newest close the highest or lowest of the window? A fact about the
   bars on screen, like the pullback tag: it never changes the label and
   predicts nothing. The table row reads its `spark` (the window's closes)
   and the chart reads the closes it draws, so both say the same thing.
   A flat or short series gets no tag. */
const EXTREME_MIN_BARS = 20;
function windowExtreme(closes) {
  const xs = (closes || []).filter(Number.isFinite);
  if (xs.length < EXTREME_MIN_BARS) return null;
  const last = xs[xs.length - 1];
  const prior = xs.slice(0, -1);
  const hi = Math.max(...prior);
  const lo = Math.min(...prior);
  if (hi === lo) return null;
  if (last >= hi) return "high";
  if (last <= lo) return "low";
  return null;
}

/* Newest bar's volume against the median bar before it in the window. A tag
   at 2x or more: on research/market-history that is 6.8% of days. A bar
   still forming counts its volume so far, which can only understate it.
   Rows read `sparkVol`, the chart its drawn points' volumes. No volume (a
   fund, a yield, an index) means no tag. */
const VOLUME_SPIKE = 2;
function volumeMedian(volumes) {
  const vs = (volumes || []).map(Number).filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b);
  if (!vs.length) return null;
  const mid = vs.length >> 1;
  return vs.length % 2 ? vs[mid] : (vs[mid - 1] + vs[mid]) / 2;
}
function volumeSpike(volumes) {
  const vs = (volumes || []).map(Number);
  if (vs.length < EXTREME_MIN_BARS || vs.some((v) => !Number.isFinite(v))) return null;
  const prior = vs.slice(0, -1).filter((v) => v > 0).sort((a, b) => a - b);
  if (prior.length < EXTREME_MIN_BARS - 1) return null;
  const mid = prior.length >> 1;
  const median = prior.length % 2 ? prior[mid] : (prior[mid - 1] + prior[mid]) / 2;
  const ratio = vs[vs.length - 1] / median;
  return median > 0 && ratio >= VOLUME_SPIKE ? ratio : null;
}

/* Descriptive geometry of the drawn 3-month window: largest peak-to-trough
   drop (maxDrawdown <= 0), current distance below the window's highest close
   (fromHigh <= 0), and typical daily move (std dev of daily log returns, %).
   Pure arithmetic on drawn closes — describes the path, never predicts. */
function windowDrawdown(closes) {
  const xs = (closes || []).filter((v) => Number.isFinite(v) && v > 0);
  if (xs.length < 2) return null;
  let peak = xs[0], maxDD = 0;
  for (const c of xs) {
    if (c > peak) peak = c;
    const dd = (c / peak - 1) * 100;
    if (dd < maxDD) maxDD = dd;
  }
  const hi = Math.max(...xs);
  const last = xs[xs.length - 1];
  const fromHigh = hi > 0 ? (last / hi - 1) * 100 : null;
  const rets = [];
  for (let i = 1; i < xs.length; i++) rets.push(Math.log(xs[i] / xs[i - 1]));
  let dailyVol = null;
  if (rets.length >= 2) {
    const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
    const varSum = rets.reduce((a, r) => a + (r - mean) * (r - mean), 0) / (rets.length - 1);
    dailyVol = Math.sqrt(varSum) * 100;
  }
  return { maxDrawdown: maxDD, fromHigh, dailyVol };
}

function haltPhrase(halt) {
  if (!halt || !halt.action) return "";
  const kind = halt.action === "Suspension" ? "Trading suspended" : "Trading halted";
  const when = halt.date ? ` (${halt.date}${halt.time ? " " + halt.time : ""})` : "";
  const lift = halt.active
    ? " — lifting TBA"
    : halt.lifting ? ` — lifted ${halt.lifting}${halt.liftingTime ? " " + halt.liftingTime : ""}` : "";
  const circ = halt.circular ? ` · ${halt.circular}` : "";
  return `PSE ${kind}${when}${lift}${circ}`;
}

/* A chart payload's volumes, one per drawn point, or null when they do not
   line up (crypto and PSE ship `volumes`, Yahoo `barVolumes`). */
function chartVolumes(data) {
  const pts = (data && data.points) || [];
  const vols = data && (Array.isArray(data.volumes) ? data.volumes : data.barVolumes);
  return Array.isArray(vols) && vols.length === pts.length && pts.length ? vols : null;
}

function volumePhrase(ratio) {
  return Number.isFinite(ratio) ? `volume ${ratio.toFixed(1)}× usual` : "";
}

function volumeSentence(ratio) {
  if (!Number.isFinite(ratio)) return "";
  return `The newest bar traded ${ratio.toFixed(1)} times the median bar's volume in this window. `
    + "A fact about the chart, not a signal; the label does not use it.";
}

function extremePhrase(kind, isYield) {
  if (kind !== "high" && kind !== "low") return "";
  return `${isYield ? "yield at" : "at"} 3-month ${kind}`;
}

function extremeSentence(kind, isYield, bars) {
  if (kind !== "high" && kind !== "low") return "";
  const what = isYield ? "yield" : "close";
  const span = Number.isInteger(bars) ? `all ${bars} bars drawn` : "the window";
  return `The newest ${what} is the ${kind === "high" ? "highest" : "lowest"} of ${span}. `
    + "A fact about the chart, not a signal; the label does not use it.";
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

/* The score's parts in plain words: how steady the path was, whether the
   move stands out from the usual daily swings, and how many signals agree.
   No direction word (the badge has it, and a bond chart reads its yield
   the other way). Cut-offs from 4,440 random 3-month windows of
   research/market-history: 90% of labelled windows had a path efficiency
   of 0.25 or more; half the neutral ones were under 0.11. */
const PATH_STEADY = 0.25, PATH_UNEVEN = 0.10;
function plainReading(t) {
  if (!t || !t.components) return "";
  const parts = [];
  const e = t.components.efficiency;
  if (Number.isFinite(e)) {
    const a = Math.abs(e);
    const word = a >= PATH_STEADY ? "steady" : a >= PATH_UNEVEN ? "uneven" : "choppy";
    parts.push(`${word === "uneven" ? "an" : "a"} ${word} path (about ${Math.round(a * 100)}% of all the daily ups and downs added up to the net move)`);
  }
  const d = t.significance;
  if (Number.isFinite(d)) {
    const a = Math.abs(d);
    parts.push(a >= 99 ? "every bar moved the same way"
      : a >= ENTRY_DRIFT ? "the move stands out clearly from the usual daily swings"
      : a >= 1 ? "the move only partly stands out from the usual daily swings"
      : "the move does not stand out from the usual daily swings");
  }
  const m = /^(\d+)\/(\d+)$/.exec(t.agreement || "");
  if (m) parts.push(`${m[1]} of ${m[2]} signals point the same way`);
  return parts.length ? `In plain words: ${parts.join("; ")}.` : "";
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
