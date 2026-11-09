#!/usr/bin/env python3
"""Philippine funds, on the net asset value per unit their managers publish.

Why this module exists
----------------------
The page's tables cover US stocks, Philippine stocks, crypto and the Philippine
government bond yields. What it did not cover is the thing a Philippine retail
investor most often actually holds: the peso fund -- a BPI Wealth UITF, an ALFM
mutual fund, an Odyssey fund, a PERA fund. Those have no ticker, no exchange
and no Yahoo quote; they publish one number a business day, the **NAVPU**
(net asset value per unit; NAVPS for a mutual fund's shares), and every chart,
table and verdict in this project is built from a daily close. A NAVPU is a
daily close. It belongs here.

The rule that makes them admissible is the project's oldest one: a verdict must
be computable from the bars the chart draws. A fund's chart draws its NAVPU
series, and `trend.classify` reads that series exactly as it reads a price, so a
row and the chart its click opens are one series and one verdict -- the same
guarantee the Philippine stocks and the bond yields already have.

Where the numbers come from
---------------------------
Three publishers, because the Philippine fund industry has three registries and
no single one lists them all:

* **UITFs** -- the Trust Officers Association of the Philippines' public
  register, `uitf.com.ph`, per fund (`bank_id=3` is BPI Wealth). The chart
  endpoint returns `{label, y}` points; it answers plain HTTPS, so no browser
  is needed. The website's *historical table* sits behind a reCAPTCHA, and this
  module deliberately does not go near it: the chart endpoint is public, the
  table is gated, and reading around a gate is not a thing to build in.
* **Mutual funds** -- the Philippine Investment Fund Association's NAV history
  pages (`pifa.com.ph`), whose daily series is embedded in the page itself.
  ALFM's funds, the Philippine Stock Index Fund and the Wealth Builder fund
  live only here.
* **PERA funds** -- BPI Wealth's own fund pages, whose graph model is a JSON
  document under `/jcr:content/.../dynamicgraph_copy.model.json`. The four PERA
  UITFs are not on the TOAP register, so their own manager is the only source.

All three answer plain HTTPS with a year or more of daily values, verified
2026-10-31 against the NAVPU figures a reader has in hand (the eleven PIFA funds
matched to the cent; the TOAP funds matched to the published valuation date).

Two facts about the raw data that decide the shape of everything below
-----------------------------------------------------------------------
**A fund does not trade on weekends, but its publishers pad the calendar.**
Both the TOAP chart endpoint and BPI's model repeat the Friday value across
Saturday and Sunday, so a "daily series" arrives with two bars a week that never
happened. They are kept out of the series here, not smoothed or carried: a
padded Saturday is not a flat session, it is a non-session, and a bar that never
happened must not vote in a 63-bar window or be dated as the day a run began.

**The published series can end in the future.** BPI's model carries stamps a
couple of days past today (its own forward padding), so anything stamped after
the current day is dropped rather than charted as a price that has not been
struck yet.

What this module does *not* claim
---------------------------------
A NAVPU is a net asset value, not a traded price: there is no volume, so a row
carries no turnover (the recent table prints a dash, and the volume floor that
keeps illiquid names off that table cannot apply to a fund).
And a fund's NAVPU is struck once a business day after the market closes, so the
newest bar is typically yesterday's -- the row's date and the chart's hero
figure are that bar's, and neither pretends otherwise.

One consequence worth stating plainly, because it looks like a bug and is not:
**a money market fund's NAVPU only goes up.** It accrues interest daily and
never marks to market to a loss, so a 90-day window on it is essentially always
"bullish", and its run is always *censored* -- "at least this long" -- because
the run reaches back past the bars fetched. That is a true statement about a
cash fund, not a mislabelled equity.

Standard library only, like the rest of the project. It imports `onset` and
`trend` for the verdict, `diskcache` for the copy that survives a restart, and
nothing else; `recent.py` and `server.py` import it.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import re
import time
import urllib.request

import diskcache
import onset as onset_module
import pse
import trend

# How many calendar days of history are fetched and kept behind the ninety-day
# window the walk reads. A year of business days is ~250 bars, which is four
# windows of history behind the latest bar -- the same allowance the other
# markets get (`recent.WALK_SPAN = "1y"`), and what lets a run that reaches the
# start of the fetched data be reported as *censored* rather than dated to the
# oldest bar fetched. It is a little over a year so the trim below never eats a
# bar the window needed.
HISTORY_DAYS = 400

# How long a fetched series is worth skipping the fetch for, and how long it is
# still worth *showing* when the fetch failed. A NAVPU is struck once a business
# day, so a copy six hours old has missed at most one bar -- the same reasoning,
# and the same two ages, as the bond yields (`tv.BOND_CACHE_TTL`). A copy a week
# old is a stale reading that still beats a gap, and the row says which it is.
CACHE_TTL = 6 * 3600
CACHE_KEEP = 7 * 24 * 3600
CACHE_PREFIX = "fund:"

# How many funds are fetched at once. The TOAP and BPI endpoints are small
# documents and tolerate a handful of parallel readers; PIFA's pages are ~2 MB
# each and *close the connection* when asked for several at once (verified
# 2026-10-31: eight parallel reads earned `RemoteDisconnected`), so that source
# is read one fund at a time, with a pause between.
FAST_WORKERS = 6
PIFA_PAUSE = 0.4

# The user agent every source sees. These are the same public pages a browser
# loads, and a browser's own identification is what keeps a plain client from
# being mistaken for a scraper and refused.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0 Safari/537.36"),
}

# TradingView's daily bar count is what the chart route's spans are measured
# in; a fund's spans are the same calendar days, so `pse.RANGE_DAYS` is the one
# table of them. Using it keeps a fund chart's window and the bond chart's
# window the same shape of thing.
RANGE_DAYS = pse.RANGE_DAYS

# The symbol prefix a fund carries in a URL and in a table row. A fund has no
# ticker, and a bare code like "BPI-INFRA" could one day collide with a real
# instrument, so the route keys on the prefix -- exactly as `TVC:` does for a
# bond yield.
PREFIX = "FUND:"

# The BPI Wealth fund pages that carry a PERA fund's graph model. The page path
# is the model's parent, so it is part of the fund's identity here: a wrong
# slug is a 404, not a wrong series.
BPI_SLUGS = {
    "BPIPERAMM": "pera/money-market-fund",
    "BPIPERACI": "pera/corporate-income-fund",
    "BPIPERAEF": "pera/equity-fund",
    "BPIPERAGB": "pera/government-bond-fund",
}

BPI_MODEL_URL = ("https://www.bpi.com.ph/content/bpi/ph/en/group/bpiwealth/"
                 "our-solutions/personal/investment-solutions/%s/jcr:content/"
                 "root/container/dynamicgraph_copy.model.json")

TOAP_URL = ("https://www.uitf.com.ph/daily_navpu_details_json.php"
            "?from=%s&to=%s&bank_id=3&fund_id=%s&verification_id=1&btn=Filter")

PIFA_URL = "https://pifa.com.ph/facts-figures/nav-history/?fund_id=%s"

# `code, name, category, source, key, currency`.
#
# `code` is what a row prints and what a URL carries; it is a *display code*,
# not an exchange ticker -- no Philippine fund has one. `source` names the
# registry the series is read from and `key` is that registry's own identifier,
# so a fund can only ever resolve against the document that publishes it.
FUNDS = (
    ("BPI-INFRA", "BPI Philippine Infrastructure Equity Index Fund", "Equity", "uitf", "292", "PHP"),
    ("BPI-USEQ-P", "BPI US Equity Index Feeder Fund (Class P)", "Equity", "uitf", "377", "PHP"),
    ("BPI-HLTH", "BPI Global Health Care Feeder Fund", "Equity", "uitf", "401", "PHP"),
    ("BPI-WTECH-A", "BPI World Technology Feeder Fund (Class A)", "Equity", "uitf", "400", "USD"),
    ("ODY-APAC", "Odyssey Asia Pacific High Dividend Equity Fund", "Equity", "uitf", "67", "USD"),
    ("BPI-USEQ-A", "BPI US Equity Index Feeder Fund (Class A)", "Equity", "uitf", "235", "USD"),
    ("BPI-GEQ-A", "BPI Global Equity Fund-of-Funds (Class A)", "Equity", "uitf", "57", "USD"),
    ("BPI-SGEQ", "BPI Sustainable Global Equity Fund-of-Funds", "Equity", "uitf", "442", "USD"),
    ("BPI-GBOND-P", "BPI Global Bond Income Fund Class P (PHP)", "Bond", "uitf", "558", "PHP"),
    ("BPI-EUROEQ", "BPI European Equity Feeder Fund", "Equity", "uitf", "236", "USD"),
    ("BPI-PERA-MM", "BPI PERA Money Market", "PERA", "bpi", "BPIPERAMM", "PHP"),
    ("ALFM-MM", "ALFM Money Market Fund", "Bond", "pifa", "69", "PHP"),
    ("ALFM-MM-U", "ALFM Money Market Fund (Units)", "Bond", "pifa", "120", "PHP"),
    ("BPI-SGBAL", "BPI Sustainable Global Balanced Fund-of-Funds", "Balanced", "uitf", "441", "USD"),
    ("BPI-ST", "BPI Short Term Fund", "Bond", "uitf", "48", "PHP"),
    ("BPI-MM", "BPI Money Market Fund", "Bond", "uitf", "50", "PHP"),
    ("BPI-WB-U", "BPI Wealth Builder Multi-Asset Mutual Fund (Units)", "Balanced", "pifa", "128", "PHP"),
    ("ALFM-GMAI", "ALFM Global Multi-Asset Income Fund (PHP)", "Balanced", "pifa", "74", "PHP"),
    ("BPI-USDST", "BPI US Dollar Short Term Fund", "Bond", "uitf", "55", "USD"),
    ("ALFM-PESO", "ALFM Peso Bond Fund", "Bond", "pifa", "51", "PHP"),
    ("BPI-BAYAN", "BPI Bayanihan Balanced Fund", "Balanced", "uitf", "345", "PHP"),
    ("BPI-PERA-CI", "BPI PERA Corporate Income Fund", "PERA", "bpi", "BPIPERACI", "PHP"),
    ("ALFM-USD", "ALFM Dollar Bond Fund", "Bond", "pifa", "49", "USD"),
    ("BPI-HIDIV", "BPI Philippine High Dividend Equity Fund", "Equity", "uitf", "189", "PHP"),
    ("BPI-SGBOND", "BPI Sustainable Global Bond Fund-of-Funds", "Bond", "uitf", "440", "USD"),
    ("ALFM-EURO", "ALFM Euro Bond Fund", "Bond", "pifa", "50", "EUR"),
    ("BPI-BAL", "BPI Balanced Fund", "Balanced", "uitf", "52", "PHP"),
    ("BPI-GBOND", "BPI Global Bond Fund-of-Funds", "Bond", "uitf", "54", "USD"),
    ("PSIF-U", "Philippine Stock Index Fund (Units)", "Equity", "pifa", "121", "PHP"),
    ("PSIF", "Philippine Stock Index Fund", "Equity", "pifa", "24", "PHP"),
    ("BPI-PREM", "BPI Premium Bond Fund", "Bond", "uitf", "49", "PHP"),
    ("BPI-PHEQ", "BPI Philippine Equity Index Fund", "Equity", "uitf", "69", "PHP"),
    ("BPI-GBOND-A", "BPI Global Bond Income Fund Class A (USD)", "Bond", "uitf", "557", "USD"),
    ("ALFM-GROW", "ALFM Growth Fund", "Equity", "pifa", "7", "PHP"),
    ("BPI-PERA-EQ", "BPI PERA Equity Fund", "PERA", "bpi", "BPIPERAEF", "PHP"),
    ("BPI-PHUSD", "BPI Philippine Dollar Bond Index Fund", "Bond", "uitf", "56", "USD"),
    ("ABF-PH", "ABF Philippines Bond Index Fund", "Bond", "uitf", "51", "PHP"),
    ("ODY-PHUSD", "Odyssey Philippine Dollar Bond Fund", "Bond", "uitf", "66", "USD"),
    ("ODY-HCE", "Odyssey Philippine High Conviction Equity Fund", "Equity", "uitf", "64", "PHP"),
    ("BPI-PERA-GB", "BPI PERA Government Bond Fund", "PERA", "bpi", "BPIPERAGB", "PHP"),
    ("ODY-PESO", "Odyssey Peso Bond Fund", "Bond", "uitf", "60", "PHP"),
    ("BPI-EQVAL", "BPI Equity Value Fund", "Equity", "uitf", "53", "PHP"),
    ("ALFM-GMAI-USD", "ALFM Global Multi-Asset Income Fund (USD)", "Balanced", "pifa", "122", "USD"),
    ("ODY-DIV", "Odyssey Diversified Capital Fund", "Balanced", "uitf", "61", "PHP"),
    ("BPI-CONS", "BPI Philippine Consumer Equity Index Fund", "Equity", "uitf", "293", "PHP"),
    ("BPI-GEQ-P", "BPI Global Equity Fund-of-Funds (Class P)", "Equity", "uitf", "599", "PHP"),
    ("BPI-WTECH-P", "BPI World Technology Feeder Fund (Class P)", "Equity", "uitf", "600", "PHP"),
)

# The code -> record index, built once. Two funds sharing a code would make a
# row and a chart disagree about which series they mean, so the table below is
# checked for that at import rather than at the first surprising click.
_BY_CODE: dict[str, dict] = {}
for _code, _name, _category, _source, _key, _currency in FUNDS:
    if _code in _BY_CODE:
        raise RuntimeError("duplicate fund code: %s" % _code)
    _BY_CODE[_code] = {"code": _code, "name": _name, "category": _category,
                       "source": _source, "key": _key, "currency": _currency}

# The publishers, named the way a reader would recognise them. A chart says
# which one its numbers came from, because "the fund's NAVPU" is not a source.
SOURCE_NAMES = {
    "uitf": "TOAP uitf.com.ph",
    "pifa": "PIFA",
    "bpi": "BPI Wealth",
}

DAY = 86400


class FundError(RuntimeError):
    """The fund's series could not be read, and no usable copy exists."""


