/* Today's overview, drawn as pictures (2026-11-26).

   The panel used to be sentences. Here every number the sentences carried
   becomes a pill, a dot, a tile or a bar; the whole old sentence moves to
   the hover title and the screen-reader label, so nothing is lost. The
   builders below return plain objects (node tests them); the draw helpers
   turn them into elements. Descriptive only: nothing here is a label. */

const GLANCE_NAMES = {
  "CL=F": "WTI oil", "BZ=F": "Brent oil", "GC=F": "Gold", "SI=F": "Silver",
  "HG=F": "Copper", "NG=F": "Nat gas", "^GSPC": "S&P 500", "^IXIC": "Nasdaq",
  "ES=F": "S&P fut", "NQ=F": "Nasdaq fut", "PSEI.PS": "PSEi",
};

function glanceName(sym) {
  const s = String(sym || "");
  if (GLANCE_NAMES[s]) return GLANCE_NAMES[s];
  const fx = /^([A-Z]{3})([A-Z]{3})=X$/.exec(s);
  if (fx) return fx[1] + "/" + fx[2];
  return s.split(":").pop();
}

function glanceSigned(pct, digits) {
  if (!Number.isFinite(pct)) return "";
  return (pct >= 0 ? "+" : "−") + Math.abs(pct).toFixed(digits == null ? 1 : digits) + "%";
}

/* Header pills from the digest: PSE session, watchlist split, fresh turns,
   fired alarms, markets running on a fallback. withMarkets adds one pill per
   market (the chart card has no health block beside it). */
function summaryPills(digest, opts) {
  const o = opts || {};
  if (!digest) return [];
  const pills = [];
  const pse = digest.pseSession;
  if (pse && pse.state) {
    const open = pse.state === "open";
    pills.push({
      kind: "pse", tone: open ? "live" : "quiet", dot: true,
      parts: [{ text: "PSE " + pse.state }].concat(pse.localTime ? [{ text: pse.localTime, tone: "muted" }] : []),
      title: "Philippine exchange: " + pse.state + (pse.localTime ? " (" + pse.localTime + " Manila)" : ""),
    });
  }
  if (o.withMarkets) {
    for (const m of (digest.marketHealth || []).slice(0, 4)) {
      pills.push({
        kind: "market", parts: [{ text: m.market }, { text: "▲" + (m.bullish || 0), tone: "up" },
          { text: "▼" + (m.bearish || 0), tone: "down" }],
        title: m.market + ": " + (m.bullish || 0) + " bullish, " + (m.bearish || 0) + " bearish",
      });
    }
  }
  const watch = digest.watchlist || [];
  if (watch.length) {
    const up = watch.filter((w) => w.label === "bullish").length;
    const down = watch.filter((w) => w.label === "bearish").length;
    pills.push({
      kind: "watch", parts: [{ text: "★ " + watch.length }, { text: "▲" + up, tone: "up" }, { text: "▼" + down, tone: "down" }],
      title: "Watchlist (" + watch.length + "): " + up + " bullish, " + down + " bearish",
    });
  }
  const turns = digest.freshTurns || [];
  if (turns.length) {
    pills.push({
      kind: "turns", tone: "accent",
      parts: [{ text: "⚡ " + turns.length + " fresh turn" + (turns.length === 1 ? "" : "s") }],
      title: "Names whose trend turned on their newest bar",
    });
  }
  const fired = (digest.alarms && digest.alarms.fired) || [];
  if (fired.length) {
    pills.push({ kind: "alarm", tone: "warn", parts: [{ text: "🔔 " + fired.length }],
      title: fired.length + " alarm" + (fired.length === 1 ? "" : "s") + " fired" });
  }
  const bad = (digest.markets || []).filter((m) => ["offline", "partial", "fallback"].includes(m.state));
  for (const m of bad.slice(0, 4)) {
    pills.push({ kind: "degraded", tone: "warn", parts: [{ text: "⚠ " + m.market + " " + m.state }],
      title: m.detail || (m.market + " is " + m.state) });
  }
  return pills;
}

/* One health row's counts as coloured pieces, plus the share bullish. */
function healthPieces(m) {
  const judged = m.judged || 0;
  return {
    parts: [
      { text: "▲" + (m.bullish || 0), tone: "up" },
      { text: "▼" + (m.bearish || 0), tone: "down" },
      { text: "●" + (m.neutral || 0), tone: "muted" },
    ],
    of: judged,
    title: (m.bullish || 0) + " bullish · " + (m.bearish || 0) + " bearish · "
      + (m.neutral || 0) + " neutral of " + judged,
  };
}

