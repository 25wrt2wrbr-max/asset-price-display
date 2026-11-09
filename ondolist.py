#!/usr/bin/env python3
"""Which assets app.ondo.finance lists, so a table can keep only what is buyable.

Why this module exists
----------------------
The leaning table answers "what is nearly bullish?". A reader who can only buy
on Ondo reads that list as a shortlist, and a row for an instrument the shelf
does not carry is not a shortlist entry -- it is a number they cannot act on
(asked for by name, 2026-11-06).

Since 2026-11-07 the shelf is also the **universe** of both tables: the reader
asked that the scan be "just what's available at app.ondo.finance -- no longer
trading volume", and that it include "all stocks & ETFs, and intelligent
portfolios". So this module answers two questions, not one: is a ticker listed
(the filter), and what is listed at all (the scan).

`app.ondo.finance/sitemap.xml` is the shelf: it publishes one URL per listed
asset, `/assets/<ticker>on` (the token is the ticker plus `on`; `NVDA` ->
`nvdaon`, `SPY` -> `spyon`, the USDY/OUSG funds under their bare names) and one
per intelligent portfolio under `/intelligent-portfolios/<code>on`
(`mag7xon` -> `MAG7X`). That makes both questions exact -- no hand-kept list can
drift from the site.

The scan's shelf, and the three shapes of slug
----------------------------------------------
* `nvdaon`, `spyon`, `von` -- a stock or an ETF, ticker plus `on`. `tickers()`
  strips the suffix and answers `NVDA`, `SPY`, `V`; those are the symbols the
  scan judges.
* `mag7xon`, `blkgrwon` ... -- an **intelligent portfolio**, the same
  construction under a different path. `portfolios()` answers `MAG7X`,
  `BLKGRW`.
* `ousg`, `usdy` -- the two yield funds, listed bare. They are neither a stock
  nor an ETF nor a portfolio, so no scan takes them: a T-bill token accrues and
  would sit in the bullish table forever, which is the money-market fund
  property `phfunds` already documents, not a finding.

Two rules
---------
1. **A fetch failure is not "not listed".** `shelf()` raises nothing: it
   answers the last copy it kept (up to `CACHE_KEEP`) or None, and the caller
   treats None as "the shelf was not read", keeping every row it had. That is
   invariant 3 -- an outage must never appear as a fact about an asset.
2. **The list is a fact with an age.** Every copy carries the second it was
   retrieved, so the page can say when the shelf was read instead of implying
   it is current.

Plain HTTPS, standard library only: the sitemap is public and answers `curl`
(the browser-gated data on that site is `/api/`, which robots.txt keeps out and
this module never asks for).
"""

from __future__ import annotations

import re
import time
import urllib.request

import diskcache

SITEMAP = "https://app.ondo.finance/sitemap.xml"

# The disk key, versioned beside every other stored answer in this project.
# v2 reads the intelligent portfolios beside the assets; a v1 copy knows only
# the assets, and the scan needs both, so it is not served as a current shelf.
CACHE_KEY = "ondo:shelf:v2"

# Fresh enough to skip the fetch: listings do not change minute to minute, and
# this list is only consulted once per recent-table sweep.
CACHE_TTL = 6 * 3600

# Still worth acting on if the fetch failed. A delisted asset would linger at
# worst this long, which is the same bargain the bond and fund copies strike.
CACHE_KEEP = 14 * 24 * 3600

# The site is not always fast on a cold connection; the request sits inside a
# background sweep, so a few seconds are cheap and a hung socket is not.
TIMEOUT = 20

# `/assets/<slug>` -- the only URLs on that sitemap that name an instrument.
_ASSET = re.compile(r"/assets/([A-Za-z0-9][A-Za-z0-9.\-]*)")

# `/intelligent-portfolios/<slug>` -- the baskets, same `<code>on` shape.
_PORTFOLIO = re.compile(r"/intelligent-portfolios/([A-Za-z0-9][A-Za-z0-9.\-]*)")

# Every listed token ends in these two letters; the ticker in front of them is
# the instrument's own spelling.
TOKEN_SUFFIX = "on"

# The shortest real slug is a one-character ticker plus the suffix (`von`,
# Visa) or a bare fund ticker (`ousg`).
_MIN_SLUG = len(TOKEN_SUFFIX) + 1


def parse(text: str) -> set[str]:
    """The asset page names a sitemap lists, lower case, from its `/assets/` URLs.

    These are the slugs, not the tickers: most tokens are `<ticker>on`
    (`nvdaon`), but the two yield funds are listed under their bare ticker
    (`ousg`, `usdy`), so the ticker question is asked against both spellings
    by `carries` rather than guessed at here. A class share is spelled the way
    the shelf spells it (`brk.bon`), never the way Yahoo or a scanner does.
    """
    return {slug.lower() for slug in _ASSET.findall(text or "")}


def parse_portfolios(text: str) -> set[str]:
    """The intelligent-portfolio page names a sitemap lists, lower case.

    A separate set from `parse`'s because they are a separate page path: the
    assets are one instrument each, a portfolio is a basket the same shop
    sells, and the scan treats the two differently (a stock's bars come from
    Yahoo, a portfolio's from its own token price).
    """
    return {slug.lower() for slug in _PORTFOLIO.findall(text or "")}


def token_ticker(slug: str) -> str | None:
    """The instrument a slug names (`nvdaon` -> `NVDA`), or None.

    A token is the ticker plus `on`, so the suffix is what is stripped -- and
    only the suffix, which is why a real ticker that ends in those letters
    survives (`onon` is ON Semiconductor, and strips to `ON`). A bare slug is
    one of the two yield funds (`ousg`, `usdy`), which are neither a stock nor
    a portfolio and are not offered to any scan.
    """
    text = (slug or "").strip().lower()
    if len(text) < _MIN_SLUG or not text.endswith(TOKEN_SUFFIX):
        return None
    return text[:-len(TOKEN_SUFFIX)].upper()