class FundNotFound(LookupError):
    """The symbol is not one of the funds this module knows."""


def canonical(symbol: str) -> str | None:
    """`FUND:<CODE>` for a fund this module knows, or None.

    Two spellings are accepted: the full symbol (`FUND:BPI-INFRA`) and the bare
    code (`BPI-INFRA`), because a reader typing a fund's name into a URL should
    not have to know about the prefix. Anything else is not a fund, and None
    says so rather than raising -- the usual caller is asking "is this mine?",
    which is a yes/no question.
    """
    text = (symbol or "").strip().upper()
    if text.startswith(PREFIX):
        text = text[len(PREFIX):]
    return PREFIX + text if text in _BY_CODE else None


def is_fund_symbol(symbol: str) -> bool:
    """Whether `symbol` names one of the funds this module knows."""
    return canonical(symbol) is not None


def record(symbol: str) -> dict:
    """The fund's own record: code, name, category, source, currency."""
    canonical_symbol = canonical(symbol)
    if canonical_symbol is None:
        raise FundNotFound("%r is not a Philippine fund." % symbol)
    return _BY_CODE[canonical_symbol[len(PREFIX):]]


def symbol_for(code: str) -> str:
    """The chart symbol for a fund code, e.g. `FUND:BPI-INFRA`."""
    return PREFIX + code.upper()