/* Overnight moves as chips: friendly name, arrow, signed percent. */
function overnightChips(moves) {
  if (!Array.isArray(moves)) return [];
  return moves.slice(0, 5).map((m) => {
    const sym = m.label || m.ticker || m.symbol || "?";
    const pct = Number(m.gapPct ?? m.pct ?? m.gap);
    const ok = Number.isFinite(pct);
    return {
      name: glanceName(sym), symbol: m.symbol || sym,
      tone: !ok ? "muted" : pct > 0 ? "up" : pct < 0 ? "down" : "muted",
      arrow: !ok ? "" : pct > 0 ? "▲" : pct < 0 ? "▼" : "•",
      text: ok ? glanceSigned(pct, 2) : "",
      title: sym + (ok ? " " + glanceSigned(pct, 2) : "") + " overnight",
    };
  });
}

/* Peso cash rates as tiles: the policy rate, then each bill with its weekly
   move. "share" is the yield over the highest one, for the little bar that
   draws the curve's shape. A rising yield is not "good" or "bad" here, so
   moves get arrows but no green or red. */
function ratesTiles(payload) {
  if (!payload || typeof payload !== "object") return null;
  const pct = (v) => (typeof v === "number" && isFinite(v) ? v.toFixed(2) + "%" : null);
  const day = (iso) => (typeof ratesDay === "function" ? ratesDay(iso) : iso || "");
  const policy = payload.policy || null;
  const tiles = [];
  if (policy && pct(policy.rate)) {
    const was = pct(policy.previous);
    const since = day(policy.since);
    let arrow = "";
    if (typeof policy.previous === "number" && typeof policy.rate === "number") {
      arrow = policy.rate > policy.previous ? "▲" : policy.rate < policy.previous ? "▼" : "";
    }
    tiles.push({
      kind: "policy", label: "BSP policy rate", value: pct(policy.rate),
      sub: [arrow && was ? arrow + " from " + was : "", since ? "since " + since : ""].filter(Boolean).join(" · "),
      title: "BSP policy rate " + pct(policy.rate) + (since ? " since " + since : "") + (was ? " (was " + was + ")" : ""),
    });
  }
  const bills = (Array.isArray(payload.bills) ? payload.bills : []).filter((b) => b && pct(b.yield));
  const top = Math.max(0, ...bills.map((b) => b.yield));
  for (const b of bills) {
    let sub = "", arrow = "";
    if (b.unchangedSince) sub = "flat since " + day(b.unchangedSince);
    else if (typeof b.changeWeek === "number" && Math.abs(b.changeWeek) >= 0.005) {
      arrow = b.changeWeek > 0 ? "▲" : "▼";
      sub = arrow + " " + Math.abs(b.changeWeek).toFixed(2) + " this week";
    } else if (typeof b.changeWeek === "number") sub = "flat this week";
    // No bar from a week back: say nothing rather than "flat".
    tiles.push({
      kind: "bill", label: String(b.tenor || "") + " bill", value: pct(b.yield), sub, arrow,
      share: top > 0 ? b.yield / top : 0,
      title: String(b.tenor || "") + " government bill yield " + pct(b.yield) + " — " + sub,
    });
  }
  if (!tiles.length) return null;
  const asOf = bills.map((b) => b.asOf).filter(Boolean).sort().pop();
  let note = "Market yields" + (asOf ? ", " + day(asOf) : "") + " · not auction results · what cash earns, not where prices go · "
    + (payload.source || "TradingView");
  if (payload.cached && !payload.revalidate) note += " · saved copy, source did not answer";
  return { tiles, note };
}

/* "2:50 PM" today, "Nov 25, 2:50 PM" on another day. */
function glanceWhen(epochSec, now) {
  if (!epochSec) return "";
  const d = new Date(epochSec * 1000);
  const n = now ? new Date(now) : new Date();
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return d.toDateString() === n.toDateString()
    ? time : d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) + ", " + time;
}

/* Watched chip: dot by label, an arrow when a neutral name leans. */
const WATCH_MARKS = { bullish: "▲", bearish: "▼", neutral: "●" };
function watchChipParts(trend) {
  if (!trend || !trend.label) return { tone: "none", lean: "", mark: "○" };
  const lean = trend.label === "neutral" && (trend.lean === "bullish" || trend.lean === "bearish")
    ? (trend.lean === "bullish" ? "↗" : "↘") : "";
  const pull = trend.pullback && trend.label !== "neutral" ? "↩" : "";
  return { tone: trend.label, lean: lean + pull, mark: WATCH_MARKS[trend.label] || "○" };
}

/* ---- DOM helpers --------------------------------------------------------- */

function glanceSpan(cls, text) {
  const s = document.createElement("span");
  if (cls) s.className = cls;
  if (text != null) s.textContent = text;
  return s;
}

function drawGlancePills(box, pills) {
  box.textContent = "";
  for (const p of pills) {
    const pill = glanceSpan("glance-pill" + (p.tone ? " tone-" + p.tone : "") + " kind-" + p.kind);
    if (p.dot) pill.append(glanceSpan("glance-dot"));
    for (const part of p.parts) pill.append(glanceSpan(part.tone ? "t-" + part.tone : "", part.text));
    pill.title = p.title || "";
    box.append(pill);
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { summaryPills, healthPieces, overnightChips, ratesTiles, glanceWhen, glanceName, watchChipParts };
}