def tickers(shelf_record: dict | None) -> list[str]:
    """Every stock and ETF on the shelf, in its own ticker spelling.

    The scan's universe, alphabetically so a sweep's order does not depend on
    the sitemap's. `BRK.B` keeps the dot the shelf uses; the caller that asks
    Yahoo for bars converts it (`markets.yahoo_symbol`), exactly as it does for
    a scanner row.
    """
    if not shelf_record:
        return []
    out = {token_ticker(slug) for slug in shelf_record.get("slugs") or ()}
    return sorted(ticker for ticker in out if ticker)


def portfolios(shelf_record: dict | None) -> list[str]:
    """Every intelligent portfolio on the shelf (`MAG7X`, `BLKGRW`, ...)."""
    if not shelf_record:
        return []
    out = {token_ticker(slug) for slug in shelf_record.get("portfolios") or ()}
    return sorted(ticker for ticker in out if ticker)


def _fetch() -> str:
    """The sitemap's text. Raises on any transport or status problem."""
    request = urllib.request.Request(SITEMAP, headers={
        # A plain UA: the sitemap is a public document, but an empty one reads
        # as a bot to more than one CDN.
        "User-Agent": "asset-price-display/1.0 (personal price page)",
        "Accept": "application/xml,text/xml,*/*",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
        status = getattr(answer, "status", 200)
        if status != 200:
            raise OSError("sitemap answered HTTP %s" % status)
        return answer.read().decode("utf-8", "replace")


def _record(slugs: set[str], fetched_at: float, cached: bool,
            portfolios: set[str] | None = None) -> dict:
    return {
        "slugs": sorted(slugs),
        "portfolios": sorted(portfolios or ()),
        "fetchedAt": float(fetched_at),
        "cached": bool(cached),
        "count": len(slugs) + len(portfolios or ()),
    }


def _read(value: dict | None) -> tuple[set[str], set[str]]:
    """A stored shelf -> (asset slugs, portfolio slugs).

    A copy stored before the portfolios were read has no `portfolios` key at
    all; it answers an empty set, which is the truth about that copy rather
    than a claim that none are listed.
    """
    value = value or {}
    return set(value.get("slugs") or ()), set(value.get("portfolios") or ())


def saved() -> dict | None:
    """The last stored shelf, disk only -- no network.

    For the startup seed, which must not wait on a socket. None means no copy
    was ever kept, or the copy is older than `CACHE_KEEP`.
    """
    stored = diskcache.load(CACHE_KEY)
    if not stored:
        return None
    fetched_at, value = stored
    slugs, portfolios = _read(value)
    if not slugs and not portfolios:
        return None
    if time.time() - fetched_at > CACHE_KEEP:
        return None
    return _record(slugs, fetched_at, cached=True, portfolios=portfolios)


def shelf(now: float | None = None) -> dict | None:
    """The shelf as it stands now, or the last one read, or None.

    A copy younger than `CACHE_TTL` is served without asking the network. A
    failed fetch falls back to the newest stored copy inside `CACHE_KEEP` and
    marks it `cached`, so the caller can say how old the answer is. Nothing
    raises: None is the one way to say "no shelf was available", and the
    caller's rule for None is to keep every row.
    """
    now = time.time() if now is None else now
    stored = diskcache.load(CACHE_KEY)
    slugs: set[str] = set()
    portfolios: set[str] = set()
    fetched_at = 0.0
    if stored:
        fetched_at, value = stored
        slugs, portfolios = _read(value)
        if (slugs or portfolios) and now - fetched_at <= CACHE_TTL:
            return _record(slugs, fetched_at, cached=False,
                           portfolios=portfolios)

    try:
        text = _fetch()
        parsed = parse(text)
        baskets = parse_portfolios(text)
    except Exception:                      # noqa: BLE001 - any failure is an outage
        parsed, baskets = set(), set()
    if parsed or baskets:
        diskcache.store(CACHE_KEY, {"slugs": sorted(parsed),
                                    "portfolios": sorted(baskets)})
        return _record(parsed, now, cached=False, portfolios=baskets)

    if (slugs or portfolios) and now - fetched_at <= CACHE_KEEP:
        return _record(slugs, fetched_at, cached=True, portfolios=portfolios)
    return None


def carries(ticker: str, shelf_record: dict | None) -> bool:
    """Whether `ticker` is one of the assets on the shelf.

    The ticker is tried the way the shelf spells a token -- `<ticker>on` --
    and bare, because the yield funds are listed under their own name (`ousg`,
    `usdy`). A class-share dot is also tried as the dash Yahoo uses
    (`BRK.B` -> `BRK-B`), because a scanner's spelling and a chart's spelling
    differ for the same listing. A missing shelf carries nothing and is never
    consulted -- the caller checks for None first, since "not listed" and "not
    read" must not answer the same way.
    """
    if not shelf_record or not ticker:
        return False
    # Separators are compared away on both sides, so a class share matches
    # whichever way either party spelled it (`BRK.B`, `BRK-B`, `brk.bon`).
    listed: set[str] = set()
    for slug in (list(shelf_record.get("slugs") or ())
                 + list(shelf_record.get("portfolios") or ())):
        listed.add(slug)
        listed.add(slug.replace(".", "").replace("-", ""))
    text = str(ticker).strip().lower()
    for spelling in {text, text.replace(".", "-"), text.replace(".", "")}:
        if not spelling:
            continue
        for form in {spelling, spelling.replace(".", "").replace("-", "")}:
            if form in listed or (form + TOKEN_SUFFIX) in listed:
                return True
    return False