# -- parsing ---------------------------------------------------------------
#
# One parser per publisher, each taking that publisher's own document and
# answering this project's bar shape: {"t": int UTC second, "c": float}. They
# are pure functions of the document, which is what makes them testable without
# a network.

def _toap_bars(document: dict) -> list[dict]:
    """TOAP's chart JSON -> bars.

    `data_point` is `[{"label": "Oct 30, 2026", "y": 221.22}, ...]`: a calendar
    day and a NAVPU, weekends included as repeats of the value before them.
    """
    bars: list[dict] = []
    for point in (document or {}).get("data_point") or []:
        try:
            moment = datetime.datetime.strptime(str(point["label"]), "%b %d, %Y")
            close = float(point["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not close > 0:
            continue
        stamps = int(moment.replace(tzinfo=datetime.timezone.utc).timestamp())
        bars.append({"t": stamps, "c": close})
    return bars


_PIFA_ENTRY = re.compile(
    r"date:\s*(\d+),\s*month:\s*(\d+),\s*year:\s*(\d+),\s*value:\s*([0-9.]+)")


def _pifa_bars(page: str) -> list[dict]:
    """PIFA's embedded dataset -> bars.

    The page carries its whole history as an inline JavaScript array
    (`{date: 30, month: 10, year: 2026, value: 202.98}`), which is the only
    place the association publishes it, so the document is read as text. A
    malformed calendar day -- a 31st of a 30-day month, which the array should
    never contain -- is skipped rather than allowed to abort the fund.
    """
    bars: list[dict] = []
    for day, month, year, value in _PIFA_ENTRY.findall(page or ""):
        try:
            moment = datetime.datetime(int(year), int(month), int(day),
                                       tzinfo=datetime.timezone.utc)
            close = float(value)
        except ValueError:
            continue
        if not close > 0:
            continue
        bars.append({"t": int(moment.timestamp()), "c": close})
    return bars


def _bpi_bars(document: dict) -> list[dict]:
    """BPI Wealth's graph model -> bars.

    `fundData` is a JSON *string* inside the JSON document (the page component
    parses it on the client), and its `fundDataHistory` is a list of
    `{navpuValue, date (milliseconds), ...}`.
    """
    raw = (document or {}).get("fundData")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    bars: list[dict] = []
    for point in (raw or {}).get("fundDataHistory") or []:
        try:
            stamps = int(int(point["date"]) // 1000)
            close = float(point["navpuValue"])
        except (KeyError, TypeError, ValueError):
            continue
        if not close > 0:
            continue
        bars.append({"t": stamps, "c": close})
    return bars


def clean(bars: list[dict], now: float | None = None) -> list[dict]:
    """A publisher's calendar-padded series -> one bar per business day.

    Three rules, each one a fact about the data rather than a smoothing choice:

    * **Weekends go.** Both registries repeat Friday's value across Saturday and
      Sunday. A padded Saturday is not a flat session; it is a day the fund did
      not strike a value, and a bar that never happened must not vote in a
      sixty-three-bar window.
    * **One bar per day**, the last value published for it. The BPI model ships
      duplicate stamps; two bars on one day would be two sessions that never
      happened.
    * **Nothing after today.** The BPI model pads a couple of days forward; a
      NAVPU stamped in the future is a price that has not been struck.

    Bars are returned oldest first. The trim to `HISTORY_DAYS` happens here too,
    so a publisher's ten-year archive is reduced to the window this project
    reads before it is stored rather than after.
    """
    stamped = time.time() if now is None else now
    today = int(stamped - (stamped % DAY))
    by_day: dict[int, float] = {}
    for bar in bars or []:
        try:
            stamps = int(bar["t"])
            close = float(bar["c"])
        except (KeyError, TypeError, ValueError):
            continue
        if not close > 0:
            continue
        day = stamps - (stamps % DAY)
        if day > today:
            continue
        if datetime.datetime.fromtimestamp(day, datetime.timezone.utc).weekday() >= 5:
            continue
        by_day[day] = close          # the last published value for that day wins
    if not by_day:
        return []
    cutoff = today - HISTORY_DAYS * DAY
    return [{"t": stamps, "c": by_day[stamps]}
            for stamps in sorted(by_day) if stamps >= cutoff]


# -- fetching --------------------------------------------------------------

def _get(url: str) -> str:
    """Read a public document as text. Raises `FundError` on any transport
    failure or non-JSON/HTML refusal, because neither is a fact about a fund."""
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 200:
                raise FundError("%s answered HTTP %s" % (url, response.status))
            return response.read().decode("utf-8", "replace")
    except FundError:
        raise
    except Exception as exc:                  # noqa: BLE001 - transport, any kind
        raise FundError("%s did not answer (%s)" % (url, exc))


def _fetch(entry: dict) -> list[dict]:
    """Ask the fund's own publisher for its series, and normalise it."""
    source, key = entry["source"], entry["key"]
    if source == "uitf":
        today = datetime.date.today()
        start = today - datetime.timedelta(days=HISTORY_DAYS + 60)
        body = _get(TOAP_URL % (start.isoformat(), today.isoformat(), key))
        try:
            document = json.loads(body)
        except ValueError:
            raise FundError("uitf.com.ph sent something that is not JSON")
        bars = _toap_bars(document)
    elif source == "pifa":
        bars = _pifa_bars(_get(PIFA_URL % key))
    elif source == "bpi":
        slug = BPI_SLUGS.get(key)
        if slug is None:
            raise FundNotFound("%r has no BPI Wealth page." % key)
        try:
            document = json.loads(_get(BPI_MODEL_URL % slug))
        except ValueError:
            raise FundError("BPI Wealth sent something that is not JSON")
        bars = _bpi_bars(document)
    else:
        raise FundError("unknown fund source %r" % source)

    cleaned = clean(bars)
    if not cleaned:
        raise FundError("%s published no usable NAVPU history" % entry["name"])
    return cleaned


def store_bars(code: str, bars: list[dict]) -> None:
    """Keep a fetched series for the next read. A failed write is not a failure:
    a cache that could not be written costs the next fetch, not this answer."""
    try:
        diskcache.store(CACHE_PREFIX + code.upper(), bars)
    except Exception:
        pass


def cached_bars(code: str) -> tuple[list[dict] | None, float]:
    """The stored series for a fund and how old it is; (None, 0) if none.

    Shared with `recent.py`, which reads the same copy for the table row: a fund
    chart and the row it was opened from must draw the same series, and two disk
    keys is how they stop doing that.
    """
    saved = diskcache.load(CACHE_PREFIX + code.upper())
    if saved is None:
        return None, 0.0
    fetched_at, bars = saved
    if not isinstance(bars, list) or not bars:
        return None, 0.0
    return bars, time.time() - float(fetched_at)


def series(code: str) -> tuple[list[dict], float, bool]:
    """One fund's bars, the age of the reading, and whether it is a fallback.

    The single path both callers take -- the sweep that builds a row and the
    chart route that draws it -- so the two cannot read different bars or
    disagree about how old they are:

    * a copy inside `CACHE_TTL` is used without asking anyone;
    * otherwise the publisher is asked, and a good answer is stored;
    * when the publisher does not answer, a copy up to `CACHE_KEEP` old is
      shown and the third element says so -- the row then prints how old the
      reading is instead of passing it off as today's.

    Raises `FundError` when the publisher did not answer and there is nothing
    worth showing, and `FundNotFound` for a code this module does not know.
    """
    entry = _BY_CODE.get((code or "").upper())
    if entry is None:
        raise FundNotFound("%r is not a Philippine fund." % code)

    bars, age = cached_bars(entry["code"])
    if bars is not None and age <= CACHE_TTL:
        return bars, age, False
    try:
        fresh = _fetch(entry)
    except FundError:
        if bars is not None and age <= CACHE_KEEP:
            return bars, age, True
        raise
    store_bars(entry["code"], fresh)
    return fresh, 0.0, False


def refresh(codes: list[str]) -> dict[str, dict]:
    """`series()` for several funds, from as few fetches as the sources allow.

    The TOAP and BPI documents are small and read in parallel; PIFA's pages are
    ~2 MB each and refuse parallel readers, so that source is read one fund at a
    time with a pause. A fund that could not be read maps to its exception, so
    the caller can tell "no series" from "not asked" and count it as missing
    rather than judging it bearish.

    A cached series needs no fetch at all, so on a warm cache this is a pass
    over memory and the concurrency never matters.
    """
    wanted = [code.upper() for code in codes if code]
    out: dict[str, dict | Exception] = {}

    def probe(code):
        try:
            bars, age, stale = series(code)
        except Exception as exc:              # noqa: BLE001 - reported per fund
            return code, exc
        return code, {"bars": bars, "age": age, "stale": stale}

    fast = [code for code in wanted if _BY_CODE[code]["source"] != "pifa"]
    slow = [code for code in wanted if _BY_CODE[code]["source"] == "pifa"]

    if fast:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(FAST_WORKERS, len(fast))) as pool:
            for code, answer in pool.map(probe, fast):
                out[code] = answer
    for code in slow:
        _, answer = probe(code)
        out[code] = answer
        time.sleep(PIFA_PAUSE)
    return out


# -- reading a series ------------------------------------------------------

def search_funds(needle: str, limit: int = 6) -> list[dict]:
    """Funds whose code or name matches `needle`, best first.

    The search box asks Yahoo, which has never heard of a Philippine fund, and
    the PSE and coin supplements next to this one exist for the same reason:
    what a source does not list, the page still has to be able to find. A match
    is every word of the query appearing in the code or the name, so "health"
    finds the health care feeder, "bpi equity" finds the two BPI equity funds
    and not the rest, and "PERA" finds the four retirement funds.

    Rows are shaped like the search route's other rows (`symbol`, `name`,
    `exchange`, `type`) so the suggest list draws them without a special case.
    """
    words = [word for word in re.split(r"[^a-z0-9]+", (needle or "").lower())
             if word]
    if not words:
        return []
    scored: list[tuple[int, str, dict]] = []
    for code, name, category, _source, _key, _currency in FUNDS:
        haystack = ("%s %s" % (code, name)).lower()
        if not all(word in haystack for word in words):
            continue
        # An exact code, or a code that starts with the query, is what the
        # reader most likely meant; everything else ranks by where the first
        # word lands in the name.
        if code.lower() == words[0]:
            rank = 0
        elif code.lower().startswith(words[0]):
            rank = 1
        elif name.lower().startswith(words[0]):
            rank = 2
        else:
            rank = 3
        scored.append((rank, code, {
            "symbol": symbol_for(code),
            "name": name,
            "exchange": "Philippine fund",
            "type": "Net asset value",
            "category": category,
        }))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [row for _rank, _code, row in scored[:limit]]


def price_hint(bars: list[dict]) -> int:
    """How many decimals this fund's NAVPU is published with, 2 to 4.

    A NAVPU's precision is decided by its manager, not by the reader: BPI's
    UITFs quote two decimals (221.22), ALFM's mutual funds four (48.1186), and
    printing a four-decimal fund at two would round away the only digits that
    moved this month. The last sixty bars are enough to see which it is, and the
    clamp keeps a publisher's stray float noise from asking for eight.
    """
    decimals = 2
    for bar in (bars or [])[-60:]:
        text = repr(float(bar.get("c", 0))).rstrip("0")
        if "." in text:
            decimals = max(decimals, len(text.split(".")[1]))
    return min(4, decimals)


def _chart_payload(code: str, bars: list[dict], span: str, interval: str,
                   stale: int = 0) -> dict:
    """One fund's bars -> the chart payload the page draws.

    The trim is `onset.window_now`, the same function the table row's walk
    asks, over the same window -- the project's rule for every source: a row's
    verdict must be computable from the window its chart draws.

    A weekly chart is not trimmed. A weekly bar spans five business days with
    its stamp on the week's last session, so comparing that stamp against a day
    boundary would amputate a bar that lies partly inside the window -- the same
    reason `server.slim_chart` leaves a weekly payload alone.
    """
    entry = _BY_CODE[code]
    ordered = sorted(bars, key=lambda bar: bar["t"])
    tail: list[dict] = []
    if interval == "1wk":
        ordered = _weekly(ordered)
        points = [{"t": int(bar["t"]), "c": round(float(bar["c"]), 6)}
                  for bar in ordered]
    else:
        points = [{"t": int(bar["t"]), "c": round(float(bar["c"]), 6)}
                  for bar in ordered]
        keep = onset_module.window_now([p["t"] for p in points],
                                       len(points) - 1,
                                       days=RANGE_DAYS.get(span, RANGE_DAYS["3mo"]))
        # The bars before the window, for `onset.decorate`'s steadiness reading.
        # The series is `HISTORY_DAYS` long, so a 90-day chart has months behind
        # it; a fund publishes one value a business day, so it carries no volume.
        tail = points[:keep[0]][-onset_module.LEAN_HOLD_BARS:]
        points = [points[i] for i in keep]
    if not points:
        raise FundNotFound("No NAVPU data for %s in this window." % entry["name"])

    try:
        call = trend.classify([p["c"] for p in points])
    except ValueError:
        call = None      # an unscorable series still draws; it just has no badge

    return {
        "symbol": symbol_for(code),
        "name": entry["name"],
        "currency": entry["currency"],
        # The meta line reads "symbol · exchange · type · via source", so the
        # two halves of the fund's identity are split between them: the market
        # it belongs to here, the registry it was read from in `source`.
        "exchange": "Philippine fund",
        "type": "Net asset value",
        "category": entry["category"],
        # A fund publishes an asset value, not a traded price: there is no
        # volume behind the newest bar, and the page must not imply one.
        "units": "NAVPU",
        "priceHint": price_hint(ordered),
        "previousClose": points[-2]["c"] if len(points) > 1 else None,
        "marketPrice": points[-1]["c"],
        "points": points,
        "historyTail": tail,
        "trend": call,
        # The page hides the research-judgment box for a series that is not a
        # traded price (it reads price history, and a daily-struck asset value
        # has none of the intraday or volume structure that box is built on).
        "fundSeries": True,
        "source": SOURCE_NAMES.get(entry["source"], entry["source"]),
        # Seconds the reading predates the request, when the publisher did not
        # answer and a stored copy was served instead. Zero for a fresh fetch or
        # a copy inside `CACHE_TTL`.
        "stale": stale,
    }


def _weekly(bars: list[dict]) -> list[dict]:
    """Business-day bars -> one bar per ISO week, the week's last session.

    Only for a weekly chart, which the page does not normally ask for; it exists
    so `interval=1wk` is an answer rather than a 404 -- the chart route allows
    it, and a fund that answered daily but refused weekly would be the only
    source in the project that did.
    """
    weeks: dict[tuple[int, int], dict] = {}
    for bar in bars:
        moment = datetime.datetime.fromtimestamp(bar["t"], datetime.timezone.utc)
        weeks[moment.isocalendar()[:2]] = bar
    return [weeks[key] for key in sorted(weeks)]


def _mark_stale(payload: dict, age: float) -> dict:
    """Say a payload was built from a stored reading, in the shape a rescue
    speaks (`cached`, `fetchedAt`, `cacheError`) -- the same three stamps
    `tv._mark_stale` adds, so the page dates the reading with one code path."""
    payload["cached"] = True
    payload["fetchedAt"] = int(time.time() - age)
    payload["cacheError"] = "the fund's publisher did not answer"
    return payload


def chart(symbol: str, span: str = "3mo", interval: str = "1d") -> dict:
    """The chart payload for one fund, from disk or its publisher.

    Raises `FundNotFound` for a symbol that is not a fund (a verdict about the
    symbol) and `FundError` when the publisher did not answer and no usable copy
    exists (an outage) -- the caller rescues the second from the chart cache like
    any other transport failure.
    """
    canonical_symbol = canonical(symbol)
    if canonical_symbol is None:
        raise FundNotFound("%r is not a Philippine fund." % symbol)
    code = canonical_symbol[len(PREFIX):]
    bars, age, used_fallback = series(code)
    payload = _chart_payload(code, bars, span, interval,
                             int(age) if used_fallback else 0)
    return _mark_stale(payload, age) if used_fallback else payload


def charts_many(symbols: list[str], span: str = "3mo",
                interval: str = "1d") -> dict[str, dict | Exception]:
    """`chart()` for several funds from as few fetches as the sources allow.

    The row warmer's leg: a click must find its fund's chart on disk, and the
    funds behind one sweep share their fetches instead of paying one apiece.
    Results are keyed by the spelling the caller asked with, and a symbol that
    could not be built maps to its exception, so the warmer can tell a verdict
    from a broken wire the way the other legs do.
    """
    asked: dict[str, str] = {}
    out: dict[str, dict | Exception] = {}
    for spelling in symbols:
        canonical_symbol = canonical(spelling)
        if canonical_symbol is None:
            out[spelling] = FundNotFound("%r is not a Philippine fund." % spelling)
        else:
            asked[canonical_symbol] = spelling
    if not asked:
        return out

    codes = [symbol[len(PREFIX):] for symbol in asked]
    answers = refresh(codes)
    for canonical_symbol, spelling in asked.items():
        code = canonical_symbol[len(PREFIX):]
        answer = answers.get(code)
        if not isinstance(answer, dict):
            out[spelling] = answer if isinstance(answer, Exception) else FundError(
                "no series for %s" % code)
            continue
        try:
            payload = _chart_payload(code, answer["bars"], span, interval,
                                     int(answer["age"]) if answer["stale"] else 0)
        except Exception as exc:          # a malformed series is this row's problem
            out[spelling] = exc
        else:
            out[spelling] = (_mark_stale(payload, answer["age"])
                             if answer["stale"] else payload)
    return out
