#!/usr/bin/env python3
"""The United States Treasury futures curve: the contracts, and how to find them.

Why this module exists
----------------------
Two gaps, one cause. The page charts whatever Yahoo quotes, and Yahoo quotes
every United States Treasury future -- `ZB=F` charts perfectly well, five years
of daily bars and a verdict. What was missing was any way to *reach* one:

* **Search could not find it by name.** Yahoo's index answers "30-year treasury
  bond" with six Korean ETFs (KODEX, ARIRANG, RISE, KIWOOM, and two KB funds)
  and answers "long bond" with three KB Asset Management funds and a Canadian
  index; the CME contract is in neither answer. `ZB=F` does surface for "zb",
  "t-bond" and "bond futures", but its Yahoo name is "U.S. Treasury Bond
  Futures,Dec-", which contains neither "30" nor "year" -- so no query built
  from the words a person uses can rank the contract above an ETF whose
  marketing name *is* the query. Measured 2026-10-31 against the live search
  route: "zb" ✓, "t-bond" ✓, "t-note" ✓, "30-year treasury bond" ✗,
  "long bond" ✗.
* **No scan ever judged it.** The recent table's United States leg is the
  TradingView turnover ranking (`markets.us_universe`), which is common stock
  and ETFs; a futures contract has no place in it -- the scanner's `typespecs`
  cannot even name one -- so the whole rates complex sat outside every sweep,
  whatever its chart said.

So the curve is a **fixed list here**, exactly as `tv.BONDS` is the Philippine
curve as a fixed list: one contract per curve point, the spelling Yahoo charts
(`ZB=F`), and the name a reader would use for it. Nothing is discovered by
turnover, because a Treasury future is not chosen from a ranking -- there is one
of it, and either you are looking at it or you are not.

A Treasury future is a price, not a yield
-----------------------------------------
`tv.BONDS` inverts its verdict and says "yield rising" because it reads a
*yield* while a bondholder cares about the price. These contracts are the
opposite case: the series **is** a price. A higher `ZB` quote is a higher bond
price, so `trend.classify`'s own label stands unchanged and nothing is inferred.
The row and the badge say the same word.

What the numbers are
--------------------
A Treasury future is quoted in 32nds of a point (the notes in 64ths of a
32nd), so `107.65625` is 107-21 and `106.640625` is 106-20½. Yahoo hands back
the decimal, and `price_hint` asks the bars themselves how many decimals the
quote needs rather than hard-coding one -- the same rule `phfunds.price_hint`
follows for a NAVPU, and for the same reason: a figure printed at two decimals
would round away the fraction that moved.

Turnover is **None**: a contract's volume counts contracts, and close ×
contracts is not a traded value in any currency. The rows keep the peso-volume
floor out of their way and the volume column prints a dash (see
`recent.rate_rows`).

Standard library only. Nothing here fetches anything: the bars come from
Yahoo, through the browser leg `server.fetch_us_bars` already runs, and this
module only says which symbols to ask for and what to call them.
"""

from __future__ import annotations

