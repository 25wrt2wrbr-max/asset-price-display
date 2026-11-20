"use strict";

/* ------------------------------------------------------------------ *
 * Shared table helpers
 *
 * Every table is ranked server-side; the page only draws the rows, formats
 * each figure in the currency it was quoted in, and (where a row carries a
 * second currency) offers the converted amount beneath it.
 * ------------------------------------------------------------------ */
function compact(value, currency) {
  if (!Number.isFinite(value)) return "—";
  try {
    return nf(2, { notation: "compact", style: "currency", currency }).format(value);
  } catch { return "—"; }
}

function leaderMoney(value, currency) {
  if (!Number.isFinite(value)) return "—";
  try { return nf(2, { style: "currency", currency }).format(value); }
  catch { return nf(2).format(value); }
}

function cell(text, className) {
  const td = document.createElement("td");
  if (className) td.className = className;
  td.textContent = text;
  return td;
}

/* A calendar date with no clock time: a trading session is the unit here, and
   the second the bar opened is noise. Read as UTC, which is what the server
   dated it in -- `toLocaleDateString` on a timestamp from a Manila session
   slips to the previous day in a western timezone. */
function sessionDate(stamp) {
  const d = new Date(stamp * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

/* The same date, read in the timezone the row names.
   A Philippine bond yield is closed at five in the morning, which is 21:00
   the day before in UTC -- so read as UTC it lands on the wrong day. The
   server says which timezone each row's bars are stamped in, and this reads
   the date there. Rows without a timezone are read as UTC, like every other
   date on the page. */
function rowDate(stamp, tz) {
  if (!tz) return sessionDate(stamp);
  try {
    // The parts are formatted in the named timezone and then put together
    // here, rather than formatted as a whole: `toLocaleDateString`'s output
    // is whatever the locale says a date looks like, and this table's dates
    // are read against the other tables' -- which are all `YYYY-MM-DD`.
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(new Date(stamp * 1000));
    const get = (type) => parts.find((p) => p.type === type)?.value ?? "";
    return `${get("year")}-${get("month")}-${get("day")}`;
  } catch {
    return sessionDate(stamp);
  }
}

/* ------------------------------------------------------------------ *
 * Recently bullish assets
 *
 * The page's one list of what is bullish now: every market it follows, in a
 * single table. Every row carries the day its current run began, and the rows
 * are ordered newest-turn first, so what turned most recently across every
 * market is at the top.
 *
 * The label is the badge's -- the same `trend.classify` the chart's own
 * badge uses -- and the date is the same walk, worked out server-side
 * (`onset.py`), because it needs a year of bars per instrument and a
 * classification per bar walked.
 *
 * Bond rows invert the yield's direction to reflect the usual price movement
 * of an existing fixed-rate bond, and name the yield movement explicitly.
 * Only a falling yield is a row: a rising yield is a falling bond price, and a
 * flat one has no run to date, so neither belongs in a table of what turned
 * bullish.
 *
 * This absorbed two tables that used to sit below it -- "Most traded crypto"
 * and "Bullish Philippine stocks" -- because both were narrow views of the same
 * scan: the crypto rows and the Philippine rows already appear here, judged by
 * the same classifier over the same bars.
 *
 * The sweep behind this reads the whole Ondo shelf, the chartable crypto
 * ranking and every fund, so the server keeps an answer warm on a background
 * thread; this only ever draws the last one it produced.
 * ------------------------------------------------------------------ */
/* Matches the server's refresh interval on purpose: polling faster than the
   sweep runs re-renders the same table from the same payload. */
const RECENT_TTL = 900 * 1000;

/* The chart's own clock. While the newest bar is a price still moving -- a
   live, pre-market or after-hours print, which the server names in
   `lastBarBasis` -- the chart and its badge re-read every minute, the
   server's own chart-cache lifetime, so the trend verdict follows the market
   in real time. Once the newest bar is a settled close nothing moves, and
   the slow fifteen-minute clock is enough to notice the next session. */
const CHART_TTL = 900 * 1000;
const CHART_LIVE_TTL = 60 * 1000;

/* A price the way this table draws it. A yield is a percentage, not an
   amount of money, so it never gets a currency symbol -- the `%` is the
   unit and the number is the yield. `priceHint` is the row's own precision
   where it has one: a fund's NAVPU is published with two or four decimals,
   and printing a four-decimal fund at two would round away the digits that
   actually moved. */
function recentPrice(value, currency, hint) {
  if (!Number.isFinite(value)) return "—";
  if (currency === "%") return `${nf(3).format(value)}%`;
  const digits = Number.isFinite(Number(hint)) ? Math.min(Math.max(Number(hint), 0), 8) : 2;
  try { return nf(digits, { style: "currency", currency: currency || "USD" }).format(value); }
  catch { return nf(digits).format(value); }
}

function drawRecent(payload, listKey, view) {
  const card = document.createElement("div");
  card.className = "card";

  // No card head: this table is the whole section, and its heading sits right
  // above it. A second title and a second row count inside the card (the note
  // already opens with the count) said the same thing three times.
  if (payload.error) {
    const p = document.createElement("p");
    p.className = "card-error";
    p.textContent = payload.error;
    card.append(p);
    return card;
  }

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const hrow = document.createElement("tr");
  for (const heading of
       ["Market", "Asset", "Direction", "Since", "Run", "Price", "3-month",
        "Trading volume (in PHP)"]) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = heading;
    hrow.append(th);
  }
  thead.append(hrow);
  table.append(thead);

  // The newest bar each market reaches, which is what "began on the latest
  // bar" is measured against: recency is a fact about the data, not about
  // the reader's clock. It is measured per market, because the markets do
  // not trade on the same clock -- the Philippine bond yield is closed at
  // five in the morning, hours before the American session opens -- and a
  // bond row compared against a New York bar would never be "fresh" for a
  // reason that has nothing to do with the bond.
  const latest = {};
  const rows = payload[listKey] || [];
  for (const row of rows) {
    const market = row.market || "";
    latest[market] = Math.max(latest[market] || 0, row.last || 0);
  }

  const tbody = document.createElement("tbody");
  // The rate the peso volume column converted at, named once and read on
  // every row's hover; the server already said it in the note.
  const rate = payload.fx && payload.fx.phpPerUsd;
  const built = rows.map((row, index) => {
    const tr = document.createElement("tr");

    tr.append(cell(row.market || "—", "market"));

    // The asset cell stacks a ticker over its name, so it is the one cell
    // allowed to wrap -- a long instrument name held on one line would need a
    // column wider than the five others leave over.
    const label = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tick-btn";
    button.textContent = row.ticker || row.symbol;
    // As in the leaderboards: no handler of its own, so a mouse click and a
    // keyboard activation bubble to the row's one handler and take the same
    // path.
    const name = document.createElement("span");
    name.className = "tick-sub";
    name.textContent = row.name || "";
    label.append(button, name);
    // Two honest marks beside the name: where the bars came from when it was
    // not the primary source, and any defect found in them. Both describe the
    // data; neither changes the verdict in the next column.
    if (row.source) {
      const via = document.createElement("span");
      via.className = "src-tag";
      via.textContent = "via " + row.source;
      via.title = "Yahoo did not answer, so this row was read from " + row.source +
                  " daily closes. They can differ slightly from the chart's series.";
      label.append(via);
    }
    if (row.quality && row.quality.length) {
      const flag = document.createElement("span");
      flag.className = "q-flag";
      flag.textContent = "⚠";
      flag.setAttribute("role", "img");
      const why = row.quality.map((f) => f.text).join("; ");
      flag.setAttribute("aria-label", "Data check: " + why);
      flag.title = "Data check: " + why + ". The verdict is unchanged.";
      label.append(flag);
    }
    tr.append(label);

    // Bond direction is inferred from yield movement, which is named too.
    const dir = document.createElement("td");
    const phrase = rowDirectionPhrase(row);
    if (phrase.yield) {
      dir.className = "dir yield";
      dir.textContent = phrase.text;
      dir.title = "Inferred from the yield: existing fixed-rate bond prices generally "
                + "move inversely to yields. The chart this row opens plots the "
                + "yield in percent, not a bond price.";
    } else {
      dir.className = `dir ${row.direction || "neutral"}`;
      dir.textContent = phrase.text;
    }
    // The badge's own tag for a label whose last two weeks ran against it
    // (trend.py's `pullback`): the row says what its chart will say.
    if (phrase.pull) {
      const pull = document.createElement("span");
      pull.className = "pull";
      pull.textContent = phrase.pull;
      pull.title = "The last 10 bars moved against this trend and the newest one is on the "
                 + "wrong side of its 20-bar average. The label is unchanged.";
      dir.append(pull);
    }
    tr.append(dir);

    // The date the current run started. A run that began on the latest bar is
    // the freshest signal in the table and the reason the sort order is worth
    // reading, so it is marked rather than left to be found by comparing dates.
    const since = cell(row.since ? rowDate(row.since, row.tz) : "—", "since");
    if (row.since && row.since === latest[row.market || ""]) since.classList.add("fresh");
    if (row.censored) {
      since.title = "Running for at least this long — the run starts before the bars fetched";
    }
    if (row.stale) {
      since.title = `Read from a stored copy — the source did not answer (${row.stale}s old)`;
    }
    tr.append(since);

    // Bars, not days: the label is decided a bar at a time, so a run of five
    // is five sessions of it however far apart they fell.
    tr.append(cell(Number.isFinite(row.run) ? String(row.run) : "—"));
    tr.append(cell(recentPrice(row.price, row.currency, row.priceHint)));

    // The window's move: the first bar the chart draws to the newest close,
    // which is the same pair the chart prints under the price when the row is
    // opened ("+12.95% three-month move, since Jul 31"), so the row and its
    // chart cannot disagree about how the window went.
    //
    // A yield gets none, by name: "for bonds, the most important thing is
    // yield. changes don't mean shit. + the bearish or bullish judgment". The
    // yield is the price column; the verdict is the direction column; a points
    // change between them would be a figure about a figure.
    const moveCell = document.createElement("td");
    moveCell.className = "move";
    if (row.currency === "%") {
      moveCell.textContent = "—";
      moveCell.title = "A yield's level is the figure — it is in the price column — "
                     + "and the badge says which way a bond price read it.";
    } else if (Number.isFinite(row.windowMove)) {
      const pct = row.windowMove * 100;
      moveCell.textContent = `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`;
      moveCell.classList.add(pct > 0 ? "up" : pct < 0 ? "down" : "flat");
      moveCell.title = "The window's first close to its newest close — the same "
                     + "bars the badge beside it was scored on.";
    } else {
      // A window that could not be measured is not a zero.
      moveCell.textContent = "—";
      moveCell.title = "This series has no window to measure a move over.";
    }
    tr.append(moveCell);

    // The latest bar's value traded, in pesos, whatever the row's own
    // currency -- the same turnover the other tables rank on, converted at
    // the payload's own rate rather than a second one. The compact figure is
    // what the column shows (a peso turnover reaches thirteen digits); the
    // exact figure, and for a converted row the native one, ride on the
    // cell's title. A yield trades no shares, so its cell is empty -- an
    // empty cell is the honest reading, not a zero.
    const vol = document.createElement("td");
    vol.className = "vol";
    if (Number.isFinite(row.turnoverPhp)) {
      vol.textContent = compact(row.turnoverPhp, "PHP");
      const native = recentPrice(row.turnover, row.currency, row.priceHint);
      vol.title = (row.currency || "").toUpperCase() === "PHP"
        ? leaderMoney(row.turnoverPhp, "PHP")
        : `${native} at USDPHP ${rate ? rate : "—"}`;
    } else if (row.kind === "INDEX") {
      // The PSEi is scanned with the stocks so its own chart can put it on
      // either table; an index is a reading of its members, not a security,
      // so it has no traded value to print. A dash, not a zero.
      vol.textContent = "—";
      vol.title = "An index tracks its members; it has no traded volume of its own";
    } else if (row.market === "Philippine bond") {
      vol.textContent = "—";
      vol.title = "A yield has no traded volume";
    } else if (row.market === "Philippine fund") {
      // A fund is not traded: units are bought from and sold back to the
      // manager at the day's NAVPU, so there is no volume to report and no
      // liquidity test to fail. A dash, not a zero.
      vol.textContent = "—";
      vol.title = "A fund publishes one net asset value per unit; nothing is traded on an exchange";
    } else if (row.market === "US Treasury") {
      // A contract's volume is a count of contracts, not money: close times
      // contracts is not a traded value in any currency, so there is no peso
      // figure to print. A dash, not a zero.
      vol.textContent = "—";
      vol.title = "A futures contract's volume counts contracts, not currency, so there is no traded value to convert";
    } else if (row.market === "Ondo portfolio") {
      // A portfolio token is bought and redeemed at the basket's value; its
      // price bars carry no exchange volume, so there is nothing to convert.
      vol.textContent = "—";
      vol.title = "A portfolio token is bought and redeemed, not traded on an exchange, so it carries no traded volume";
    } else {
      vol.textContent = "—";
    }
    tr.append(vol);

    // Every row on this table opens a chart: a price row through its own
    // source, a bond yield through `tv.py`'s series of the same bars the row
    // was judged on. The fallback stays for a row that genuinely has no chart
    // (a payload with no `chartSymbol`), and says so rather than pretending.
    if (row.chartable && row.chartSymbol) {
      tr.addEventListener("click", () => loadChart(row.chartSymbol));
    } else {
      tr.classList.add("no-chart");
      tr.title = "No chart for this row.";
    }
    return { row, tr, index };
  });
  table.append(tbody);

  // Sorting and filtering are the reader's view of the table, not the
  // sweep's: they reorder and hide rows already on the page and never touch
  // what was judged. The server's order (newest turn first) is the default,
  // and the choice survives the 15-minute refresh.
  const markets = [...new Set(rows.map((r) => r.market || ""))].sort();
  if (view.market && !markets.includes(view.market)) view.market = "";

  const controls = document.createElement("div");
  controls.className = "table-controls";
  const marketLabel = document.createElement("label");
  marketLabel.textContent = "Market ";
  const select = document.createElement("select");
  select.append(new Option(`All markets (${rows.length})`, ""));
  for (const m of markets) {
    const n = rows.filter((r) => (r.market || "") === m).length;
    select.append(new Option(`${m || "—"} (${n})`, m));
  }
  select.value = view.market;
  marketLabel.append(select);
  const searchLabel = document.createElement("label");
  searchLabel.textContent = "Find ";
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "ticker or name";
  search.value = view.text;
  search.setAttribute("autocomplete", "off");
  searchLabel.append(search);

  const hidePullLabel = document.createElement("label");
  hidePullLabel.className = "check-filter";
  const hidePullCheck = document.createElement("input");
  hidePullCheck.type = "checkbox";
  hidePullCheck.checked = Boolean(view.hidePullback);
  hidePullLabel.append(hidePullCheck, listKey === "bearish" ? "Hide bouncing" : "Hide pulling back");

  const freshLabel = document.createElement("label");
  freshLabel.className = "check-filter";
  const freshCheck = document.createElement("input");
  freshCheck.type = "checkbox";
  freshCheck.checked = Boolean(view.freshOnly);
  freshLabel.append(freshCheck, "Fresh turns only");

  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "ghost";
  reset.textContent = "Reset";
  const csvBtn = document.createElement("button");
  csvBtn.type = "button";
  csvBtn.className = "ghost";
  csvBtn.textContent = "Download CSV";
  const count = document.createElement("span");
  count.className = "view-count";
  count.setAttribute("role", "status");
  controls.append(marketLabel, searchLabel, hidePullLabel, freshLabel, reset, csvBtn, count);

  const SORTS = {
    Market: ["market", 1, (r) => r.market || ""],
    Asset: ["asset", 1, (r) => (r.ticker || r.symbol || "").toUpperCase()],
    Since: ["since", -1, (r) => r.since],
    Run: ["run", -1, (r) => r.run],
    "3-month": ["move", -1, (r) => r.windowMove],
  };
  const heads = [...hrow.children];
  heads.forEach((th) => {
    const spec = SORTS[th.textContent];
    if (!spec) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sort-btn";
    btn.textContent = th.textContent;
    btn.addEventListener("click", () => {
      if (view.key === spec[0]) view.dir = -view.dir;
      else { view.key = spec[0]; view.dir = spec[1]; }
      render();
    });
    th.textContent = "";
    th.append(btn);
    th.dataset.sort = spec[0];
  });

  let lastShown = [];
  function render() {
    const text = view.text.trim().toLowerCase();
    let shown = built.filter(({ row }) =>
      (!view.market || (row.market || "") === view.market) &&
      (!view.hidePullback || !row.pullback) &&
      (!view.freshOnly || Boolean(row.since && row.since === latest[row.market || ""])) &&
      (!text || [row.ticker, row.symbol, row.name].some(
        (v) => String(v || "").toLowerCase().includes(text))));
    const spec = Object.values(SORTS).find((s) => s[0] === view.key);
    if (spec) {
      const get = spec[2];
      shown = shown.slice().sort((a, b) => {
        const x = get(a.row), y = get(b.row);
        const xMissing = x === null || x === undefined || Number.isNaN(x);
        const yMissing = y === null || y === undefined || Number.isNaN(y);
        if (xMissing || yMissing) return xMissing - yMissing;   // gaps sort last
        const c = typeof x === "string" ? x.localeCompare(y) : x - y;
        return (c * view.dir) || (a.index - b.index);
      });
    } else {
      shown = shown.slice().sort((a, b) => a.index - b.index);
    }
    lastShown = shown;
    tbody.textContent = "";
    shown.forEach(({ tr }) => tbody.append(tr));
    heads.forEach((th) => {
      if (!th.dataset.sort) return;
      const on = th.dataset.sort === view.key;
      th.setAttribute("aria-sort", on ? (view.dir > 0 ? "ascending" : "descending") : "none");
      th.firstChild.textContent = th.firstChild.textContent.replace(/ [▲▼]$/, "") +
        (on ? (view.dir > 0 ? " ▲" : " ▼") : "");
    });
    count.textContent = shown.length === built.length
      ? `${built.length} rows` : `Showing ${shown.length} of ${built.length} rows`;
    reset.hidden = !(view.key || view.market || view.text || view.hidePullback || view.freshOnly);
    csvBtn.disabled = !shown.length;
  }
  select.addEventListener("change", () => { view.market = select.value; render(); });
  search.addEventListener("input", () => { view.text = search.value; render(); });
  hidePullCheck.addEventListener("change", () => { view.hidePullback = hidePullCheck.checked; render(); });
  freshCheck.addEventListener("change", () => { view.freshOnly = freshCheck.checked; render(); });
  reset.addEventListener("click", () => {
    view.market = ""; view.text = ""; view.hidePullback = false; view.freshOnly = false; view.key = null; view.dir = 1;
    select.value = ""; search.value = ""; hidePullCheck.checked = false; freshCheck.checked = false;
    render();
  });
  csvBtn.addEventListener("click", () => {
    const headers = [
      "Market", "Ticker", "Symbol", "Name", "Direction", "Pullback",
      "Since", "Run (bars)", "Price", "Currency", "3-month (%)", "Trading volume (PHP)",
    ];
    const dataRows = lastShown.map(({ row }) => {
      const phrase = rowDirectionPhrase(row);
      const move = row.currency === "%" || !Number.isFinite(row.windowMove)
        ? "" : Number((row.windowMove * 100).toFixed(2));
      return [
        row.market || "",
        row.ticker || row.symbol || "",
        row.symbol || "",
        row.name || "",
        phrase.text || "",
        phrase.pull || "",
        row.since ? rowDate(row.since, row.tz) : "",
        Number.isFinite(row.run) ? row.run : "",
        Number.isFinite(row.price) ? row.price : "",
        row.currency || "",
        move,
        Number.isFinite(row.turnoverPhp) ? Math.round(row.turnoverPhp) : "",
      ];
    });
    const name = listKey === "bearish" ? "recently-bearish.csv" : "recently-bullish.csv";
    downloadCsv(name, headers, dataRows);
  });
  render();

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  wrap.append(table);
  card.append(controls, wrap);
  return card;
}

// The reader's sort and filter on the tables.
const recentView = { market: "", text: "", hidePullback: false, freshOnly: false, key: null, dir: 1 };
const bearishView = { market: "", text: "", hidePullback: false, freshOnly: false, key: null, dir: 1 };
const leaningView = { market: "", text: "", key: null, dir: 1 };

/* One chip per market: did it answer, and how fresh are its bars? An outage
 * has to read as an outage, not as a market with nothing bullish in it. */
const STATE_WORDS = {
  live: ["✓", "live"],
  partial: ["◐", "partial"],
  fallback: ["⇄", "Nasdaq closes"],
  offline: ["✕", "offline"],
};
function drawMarketStatus(payload) {
  const box = el.recentStatus;
  box.textContent = "";
  for (const m of payload.markets || []) {
    const [glyph, word] = STATE_WORDS[m.state] || ["?", m.state];
    const chip = document.createElement("span");
    chip.className = "mkt-chip state-" + m.state;
    const bits = [m.market, word];
    if (m.state === "partial" && m.missing) bits[1] = `partial, ${m.missing} did not answer`;
    if (m.state === "fallback" && m.fallback) bits[1] = `Nasdaq closes for ${m.fallback}`;
    if (m.asOf && m.state !== "offline") {
      bits.push("bars to " + rowDate(m.asOf, m.market === "Philippine bond" ? "Asia/Manila" : undefined));
    }
    chip.textContent = `${glyph} ${bits.join(" · ")}`;
    if (m.detail) chip.title = m.detail;
    box.append(chip);
  }
  box.hidden = !box.children.length;
}


function drawRecentNote(payload) {
  const parts = [];
  if (payload.pending) {
    // The first sweep has not landed yet. Saying so is the whole reason this
    // note exists: an empty table would read as "nothing anywhere is
    // bullish", which is a far stronger claim than "not measured yet".
    parts.push("Scanning — this table fills in when the first sweep finishes");
  } else if (payload.cached && payload.fetchedAt) {
    // The table is a sweep read off disk, not one this server ran. The rows
    // and their dates are real either way; what changes is that the sweep
    // itself stopped arriving at `fetchedAt`, and the note says so.
    parts.push("Swept " + retrievedAt(payload.fetchedAt) + " — source offline");
  } else if (payload.checkedAt) {
    parts.push("Swept " + new Date(payload.checkedAt * 1000).toLocaleTimeString());
  }
  // The server's own one-line summary of what was judged and what answered.
  if (payload.note) parts.push(payload.note);
  // A failed refresh leaves the last good sweep on screen, dated, so the
  // failure is reported beside the rows rather than by clearing them.
  if (payload.staleError) parts.push("last refresh failed — " + payload.staleError);
  el.recentNote.textContent = parts.join(" · ");
}

/* ------------------------------------------------------------------ *
 * Leaning bullish -- not confirmed
 *
 * The near-misses of the same sweep: assets whose own chart reads Neutral
 * but whose window sits inside the band that keeps a bullish label
 * (score >= 0.15, drift t >= 1.0) without meeting the bar that earns one
 * (score >= 0.25, t >= 1.96). Same classifier, same window; ordered by how
 * much of that bar is met. No date: a label was never given, so there is
 * no run to date.
 * ------------------------------------------------------------------ */
function drawLeaning(payload) {
  const rows = payload.leaning || [];
  const card = document.createElement("div");
  card.className = "card";
  const head = document.createElement("div");
  head.className = "card-head";
  const title = document.createElement("h3");
  title.textContent = "Neutral on the chart, leaning bullish";
  const sub = document.createElement("span");
  sub.className = "card-sub";
  // The row count is every market. The subtitle names the filter that decides
  // whether a name is on this list at all (`onset.steady_lean`); the note under
  // the table spells out the rule and the Ondo shelf, so this stays short.
  sub.textContent = `${rows.length} rows · steady leans only`;
  head.append(title, sub);
  card.append(head);

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const hrow = document.createElement("tr");
  for (const heading of ["Market", "Asset", "Toward bullish", "Score", "Drift t",
                         "Price", "Trading volume (in PHP)"]) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = heading;
    hrow.append(th);
  }
  thead.append(hrow);
  table.append(thead);

  const tbody = document.createElement("tbody");
  const built = rows.map((row, index) => {
    const tr = document.createElement("tr");
    tr.append(cell(row.market || "—", "market"));

    const label = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tick-btn";
    button.textContent = row.ticker || row.symbol;
    const name = document.createElement("span");
    name.className = "tick-sub";
    name.textContent = row.note ? `${row.name || ""} (${row.note})` : (row.name || "");
    label.append(button, name);
    tr.append(label);

    const pct = Number.isFinite(row.progress) ? Math.round(row.progress * 100) : null;
    const meter = document.createElement("td");
    meter.className = "meter-cell";
    const wrap = document.createElement("span");
    wrap.className = "meter";
    const bar = document.createElement("span");
    bar.className = "meter-bar";
    const fill = document.createElement("span");
    fill.className = "meter-fill";
    fill.style.width = `${Math.min(100, Math.max(0, pct || 0))}%`;
    bar.append(fill);
    const num = document.createElement("span");
    num.className = "num";
    num.textContent = pct === null ? "—" : `${pct}%`;
    wrap.append(bar, num);
    meter.append(wrap);
    const held = Number.isFinite(row.held) && Number.isFinite(row.holdBars)
      ? ` Steady: the same reading held on ${row.held} of the last ${row.holdBars} sessions.`
      : "";
    meter.title = "Share of the bullish entry bar met: score 0.25 and drift t 1.96 "
                + "both reached is 100%. Not a probability." + held;
    tr.append(meter);

    const score = Number.isFinite(row.score)
      ? (row.score >= 0 ? "+" : "−") + Math.abs(row.score).toFixed(3) : "—";
    tr.append(cell(score, "num"));
    const t = Number.isFinite(row.significance)
      ? (row.significance >= 0 ? "+" : "−") + Math.abs(row.significance).toFixed(2) : "—";
    tr.append(cell(t, "num"));
    tr.append(cell(recentPrice(row.price, row.currency, row.priceHint)));

    const vol = document.createElement("td");
    vol.className = "vol";
    vol.textContent = Number.isFinite(row.turnoverPhp) ? compact(row.turnoverPhp, "PHP") : "—";
    tr.append(vol);

    if (row.chartable && row.chartSymbol) {
      tr.addEventListener("click", () => loadChart(row.chartSymbol));
    } else {
      tr.classList.add("no-chart");
    }
    return { row, tr, index };
  });
  table.append(tbody);

  const view = leaningView;
  const markets = [...new Set(rows.map((r) => r.market || ""))].sort();
  if (view.market && !markets.includes(view.market)) view.market = "";

  const controls = document.createElement("div");
  controls.className = "table-controls";
  const marketLabel = document.createElement("label");
  marketLabel.textContent = "Market ";
  const select = document.createElement("select");
  select.append(new Option(`All markets (${rows.length})`, ""));
  for (const m of markets) {
    const n = rows.filter((r) => (r.market || "") === m).length;
    select.append(new Option(`${m || "—"} (${n})`, m));
  }
  select.value = view.market;
  marketLabel.append(select);
  const searchLabel = document.createElement("label");
  searchLabel.textContent = "Find ";
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "ticker or name";
  search.value = view.text;
  search.setAttribute("autocomplete", "off");
  searchLabel.append(search);
  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "ghost";
  reset.textContent = "Reset";
  const csvBtn = document.createElement("button");
  csvBtn.type = "button";
  csvBtn.className = "ghost";
  csvBtn.textContent = "Download CSV";
  const count = document.createElement("span");
  count.className = "view-count";
  count.setAttribute("role", "status");
  controls.append(marketLabel, searchLabel, reset, csvBtn, count);

  const SORTS = {
    Market: ["market", 1, (r) => r.market || ""],
    Asset: ["asset", 1, (r) => (r.ticker || r.symbol || "").toUpperCase()],
    "Toward bullish": ["progress", -1, (r) => r.progress],
    Score: ["score", -1, (r) => r.score],
    "Drift t": ["significance", -1, (r) => r.significance],
  };
  const heads = [...hrow.children];
  heads.forEach((th) => {
    const spec = SORTS[th.textContent];
    if (!spec) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sort-btn";
    btn.textContent = th.textContent;
    btn.addEventListener("click", () => {
      if (view.key === spec[0]) view.dir = -view.dir;
      else { view.key = spec[0]; view.dir = spec[1]; }
      render();
    });
    th.textContent = "";
    th.append(btn);
    th.dataset.sort = spec[0];
  });

  let lastShown = [];
  function render() {
    const text = view.text.trim().toLowerCase();
    let shown = built.filter(({ row }) =>
      (!view.market || (row.market || "") === view.market) &&
      (!text || [row.ticker, row.symbol, row.name].some(
        (v) => String(v || "").toLowerCase().includes(text))));
    const spec = Object.values(SORTS).find((s) => s[0] === view.key);
    if (spec) {
      const get = spec[2];
      shown = shown.slice().sort((a, b) => {
        const x = get(a.row), y = get(b.row);
        const xMissing = x === null || x === undefined || Number.isNaN(x);
        const yMissing = y === null || y === undefined || Number.isNaN(y);
        if (xMissing || yMissing) return xMissing - yMissing;
        const c = typeof x === "string" ? x.localeCompare(y) : x - y;
        return (c * view.dir) || (a.index - b.index);
      });
    } else {
      shown = shown.slice().sort((a, b) => a.index - b.index);
    }
    lastShown = shown;
    tbody.textContent = "";
    shown.forEach(({ tr }) => tbody.append(tr));
    heads.forEach((th) => {
      if (!th.dataset.sort) return;
      const on = th.dataset.sort === view.key;
      th.setAttribute("aria-sort", on ? (view.dir > 0 ? "ascending" : "descending") : "none");
      th.firstChild.textContent = th.firstChild.textContent.replace(/ [▲▼]$/, "") +
        (on ? (view.dir > 0 ? " ▲" : " ▼") : "");
    });
    count.textContent = shown.length === built.length
      ? `${built.length} rows` : `Showing ${shown.length} of ${built.length} rows`;
    reset.hidden = !(view.key || view.market || view.text);
    csvBtn.disabled = !shown.length;
  }
  select.addEventListener("change", () => { view.market = select.value; render(); });
  search.addEventListener("input", () => { view.text = search.value; render(); });
  reset.addEventListener("click", () => {
    view.market = ""; view.text = ""; view.key = null; view.dir = 1;
    select.value = ""; search.value = "";
    render();
  });
  csvBtn.addEventListener("click", () => {
    const headers = [
      "Market", "Ticker", "Symbol", "Name", "Toward bullish (%)",
      "Score", "Drift t", "Price", "Currency", "Trading volume (PHP)",
    ];
    const dataRows = lastShown.map(({ row }) => [
      row.market || "",
      row.ticker || row.symbol || "",
      row.symbol || "",
      row.name || "",
      Number.isFinite(row.progress) ? Math.round(row.progress * 100) : "",
      Number.isFinite(row.score) ? Number(row.score.toFixed(4)) : "",
      Number.isFinite(row.significance) ? Number(row.significance.toFixed(2)) : "",
      Number.isFinite(row.price) ? row.price : "",
      row.currency || "",
      Number.isFinite(row.turnoverPhp) ? Math.round(row.turnoverPhp) : "",
    ]);
    downloadCsv("leaning-bullish.csv", headers, dataRows);
  });
  render();

  const tw = document.createElement("div");
  tw.className = "table-wrap";
  tw.append(table);
  card.append(controls, tw);
  return card;
}

