/* Source status page: draws /api/sources, re-read every 30 s. */
"use strict";

const STATUS_POLL_MS = 30000;

function ago(seconds, now) {
  if (seconds == null) return "never";
  const s = Math.max(0, Math.round(now - seconds));
  if (s < 60) return s + " s ago";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " d ago";
}

function tally(t) {
  if (!t || !t.calls) return "—";
  const pct = (t.failRate * 100).toFixed(t.failRate && t.failRate < 0.01 ? 1 : 0);
  return t.calls + (t.calls === 1 ? " call, " : " calls, ") + pct + "% failed";
}

function secs(v) {
  return v == null ? "—" : v.toFixed(v < 10 ? 2 : 1) + " s";
}

function cell(text, cls) {
  const td = document.createElement("td");
  td.textContent = text;
  if (cls) td.className = cls;
  return td;
}

function stateWord(state) {
  return { ok: "Answering", failing: "Failing", unused: "Not used yet" }[state] || state;
}

function draw(payload) {
  const now = payload.now;
  const body = document.getElementById("statusRows");
  body.replaceChildren();
  let failing = 0;
  for (const row of payload.sources) {
    if (row.state === "failing") failing += 1;
    const tr = document.createElement("tr");
    tr.className = "state-" + row.state;
    tr.append(cell(row.source));
    tr.append(cell(stateWord(row.state), "state"));
    tr.append(cell(ago(row.lastOkAt, now)));
    const fail = cell(row.lastFailAt == null ? "never" : ago(row.lastFailAt, now));
    if (row.lastError) fail.title = row.lastError;
    tr.append(fail);
    tr.append(cell(tally(row.today)));
    tr.append(cell(tally(row.week)));
    tr.append(cell(tally(row.month)));
    tr.append(cell(secs(row.month && row.month.avgSeconds)));
    tr.append(cell(secs(row.month && row.month.slowestSeconds)));
    body.append(tr);
    if (row.state === "failing" && row.lastError) {
      const why = document.createElement("tr");
      why.className = "status-why";
      const td = cell("Last failure: " + row.lastError);
      td.colSpan = 9;
      why.append(td);
      body.append(why);
    }
  }
  document.getElementById("statusSummary").textContent = failing
    ? failing + (failing === 1 ? " source is" : " sources are") + " failing right now."
    : "Every source that has been used is answering.";
}

async function refresh() {
  try {
    const res = await fetch("/api/sources", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    draw(await res.json());
  } catch (err) {
    document.getElementById("statusSummary").textContent =
      "Could not reach the local server (" + err.message + ").";
  }
}

refresh();
setInterval(() => { if (!document.hidden) refresh(); }, STATUS_POLL_MS);
let statusShownAt = 0;
document.addEventListener("visibilitychange", () => {
  // Quick tab switching re-reads at most once every ten seconds.
  if (document.hidden || Date.now() - statusShownAt < 10000) return;
  statusShownAt = Date.now();
  refresh();
});