# The curve, shortest first. This is the delivery order too: `search_contracts`
# breaks a tie between equally specific matches by it, so a reader asking for
# "treasury futures" gets the curve from the two-year out rather than ZB
# followed by whatever the alphabet says.
#
# `phrases` are the words a reader actually types, normalised the way
# `_tokens` normalises a query (lower case, hyphens and slashes to spaces).
# A phrase matches when it appears as a contiguous run of the query's words, so
# "30 year treasury bond" answers ZB through "30 year" and "treasury bond"
# alike, while "12 year" can never match the two-year through "2 year".
CONTRACTS = (
    {
        "symbol": "ZT=F",
        "ticker": "ZT",
        "name": "2-Year T-Note Futures",
        "phrases": ("zt", "2 year", "2y", "two year", "t note"),
    },
    {
        "symbol": "Z3N=F",
        "ticker": "Z3N",
        "name": "3-Year T-Note Futures",
        "phrases": ("z3n", "3 year", "3y", "three year", "t note"),
    },
    {
        "symbol": "ZF=F",
        "ticker": "ZF",
        "name": "5-Year T-Note Futures",
        "phrases": ("zf", "5 year", "5y", "five year", "t note"),
    },
    {
        "symbol": "ZN=F",
        "ticker": "ZN",
        "name": "10-Year T-Note Futures",
        "phrases": ("zn", "10 year", "10y", "ten year", "t note"),
    },
    {
        "symbol": "TN=F",
        "ticker": "TN",
        "name": "Ultra 10-Year T-Note Futures",
        "phrases": ("tn", "ultra 10 year", "ultra ten year", "ultra note",
                    "t note"),
    },
    {
        "symbol": "ZB=F",
        "ticker": "ZB",
        "name": "30-Year U.S. Treasury Bond Futures",
        # The thirty-year is the one people call "the long bond" and "the
        # T-bond"; those two names are why it was unfindable, so they are the
        # phrases that matter most here.
        "phrases": ("zb", "30 year", "30y", "thirty year", "long bond",
                    "t bond", "treasury bond", "bond future"),
    },
    {
        "symbol": "UB=F",
        "ticker": "UB",
        "name": "Ultra U.S. Treasury Bond Futures",
        "phrases": ("ub", "ultra bond", "ultra 30 year", "ultra long"),
    },
)

# Every contract answers to the curve's own words as well. Two lists, because
# they are ranked differently: "treasury future" asks for the complex and is
# *specific*, like a tenor is, while the bare word "treasury" names the asset
# class -- so a query of that one word is left to Yahoo's own order and the
# supplement only fills in what Yahoo left out.
CURVE_PHRASES = ("treasury future",)
CLASS_WORDS = ("treasury",)

# The venue Yahoo's search row carries for every one of them, so a supplement
# is indistinguishable from an original. `exchDisp` on `ZB=F` reads exactly
# this (measured 2026-10-31).
EXCHANGE = "Chicago Board of Trade"
QUOTE_TYPE = "FUTURE"


# Words that mean another word here. A plural is folded away generally below;
# these are the ones that folding alone would miss, and the "yr" spellings a
# trader types for "year".
_WORD_ALIASES = {
    "yr": "year", "yrs": "year",
    "treasuries": "treasury", "treasurys": "treasury",
}


def _tokens(text: str) -> list[str]:
    """A query or a phrase as comparable words: lower case, no punctuation.

    "30-Year Treasury Bond" -> ["30", "year", "treasury", "bond"]. A trailing
    plural is folded away ("bonds" -> "bond") and the `_WORD_ALIASES` spellings
    are resolved, so the one phrase table serves "30 year", "30-year",
    "30 yrs" and "30 yrs. Treasury bonds".
    """
    words = []
    for raw in (text or "").lower().replace("-", " ").replace("/", " ").split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if not word:
            continue
        if word in _WORD_ALIASES:
            word = _WORD_ALIASES[word]
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.append(word)
    return words


def _match(contract: dict, words: list[str]) -> tuple[int, bool] | None:
    """How specifically `contract` answers `words` -> (length, specific), or None.

    `length` is how many query words the longest matching phrase covers, which
    is what makes "ultra 10 year" beat "10 year" for the Ultra contract. A match
    is *specific* when it names a contract -- one of the contract's own phrases
    ("zb", "30 year", "long bond") or the curve's own "treasury future" -- and
    generic when it is the bare word "treasury".
    """
    best = None
    for phrase in (tuple(contract["phrases"]) + CURVE_PHRASES + CLASS_WORDS):
        needle = _tokens(phrase)
        if not needle or (best is not None and len(needle) <= best[0]):
            continue
        for start in range(len(words) - len(needle) + 1):
            if words[start:start + len(needle)] == needle:
                specific = (phrase in contract["phrases"]
                            or phrase in CURVE_PHRASES)
                best = (len(needle), specific)
                break
    return best