function drawLeaningNote(payload) {
  if (!Array.isArray(payload.leaning) || (payload.pending && !payload.leaning.length)) {
    el.leaningNote.textContent = "Scanning — fills in when the next sweep finishes";
    return;
  }
  const n = (payload.leaning || []).length;
  const shelf = payload.ondoShelf;
  // What the Philippine sweep looked at, built server-side (`recent.ph_scan_line`)
  // so this note and the one above it print the same words about the same scan.
  // Absent on a table read from an older copy; the note simply says less then.
  const scan = payload.phScan ? " " + payload.phScan + "." : "";
  // The peso-volume floor covers Philippine stocks on this list too, so a name
  // missing here for volume is counted and named, not silently absent.
  const hiddenPh = payload.stats && payload.stats.Philippines && payload.stats.Philippines.hidden;
  const floor = hiddenPh
    ? " " + hiddenPh + " Philippine name" + (hiddenPh === 1 ? "" : "s") +
      " below ₱1,000,000 traded volume " + (hiddenPh === 1 ? "is" : "are") +
      " left out of this list and the tables above."
    : "";
  const shown = shelf
    ? " Only assets listed at app.ondo.finance are shown — a United States row needs an Ondo token, " +
      "and the funds are not on that shelf. Shelf read " +
      new Date(shelf.fetchedAt * 1000).toLocaleString() + "."
    : " The app.ondo.finance list could not be read, so nothing was filtered out of this list.";
  el.leaningNote.textContent =
    `${n} assets whose own chart reads Neutral but sit in the band that keeps a bullish label ` +
    "(score ≥ 0.15, drift t ≥ 1.0) without meeting the bar that earns one (score ≥ 0.25, t ≥ 1.96). " +
    "Only steady leans are listed: the drift has to clear 1.15, not just the 1.00 line, and the same " +
    "reading has to have held on at least 4 of the last 5 sessions — a name that flickers in and out of " +
    "the band is left out until it settles. Its own chart still shows the lean either way, so a name " +
    "missing here is not a name that changed. " +
    "Closest to Bullish first. Measured on saved history: about 1 in 4 of these became Bullish within " +
    "the next ~20 bars. Not a buy signal." + scan + floor + shown;
}

