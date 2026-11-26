"""Search helpers: ranking, currency rows, and the ticker probe.

Split out of server.py; behaviour unchanged. Every name here is re-exported from
`server`, and the code reaches its names through `S.`, so a test that patches
`server.<name>` still reaches it.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import markets
import phfunds

import server as S


def relevance(row: dict, needle: str) -> int:
    """Sort key: how directly a search result answers the query.

    Deliberately source-agnostic and capped well above any tiebreak below, so
    it only ever separates matches from near-misses and never reorders two
    equally good ones -- within a rank the original order survives.
    """
    symbol = row["symbol"].upper()
    name = (row.get("name") or "").lower()
    # BTC-USD, ^GSPC, GC=F and PSE:TEL all name their instrument in the leading
    # token. A `PSE:` prefix is a venue, so the ticker is what follows it, not
    # what precedes it -- split(":")[0] would tokenise "PSE:TEL" to "pse" and no
    # exact PSE hit would ever rank. Where a symbol carries no colon, the whole
    # string comes back either way, so [-1] is safe for both shapes.
    token = symbol.split("-")[0].split(":")[-1].split(".")[0].lstrip("^=").lower()
    # A fund's code is the instrument's whole name, hyphens and all: "BPI-HLTH"
    # is one code, not the token "BPI" followed by something, so the split above
    # would file an exact fund query behind Yahoo's noise. A `FUND:` symbol
    # carries no venue with its own listings, so the code after the prefix is
    # the token.
    if symbol.startswith(phfunds.PREFIX):
        token = symbol[len(phfunds.PREFIX):].lower()
    if token == needle or name == needle:
        return 0                      # AAPL for "apple", BTC-USD for "btc"
    if token.startswith(needle) or name.startswith(needle):
        return 1                      # PEPE-USD for "pepe"
    if needle in name:
        return 2                      # "jupiter" inside a fund's long name
    return 3                          # surfaced by Yahoo on some other signal


# Yahoo's search answers a single-currency query with the crosses its index
# holds and omits the peso crosses it will still serve *by name*: "krwphp"
# finds `KRWPHP=X` outright, but "krw" lists six other won pairs and none of
# them is the won→peso cross, and "jpy" likewise omits the yen→peso cross
# (`JPYPHP=X`) from every query that names the yen alone. Both are crosses
# this server charts honestly -- no dollar leg, so the ECB fix series under
# `ecb_route` -- yet no query a reader would actually type could ever reach
# them. This table names the queries that hide a cross and the cross each
# one hides; `fx_search_extra` turns them into rows. Hand-curated like
# `pse.SYNONYMS`: the omission is Yahoo's index, not a rule we could query.
FX_SEARCH_EXTRA: dict[str, tuple[str, ...]] = {
    "krw": ("KRWPHP=X",),
    "won": ("KRWPHP=X",),
    "jpy": ("JPYPHP=X",),
    "yen": ("JPYPHP=X",),
    "php": ("JPYPHP=X", "KRWPHP=X"),
    "peso": ("JPYPHP=X", "KRWPHP=X"),
    "philippine peso": ("JPYPHP=X", "KRWPHP=X"),
    # Indian rupee over Vietnamese dong. Yahoo's search returns nothing for
    # "inrvnd" (measured 2026-11-25), but the chart works: it is divided out
    # of the dollar legs `INR=X` and `VND=X` (`fx_cross_chart`).
    "inrvnd": ("INRVND=X",),
    "inrvnd=x": ("INRVND=X",),
    "inr/vnd": ("INRVND=X",),
    "inr vnd": ("INRVND=X",),
}


def fx_search_extra(needle: str) -> list[dict]:
    """Search rows for the peso crosses Yahoo's own index hides.

    The same shape Yahoo's rows carry (`KRWPHP=X` / "KRW/PHP" / CCY), so the
    page renders an addition indistinguishably from an original. The caller
    de-duplicates against `seen` before appending, so a cross Yahoo did list
    is never described twice.
    """
    rows = []
    for symbol in S.FX_SEARCH_EXTRA.get(needle) or ():
        rows.append({
            "symbol": symbol,
            "name": f"{symbol[:3]}/{symbol[3:6]}",
            "exchange": "CCY",
            "type": "CURRENCY",
        })
    return rows


# A word that could be a ticker: `VTV`, `BRK.B`, `BTC-USD`, `GC=F`, `^GSPC`,
# `JPYPHP=X`. Only a word of this shape is ever handed to the chart route as a
# symbol, so a sentence is never mistaken for one.
TICKER_RE = re.compile(r"^[A-Za-z^][A-Za-z0-9.\-=^]{0,11}$")

# Words that only name the *kind* of thing a reader wants, never the thing
# itself. "vtv etf" is still a ticker query, so its first word is probed; any
# other multi-word query is prose and is left to the search index rather than
# guessed at. That guard is what stops "the long bond" from resolving to `THE`
# (Target Hospitality) on a day the index answers nothing.
INSTRUMENT_WORDS = {
    "etf", "etfs", "fund", "funds", "stock", "stocks",
    "share", "shares", "index", "trust", "adr", "adrs",
}


def probe_ticker(text: str) -> dict | None:
    """The instrument `text` *names*, for a query Yahoo's search could not answer.

    Yahoo's search index refuses some queries for instruments it holds: measured
    2026-11-02, `/v1/finance/search?q=vtv` answered **HTTP 500** on query1 and
    query2 alike, with and without parameters, while `VTV` charted normally,
    `/v1/finance/quoteType/?symbol=VTV` resolved it, and the query `vt` listed it
    third. So the search box had no way to reach one of the largest US ETFs,
    and the failure was an index bug, not a missing instrument.

    Resolving the word as a *symbol* is the fallback, and the chart route is
    what resolves it: a row is offered only for a symbol it draws, carrying the
    name and venue it reports. `markets.yahoo_symbol` supplies the one spelling
    difference (`BRK.B` charts as `BRK-B`), so the row a reader clicks is the
    chart that answers.

    A multi-word query is tried by its first word only when every other word
    names the *kind* of thing asked for ("vtv etf" -> `VTV`), because the
    caller reaches this having been told nothing at all by the index. Any other
    multi-word query is prose and is not guessed at. Returns None when nothing
    resolves, so a dead end stays a dead end rather than becoming a guess.
    """
    words = [word for word in re.split(r"[^A-Za-z0-9.\-=^]+", text) if word]
    candidates = [text]
    if len(words) > 1 and all(word.lower() in S.INSTRUMENT_WORDS
                              for word in words[1:]):
        candidates.append(words[0])
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or not S.TICKER_RE.match(candidate):
            continue
        row = S._chart_meta_row(markets.yahoo_symbol(candidate.upper()))
        if row:
            return row
    return None


def _chart_meta_row(symbol: str) -> dict | None:
    """One search row from the chart payload for `symbol`, or None."""
    url = (f"https://{S.CHART_HOST}/v8/finance/chart/"
           f"{urllib.parse.quote(symbol, safe='')}?range=5d&interval=1d")
    try:
        status, body = S.moli_get(url)
        if status >= 400:
            return None
        result = ((json.loads(body).get("chart") or {}).get("result") or [None])[0]
    except (S.UpstreamError, ValueError):
        return None
    if not result:
        return None
    meta = result.get("meta") or {}
    kind = str(meta.get("instrumentType") or "").upper()
    resolved = str(meta.get("symbol") or "").strip()
    # A type the search route would have offered, a symbol to ask the chart
    # route for, and at least one bar behind it: a row with no history is a
    # row that cannot be drawn, which is the thing search exists to avoid.
    if kind not in S.KEEP_QUOTE_TYPES or not resolved or not result.get("timestamp"):
        return None
    return {
        "symbol": resolved,
        "name": meta.get("longName") or meta.get("shortName") or resolved,
        "exchange": (meta.get("fullExchangeName")
                     or meta.get("exchangeName") or ""),
        "type": kind,
    }
