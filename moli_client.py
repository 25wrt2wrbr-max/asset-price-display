"""Moli browser client: runs Yahoo fetches from inside a Yahoo-origin page.

Split out of server.py; behaviour unchanged. See README "Layout".
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.parse
import crypto
import faults
import pse
import sourcestats


HERE = os.path.dirname(os.path.abspath(__file__))

MOLI = os.environ.get("MOLI_BIN") or shutil.which("moli") or os.path.expanduser("~/.local/bin/moli")

# A Yahoo page is required as the fetch origin (see module docstring) -- but only
# its *origin*, never its content. Yahoo's CORS allowlist is keyed on the Origin
# header, not the path, so `robots.txt` on finance.yahoo.com is an equally good
# origin page, and it is a two-line document instead of a two-megabyte dashboard.
# The quote page costs ~1.6 s to render before the API call inside it even
# starts; robots.txt costs ~0.1 s. The API answers HTTP 200 from either.
ORIGIN_PAGE = "https://finance.yahoo.com/robots.txt"
MOLI_TIMEOUT_MS = 25_000
SUBPROCESS_TIMEOUT = 40
WARM_BATCH_TIMEOUT_MS = 45_000
WARM_BATCH_SUBPROCESS_TIMEOUT = 75
BATCH_CONCURRENCY = 20
# The sweep needs a longer browser budget than one chart: a forty-symbol chunk
# answers in about ten seconds, but a chunk that has to be retried runs twice that.
BATCH_TIMEOUT_MS = 60_000
BATCH_SUBPROCESS_TIMEOUT = 90

# Runs inside the Moli-rendered Yahoo page. Returns a JSON *string* (Moli writes
# strings as plain text), which we parse on this side.
EVAL_SCRIPT = """(async () => {
  const r = await fetch(%s, { headers: { Accept: "application/json" } });
  return JSON.stringify({ status: r.status, body: await r.text() });
})()"""

# The same fetch, widened to a batch: one Moli run, many chart URLs. The
# browser launch and the Yahoo origin page are the fixed cost of every
# `moli_get` -- roughly a second each -- so a row warmer or US sweep that
# fetched twenty URLs per run spent most of its pass paying for Chrome, not
# for data. Fetching N URLs inside one page with a bounded worker pool
# (`BATCH_CONCURRENCY` in flight at a time) amortises that startup cost across
# the whole batch while keeping request concurrency identical to the old
# twenty-at-a-time chunks. Each result keeps its own HTTP status so a 404
# verdict is not promoted to an outage. One URL's transport failure (a rejected
# promise, a non-JSON body) is recorded per URL rather than failing the batch
# -- the caller decides, per symbol, whether what came back is an answer or an
# outage.
BATCH_EVAL_SCRIPT = """(async () => {
  const urls = %s;
  const limit = Math.max(1, Math.min(%d, urls.length));
  const results = {};
  let next = 0;
  async function worker() {
    while (next < urls.length) {
      const url = urls[next++];
      try {
        const r = await fetch(url, { headers: { Accept: "application/json" } });
        results[url] = { status: r.status, body: await r.text() };
      } catch (e) {
        results[url] = { status: 0, body: String(e && e.message || e) };
      }
    }
  }
  await Promise.all(Array.from({ length: limit }, worker));
  return JSON.stringify(results);
})()"""

# Moli fetches in flight, so shutdown can reap them instead of orphaning
# browser processes that hold the Moli profile lock.
_running: set[subprocess.Popen] = set()
_running_lock = threading.Lock()

# At most this many browsers at once (2026-11-24). Row hover prefetch, chart
# misses, compare lines, the warmer and the sweeps each start their own run,
# and nothing else bounded them: a burst could open a dozen Chromes and draw
# Yahoo's 429. Six leaves room for the PSE sweep's four socket workers
# (`pse.BATCH_WORKERS`) plus a chart click. A run waits for a slot up to its
# own wall budget, then fails as an outage like any other browser failure.
# `APD_MOLI_MAX` overrides.
MAX_BROWSERS = max(1, int(os.environ.get("APD_MOLI_MAX") or 6))
_browser_slots = threading.BoundedSemaphore(MAX_BROWSERS)

YAHOO_429_TRIP = 3
YAHOO_COOL_SEC = 90
_yahoo_cool_until = 0.0
_yahoo_429_streak = 0
_yahoo_cb_lock = threading.Lock()
_slot_wait_ms_total = 0.0
_slot_wait_ms_last = 0.0
_browsers_recycled = 0


class UpstreamError(RuntimeError):
    """Moli could not be run, or returned something unusable."""


class MoliBusy(UpstreamError):
    """Every browser slot stayed taken: a queue, not a broken browser."""


# What the last browser run did, kept in place (never rebound) so every module
# that imported it sees the same dict. `/api/health` reports it: whether Moli is
# *installed* says little; whether its last run worked is what the page needs.
health: dict = {"ok": None, "error": None, "at": None}


def moli_run(page: str, script: str,
             timeout_ms: int = MOLI_TIMEOUT_MS,
             wall_timeout: float = SUBPROCESS_TIMEOUT) -> str:
    """`_moli_run`, recording whether the browser leg is working."""
    start = time.monotonic()
    try:
        text = _moli_run(page, script, timeout_ms, wall_timeout)
    except MoliBusy:
        # A full queue says nothing about whether the browser works, so it
        # neither marks the browser broken nor counts as its failure.
        raise
    except UpstreamError as exc:
        health.update(ok=False, error=str(exc)[:200], at=time.time())
        sourcestats.record("Moli browser", failed=1,
                           seconds=time.monotonic() - start, error=str(exc))
        raise
    health.update(ok=True, error=None, at=time.time())
    sourcestats.record("Moli browser", ok=1, seconds=time.monotonic() - start)
    return text


# A Yahoo status that is an answer: 200, or a 404 "no such symbol" verdict.
# Anything else (429, 5xx, 0 for a fetch the page could not make) is the
# source not answering.
YAHOO_ANSWERS = (200, 404)


def _yahoo_url(url: str) -> bool:
    return sourcestats.name_for(url) == "Yahoo Finance"


def _note_yahoo_status(status: int) -> None:
    global _yahoo_429_streak, _yahoo_cool_until
    with _yahoo_cb_lock:
        if status in YAHOO_ANSWERS:
            _yahoo_429_streak = 0
            return
        if status == 429:
            _yahoo_429_streak += 1
            if _yahoo_429_streak >= YAHOO_429_TRIP:
                _yahoo_cool_until = time.time() + YAHOO_COOL_SEC
                sourcestats.record(
                    "Yahoo Finance", failed=1, error="429 circuit open %ss" % YAHOO_COOL_SEC)
        else:
            _yahoo_429_streak = 0


def _yahoo_cooling() -> bool:
    return time.time() < _yahoo_cool_until


def reset_yahoo_circuit() -> None:
    """Reset 429 circuit state (tests)."""
    global _yahoo_429_streak, _yahoo_cool_until, _slot_wait_ms_total, _slot_wait_ms_last
    global _browsers_recycled
    with _yahoo_cb_lock:
        _yahoo_429_streak = 0
        _yahoo_cool_until = 0.0
    _slot_wait_ms_total = 0.0
    _slot_wait_ms_last = 0.0
    _browsers_recycled = 0


def yahoo_cool_status() -> dict:
    """Circuit breaker and browser-slot wait stats for `/api/health`."""
    with _yahoo_cb_lock:
        cool_until = _yahoo_cool_until
        streak = _yahoo_429_streak
    return {
        "cooling": _yahoo_cooling(),
        "coolUntil": int(cool_until) if cool_until else None,
        "streak429": streak,
        "tripAfter": YAHOO_429_TRIP,
        "coolSeconds": YAHOO_COOL_SEC,
        "slotWaitMsTotal": round(_slot_wait_ms_total, 1),
        "slotWaitMsLast": round(_slot_wait_ms_last, 1),
        "browsersRecycled": _browsers_recycled,
        "maxBrowsers": MAX_BROWSERS,
    }


def _tally_yahoo(results: dict, seconds: float) -> None:
    """Count one Moli run's Yahoo URLs in `sourcestats` (other hosts are
    counted by the module that asked, so they are skipped here)."""
    ok = failed = 0
    error = None
    for url, (status, _body) in results.items():
        if not _yahoo_url(url):
            continue
        _note_yahoo_status(status)
        if status in YAHOO_ANSWERS:
            ok += 1
        else:
            failed += 1
            error = "HTTP %s" % status
    if ok or failed:
        sourcestats.record("Yahoo Finance", ok=ok, failed=failed,
                           seconds=seconds, error=error)



def kill_tree(popen: subprocess.Popen, sig: int = signal.SIGTERM) -> None:
    """Signal Moli and every process it started (one process group)."""
    try:
        os.killpg(popen.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass
    except OSError as exc:
        faults.note("moli kill_tree", exc)
        try:
            popen.send_signal(sig)
        except OSError:
            pass


def _moli_run(page: str, script: str,
              timeout_ms: int = MOLI_TIMEOUT_MS,
              wall_timeout: float = SUBPROCESS_TIMEOUT) -> str:
    """Run `script` inside the Moli-rendered `page`; return Moli's stdout.

    The single place a browser is shelled out to. Callers differ in the page that
    supplies the origin, in what they make of the output, and in how long they are
    willing to wait: both live above this. `moli_get` and `moli_fallback` want a
    `fetch` envelope, `moli_eval` wants whatever the script itself returned, and
    `moli_sweep` needs the longer budget the whole-universe socket takes.

    `timeout_ms` is Moli's own patience with the page; `wall_timeout` is this
    process's patience with Moli. The second is the one that fires if Moli hangs
    before it can honour the first, so it must stay comfortably larger.
    """
    if not os.path.exists(MOLI):
        raise UpstreamError(
            f"moli not found at {MOLI!r}. Install it from the latest release "
            "(see ~/.claude/skills/moli-webfetch/SKILL.md), or set MOLI_BIN."
        )
    global _slot_wait_ms_total, _slot_wait_ms_last
    slot_wait_start = time.monotonic()
    if not _browser_slots.acquire(timeout=wall_timeout):
        raise MoliBusy(
            f"moli busy: {MAX_BROWSERS} browser runs in flight for {wall_timeout}s")
    waited = (time.monotonic() - slot_wait_start) * 1000.0
    _slot_wait_ms_last = waited
    _slot_wait_ms_total += waited
    try:
        return _moli_run_slot(page, script, timeout_ms, wall_timeout)
    finally:
        _browser_slots.release()


def _moli_run_slot(page: str, script: str,
                   timeout_ms: int, wall_timeout: float) -> str:
    """`_moli_run`'s body, run while holding one of `MAX_BROWSERS` slots."""
    popen = subprocess.Popen(
        [MOLI, "fetch", "--eval", script,
         "--wait-until", "domcontentloaded",
         "--timeout", str(timeout_ms), page],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=HERE,
        # Its own process group, so a timeout or shutdown can stop the browser
        # Moli started too, not only Moli (see `kill_tree`).
        start_new_session=True,
    )
    with _running_lock:
        _running.add(popen)
    try:
        stdout, stderr = popen.communicate(timeout=wall_timeout)
        returncode = popen.returncode
    except subprocess.TimeoutExpired:
        global _browsers_recycled
        _browsers_recycled += 1
        kill_tree(popen, signal.SIGKILL)
        try:
            popen.communicate(timeout=5)
        except subprocess.TimeoutExpired as exc:
            # A child still holds the pipe; give up on its output rather than
            # leave this thread waiting on it for ever.
            faults.note("moli timeout reap", exc)
        raise UpstreamError(f"moli timed out after {wall_timeout}s")
    finally:
        with _running_lock:
            _running.discard(popen)

    if returncode != 0:
        detail = (stderr or stdout or "").strip()
        raise UpstreamError(f"moli exited {returncode}: {detail[:400] or 'no output'}")

    text = (stdout or "").strip()
    if not text:
        raise UpstreamError("moli produced no output")
    return text


