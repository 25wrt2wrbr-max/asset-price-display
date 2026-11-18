"""Moli browser client: runs Yahoo fetches from inside a Yahoo-origin page.

Split out of server.py; behaviour unchanged. See README "Layout".
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import time
import urllib.parse
import crypto
import pse


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
# `moli_get` -- roughly a second each -- so a row warmer that fetched one URL
# per run spent most of its pass paying for Chrome, not for data. Fetching N
# URLs inside the page they share amortises that cost N-fold: the page is
# already loaded, the fetches are same-origin like `EVAL_SCRIPT`'s, and each
# result keeps its own HTTP status so a 404 verdict is not promoted to an
# outage. One URL's transport failure (a rejected promise, a non-JSON body)
# is recorded per URL rather than failing the batch -- the caller decides,
# per symbol, whether what came back is an answer or an outage.
BATCH_EVAL_SCRIPT = """(async () => {
  const urls = %s;
  const results = {};
  await Promise.all(urls.map(async (url) => {
    try {
      const r = await fetch(url, { headers: { Accept: "application/json" } });
      results[url] = { status: r.status, body: await r.text() };
    } catch (e) {
      results[url] = { status: 0, body: String(e && e.message || e) };
    }
  }));
  return JSON.stringify(results);
})()"""

# Moli fetches in flight, so shutdown can reap them instead of orphaning
# browser processes that hold the Moli profile lock.
_running: set[subprocess.Popen] = set()
_running_lock = threading.Lock()


class UpstreamError(RuntimeError):
    """Moli could not be run, or returned something unusable."""


# What the last browser run did, kept in place (never rebound) so every module
# that imported it sees the same dict. `/api/health` reports it: whether Moli is
# *installed* says little; whether its last run worked is what the page needs.
health: dict = {"ok": None, "error": None, "at": None}


def moli_run(page: str, script: str,
             timeout_ms: int = MOLI_TIMEOUT_MS,
             wall_timeout: float = SUBPROCESS_TIMEOUT) -> str:
    """`_moli_run`, recording whether the browser leg is working."""
    try:
        text = _moli_run(page, script, timeout_ms, wall_timeout)
    except UpstreamError as exc:
        health.update(ok=False, error=str(exc)[:200], at=time.time())
        raise
    health.update(ok=True, error=None, at=time.time())
    return text


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
    popen = subprocess.Popen(
        [MOLI, "fetch", "--eval", script,
         "--wait-until", "domcontentloaded",
         "--timeout", str(timeout_ms), page],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=HERE,
    )
    with _running_lock:
        _running.add(popen)
    try:
        stdout, stderr = popen.communicate(timeout=wall_timeout)
        returncode = popen.returncode
    except subprocess.TimeoutExpired:
        popen.kill()
        popen.communicate()
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


def moli_get(url: str, page: str = ORIGIN_PAGE) -> tuple[int, str]:
    """Fetch `url` through Moli. Returns (http_status, response_body)."""
    text = moli_run(page, EVAL_SCRIPT % json.dumps(url))
    try:
        outer = json.loads(text)
        return int(outer["status"]), outer["body"]
    except (ValueError, KeyError, TypeError) as exc:
        raise UpstreamError(f"unexpected moli output ({exc}): {text[:200]}")


def moli_batch_get(urls: list[str],
                   page: str = ORIGIN_PAGE) -> dict[str, tuple[int, str]]:
    """Fetch several same-origin URLs in one Moli run; `{url: (status, body)}`.

    The row warmer's Yahoo leg. One browser launch, one origin page, N fetches
    -- the per-URL contract matches `moli_get`'s, so a caller can treat each
    result exactly as it would have treated that URL fetched alone: a 404 with
    a `chart.error` body is still a verdict about the symbol, still not
    promoted to an outage by its neighbours.

    A URL whose fetch *rejected* in the page -- connection refused, TLS failure
    -- comes back with status 0 rather than disappearing from the dict, so the
    caller can tell "Yahoo said no" from "the wire said nothing". The run as a
    whole can still fail (`UpstreamError` from `moli_run`): Moli down, the
    envelope never arriving. That is the batch-fatal case, and it is the
    caller's to handle -- every URL it wanted is an outage at once, which is
    the same sentence `moli_get` would have spoken one URL at a time.

    Runs on the longer batch budget (`WARM_BATCH_*`): twenty fetches inside one
    page take longer than one, and a wall timeout that fit a single chart
    would kill a healthy batch's last few responses.
    """
    text = moli_run(page, BATCH_EVAL_SCRIPT % json.dumps(urls),
                    WARM_BATCH_TIMEOUT_MS, WARM_BATCH_SUBPROCESS_TIMEOUT)
    try:
        outer = json.loads(text)
        out = {}
        for url in urls:
            entry = outer[url]
            out[url] = (int(entry["status"]), entry["body"])
        return out
    except (ValueError, KeyError, TypeError) as exc:
        raise UpstreamError(f"unexpected moli batch output ({exc}): {text[:200]}")


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
