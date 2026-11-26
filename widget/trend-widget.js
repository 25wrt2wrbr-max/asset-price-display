/*! Trend Badge v1.0.0. Commercial license: see LICENSE.txt.
 * The badge describes past prices. It is not a forecast. */
/*
 * trend.js -- the price-trend classifier, ported to standalone JavaScript.
 *
 * This is a faithful port of the project's Python `trend.py` (the classifier)
 * and `onset.py` (the "since when" walk). Same formulas, same weights, same
 * thresholds, same edge cases. It has NO dependencies -- no npm, no build
 * step, no server -- so it can be dropped into any hosted site as a plain
 * <script> tag, or imported with `import { classify } from "./trend.js"`.
 *
 *   const { classify, onset } = Trend;
 *   const v = classify(closes, volumes);
 *   // { label: "bullish", score: 0.61, confidence: "strong", bars: 63,
 *   //   agreement: "4/4", components: { momentum: 0.42, trend: 0.51, ... } }
 *
 * `closes` is oldest-first. `volumes` is optional and accepted for
 * compatibility; it never votes.
 *
 * Version 2 (2026-10-31). The whole series given is the window -- every bar
 * the chart draws counts. Four signals are blended:
 *
 *     weight  signal      what it measures
 *     ------  ----------  -------------------------------------------------
 *     0.40    momentum    the window's drift as a t-statistic
 *     0.25    trend       weighted log-price regression slope x R^2
 *     0.20    efficiency  weighted net move / weighted path length
 *     0.15    range       where the last close sits in the window's range
 *
 * A directional label needs evidence: score >= 0.25 AND drift t >= 1.96 to
 * enter, and it holds while score >= 0.15 and t >= 1.0 as long as an
 * unbroken run of same-side bars leads back, within 10 bars, to one that
 * entered. Returns are ramp-weighted so the oldest 25% of the window phases
 * in and the bar leaving the window barely moves the call. The t is read
 * against the Student-t critical value for the bars there are, and widened
 * for positive serial correlation, so short and thinly traded series need
 * more evidence rather than being damped by an arbitrary curve.
 *
 * Measured on the project's saved history (74 instruments): 0.8 label
 * changes per 100 bars (v1: 8.1); a one-sigma move in the newest close
 * changes the label 0.4% of the time (v1: 9.3%); dropping the oldest bar
 * 0.6% (v1: 3.4%); driftless random walks labelled ~8% (v1: 49%).
 *
 * The score is not a probability and the label is not a forecast.
 *
 * See trend.py for the full reasoning; export/verify_parity.py checks that
 * this file and trend.py agree digit for digit.
 */