def _scored(query: str) -> list[tuple[bool, dict]]:
    """Every contract the query names -> (specific, contract), best first.

    Longest phrase first, then the curve's own order, so the answer is
    repeatable and a more particular phrase always outranks a looser one.
    """
    words = _tokens(query)
    if not words:
        return []
    scored = []
    for index, contract in enumerate(CONTRACTS):
        hit = _match(contract, words)
        if hit is None:
            continue
        length, specific = hit
        scored.append((-length, 0 if specific else 1, index, contract))
    scored.sort(key=lambda item: item[:3])
    return [(item[1] == 0, item[3]) for item in scored]


def _row(contract: dict) -> dict:
    """The search-result shape the page renders, as Yahoo's own rows carry it."""
    return {
        "symbol": contract["symbol"],
        "name": contract["name"],
        "exchange": EXCHANGE,
        "type": QUOTE_TYPE,
    }


def search_contracts(query: str, limit: int = 5) -> list[dict]:
    """Search rows for the Treasury contracts the query names, best first.

    Always finds something for a reader who types a contract's ticker, its
    tenor, or the name it goes by on a trading desk -- which is the whole
    point: Yahoo's index holds "t-bond" and "zb" but not "30-year treasury
    bond", and a search box that answers only the words Yahoo happens to have
    indexed is a search box that cannot find the thirty-year.

    A query that names a contract gets *that* contract and not the rest of the
    curve: "long bond" is one row, not seven rows padded with the two-year.
    Only a query that names no contract ("treasury", "treasury futures") is
    answered with the curve.

    Never raises, returns an empty list for a query that names no contract.
    """
    scored = _scored(query)
    specific = [contract for is_specific, contract in scored if is_specific]
    chosen = specific or [contract for _specific, contract in scored]
    return [_row(contract) for contract in chosen][:limit]


def named_contracts(query: str) -> list[str]:
    """The symbols whose contract the query names *specifically*, curve order.

    The caller leads with these, the way the funds lead with a code a query
    answers: a reader who typed "30-year treasury bond" asked for the contract,
    not for an ETF that happens to be marketed with those three words. The bare
    word "treasury" is not specific -- it names the asset class -- so a query
    of that one word takes Yahoo's own order and this returns nothing for it.
    """
    return [contract["symbol"]
            for specific, contract in _scored(query) if specific]


def price_hint(closes) -> int:
    """Decimals the fetched closes are quoted with, 2 to 8.

    A Treasury contract's fraction is a 32nd (0.03125), a 64th (0.015625) or a
    128th (0.0078125), so the decimals a quote needs are a property of the
    instrument, not a house style -- and the bars say which it is. The same
    rule, and the same clamp, as `phfunds.price_hint`: the last sixty closes
    are enough to see it, and a stray float artifact must not ask for eight
    decimals on a contract that trades in thirty-seconds.
    """
    decimals = 2
    for close in list(closes or [])[-60:]:
        try:
            text = repr(float(close)).rstrip("0")
        except (TypeError, ValueError):
            continue
        if "." in text:
            decimals = max(decimals, len(text.split(".")[1]))
    return min(8, decimals)



def chart_alias(symbol: str) -> str | None:
    """The contract a bare futures ticker names ("ZB" -> "ZB=F"), or None.

    The chart route asks Yahoo for what was typed, and a bare contract ticker
    is not one of Yahoo's symbols -- the future is `ZB=F` -- so "zb" typed into
    the search box and submitted without picking the suggestion ended in "no
    usable price data" for a contract that charts perfectly well.

    The caller asks this **only after Yahoo has refused the typed spelling**, so
    a listing that really does trade under the bare ticker keeps its own chart:
    `UB` resolves to an ETF, and that ETF is what the reader asked for.
    """
    needle = (symbol or "").strip().upper()
    for contract in CONTRACTS:
        if contract["ticker"] == needle:
            return contract["symbol"]
    return None