def _check_yahoo_cool(urls: list[str]) -> None:
    if not any(_yahoo_url(u) for u in urls):
        return
    if _yahoo_cooling():
        raise UpstreamError(
            "Yahoo cooling after 429s (%ss); try disk or wait" % YAHOO_COOL_SEC)


def moli_get(url: str, page: str = ORIGIN_PAGE) -> tuple[int, str]:
    """Fetch `url` through Moli. Returns (http_status, response_body)."""
    _check_yahoo_cool([url])
    # A run that fails outright is the browser's failure, tallied as
    # "Moli browser" in `moli_run`: Yahoo was never asked, so it is not
    # blamed. Only the statuses Yahoo itself sent are counted for it.
    start = time.monotonic()
    text = moli_run(page, EVAL_SCRIPT % json.dumps(url))
    try:
        outer = json.loads(text)
        answer = int(outer["status"]), outer["body"]
    except (ValueError, KeyError, TypeError) as exc:
        raise UpstreamError(f"unexpected moli output ({exc}): {text[:200]}")
    _tally_yahoo({url: answer}, time.monotonic() - start)
    return answer


def moli_batch_get(urls: list[str],
                   page: str = ORIGIN_PAGE,
                   concurrency: int = BATCH_CONCURRENCY) -> dict[str, tuple[int, str]]:
    """Fetch several same-origin URLs in one Moli run; `{url: (status, body)}`.

    The row warmer's and US sweep's Yahoo leg. One browser launch, one origin
    page, N fetches (at most `concurrency` in flight at once) -- the per-URL
    contract matches `moli_get`'s, so a caller can treat each result exactly as
    it would have treated that URL fetched alone: a 404 with a `chart.error`
    body is still a verdict about the symbol, still not promoted to an outage
    by its neighbours.

    A URL whose fetch *rejected* in the page -- connection refused, TLS failure
    -- comes back with status 0 rather than disappearing from the dict, so the
    caller can tell "Yahoo said no" from "the wire said nothing". The run as a
    whole can still fail (`UpstreamError` from `moli_run`): Moli down, the
    envelope never arriving. That is the batch-fatal case, and it is the
    caller's to handle -- every URL it wanted is an outage at once, which is
    the same sentence `moli_get` would have spoken one URL at a time.

    The timeout scales with the URL count so a large sweep batch has enough
    headroom while a small batch keeps the existing `WARM_BATCH_*` budget.
    """
    if not urls:
        return {}
    _check_yahoo_cool(urls)
    timeout_ms = max(WARM_BATCH_TIMEOUT_MS, 25_000 + len(urls) * 500)
    wall_timeout = max(WARM_BATCH_SUBPROCESS_TIMEOUT, timeout_ms / 1000.0 + 30.0)
    start = time.monotonic()
    text = moli_run(page, BATCH_EVAL_SCRIPT % (json.dumps(urls), max(1, int(concurrency))),
                    timeout_ms, wall_timeout)
    try:
        outer = json.loads(text)
        out = {}
        for url in urls:
            entry = outer[url]
            out[url] = (int(entry["status"]), entry["body"])
    except (ValueError, KeyError, TypeError) as exc:
        raise UpstreamError(f"unexpected moli batch output ({exc}): {text[:200]}")
    _tally_yahoo(out, time.monotonic() - start)
    return out