/* eslint-disable no-var */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Trend = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // The bar count a chart falls back to when its window holds fewer than two
  // bars. Not a scoring threshold any more.
  var MIN_BARS = 50;

  // Below this many bars a walk's tested window is the data floor (onset's
  // censoring rule).
  var MIN_RETURNS = 10;

  // The fewest log returns a drift t-statistic can be measured over.
  var MIN_RETURNS_T = 3;

  var WEIGHTS = {
    momentum: 0.40,
    trend: 0.25,
    efficiency: 0.20,
    range: 0.15,
  };

  // Entry and hold bands (see the header).
  var ENTER_SCORE = 0.25;
  var ENTER_T = 1.96;
  var HOLD_SCORE = 0.15;
  var HOLD_T = 1.00;
  var HOLD_BARS = 10;
  var CALL_THRESHOLD = ENTER_SCORE;
  var STRONG_THRESHOLD = 0.45;
  // A label whose last two weeks ran against it is tagged, never changed.
  var PULLBACK_BARS = 10;
  var PULLBACK_AVG = 20;

  // The share of the window, oldest first, that phases in.
  var FADE_IN = 0.25;

  var Z95 = 1.6448536269514722;

  // ------------------------------------------------------------------ helpers

  function _clamp(x, lo, hi) {
    if (lo === undefined) lo = -1.0;
    if (hi === undefined) hi = 1.0;
    return x < lo ? lo : x > hi ? hi : x;
  }

  // Python's sum() adds left to right; so does this, so the floats match.
  function sum(xs) {
    var s = 0;
    for (var i = 0; i < xs.length; i++) s += xs[i];
    return s;
  }

  // Round half to even, like Python's round(), so exported numbers match the
  // Python implementation digit for digit.
  function roundHalfEven(x, digits) {
    if (!isFinite(x)) return x;
    var f = Math.pow(10, digits);
    var y = x * f;
    var floorY = Math.floor(y);
    var frac = y - floorY;
    var rounded;
    if (frac > 0.5) rounded = floorY + 1;
    else if (frac < 0.5) rounded = floorY;
    else rounded = floorY % 2 === 0 ? floorY : floorY + 1;
    return rounded / f;
  }

  function round4(x) {
    return roundHalfEven(x, 4);
  }

  // Student-t quantile (Cornish-Fisher), the small-sample penalty.
  function tcrit(df, z) {
    var g1 = (Math.pow(z, 3) + z) / 4.0;
    var g2 = (5 * Math.pow(z, 5) + 16 * Math.pow(z, 3) + 3 * z) / 96.0;
    var g3 = (3 * Math.pow(z, 7) + 19 * Math.pow(z, 5) + 17 * Math.pow(z, 3) - 15 * z) / 384.0;
    return z + g1 / df + g2 / Math.pow(df, 2) + g3 / Math.pow(df, 3);
  }

  // Weights for m returns, oldest first: a linear fade-in, then 1.0.
  function ramp(m) {
    var k = Math.max(1, roundHalfEven(m * FADE_IN, 0));
    var out = [];
    for (var i = 0; i < m; i++) out.push(Math.min(1.0, (i + 1) / (k + 1)));
    return out;
  }

  function logReturns(closes) {
    var lr = [];
    for (var i = 1; i < closes.length; i++) lr.push(Math.log(closes[i] / closes[i - 1]));
    return lr;
  }

  // --------------------------------------------------------------- components

  // Momentum and drift t: the ramp-weighted log return over its standard
  // error, widened for positive lag-1 autocorrelation, read against the
  // Student-t critical value for the bars there are.
  function stats(closes) {
    var m = closes.length - 1;
    if (m < MIN_RETURNS_T) return { momentum: null, t: null };
    var lr = logReturns(closes);
    var w = ramp(m);
    var mu = sum(lr) / m;
    var dev = [];
    for (var i = 0; i < m; i++) dev.push(Math.pow(lr[i] - mu, 2));
    var variance = sum(dev) / (m - 1);
    var sigma = Math.sqrt(variance);
    if (sigma <= 1e-9) {
      if (lr.every(function (r) { return r > 1e-12; })) return { momentum: null, t: Infinity };
      if (lr.every(function (r) { return r < -1e-12; })) return { momentum: null, t: -Infinity };
      return { momentum: null, t: 0.0 };
    }
    var prods = [];
    for (var j = 1; j < m; j++) prods.push((lr[j] - mu) * (lr[j - 1] - mu));
    var rho = sum(prods) / (variance * (m - 1));
    var inflate = Math.sqrt(1.0 + 2.0 * Math.max(0.0, rho));
    var sq = [], wr = [];
    for (var k = 0; k < m; k++) { sq.push(w[k] * w[k]); wr.push(w[k] * lr[k]); }
    var sw2 = Math.sqrt(sum(sq));
    var z = sum(wr) / (sigma * sw2 * inflate);
    var t = z * Z95 / tcrit(m - 1, Z95);
    return { momentum: _clamp(t / 3.0), t: t };
  }

  // Weighted log-price regression: slope move x R^2, normalized to 30%.
  function regr2(closes) {
    var n = closes.length;
    if (n < 3) return { score: null, r2: null };
    var w = ramp(n - 1);
    var pw = [w[0] * 0.5].concat(w);
    var y = closes.map(function (c) { return Math.log(c); });
    var tw = sum(pw);
    var ax = [], ay = [];
    for (var i = 0; i < n; i++) { ax.push(pw[i] * i); ay.push(pw[i] * y[i]); }
    var mx = sum(ax) / tw;
    var my = sum(ay) / tw;
    var sxx = 0, sxy = 0, syy = 0;
    for (var j = 0; j < n; j++) {
      var dx = j - mx, dy = y[j] - my;
      sxx += pw[j] * dx * dx;
      sxy += pw[j] * dx * dy;
      syy += pw[j] * dy * dy;
    }
    if (sxx <= 0 || syy <= 1e-18) return { score: null, r2: null };
    var r2 = (sxy * sxy) / (sxx * syy);
    var slope = sxy / sxx;
    var move = Math.exp(_clamp(slope * (n - 1), -5.0, 5.0)) - 1.0;
    return { score: _clamp(move / 0.30) * r2, r2: r2 };
  }

  // Weighted efficiency ratio: weighted net log move / weighted path.
  function effr(closes) {
    var m = closes.length - 1;
    if (m < 1) return null;
    var w = ramp(m);
    var lr = logReturns(closes);
    var p = [], q = [];
    for (var i = 0; i < m; i++) { p.push(w[i] * Math.abs(lr[i])); q.push(w[i] * lr[i]); }
    var path = sum(p);
    if (path <= 1e-12) return null;
    return _clamp(sum(q) / path);
  }

  // Last close's position in the window's [low, high], as [-1, +1].
  function rng(closes) {
    var lo = Math.min.apply(null, closes);
    var hi = Math.max.apply(null, closes);
    if (hi <= lo) return null;
    return ((closes[closes.length - 1] - lo) / (hi - lo) - 0.5) * 2.0;
  }

  // ------------------------------------------------------------------- scoring

  var ORDER = ["momentum", "trend", "efficiency", "range"];

  function evaluate(closes) {
    var s = stats(closes);
    var tr = regr2(closes);
    var raw = { momentum: s.momentum, trend: tr.score,
                efficiency: effr(closes), range: rng(closes) };
    var tot = [], acc = [];
    for (var i = 0; i < ORDER.length; i++) {
      var v = raw[ORDER[i]];
      if (v !== null && v !== undefined) {
        tot.push(WEIGHTS[ORDER[i]]);
        acc.push(WEIGHTS[ORDER[i]] * v);
      }
    }
    var total = sum(tot);
    var score = total ? sum(acc) / total : 0.0;
    return { score: _clamp(score), t: s.t, raw: raw, r2: tr.r2 };
  }

  function zone(score, t) {
    if (t === null || t === undefined) return 0;
    if (score >= ENTER_SCORE && t >= ENTER_T) return 2;
    if (score <= -ENTER_SCORE && t <= -ENTER_T) return -2;
    if (score >= HOLD_SCORE && t >= HOLD_T) return 1;
    if (score <= -HOLD_SCORE && t <= -HOLD_T) return -1;
    return 0;
  }

  // True when a labelled window's newest bars ran against its label
  // (trend.pullback): a tag beside the label, never a change to it.
  function pullback(closes, sign) {
    var n = closes.length;
    if (!sign || n < Math.max(PULLBACK_BARS + 1, PULLBACK_AVG)) return false;
    var last = closes[n - 1];
    var total = 0.0;
    for (var i = n - PULLBACK_AVG; i < n; i++) total += closes[i];
    return (last - closes[n - 1 - PULLBACK_BARS]) * sign < 0 &&
           (last - total / PULLBACK_AVG) * sign < 0;
  }

  // Share of the entry bar met on the score's side (trend.progress).
  function progress(score, t) {
    if (t === null || t === undefined || !score) return 0.0;
    var side = score > 0 ? 1 : -1;
    var tPart = !isFinite(t) && t * side > 0 ? 1.0 : Math.max(0.0, t * side / ENTER_T);
    return round4(Math.min(score * side / ENTER_SCORE, tPart));
  }

  /**
   * Score a daily close series; the whole series is the window.
   *
   * @param {number[]} closes  oldest-first daily closes
   * @param {number[]|null} [volumes]  accepted, never votes
   */
  function classify(closes, volumes) {
    closes = (closes || []).map(function (c) { return Number(c); });
    var n = closes.length;
    if (!n) throw new Error("No closes to classify.");
    for (var q = 0; q < n; q++) {
      if (!(closes[q] > 0)) throw new Error("Prices must be positive.");
    }

    var ev = evaluate(closes);
    var score = ev.score, t = ev.t, raw = ev.raw;
    var zoneNow = zone(score, t);

    var sign = 0, held = false;
    if (Math.abs(zoneNow) === 2) sign = zoneNow / 2;
    else if (zoneNow !== 0) {
      var side = zoneNow > 0 ? 1 : -1;
      for (var back = 1; back <= HOLD_BARS; back++) {
        if (n - back < 2) break;
        var e = evaluate(closes.slice(0, n - back));
        var z = zone(e.score, e.t);
        if (z * side <= 0) break;
        if (Math.abs(z) === 2) { sign = side; held = true; break; }
      }
    }
    var label = sign === 1 ? "bullish" : sign === -1 ? "bearish" : "neutral";

    var mag = Math.abs(score);
    var confidence;
    if (sign) confidence = mag >= STRONG_THRESHOLD ? "strong" : !held ? "moderate" : "holding";
    else confidence = mag >= 0.10 ? "weak" : "flat";

    var direction = score > 0 ? 1 : score < 0 ? -1 : 0;
    var voting = [];
    for (var v = 0; v < ORDER.length; v++) {
      var x = raw[ORDER[v]];
      if (x !== null && x !== undefined && x !== 0) voting.push(x);
    }
    var agreement = null;
    if (direction !== 0 && voting.length) {
      var agree = 0;
      for (var a = 0; a < voting.length; a++) if ((voting[a] > 0) === (direction > 0)) agree++;
      agreement = agree + "/" + voting.length;
    }

    var components = {};
    for (var c = 0; c < ORDER.length; c++) {
      var val = raw[ORDER[c]];
      components[ORDER[c]] = val === null || val === undefined ? null : round4(val);
    }
    if (ev.r2 !== null && ev.r2 !== undefined) components.r2 = round4(ev.r2);

    var significance = null;
    if (t !== null && t !== undefined) {
      significance = !isFinite(t) ? (t > 0 ? 99.0 : -99.0) : round4(t);
    }

    return {
      label: label,
      score: round4(score),
      confidence: confidence,
      bars: n,
      agreement: agreement,
      significance: significance,
      held: held,
      lean: !sign && zoneNow === 1 ? "bullish" : !sign && zoneNow === -1 ? "bearish" : null,
      progress: progress(score, t),
      pullback: pullback(closes, sign),
      components: components,
    };
  }

  // --------------------------------------------------------------------- onset
  // Port of onset.py: when did the current run of like labels begin?

  var WINDOW_DAYS = 90;
  var WINDOW_MONTHS = 3;
  var DAY = 86400;

  // Why-did-it-turn read: the span behind a run's first bar, and how big a move
  // counts as a move. Mirrors TURN_BARS / TURN_MOVE in onset.py.
  var TURN_BARS = 20;
  var TURN_MOVE = 0.02;

  // The UTC midnight of the day `ts` falls in.
  function dayStart(ts) {
    return ts - (ts % DAY);
  }

  // The UTC midnight of the day `months` calendar months before `ts`'s day.
  // This is Yahoo's own `range=` rule: `range=3mo` is three *calendar* months
  // back from today, not ninety days. Month arithmetic is not day arithmetic,
  // and the difference is a couple of trading sessions -- enough to cross the
  // classifier's 63-bar regime boundary, so a chart and a table that cut
  // their windows differently can answer differently about the same series.
  function monthsBack(ts, months) {
    var d = new Date(dayStart(ts) * 1000);
    var year = d.getUTCFullYear();
    var month = d.getUTCMonth() + 1 - months;
    while (month <= 0) { month += 12; year -= 1; }
    var day = d.getUTCDate();
    var lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    if (day > lastDay) day = lastDay;
    return Date.UTC(year, month - 1, day) / 1000;
  }

  // Bar indices of the window that ends at bar `end`, measured back from
  // `anchor` (a unix timestamp in seconds). `months` asks for a
  // calendar-months window (Yahoo's own spans); without it the window is the
  // ninety-day one.
  function windowIndices(stamps, end, anchor, months) {
    var cutoff = months ? monthsBack(anchor, months)
                         : anchor - WINDOW_DAYS * DAY;
    var start = null;
    for (var i = 0; i <= end; i++) {
      if (stamps[i] >= cutoff) { start = i; break; }
    }
    if (start === null || end - start + 1 < 2) {
      start = Math.max(0, end + 1 - Math.max(2, MIN_BARS));
    }
    var out = [];
    for (var j = start; j <= end; j++) out.push(j);
    return out;
  }

  // The window the chart draws today -- the badge's own window.
  function windowNow(stamps, end, now, months) {
    var anchor = now === undefined ? Math.floor(Date.now() / 1000) : now;
    return windowIndices(stamps, end, anchor, months);
  }

  // The window the chart would have drawn on the day of bar `end`.
  function windowAt(stamps, end, months) {
    return windowIndices(stamps, end, stamps[end], months);
  }

  // The verdict over the bars `idx` names, or null when it cannot be scored.
  function labelOver(closes, volumes, idx) {
    var cs = [], vs = [];
    try {
      for (var i = 0; i < idx.length; i++) {
        cs.push(closes[idx[i]]);
        vs.push(volumes ? volumes[idx[i]] : 0);
      }
      return classify(cs, vs).label;
    } catch (e) {
      return null;
    }
  }

  // The badge's own call on the latest bar: label, score, confidence, window.
  function current(stamps, closes, volumes, now, months) {
    var n = closes.length;
    if (n < 3 || stamps.length !== n) return null;
    var used = windowNow(stamps, n - 1, now, months);
    var cs = [], vs = [];
    for (var i = 0; i < used.length; i++) {
      cs.push(closes[used[i]]);
      vs.push(volumes ? volumes[used[i]] : 0);
    }
    var call;
    try {
      call = classify(cs, vs);
    } catch (e) {
      return null;
    }
    return {
      label: call.label,
      score: call.score,
      confidence: call.confidence,
      window: used.length,
      bars: n,
    };
  }

  /**
   * When the current run of `want` labels began, or null if it is not running.
   *
   * `want` is "bullish" or "bearish" (a falling bond yield is a bearish run of
   * the same algorithm applied to the yield's own numbers).
   *
   * @param {number[]} stamps  unix timestamps (seconds), oldest-first
   * @param {number[]} closes  oldest-first
   * @param {number[]} [volumes] oldest-first
   * @param {string} [want="bullish"]
   * @param {number} [now]  override for "today" (unix seconds)
   * @param {number} [months]  calendar-months window (Yahoo's own spans)
   */
  function onset(stamps, closes, volumes, want, now, months) {
    if (want === undefined) want = "bullish";
    volumes = volumes || [];
    var n = closes.length;
    if (n < 3 || stamps.length !== n) return null;

    var last = n - 1;
    // Inclusion is the badge's own window.
    if (labelOver(closes, volumes, windowNow(stamps, last, now, months)) !== want) return null;

    // The walk's first step reads the latest bar through the anchored window.
    var anchored = labelOver(closes, volumes, windowAt(stamps, last, months)) === want;

    var start = last;
    while (start - 1 >= 0 &&
           labelOver(closes, volumes, windowAt(stamps, start - 1, months)) === want) {
      start -= 1;
    }

    var used = windowNow(stamps, last, now, months);
    var cs = [], vs = [];
    for (var i = 0; i < used.length; i++) {
      cs.push(closes[used[i]]);
      vs.push(volumes ? volumes[used[i]] : 0);
    }
    var score = null, pulling = null;
    try {
      var nowCall = classify(cs, vs);
      score = nowCall.score;
      pulling = nowCall.pullback;
    } catch (e) {
      score = null;
    }

    // A missing volume is not a zero-volume session, so the turnover is left
    // as null rather than 0.0.
    var volume = volumes[last];
    var turnover = volume ? closes[last] * volume : null;

    // Why the run began: read at its first bar, over the bars before it, never
    // over today's -- the question is what changed when the label flipped.
    var why = turn(closes, start, want);

    // The data floor: below MIN_RETURNS + 1 bars the tested window cannot
    // carry the momentum signal, so a stop there is the walk running out of
    // judgable history, not a bar that judged against the run. The date is
    // a floor; say so.
    return {
      since: stamps[start],
      run: last - start + 1,
      censored: start <= MIN_RETURNS,
      anchored: anchored,
      manner: why.manner,
      turnMove: why.move === null ? null : round4(why.move),
      pullback: pulling,
      score: score,
      bars: n,
      last: stamps[last],
      price: closes[last],
      turnover: turnover,
      window: used.length,
      // The window's first drawn close. (windowFirst, price) is the pair a
      // caller's three-month move is computed from -- a percentage for a
      // price, points for a yield; the caller knows which it asked about.
      windowFirst: used.length ? closes[used[0]] : null,
    };
  }

  /**
   * Did the series itself move when the run began, or only the window's base?
   * Port of onset.turn: read at the run's first bar over the TURN_BARS bars
   * before it, signed in the run's own direction.
   */
  function turn(closes, start, want) {
    if (start < TURN_BARS) return {manner: null, move: null};
    var base = closes[start - TURN_BARS];
    if (!(base > 0)) return {manner: null, move: null};
    var move = closes[start] / base - 1.0;
    if (want === "bearish") move = -move;
    if (move >= TURN_MOVE) return {manner: "turn", move: move};
    if (move <= -TURN_MOVE) return {manner: "against", move: move};
    return {manner: "flat", move: move};
  }

  function maxFn(a) {
    return Math.max.apply(null, a);
  }
  function minFn(a) {
    return Math.min.apply(null, a);
  }

  return {
    classify: classify,
    onset: onset,
    current: current,
    windowNow: windowNow,
    windowAt: windowAt,
    monthsBack: monthsBack,
    constants: {
      MIN_BARS: MIN_BARS,
      MIN_RETURNS: MIN_RETURNS,
      MIN_RETURNS_T: MIN_RETURNS_T,
      ENTER_SCORE: ENTER_SCORE,
      ENTER_T: ENTER_T,
      HOLD_SCORE: HOLD_SCORE,
      HOLD_T: HOLD_T,
      HOLD_BARS: HOLD_BARS,
      FADE_IN: FADE_IN,
      WEIGHTS: WEIGHTS,
      CALL_THRESHOLD: CALL_THRESHOLD,
      STRONG_THRESHOLD: STRONG_THRESHOLD,
      PULLBACK_BARS: PULLBACK_BARS,
      PULLBACK_AVG: PULLBACK_AVG,
      WINDOW_DAYS: WINDOW_DAYS,
      WINDOW_MONTHS: WINDOW_MONTHS,
      TURN_BARS: TURN_BARS,
      TURN_MOVE: TURN_MOVE,
    },
  };
});

