"""HTTP handler and entry point for the page server.

Split out of server.py; behaviour unchanged. See README "Layout".
"""

from __future__ import annotations

import labpath  # noqa: F401  (puts lab/ on sys.path)

import datetime as dt
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import faults
import live_quote
import bullish
import crypto
import cryptobull
import diskcache
import markets
import ondo
import phfunds
import pse
import rates
import recent
import research_judgment
import sourcestats

import server as S
import moli_client
import netwatch


class Handler(SimpleHTTPRequestHandler):
    server_version = "AssetPriceDisplay/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=S.HERE, **kwargs)

    # -- helpers -----------------------------------------------------------

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The reader hung up before the answer landed -- a superseded
            # poll the page aborted, a tab closing mid-fetch. The answer
            # has nowhere to go and nothing about the data was wrong, so
            # drop it quietly instead of raising (which, on this dead
            # socket, would only print a second traceback from fail()).
            self.close_connection = True

    def fail(self, status: int, message: str) -> None:
        self.send_json(status, {"error": message})

    # The only files this server hands out. It used to serve the whole project
    # folder, source and cache included; the page needs just these.
    PUBLIC_PAGES = ("/", "/index.html", "/jpy-php.html", "/status.html")

    def app_page(self):
        # Multiple project copies can run at the same localhost address. Dates
        # alone cannot identify their scripts (a restored copy may be older).
        root = Path(self.directory)
        def version(match):
            asset = match[2]
            digest = hashlib.sha256((root / asset).read_bytes()).hexdigest()[:16]
            return f'{match[1]}="{asset}?v={digest}"'

        html = (root / "index.html").read_text(encoding="utf-8")
        body = re.sub(r'(src|href)="(static/[\w.-]+\.(?:js|css))"', version, html).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return io.BytesIO(body)

    def send_head(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.app_page()
        is_asset = path.startswith("/static/") and not path.endswith("/")
        if path not in self.PUBLIC_PAGES and not is_asset:
            self.send_error(404, "Not found")
            return None
        return super().send_head()

    def refuse(self) -> None:
        """Answer a probe path with a bare 404: the status line and nothing
        else. `send_response_only` adds no headers, so even the Server line
        that names Python is withheld."""
        self.send_response_only(404)
        self.end_headers()

    def log_message(self, fmt, *args):  # quieter, one line per request
        sys.stderr.write("  %s\n" % (fmt % args))

    def log_request(self, code="-", size="-"):
        # Unknown paths get probed constantly from outside this project
        # (`/health`, then `/v1/models` — background machinery that mistook
        # this port for some other service's). A 404 here is that noise, not
        # a reader's broken link, so it takes no console space; every
        # request this server actually serves still logs.
        if code == 404:
            return
        self.log_message('"%s" %s %s', self.requestline, str(code), str(size))

    def log_error(self, fmt, *args):
        # The 404 half of the pair above (`code 404, message File not
        # found`), dropped for the same reason.
        if args and args[0] == 404:
            return
        self.log_message(fmt, *args)

    # -- routes ------------------------------------------------------------

    def do_GET(self):
        route = urllib.parse.urlparse(self.path)
        # Probes for services this is not (`/health`, `/v1/models` -- the
        # latter an LLM-server convention) get a bare refusal: a status line
        # and nothing after it. No health payload, no model list, no error
        # page, not even the Server header -- whoever is asking learns
        # nothing about what runs here.
        if route.path in ("/health", "/v1/models"):
            return self.refuse()
        try:
            if route.path == "/api/chart":
                return self.api_chart(route.query)
            if route.path == "/api/quote":
                return self.api_quote(route.query)
            if route.path == "/api/research-judgment":
                return self.api_research_judgment(route.query)
            if route.path == "/api/search":
                return self.api_search(route.query)
            if route.path == "/api/top":
                return self.api_top()
            if route.path == "/api/bullish":
                return self.api_bullish()
            if route.path == "/api/cryptobull":
                return self.api_cryptobull()
            if route.path == "/api/recent":
                return self.api_recent()
            if route.path == "/api/watch":
                return self.send_json(200, {"ok": True, "watchlist": S.saved_watchlist()})
            if route.path == "/api/sources":
                # Each outside source's last answer, failures and speed
                # (`sourcestats`); `status.html` draws it.
                return self.send_json(200, {"ok": True, **sourcestats.snapshot()})
            if route.path == "/api/health":
                return self.send_json(200, {
                    "ok": True,
                    "moli": S.MOLI,
                    "moliFound": os.path.exists(S.MOLI),
                    # Whether the last browser run worked, and why not if it
                    # did not: an installed Moli can still be failing.
                    "moliLast": dict(moli_client.health),
                    # The offline fallback is only as good as what is on disk,
                    # so say where that is and how much of it exists.
                    "cacheDir": diskcache.dir(),
                    "cacheEntries": diskcache.count(),
                    # What the connectivity watch last saw, and how many times
                    # it has caught the wire coming back -- the two facts that
                    # explain why the cache holds what it holds right now.
                    "online": netwatch._watch_online,
                    "reconnections": S._refresh_epoch,
                    # What the warmer has been *told* to care about: the
                    # declared union, so a reader can see whether the list the
                    # server holds is the list they are looking at.
                    "watchlist": S.union_watchlist(),
                })
        except (S.UpstreamError, pse.PseError) as exc:
            return self.fail(502, str(exc))
        except Exception as exc:  # never let the page see a traceback
            return self.fail(500, f"{type(exc).__name__}: {exc}")
        return super().do_GET()

    def read_json(self):
        """Parse the request body as JSON, capped like everything a browser
        sends here; raises ValueError (the route's 400) on size or syntax.

        The cap is a memory guard, not a product limit: the only body this
        server reads is a declared watchlist, and that list has no length
        ceiling any more (see `_clean_watch`). Two megabytes holds ten thousand
        `{symbol, name}` pairs -- far past any list a person curates -- while
        still refusing to buffer a stream that never ends.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("bad Content-Length")
        if length > 2 * 1024 * 1024:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_POST(self):
        route = urllib.parse.urlparse(self.path)
        if route.path != "/api/watch":
            return self.fail(404, "Unknown endpoint")
        try:
            body = self.read_json()
        except (ValueError, UnicodeDecodeError) as exc:
            return self.fail(400, f"Expected a JSON list: {exc}")
        # Accept the page's own shape (an array of {symbol, name}) directly;
        # wrapped is tolerated too, since `_clean_watch` reads either spelling.
        symbols = body if isinstance(body, list) else body.get("symbols") \
            if isinstance(body, dict) else None
        if symbols is None:
            return self.fail(400, "Expected a JSON array of {symbol, name}")
        # A declared list may legitimately be empty -- the reader deleted every
        # row -- and replaces the server's list so removed symbols stop warming.
        S.record_watchlist(symbols)
        return self.send_json(200, {"ok": True, "watchlist": S.union_watchlist()})

    def api_chart(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        symbol = (params.get("symbol") or [""])[0].strip()
        span = (params.get("range") or ["3mo"])[0]
        interval = (params.get("interval") or ["1d"])[0]

        if not symbol:
            return self.fail(400, "Missing ?symbol=")
        if len(symbol) > 32:
            return self.fail(400, "Symbol too long")
        if span not in S.ALLOWED_RANGES:
            return self.fail(400, f"Unsupported range {span!r}")
        if interval not in S.ALLOWED_INTERVALS:
            return self.fail(400, f"Unsupported interval {interval!r}")

        try:
            data = S.chart_data(symbol, span, interval)
        except (LookupError, pse.PseNotFound) as exc:
            return self.fail(404, str(exc))
        return self.send_json(200, data)

    def api_quote(self, query: str) -> None:
        """Newest price only, for the chart's fast clock (see `live_quote`)."""
        symbol = (urllib.parse.parse_qs(query).get("symbol") or [""])[0].strip()
        if not symbol or len(symbol) > 32:
            return self.fail(400, "Missing or invalid ?symbol=")
        if not live_quote.is_yahoo_symbol(symbol):
            return self.fail(404, "No fast quote for this symbol")
        try:
            return self.send_json(200, live_quote.quote(symbol))
        except LookupError as exc:
            return self.fail(404, str(exc))

    def api_research_judgment(self, query: str) -> None:
        """Separate request: slow research inputs never hold up chart loading."""
        params = urllib.parse.parse_qs(query)
        symbol = (params.get("symbol") or [""])[0].strip().upper()
        if not symbol or len(symbol) > 32:
            return self.fail(400, "Missing or invalid ?symbol=")
        try:
            # A full year is needed to reconstruct the first monthly signal's
            # window even at month end. The chart route preserves actual source.
            data = S.chart_data(symbol, "3mo" if pse.is_pse_symbol(symbol) else "1y", "1d")
            def fetch_pse_snapshot(name):
                def produce():
                    rows = pse.history_many([name], count=pse.MAX_BARS).get(name, [])
                    if not rows:
                        raise S.UpstreamError("Philippine stock history unavailable")
                    return {"rows": rows}
                return S.cached(f"research:pse-history:v1:{name}", produce, ttl=3600)
            def fetch_pse(name):
                return fetch_pse_snapshot(name)["rows"]
            refs = research_judgment.references()
            def fetch_pse_peers():
                # One shared, bounded snapshot for all stocks, never a new
                # market-wide browser sweep per row or per concurrent request.
                def produce():
                    rows = pse.history_many(sorted(refs["pse_universe"]), count=120)
                    if len(rows) < max(11, int(len(refs["pse_universe"]) * .8)):
                        raise S.UpstreamError("Philippine peer history incomplete")
                    return {"rows": rows}
                snapshot = S.cached("research:pse-peers:v1", produce, ttl=3600)
                # Never silently reuse an outage fallback as a fresh peer rank.
                return {} if snapshot.get("cached") else snapshot["rows"]
            import datetime as dt
            now = dt.datetime.now(dt.timezone.utc)
            answer = research_judgment.evaluate(symbol, data, refs, now, fetch_pse,
                                                fetch_pse_peers)
            answer = S.retry_sparse_research(symbol, data, answer, refs, now, fetch_pse,
                                           fetch_pse_peers)
            if not any(answer[d].get("status") == "signaled" for d in ("bullish", "bearish")):
                try:
                    now = dt.datetime.now(dt.timezone.utc)
                    if pse.is_pse_symbol(symbol):
                        history = fetch_pse_snapshot(symbol)
                        points = [{"t": row[0], "c": row[4]} for row in history["rows"] if len(row) > 4]
                        zone = "Asia/Manila"
                    else:
                        history = S.chart_data(symbol, "2y", "1d")
                        if (history.get("source") != data.get("source") or
                                str(history.get("symbol", "")).upper() != str(data.get("symbol", "")).upper()):
                            raise S.UpstreamError("Long history resolved to a different asset or source")
                        points = history.get("points") or []
                        source = history.get("source")
                        zone = ("UTC" if source == "Binance" else
                                history.get("timezone") or refs.get("timezones", {}).get(symbol))
                    answer["fallback"] = research_judgment.historical_baseline(points, symbol, zone, now)
                    if history.get("cached"):
                        answer["fallback"]["cached"] = True
                        answer["fallback"]["fetchedAt"] = history.get("fetchedAt")
                except Exception as exc:
                    faults.note("research fallback history", exc)
                    answer["fallback"] = research_judgment.unavailable("Asset history could not be retrieved")
        except Exception as exc:
            faults.note("research judgment", exc)
            # Network failures and absent research files are not market calls.
            answer = {"market": None, "bullish": research_judgment.unavailable("Research data or source unavailable"),
                      "bearish": research_judgment.unavailable("Research data or source unavailable"),
                      "note": "Historical research hit rates are not individual probabilities."}
        return self.send_json(200, answer)

    def api_top(self) -> None:
        """Both most-traded tables, plus the cross rate their dollar column uses.

        No parameters, so there is nothing to validate -- the shape of what comes
        back is fixed by `markets`. Each market carries its own `error`, so one
        section being unreachable still serves the other's table; see
        `markets.tables`.
        """
        # `tables_payload` is what the prewarm thread and the row warmer read
        # as well, so a browser's tables and the warmed ones are the same call
        # through the same key; the helper's docstring carries the caching and
        # stamping rationale.
        return self.send_json(200, S.tables_payload())

    def api_bullish(self) -> None:
        """The bullish table, as the background sweeper last left it.

        No fetch happens here and no parameters are read: the answer is whatever
        `bullish_state` holds, which is why this route returns in milliseconds
        whether the sweep behind it took thirty-five seconds or failed outright.
        A failure is reported in the payload rather than as a status, because the
        table is a section of the page and a section that cannot load should say
        so in place (see `markets.tables` for the same convention).
        """
        return self.send_json(200, S.bullish_state())

    def api_cryptobull(self) -> None:
        """The bullish crypto table, cached and stamped like the leaderboards.

        Unlike `/api/bullish` this *can* fetch on demand -- the crypto scan is
        seconds of plain HTTPS, not a half-minute browser sweep -- so the route
        is `cryptobull_payload`, the same `cached` path the prewarm pass reads.
        A cold miss is answered by the one scan already in flight rather than
        starting a second, and an outage serves the last good copy stamped
        `cached`, dated on the page like every other fallback.
        """
        return self.send_json(200, S.cryptobull_payload())

    def api_recent(self) -> None:
        """The recently-bullish table, as the background sweeper last left it.

        No fetch happens here and no parameters are read, for the reason
        `/api/bullish` gives: the United States leg is fifty tickers' worth of
        browser-fetched bars, and a reader should not pay for that. The answer
        is whatever the sweeper produced, dated.
        """
        return self.send_json(200, S.recent_state())

    def api_search(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        text = (params.get("q") or [""])[0].strip()
        if not text:
            return self.send_json(200, {"results": []})
        if len(text) > 64:
            return self.fail(400, "Query too long")

        quoted = urllib.parse.quote(text, safe="")
        url = (f"https://{S.SEARCH_HOST}/v1/finance/search?q={quoted}"
               f"&quotesCount=10&newsCount=0&enableFuzzyQuery=false")

        def produce():
            # A refused search is an *empty* answer here, not a failure of the
            # whole route. Yahoo 500s some queries outright (see
            # `probe_ticker`), and raising used to abort the supplements below
            # with it, so a reader typing "vtv" got an error page instead of a
            # row and a Philippine fund query got nothing when the index
            # hiccuped. `moli_get` failing at the transport level still raises:
            # that is the browser, not the index.
            quotes = []
            status, body = S.moli_get(url)
            if status < 400:
                try:
                    quotes = json.loads(body).get("quotes") or []
                except ValueError:
                    quotes = []           # a body that is not the JSON it claims
            results = []
            seen = set()
            for quote in quotes:
                symbol = quote.get("symbol")
                if not symbol or quote.get("quoteType") not in S.KEEP_QUOTE_TYPES:
                    continue
                seen.add(symbol.upper())
                results.append({
                    "symbol": symbol,
                    "name": quote.get("longname") or quote.get("shortname") or symbol,
                    "exchange": quote.get("exchDisp") or "",
                    "type": quote.get("quoteType") or "",
                })

            # Nothing from Yahoo at all, and the query is itself a ticker: ask
            # the chart route whether that symbol exists. This is what finds
            # VTV, whose every search query the index answers with HTTP 500 --
            # and what keeps a *dead* ticker denied, since only a symbol the
            # chart route draws becomes a row.
            if not results:
                probed = S.probe_ticker(text)
                if probed:
                    results.append(probed)
                    seen.add(probed["symbol"].upper())

            # Yahoo has no listing for some coins at all -- the real Jupiter
            # among them -- so no query can surface them. Add what the coin
            # index knows and Yahoo does not. A ticker both sources report
            # becomes one row, described by the coin rather than by Yahoo, so
            # the venue matches where the bars will actually come from.
            for match in crypto.search_coins(text):
                key = match["symbol"].upper()
                if key not in seen:
                    results.append(match)
                    seen.add(key)
                    continue
                # A ticker both sources report becomes one row, described by
                # what the coin is rather than by Yahoo's venue tag: "CCC" is
                # where the dead token trades, and naming it was part of what
                # made search misleading.
                for row in results:
                    if row["symbol"].upper() == key:
                        row["name"] = match["name"]
                        row["exchange"] = match["exchange"]
                        break

            # Yahoo carries no PSE equities, so every Philippine listing the
            # search box should offer has to be added from the PSE universe.
            # Same de-dupe as the coins above, though a `PSE:`-prefixed symbol
            # can never collide with a Yahoo one.
            for match in pse.search_stocks(text):
                key = match["symbol"].upper()
                if key not in seen:
                    results.append(match)
                    seen.add(key)

            # No fund Yahoo lists, and no fund a reader can find by any query
            # this project asks it: a Philippine fund has no ticker at all.
            # The funds this page charts are offered from the one table that
            # knows them, so a reader can reach one by name ("health care") as
            # well as by the code a row prints (`BPI-HLTH`). A `FUND:` symbol
            # cannot collide with a Yahoo one.
            for match in phfunds.search_funds(text):
                key = match["symbol"].upper()
                if key not in seen:
                    results.append(match)
                    seen.add(key)

            # Nor tokens: OUSG is in no Yahoo answer at all -- `/search?q=ousg`
            # returns an empty list, `/lookup?query=ousg` reports `total: 0`,
            # and every chart spelling is a 404 (measured 2026-11-02, see
            # `ondo.py`) -- even though the page charts it from the contract's
            # on-chain price. The row carries the `ONDO:` prefix, so it cannot
            # collide with a Yahoo symbol.
            for match in ondo.search_tokens(text):
                key = match["symbol"].upper()
                if key not in seen:
                    results.append(match)
                    seen.add(key)

            # A no-dollar-leg cross Yahoo will serve by name ("krwphp" finds
            # `KRWPHP=X`) but hides from every query that names one leg alone
            # ("krw" lists six other won pairs, none of them the peso cross).
            # The supplement fires on the exact needle -- "PHP" and "php" hide
            # the same crosses -- and its rows join the pool before the sort,
            # where `relevance` files them honestly: for "krw" the cross ranks
            # with the other won pairs (its ticker starts with the query),
            # while "peso" leaves it among the remainder, which is still
            # showing it where Yahoo showed nothing. De-duplicated against
            # `seen`, so a cross Yahoo did list is never described twice.
            needle = text.lower()
            for row in S.fx_search_extra(needle):
                key = row["symbol"].upper()
                if key not in seen:
                    results.append(row)
                    seen.add(key)

            # The United States Treasury futures. Yahoo's index holds "zb" and
            # "t-bond" but not the words a reader uses: "30-year treasury bond"
            # answers with six Korean ETFs and "long bond" with three KB funds,
            # because the contract's own Yahoo name ("U.S. Treasury Bond
            # Futures,Dec-") contains neither "30" nor "year". So the curve
            # `rates.py` knows is offered here, where a query can reach it by
            # tenor, by desk name ("the long bond") or by ticker. Yahoo-shaped
            # rows, de-duplicated against `seen` like every other supplement.
            rate_rows = rates.search_contracts(text)
            rate_order = {symbol.upper(): index for index, symbol
                          in enumerate(rates.named_contracts(text))}
            for row in rate_rows:
                key = row["symbol"].upper()
                if key not in seen:
                    results.append(row)
                    seen.add(key)

            # Float an exact hit above the noise: Yahoo answers "pepe" with
            # seven low-cap variants and omits the real coin, so appending it
            # would bury it. Ties keep each source's own order (sort is stable).
            pse_rows = [r for r in results if pse.is_pse_symbol(r["symbol"])]
            yahoo_rows = [r for r in results if not pse.is_pse_symbol(r["symbol"])]
            if pse.market_query(text):
                # "philippines" is not a name any PSE listing contains, so
                # `relevance` would file every PSE row behind Yahoo's, and
                # Yahoo's answer here is `EPHE` plus a wall of `^NQPHLMT` index
                # codes. A query that names the market wants the market's
                # securities, so those rows go first and Yahoo's follow.
                results = pse_rows + yahoo_rows
            elif pse_rows and min((S.relevance(r, needle) for r in yahoo_rows),
                                  default=99) > 0:
                # No Yahoo row answers this query by ticker, only by resembling
                # it -- and for a Philippine company those rows are foreign and
                # OTC shells. "pldt" is really answered by `PHI` (a NYSE
                # closed-end fund), `PLDTX`, `PLO.HM`, `PLO.SG`... while the
                # Manila listing sits seventh. So a PSE row that matches leads,
                # unless Yahoo's best is an exact ticker hit -- which is how
                # "tel" still puts TE Connectivity first, with `PSE:TEL` next.
                results = (sorted(pse_rows, key=lambda r: S.relevance(r, needle))
                           + sorted(yahoo_rows, key=lambda r: S.relevance(r, needle)))
            else:
                results.sort(key=lambda row: S.relevance(row, needle))
            # A fund query has no competitor worth deferring to. Yahoo's index
            # has never heard of a Philippine fund, so its rows for "alfm" are
            # `ALFMF` (an OTC shell) and for "pera" a wall of Perak and Peraso
            # -- near-misses dressed as answers. So the funds whose *code*
            # answers the query lead, unless another row is an exact ticker hit
            # (which is what the reader typed, and outranks any supplement).
            # Matching the code rather than the name is deliberate: "health"
            # should still find the health-care stocks first, while "pera"
            # and "alfm" are names only the funds answer.
            words = [w for w in re.split(r"[^a-z0-9]+", needle) if w]
            def answers_by_code(row):
                code = row["symbol"].split(":", 1)[-1].lower()
                return bool(words) and all(w in code for w in words)
            lead = [r for r in results
                    if phfunds.is_fund_symbol(r["symbol"])
                    and answers_by_code(r)]
            exact_elsewhere = any(S.relevance(r, needle) == 0 for r in results
                                  if not phfunds.is_fund_symbol(r["symbol"]))
            if lead and not exact_elsewhere:
                rest = [r for r in results if r not in lead]
                results = (sorted(lead, key=lambda r: S.relevance(r, needle))
                           + rest)

            # A query that *names* a Treasury contract -- "zb", "30-year
            # treasury bond", "long bond", "t-note" -- wants that contract, and
            # not an ETF or a fund that happens to be marketed with the same
            # words. `rates.named_contracts` is the list of the ones the query
            # named specifically (the bare word "treasury" names the asset
            # class and is not in it), so those rows lead in the curve's own
            # order. Same guard as the funds above: an exact ticker hit
            # elsewhere is what the reader typed and outranks any supplement,
            # which is why "bond" still puts the `BOND` ETF first.
            named = sorted((r for r in results
                            if r["symbol"].upper() in rate_order),
                           key=lambda r: rate_order[r["symbol"].upper()])
            named_exact = any(S.relevance(r, needle) == 0 for r in results
                              if r["symbol"].upper() not in rate_order)
            if named and not named_exact:
                rest = [r for r in results if r not in named]
                results = named + rest
            return {"results": results[:10]}

        return self.send_json(200, S.cached(f"search:{url}", produce))


def kill_running_moli() -> None:
    """Terminate any Moli fetch still in flight (called at shutdown)."""
    with S._running_lock:
        procs = list(S._running)
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def port_owner(port: int) -> int | None:
    """PID listening on `port`, or None if it is free or lsof is unavailable."""
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5,
        ).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return int(out[0]) if out else None


def main() -> int:
    port = S.DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Not a port: {sys.argv[1]!r}", file=sys.stderr)
            return 2

    # Signals are delivered on the main thread, which is the one blocked in
    # serve_forever(), so raising there breaks out of the accept loop. (Calling
    # sys.exit() from a worker thread would only end that thread.) Restoring
    # the default handler afterwards makes a second Ctrl-C kill outright.
    def _stop(signum, _frame):
        signal.signal(signum, signal.SIG_DFL)
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
    except ValueError:  # no signal handling outside the main thread
        pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        owner = port_owner(port)
        print(f"Port {port} is already in use.", file=sys.stderr)
        if owner:
            print(f"  Held by PID {owner} — stop it with:  kill {owner}", file=sys.stderr)
        print(f"  Or run this server elsewhere:        python3 server.py {port + 1}",
              file=sys.stderr)
        return 1
    server.daemon_threads = True  # don't block shutdown on idle keep-alive threads

    # Housekeeping for the offline copies first: one directory scan here is
    # cheaper than the amortised sweep inside `store` noticing months-old
    # symbols on the 200th write of a session that never asked for them.
    diskcache.prune()

    moli_ok = os.path.exists(S.MOLI)
    print("Asset price display")
    print(f"  page   http://127.0.0.1:{port}/")
    print(f"  moli   {S.MOLI}  {'(found)' if moli_ok else '(NOT FOUND - requests fall back to the cache below)'}")
    print(f"  cache  {diskcache.dir()}  ({diskcache.count()} saved answers for offline use)")
    print("  stop   Ctrl-C\n")

    # Hydrate the sweep from disk before the refresher starts: the first
    # request must not see the empty stand-in for a table that exists in the
    # cache folder, and a seed racing a live sweep is the one ordering that
    # must not happen (see `seed_bullish`).
    S.seed_bullish()
    # The recently-bullish table is seeded the same way, for the same reason:
    # its first sweep is a browser sweep, so an offline start must not show an
    # empty table while a dated copy sits in `.cache/`.
    S.seed_recent()
    # Same reason for the watchlist, one degree quieter: the warmer starts on a
    # timer of its own and reads the declared union every pass, so a server
    # rebooted -- or one that simply has no browser open yet -- still knows
    # which symbols the reader asked it to keep current (see `WATCHLIST_KEY`).
    S.adopt_watchlist(diskcache.load_plain(S.WATCHLIST_KEY))
    # Open the startup completion report before any warming thread exists: the
    # three first passes below (first paint, bullish sweep, row charts) mark it
    # as each finishes, and the last mark prints the closing sentence --
    # "startup warm: all refetches finished (Ns)" -- so the console says when
    # the boot's fetching is over, the same way it does after a reconnection.
    S.open_startup_report()
    # Started before the first request can arrive, and before the port even
    # accepts one: the sweep's whole design depends on it being already underway
    # (or already done) by the time a reader asks, since nothing waits for it.
    S.start_bullish_refresh()
    # The recently-bullish table sweeps on its own clock for the same reason,
    # and for one more: it reads the Philippine sweep's rows, so it must not
    # outrun the sweep it is built from.
    S.start_recent_refresh()
    # Same reasoning for the caches the first paint reads, once instead of
    # forever: the browser round trips go after the port opens so binding is
    # never kept waiting, and a reader who arrives mid-warm-up waits only on
    # what is genuinely still missing.
    #
    # Warmed even when Moli is missing: with no browser the producers fail at
    # once, and `cached` turns each failure into a stamped disk copy -- so a
    # reader arriving offline is served the dated fallback immediately instead
    # of paying for a doomed live fetch per route.
    S.start_prewarm()
    # And the perpetual one: the prewarm fills the hero's caches, this thread
    # keeps *every listed row's* chart retrievable, pass after pass, whether or
    # not anyone clicks it. It waits for the first paint's fetches to clear the
    # browser before it starts spending round trips (see `warm_rows_loop`), so
    # launching it here costs a reader nothing.
    S.start_row_warming()
    # The eye that decides when all of the above should stop working to a
    # schedule: watches for the internet coming back and, on that edge,
    # expires the memos, wakes the sleepers, and re-warms the first paint --
    # so new data lands the moment it is reachable, not the moment someone
    # opens the page or a backoff happens to end (see `net_watch_loop`).
    S.start_net_watch()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nshutting down…")
        server.server_close()
        kill_running_moli()
        sourcestats.flush()
        print("stopped — port released")
    return 0