def moli_eval(page: str, script: str) -> str:
    """Run a caller's own script in a Moli-rendered `page`, returning its output.

    Unlike `moli_get` this does not unwrap a `(status, body)` envelope, because
    the caller's script speaks its own protocol -- `pse.py` drives a websocket,
    not a fetch -- and parses its own reply.
    """
    return moli_run(page, script)


def moli_sweep(page: str, script: str) -> str:
    """`moli_eval` with the whole-universe budget (see `BATCH_TIMEOUT_MS`).

    The same browser path, given longer: a sweep chunk is one deliberately
    long-lived socket that has to outlive the several seconds a hundred-odd frames
    take to arrive, so it cannot share the per-chart timeout without one of the two
    being wrong.
    """
    return moli_run(page, script, BATCH_TIMEOUT_MS, BATCH_SUBPROCESS_TIMEOUT)


def moli_fallback(url: str) -> tuple[int, str]:
    """`(status, body)` for a non-Yahoo URL, via Moli.

    Binance and CoinGecko answer an ordinary HTTP client and send `*` CORS
    headers, so `crypto.py` tries plain HTTP first. This exists only as a safety
    net -- and it earns its keep, because CoinGecko's rate limiter answers a
    browser navigation with a 429 body, which is exactly what we want to detect.

    Moli is pointed at a page on the target's own host where there is one, so
    the fetch stays same-origin; otherwise a throwaway page on that host.
    """
    split = urllib.parse.urlsplit(url)
    return moli_get(url, page=f"{split.scheme}://{split.netloc}/")