/*
 * Trend Badge widget -- draws a price line and a Bullish / Bearish / Neutral
 * badge from prices the page supplies. No dependencies, no build step.
 *
 *   <script src="trend-widget.js"></script>
 *   <trend-badge name="ACME" closes="101,102,104,103,106,..."></trend-badge>
 *   <trend-badge name="ACME" src="/prices/acme.json"></trend-badge>
 *
 * The label describes the shape of the prices shown. It is not a forecast.
 */
(function (root) {
  "use strict";

  var Trend = root.Trend;
  if (!Trend || typeof Trend.classify !== "function") {
    throw new Error("trend-widget: the Trend scorer did not load.");
  }

  var VERSION = "1.0.0";
  var DEFAULT_BARS = 63; // about three months of trading days
  var MIN_CLOSES = 3;

  // ------------------------------------------------------------ reading data

  function toNumber(v) {
    if (typeof v === "number") return v;
    if (typeof v !== "string") return NaN;
    var s = v.trim().replace(/[$,_\s]/g, "");
    return s === "" ? NaN : Number(s);
  }

  // A date from a unix time (seconds or milliseconds), a Date or a string.
  function toDate(v) {
    if (v === null || v === undefined || v === "") return null;
    if (v instanceof Date) return isNaN(v.getTime()) ? null : v;
    if (typeof v === "number" || /^\d+(\.\d+)?$/.test(String(v).trim())) {
      var n = Number(v);
      if (!isFinite(n)) return null;
      return new Date(n < 1e12 ? n * 1000 : n);
    }
    var d = new Date(String(v).trim());
    return isNaN(d.getTime()) ? null : d;
  }

  function splitList(text) {
    return String(text).split(/[\s,;]+/).filter(Boolean);
  }

  function pick(obj, names) {
    for (var i = 0; i < names.length; i++) {
      if (obj[names[i]] !== undefined) return obj[names[i]];
    }
    return undefined;
  }

  var CLOSE_KEYS = ["close", "Close", "c", "price", "Price", "value", "Value", "nav", "NAV"];
  var DATE_KEYS = ["date", "Date", "time", "Time", "t", "timestamp", "day"];

  // CSV with an optional header. With a header, the "close" (or "adj close",
  // "price", "value") column is the price and a "date" column the date.
  // Without one: one column is prices, two or more are date then price.
  function parseCSV(text) {
    var lines = String(text).split(/\r?\n/).map(function (l) { return l.trim(); })
      .filter(function (l) { return l && l.charAt(0) !== "#"; });
    if (!lines.length) return { closes: [], dates: null };
    var sep = lines[0].indexOf(";") >= 0 && lines[0].indexOf(",") < 0 ? ";" :
              lines[0].indexOf("\t") >= 0 ? "\t" : ",";
    var rows = lines.map(function (l) {
      return l.split(sep).map(function (c) { return c.trim().replace(/^"|"$/g, ""); });
    });
    var head = rows[0];
    var hasHeader = head.some(function (c) { return /[a-z]/i.test(c) && isNaN(toNumber(c)) && !toDate(c); });
    var closeCol, dateCol = -1;
    if (hasHeader) {
      var low = head.map(function (c) { return c.toLowerCase(); });
      closeCol = ["close", "adj close", "adj_close", "price", "value", "nav", "navpu"]
        .map(function (k) { return low.indexOf(k); })
        .filter(function (i) { return i >= 0; })[0];
      if (closeCol === undefined) closeCol = head.length - 1;
      dateCol = ["date", "time", "timestamp", "day"]
        .map(function (k) { return low.indexOf(k); })
        .filter(function (i) { return i >= 0; })[0];
      if (dateCol === undefined) dateCol = -1;
      rows = rows.slice(1);
    } else if (head.length >= 2) {
      dateCol = 0;
      closeCol = 1;
    } else {
      closeCol = 0;
    }
    var points = rows.map(function (r) {
      return { close: r[closeCol], date: dateCol >= 0 ? r[dateCol] : null };
    });
    return { points: points };
  }

  // Text from a file or an attribute: JSON first, then CSV, then a bare list.
  function parseText(text) {
    var s = String(text || "").trim();
    if (!s) return { closes: [], dates: null };
    if (s.charAt(0) === "[" || s.charAt(0) === "{") {
      try { return JSON.parse(s); } catch (e) { /* not JSON: read it as CSV */ }
    }
    if (/\n/.test(s)) return parseCSV(s);
    return splitList(s).map(toNumber);
  }

  /**
   * Turn any supported input into { closes, dates, dropped }, oldest first.
   * Accepts: [101, 102], [[date, close], ...], [{date, close}, ...],
   * { closes: [...], dates: [...] }, or the result of parseCSV.
   */
  function normalize(input) {
    var points = [];
    if (typeof input === "string") input = parseText(input);
    if (input && !Array.isArray(input) && typeof input === "object") {
      if (Array.isArray(input.points)) {
        points = input.points;
      } else {
        var cl = pick(input, ["closes", "close", "prices", "values", "c"]);
        var dt = pick(input, ["dates", "date", "timestamps", "times", "t"]);
        if (typeof cl === "string") cl = splitList(cl);
        if (typeof dt === "string") dt = splitList(dt);
        cl = cl || [];
        points = cl.map(function (c, i) {
          return { close: c, date: Array.isArray(dt) ? dt[i] : null };
        });
      }
    } else if (Array.isArray(input)) {
      points = input.map(function (p) {
        if (Array.isArray(p)) return p.length >= 2 ? { date: p[0], close: p[1] } : { close: p[0] };
        if (p && typeof p === "object") return { close: pick(p, CLOSE_KEYS), date: pick(p, DATE_KEYS) };
        return { close: p, date: null };
      });
    }

    var closes = [], dates = [], dropped = 0, anyDate = false;
    for (var i = 0; i < points.length; i++) {
      var c = toNumber(points[i].close);
      if (!(isFinite(c) && c > 0)) { dropped++; continue; }
      var d = toDate(points[i].date);
      if (d) anyDate = true;
      closes.push(c);
      dates.push(d);
    }
    if (!anyDate) dates = null;

    // Newest-first files are common; the scorer needs oldest first.
    if (dates && dates.length > 1 && dates[0] && dates[dates.length - 1] &&
        dates[0].getTime() > dates[dates.length - 1].getTime()) {
      closes.reverse();
      dates.reverse();
    }
    return { closes: closes, dates: dates, dropped: dropped };
  }

  // ----------------------------------------------------------------- verdict

  function words(result) {
    if (!result) return { text: "Not enough data", tag: "", tone: "none" };
    var tag = "";
    if (result.label === "bullish" && result.pullback) tag = "pulling back";
    if (result.label === "bearish" && result.pullback) tag = "bouncing";
    if (result.label === "neutral" && result.lean) tag = "leaning " + result.lean;
    var text = result.label.charAt(0).toUpperCase() + result.label.slice(1);
    var tone = result.label === "bullish" ? "up" : result.label === "bearish" ? "down" : "flat";
    return { text: text, tag: tag, tone: tone };
  }

  /**
   * Score prices without drawing anything.
   * @param {*} input  any form normalize() accepts
   * @param {{bars?: number|"all"}} [options]
   */
  function judge(input, options) {
    options = options || {};
    var series = input && input.closes && input.dropped !== undefined ? input : normalize(input);
    var bars = options.bars === "all" ? series.closes.length :
               Math.max(MIN_CLOSES, Math.floor(Number(options.bars) || DEFAULT_BARS));
    var start = Math.max(0, series.closes.length - bars);
    var closes = series.closes.slice(start);
    var dates = series.dates ? series.dates.slice(start) : null;
    var result = closes.length >= MIN_CLOSES ? Trend.classify(closes) : null;
    var first = closes[0], last = closes[closes.length - 1];
    var w = words(result);
    return {
      label: result ? result.label : null,
      words: w.text + (w.tag ? ", " + w.tag : ""),
      tone: w.tone,
      tag: w.tag,
      result: result,
      closes: closes,
      dates: dates,
      first: first,
      last: last,
      change: closes.length > 1 ? last / first - 1 : null,
      bars: closes.length,
      dropped: series.dropped,
    };
  }

  // --------------------------------------------------------------- formatting

  function fmtPrice(x, currency, locale) {
    if (!isFinite(x)) return "";
    var digits = x >= 1 ? 2 : x >= 0.01 ? 4 : 6;
    try {
      var opts = { minimumFractionDigits: digits, maximumFractionDigits: digits };
      if (currency) { opts.style = "currency"; opts.currency = currency; }
      return new Intl.NumberFormat(locale || undefined, opts).format(x);
    } catch (e) {
      return (currency ? currency + " " : "") + x.toFixed(digits);
    }
  }

  function fmtPct(x, locale) {
    if (x === null || !isFinite(x)) return "";
    try {
      return new Intl.NumberFormat(locale || undefined, {
        style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1, signDisplay: "exceptZero",
      }).format(x);
    } catch (e) {
      return (x > 0 ? "+" : "") + (x * 100).toFixed(1) + "%";
    }
  }

  function fmtDate(d, locale, withYear) {
    if (!d) return "";
    var opts = { month: "short", day: "numeric", timeZone: "UTC" };
    if (withYear) opts.year = "numeric";
    try { return new Intl.DateTimeFormat(locale || undefined, opts).format(d); }
    catch (e) { return d.toISOString().slice(0, 10); }
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  // ------------------------------------------------------------------ drawing

  var W = 300, H = 72, PAD = 3;

  function linePoints(closes) {
    var lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
    var span = hi - lo || 1;
    var n = closes.length;
    return closes.map(function (c, i) {
      var x = n === 1 ? W / 2 : (i / (n - 1)) * W;
      var y = PAD + (1 - (c - lo) / span) * (H - 2 * PAD);
      return [Math.round(x * 100) / 100, Math.round(y * 100) / 100];
    });
  }

  var CSS = [
    ":host{--trend-up:#157a43;--trend-down:#c0392b;--trend-flat:#5f6873;",
    "--trend-bg:#ffffff;--trend-fg:#1d2330;--trend-muted:#5f6873;--trend-border:#dfe3e8;",
    "--trend-radius:12px;--trend-font:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;",
    "display:block;font-family:var(--trend-font);color:var(--trend-fg);}",
    ":host([layout=badge]){display:inline-block;vertical-align:middle;}",
    ":host([theme=dark]){--trend-up:#4cc38a;--trend-down:#ff7a6b;--trend-flat:#a0a9b4;",
    "--trend-bg:#161b22;--trend-fg:#e8ecf1;--trend-muted:#a0a9b4;--trend-border:#2d3541;}",
    "@media (prefers-color-scheme:dark){:host(:not([theme=light])){--trend-up:#4cc38a;",
    "--trend-down:#ff7a6b;--trend-flat:#a0a9b4;--trend-bg:#161b22;--trend-fg:#e8ecf1;",
    "--trend-muted:#a0a9b4;--trend-border:#2d3541;}}",
    ".card{background:var(--trend-bg);border:1px solid var(--trend-border);border-radius:var(--trend-radius);",
    "padding:14px 16px 12px;box-sizing:border-box;min-width:0;}",
    ".top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;}",
    ".name{font-weight:650;font-size:15px;overflow-wrap:anywhere;}",
    ".pill{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:650;line-height:1;",
    "padding:5px 10px;border-radius:999px;border:1px solid currentColor;white-space:nowrap;}",
    ".pill::before{content:'';width:7px;height:7px;border-radius:50%;background:currentColor;}",
    ".pill .tag{font-weight:500;opacity:.85;}",
    ".up{color:var(--trend-up);}.down{color:var(--trend-down);}.flat,.none{color:var(--trend-flat);}",
    ".price{margin-top:8px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;}",
    ".last{font-size:22px;font-weight:650;font-variant-numeric:tabular-nums;}",
    ".chg{font-size:13px;color:var(--trend-muted);font-variant-numeric:tabular-nums;}",
    "svg{display:block;width:100%;height:72px;margin-top:8px;overflow:visible;touch-action:pan-y;}",
    ".line{fill:none;stroke:currentColor;stroke-width:2;vector-effect:non-scaling-stroke;",
    "stroke-linejoin:round;stroke-linecap:round;}",
    ".area{fill:currentColor;opacity:.10;stroke:none;}",
    ".cross{stroke:var(--trend-muted);stroke-width:1;vector-effect:non-scaling-stroke;opacity:0;}",
    ".dot{fill:currentColor;opacity:0;}",
    "svg.hover .cross,svg.hover .dot{opacity:1;}",
    ".note{margin-top:8px;font-size:11.5px;color:var(--trend-muted);line-height:1.4;}",
    ".msg{font-size:13px;color:var(--trend-muted);}",
  ].join("");

  function pillHTML(v) {
    var w = words(v.result);
    return '<span class="pill ' + w.tone + '" part="badge">' + esc(w.text) +
      (w.tag ? ' <span class="tag">· ' + esc(w.tag) + "</span>" : "") + "</span>";
  }

  function cardHTML(v, o) {
    var w = words(v.result);
    var pts = linePoints(v.closes);
    var line = pts.map(function (p) { return p[0] + "," + p[1]; }).join(" ");
    var area = "0," + H + " " + line + " " + W + "," + H;
    var d0 = v.dates && v.dates[0], d1 = v.dates && v.dates[v.dates.length - 1];
    var spanYears = d0 && d1 && d0.getUTCFullYear() !== d1.getUTCFullYear();
    var range = d0 && d1 ? fmtDate(d0, o.locale, spanYears) + " – " + fmtDate(d1, o.locale, true) : "";
    var label = (o.name ? o.name + ": " : "") + w.text + (w.tag ? ", " + w.tag : "") +
      ". Last price " + fmtPrice(v.last, o.currency, o.locale) + ", " +
      fmtPct(v.change, o.locale) + " over " + v.bars + " days.";
    var note = o.note === "off" ? "" :
      '<div class="note" part="note">' + (range ? esc(range) + " · " : "") +
      "Trend of the last " + v.bars + " days. Describes the past, not a forecast.</div>";
    return '<div class="card" part="card">' +
      '<div class="top">' + (o.name ? '<span class="name" part="name">' + esc(o.name) + "</span>" : "<span></span>") +
      pillHTML(v) + "</div>" +
      '<div class="price"><span class="last" part="price">' + esc(fmtPrice(v.last, o.currency, o.locale)) +
      '</span><span class="chg" part="change">' + esc(fmtPct(v.change, o.locale)) +
      " over " + v.bars + " days</span></div>" +
      '<svg class="' + w.tone + '" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" role="img" aria-label="' +
      esc(label) + '"><polygon class="area" points="' + area + '"/>' +
      '<polyline class="line" points="' + line + '"/>' +
      '<line class="cross" x1="0" x2="0" y1="0" y2="' + H + '"/>' +
      '<circle class="dot" r="2.5" cx="0" cy="0"/></svg>' + note + "</div>";
  }

  // ------------------------------------------------------------ the element

  var Base = root.HTMLElement || function () {};

  function TrendBadgeClass() {
    // Built only where custom elements exist (browsers), so this file also
    // loads under Node for testing.
    return class TrendBadge extends Base {
      static get observedAttributes() {
        return ["closes", "dates", "src", "name", "currency", "locale", "bars", "layout", "note", "refresh"];
      }
      constructor() {
        super();
        this._shadow = this.attachShadow({ mode: "open" });
        this._data = null;
        this._token = 0;
        this._verdict = null;
        this._pending = false;
        this._timer = null;
      }
      connectedCallback() { this._schedule(); this._startTimer(); }
      disconnectedCallback() { this._stopTimer(); }
      attributeChangedCallback(name) {
        if (name === "refresh") { this._stopTimer(); this._startTimer(); }
        if (this.isConnected) this._schedule();
      }
      get data() { return this._data; }
      set data(v) { this._data = v; this._schedule(); }
      get verdict() { return this._verdict; }
      reload() { this._schedule(); }

      _startTimer() {
        var s = Number(this.getAttribute("refresh"));
        if (this.isConnected && this.getAttribute("src") && s >= 30) {
          var self = this;
          this._timer = setInterval(function () { self._schedule(); }, s * 1000);
        }
      }
      _stopTimer() { if (this._timer) clearInterval(this._timer); this._timer = null; }

      _schedule() {
        if (this._pending) return;
        this._pending = true;
        var self = this;
        Promise.resolve().then(function () { self._pending = false; self._load(); });
      }

      _load() {
        var token = ++this._token, self = this;
        var src = this.getAttribute("src");
        if (this._data) return this._show(normalize(this._data));
        if (src) {
          if (!this._verdict) this._message("Loading prices…");
          fetch(src, { cache: "no-cache" })
            .then(function (r) {
              if (!r.ok) throw new Error("HTTP " + r.status);
              return r.text();
            })
            .then(function (text) { if (token === self._token) self._show(normalize(parseText(text))); })
            .catch(function (err) {
              if (token !== self._token) return;
              // A failed load is never shown as a verdict.
              self._verdict = null;
              self._message("Prices could not be loaded.");
              self._emit("trenderror", { error: String(err && err.message || err) });
            });
          return;
        }
        var closes = this.getAttribute("closes");
        if (closes) {
          var dates = this.getAttribute("dates");
          return this._show(normalize({ closes: splitList(closes), dates: dates ? splitList(dates) : null }));
        }
        this._message("No prices given.");
      }

      _options() {
        return {
          name: this.getAttribute("name") || "",
          currency: this.getAttribute("currency") || "",
          locale: this.getAttribute("locale") || "",
          layout: this.getAttribute("layout") || "card",
          note: this.getAttribute("note") || "",
        };
      }

      _message(text) {
        var o = this._options();
        this._shadow.innerHTML = "<style>" + CSS + "</style>" + (o.layout === "badge" ?
          '<span class="pill none" part="badge">' + esc(text) + "</span>" :
          '<div class="card" part="card">' + (o.name ? '<div class="name" part="name">' + esc(o.name) + "</div>" : "") +
          '<div class="msg">' + esc(text) + "</div></div>");
      }

      _show(series) {
        var bars = this.getAttribute("bars");
        var v = judge(series, { bars: bars === "all" ? "all" : bars });
        if (!v.result) {
          this._verdict = null;
          this._message(v.closes.length ? "Not enough data." : "No prices given.");
          return;
        }
        this._verdict = v;
        var o = this._options();
        this._shadow.innerHTML = "<style>" + CSS + "</style>" + (o.layout === "badge" ? pillHTML(v) : cardHTML(v, o));
        this.setAttribute("data-label", v.label);
        if (o.layout !== "badge") this._hover(v, o);
        this._emit("trend", v);
      }

      _hover(v, o) {
        var svg = this._shadow.querySelector("svg");
        var last = this._shadow.querySelector(".last");
        var chg = this._shadow.querySelector(".chg");
        var cross = svg.querySelector(".cross"), dot = svg.querySelector(".dot");
        var pts = linePoints(v.closes);
        var restLast = last.textContent, restChg = chg.textContent;
        function move(ev) {
          var box = svg.getBoundingClientRect();
          if (!box.width) return;
          var f = Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width));
          var i = Math.round(f * (v.closes.length - 1));
          var p = pts[i];
          cross.setAttribute("x1", p[0]); cross.setAttribute("x2", p[0]);
          dot.setAttribute("cx", p[0]); dot.setAttribute("cy", p[1]);
          svg.classList.add("hover");
          last.textContent = fmtPrice(v.closes[i], o.currency, o.locale);
          var d = v.dates && v.dates[i];
          chg.textContent = d ? fmtDate(d, o.locale, true) : "day " + (i + 1) + " of " + v.closes.length;
        }
        function leave() {
          svg.classList.remove("hover");
          last.textContent = restLast; chg.textContent = restChg;
        }
        svg.addEventListener("pointermove", move);
        svg.addEventListener("pointerdown", move);
        svg.addEventListener("pointerleave", leave);
      }

      _emit(type, detail) {
        if (typeof CustomEvent === "function") {
          this.dispatchEvent(new CustomEvent(type, { detail: detail, bubbles: true }));
        }
      }
    };
  }

  if (root.customElements && root.HTMLElement && !root.customElements.get("trend-badge")) {
    root.customElements.define("trend-badge", TrendBadgeClass());
  }

  /** Put a widget inside `target` (an element or a CSS selector). */
  function mount(target, data, attrs) {
    var host = typeof target === "string" ? root.document.querySelector(target) : target;
    if (!host) throw new Error("trend-widget: no element matches " + target);
    var el = root.document.createElement("trend-badge");
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    if (data !== undefined && data !== null) el.data = data;
    host.appendChild(el);
    return el;
  }

  root.TrendWidget = {
    version: VERSION,
    judge: judge,
    mount: mount,
    normalize: normalize,
    parseText: parseText,
    words: words,
  };
})(typeof self !== "undefined" ? self : this);