function drawBearishNote(payload) {
  if (payload.pending && !(payload.bearish && payload.bearish.length)) {
    el.bearishNote.textContent = "Scanning — this table fills in when the first sweep finishes";
    return;
  }
  if (!Array.isArray(payload.bearish)) {
    el.bearishNote.textContent = "This sweep did not record a bearish list.";
    return;
  }
  const n = payload.bearish.length;
  let when = "";
  if (payload.cached && payload.fetchedAt) {
    when = "Swept " + retrievedAt(payload.fetchedAt) + " — source offline · ";
  } else if (payload.checkedAt) {
    when = "Swept " + new Date(payload.checkedAt * 1000).toLocaleTimeString() + " · ";
  }
  const ph = payload.phBearish
    ? ""
    : " Philippine names join this list on the next Philippine sweep.";
  el.bearishNote.textContent =
    when + n + " bearish, from the same sweep as the table above. " +
    "A rising bond yield is not listed. Money-market and short-term funds are not listed." +
    ph;
}

async function loadRecent() {
  try {
    const payload = await requestJSON("/api/recent");
    el.recentGrid.textContent = "";
    // Nothing to draw before the first sweep lands; the note carries it.
    if (payload.rows && payload.rows.length) {
      el.recentGrid.append(drawRecent(payload, "rows", recentView));
    }
    drawRecentNote(payload);
    drawMarketStatus(payload);
    el.bearishGrid.textContent = "";
    if (payload.bearish && payload.bearish.length) {
      el.bearishGrid.append(drawRecent(payload, "bearish", bearishView));
    }
    drawBearishNote(payload);
    el.leaningGrid.textContent = "";
    if (payload.leaning && payload.leaning.length) {
      el.leaningGrid.append(drawLeaning(payload));
    }
    drawLeaningNote(payload);
  } catch (err) {
    // Same rule as the leaderboards: a failed refresh must not clear a table
    // already on screen.
    el.recentNote.textContent = "Recently bullish table unavailable — " + err.message;
    el.bearishNote.textContent = "Recently bearish table unavailable — " + err.message;
  }
}
