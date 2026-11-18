"""The chart route: one symbol, one range, one payload.

Split out of \`server.py\` on 2026-11-18. \`chart_key\` (the cache key a chart
is stored under), \`retry_sparse_research\` and \`chart_data\` (the route logic
every chart request and the warm-up go through) live here.

Every name is re-exported by \`server.py\`, and every function body reads the
server's names as \`S.x\`, so \`server.chart_data\` and
\`mock.patch.object(server, ...)\` keep working.
"""

from __future__ import annotations

import time
import urllib.parse

import coinsph
import crypto
import faults
import ondo
import onset as onset_module
import phfunds
import probability
import pse
import rates
import recent
import research_judgment
import trend
import tv

import server as S


def chart_key(symbol: str, span: str, interval: str) -> str:
    """The cache key a chart is stored under, for either upstream.

    Lifted out of `chart_data` because the row warmer needs to ask "is this
    symbol's chart fresh?" without going through the chart itself -- and the
    answer is only honest if it reads through the *same* key the chart writes
    through, the way `LEADERS_KEY` keeps `warm_routes` and `api_top` honest.
    The Yahoo leg is the URL itself; the PSE and bond legs are synthetic
    because TradingView has no URL to key on. A bond key is deliberately *not*
    the key its raw bars live under (`tv.BOND_CACHE_PREFIX`): the bars are
    shared with the recent table's row, the finished chart is not.
    """
    if tv.is_bond_symbol(symbol):
        return f"tv:{symbol.strip().upper()}:{span}:{interval}"
    if pse.is_pse_symbol(symbol):
        return f"pse:{symbol.upper()}:{span}:{interval}"
    if phfunds.is_fund_symbol(symbol):
        # The fund's own synthetic key, for the same reason the bond's is: the
        # bars live under their own key (`phfunds.CACHE_PREFIX`) because they
        # are shared with the recent table's row, and the finished chart is not.
        return f"fund:{symbol.strip().upper()}:{span}:{interval}"
    if ondo.is_ondo_symbol(symbol):
        # A token Yahoo has no spelling for at all (see `ondo.py`), so its chart
        # needs a key of its own; nothing else in the project stores a `ondo:`.
        return f"ondo:{symbol.strip().upper()}:{span}:{interval}"
    quoted = urllib.parse.quote(symbol, safe="")
    return (f"https://{S.CHART_HOST}/v8/finance/chart/{quoted}"
            f"?range={span}&interval={interval}")


def retry_sparse_research(symbol, data, answer, refs, now, fetch_pse, fetch_pse_peers):
    """Try longer same-source histories without changing the studied window or chart."""
    if pse.is_pse_symbol(symbol) or data.get("cached"):
        return answer
    if not any(answer.get(d, {}).get("reason") == research_judgment.TOO_FEW_WINDOW_BARS
               for d in ("bullish", "bearish")):
        return answer
    for span in ("2y", "5y"):
        try:
            history = S.chart_data(symbol, span, "1d")
            # Never combine feeds, identities, stale data or adjusted price
            # series. Re-evaluate the original window from one complete series.
            if (history.get("cached") or not data.get("symbol") or
                    str(history.get("symbol", "")).upper() != str(data["symbol"]).upper() or
                    history.get("source") != data.get("source") or
                    history.get("type") != data.get("type")):
                continue
            candidate = research_judgment.evaluate(symbol, history, refs, now,
                                                   fetch_pse, fetch_pse_peers)
            if any(candidate.get(d, {}).get("status") != "unavailable"
                   for d in ("bullish", "bearish")):
                return candidate
        except Exception as exc:
            faults.note("research retry", exc)
            # A failed research-only fetch cannot change the chart or invent a call.
            continue
    return answer


def chart_data(symbol: str, span: str, interval: str) -> dict:
    """The chart payload for one symbol, from cache or upstream.

    The route logic, lifted out of `Handler` so the startup prewarm can ask for
    the first paint's chart through the same code a request takes -- warming and
    serving cannot then drift apart. Validation stays in the route (bad input is
    a caller error, and the prewarm only ever passes constants).

    Raises LookupError (Yahoo "no such symbol") or `pse.PseNotFound` for a
    symbol no source knows; UpstreamError / `pse.PseError` for transport, which
    is a verdict about the network, not the symbol.
    """
    # A PSE symbol is served entirely from TradingView. Routed before the
    # Yahoo URL is even built, because Yahoo has no PSE equities: asking it
    # would spend a Moli round trip to earn a guaranteed 404.
    if tv.is_bond_symbol(symbol):
        # A Philippine bond yield has the same problem, one market over: Yahoo
        # quotes no Philippine yield at all, so the route would earn a 404 for
        # `TVC:PH10Y` -- a spelling Yahoo does not even tokenise as a ticker.
        # `tv.py` reads the series off the same TradingView socket the PSE rows
        # use, and the row that opened this chart was judged on that very
        # series (see `recent.bond_rows`), so the badge and the table agree.
        def bond_produce():
            return tv.chart(symbol, span, interval)

        data = S.cached(S.chart_key(symbol, span, interval), bond_produce)
    elif phfunds.is_fund_symbol(symbol):
        # A fund is the third instrument neither Yahoo nor TradingView quotes:
        # it has no ticker and no exchange, only the NAVPU its manager strikes
        # once a business day. Routed here before the Yahoo URL is built, for
        # the same reason the PSE and bond symbols are -- Yahoo would spend a
        # Moli round trip to answer 404 -- and drawn from the very series the
        # recent table's row was judged on (see `recent.fund_rows`), so the
        # badge and the row agree by construction.
        def fund_produce():
            return phfunds.chart(symbol, span, interval)

        data = S.cached(S.chart_key(symbol, span, interval), fund_produce)
    elif symbol.strip().upper().startswith(phfunds.PREFIX):
        # A `FUND:` spelling this module does not know is a verdict about the
        # symbol, not something to ask Yahoo about: Yahoo has never quoted a
        # Philippine fund, so the only thing a round trip could add is a
        # misleading "may be delisted".
        raise LookupError("%r is not one of the funds this page charts." % symbol)
    elif ondo.is_ondo_symbol(symbol):
        # A token neither Yahoo nor TradingView quotes: OUSG has no spelling
        # Yahoo's index or chart route answers at all (measured 2026-11-02 --
        # see `ondo.py`), so asking it would spend a Moli round trip to earn a
        # guaranteed 404. DeFiLlama prices the contract on chain.
        def token_produce():
            return ondo.chart(symbol, span, interval)

        data = S.cached(S.chart_key(symbol, span, interval), token_produce)
    elif symbol.strip().upper().startswith(ondo.PREFIX):
        # The same verdict the fund prefix earns: an `ONDO:` spelling this
        # module does not know is about the symbol, not about the wire.
        raise LookupError("%r is not one of the Ondo tokens this page charts."
                          % symbol)
    elif pse.is_pse_symbol(symbol):

        def pse_produce():
            return pse.chart(symbol, span, interval)

        data = S.cached(S.chart_key(symbol, span, interval), pse_produce)
    else:
        url = S.chart_key(symbol, span, interval)
        # What Yahoo is asked for, versus what the chart draws: one span wider,
        # so the badge has bars behind its window (`FETCH_SPAN`). The cache key
        # stays the requested span's URL, because that is the chart this entry
        # holds -- and the entry is the trimmed chart, not Yahoo's answer.
        fetch_url = S.chart_key(symbol, S.FETCH_SPAN.get(span, span), interval)

        def produce():
            # Yahoo's answer is the default, crypto or not.
            yahoo = None
            yahoo_error = None
            try:
                yahoo = S.yahoo_chart(fetch_url, symbol, span, interval)
            except LookupError as exc:
                yahoo_error = exc          # Yahoo has no such instrument
            # A transport failure is not a verdict about the symbol, so let it
            # propagate rather than quietly substituting another source.

            # Yahoo lists no `AEDPHP=X` or `SARPHP=X` at all (404), yet both
            # currencies have a dollar leg it charts (`AED=X`, `SAR=X`) and so
            # does the peso. A dollar-less cross Yahoo refuses is divided out of
            # those legs; a leg that is missing too leaves Yahoo's verdict.
            if yahoo is None and S.FX_CROSS_RE.fullmatch(symbol.upper()):
                pair = symbol.upper()[:-2]
                if "USD" not in (pair[:3], pair[3:]):
                    try:
                        return S.fx_cross_chart(symbol.upper(), span, interval)
                    except (LookupError, ZeroDivisionError):
                        pass

            # A bare futures ticker is not one of Yahoo's symbols -- the
            # Treasury contract is `ZB=F` -- so "zb" submitted straight from
            # the search box used to end in "no usable price data" for a
            # contract that charts perfectly well. Asked again as the contract,
            # and only after Yahoo refused the bare spelling: `UB` is a real
            # ETF and keeps its own chart. The payload names the symbol it
            # actually drew, so the meta line says where the price came from.
            if yahoo is None and isinstance(yahoo_error, LookupError):
                alias = rates.chart_alias(symbol)
                if alias:
                    try:
                        yahoo = S.yahoo_chart(
                            S.chart_key(alias, S.FETCH_SPAN.get(span, span),
                                      interval),
                            alias, span, interval)
                    except LookupError:
                        pass

            # Ask the crypto module for the coin's own chart once. It is both
            # the independent price for the disagreement test below and the
            # series to draw if Yahoo is quoting a different instrument --
            # and it is the very series the recent table's row was judged on.
            #
            # Measured 2026-11-10: BEAM-USD is a *different* coin on Yahoo
            # (0.00633 and falling, neutral) than the Beam the crypto index
            # and the table chart from Kraken (0.004288 and rising, bullish
            # +212%). The old test asked only `latest_close`, which answers
            # None while Binance's pair has stopped printing and is cached
            # for five minutes -- so Yahoo's different coin stood in silently
            # and the row and its chart disagreed. One chart read settles it
            # for a live coin and a delisted one alike. A pair whose every
            # venue is silent answers None here and Yahoo stands: a missing
            # fetch is not a verdict about the coin.
            coin = None
            crypto_tried = False
            if yahoo is not None and yahoo.get("type") == "CRYPTOCURRENCY":
                crypto_tried = True
                coin = crypto.try_chart(symbol, span, interval)

            if yahoo is not None and not S.yahoo_is_wrong(
                    symbol, yahoo, coin, tried=crypto_tried):
                # A cross with no dollar leg is one Yahoo composes rather than
                # charts, and its composed series carries a phantom weekly
                # "Sunday reopen" bar ~3% below the true cross -- the fix
                # snapshot is one per business day, so those bars cannot exist
                # there. Only such crosses route here: a USD-leg cross
                # (`USDPHP=X`) has genuine Sunday bars -- the FX week really
                # does open Sunday 21:05 GMT -- and keeps Yahoo's series.
                # None (an outage, or a pair outside the ECB set) leaves
                # Yahoo's chart standing rather than failing the symbol.
                if S.FX_CROSS_RE.fullmatch(symbol.upper()):
                    pair = symbol.upper()[:-2]
                    if "USD" not in (pair[:3], pair[3:]):
                        substituted = S.ecb_route(symbol, span, interval, yahoo)
                        if substituted is not None:
                            return substituted
                return S.fill_missing_days(yahoo, coin, interval)

            if coin is None and not crypto_tried:
                coin = crypto.try_chart(symbol, span, interval)
            if coin is not None:
                return coin
            if yahoo is not None:
                return yahoo               # disagreement, but nothing better
            raise yahoo_error

        try:
            data = S.cached(url, produce)
        except LookupError:
            # A bare token ticker is not one of Yahoo's symbols and Yahoo has no
            # spelling for the token at all, so "ousg" typed into the search box
            # and submitted without picking the suggestion ended in "No usable
            # price data" for an instrument the page can chart. Asked as the
            # token, and only after Yahoo refused the typed spelling -- the same
            # rule the Treasury contracts follow, so a listing that really
            # trades under the bare ticker keeps its own chart. The chart is
            # stored under the token's own key, so the second read of "OUSG"
            # costs nothing upstream.
            token_symbol = ondo.alias(symbol)
            if not token_symbol:
                raise
            data = S.cached(S.chart_key(token_symbol, span, interval),
                          lambda: ondo.chart(token_symbol, span, interval))

        # A currency cross Yahoo quotes but has no history for -- one bar,
        # not a series -- is divided out of its dollar legs instead. Guarded
        # on the snapshot shape, so a pair Yahoo does chart (EURUSD=X) keeps
        # its own series untouched. A missing leg is a verdict about the
        # legs, not the cross: fall back to Yahoo's snapshot rather than
        # failing the symbol. A leg *outage* is treated the same way: online
        # it means one wire hiccup costs the cross its series for a memo
        # lifetime, and offline it is the difference between the chart the
        # user clicked for and a 502 -- `fx_cross_chart`'s own contract is
        # "the caller treats every failure as serve what Yahoo gave", and
        # this block is that caller.
        if (S.FX_CROSS_RE.fullmatch(symbol.upper())
                and len(data.get("points") or []) < 2):
            try:
                data = S.fx_cross_chart(symbol.upper(), span, interval, data)
            except (LookupError, ZeroDivisionError):
                pass
            except S.TRANSIENT_ERRORS:
                # An outage during synthesis: the legs failed offline while
                # the cross's own copy was rescued, so `data` still carries
                # that stamped copy. Serving it beats failing the symbol,
                # and keeping it stamped keeps `cached`'s memo entry the
                # same shape a direct rescue would have produced.
                pass
            else:
                # Synthesis succeeded: persist the composed series under the
                # cross's own key, so the disk copy a later outage rescues
                # is the full chart and not the one-bar snapshot Yahoo
                # stores. A stale rescue is a chart, not a headline. The
                # stamps are stripped when `data` itself was a rescue -- the
                # disk copy is stored plain, the way `cached` would have.
                S._store_chart(url, {k: v for k, v in data.items()
                                   if k not in ("cached", "fetchedAt",
                                                "cacheError")})

    # The cache holds one shared dict; the range/interval stamps are per
    # response, so callers get a copy, never the entry itself.
    out = dict(data)
    # The peso pair's weekend, drawn from Coins.ph's USDC/PHP book: the FX week
    # is Monday to Friday, so a chart read on a Saturday or a Sunday otherwise
    # stops at Friday's close. Applied to the copy, after the memo, so the
    # Yahoo-only answer stays what is stored and a weekend bar is never
    # mistaken for a bar Yahoo published. Before the re-score below, because
    # the badge must read the series the plot draws.
    if interval == "1d" and coinsph.is_usd_php(symbol):
        out = S.weekend_proxy(out)
    # The session trading now, when Yahoo has not published a bar for it yet:
    # the chart draws that print as today's point instead of stopping at
    # yesterday's official close (see `live_point`). Before the re-score below,
    # because the badge reads the series the plot draws.
    if interval == "1d":
        out = S.live_point(out)
    if pse.is_pse_symbol(symbol) and out.get("source") == "TradingView" and not out.get("longTermContext"):
        out["longTermContext"] = {"status": "insufficient",
                                  "reason": "Longer history was not saved in this cached chart"}
    # Older offline chart copies contain the previous classifier's verdict.
    # Re-score the exact points drawn, so an outage cannot resurrect that call.
    points = out.get("points") or []
    try:
        call = trend.classify([p["c"] for p in points])
    except (KeyError, TypeError, ValueError):
        call = None
    # ... and then the one place the steady-lean rule is applied to a badge, so
    # the chart, the watchlist tag and the leaning table agree about the same
    # asset at the same moment (2026-11-07). The drawn window and the bars
    # behind it (`historyTail`, shipped by every producer that has them) are
    # handed over together; a series with no tail keeps its lean, because an
    # unanswerable question is not a negative one.
    if call is not None:
        drawn = [p for p in points
                 if isinstance(p, dict) and p.get("t") is not None
                 and p.get("c") is not None]
        tail = [p for p in (out.get("historyTail") or [])
                if isinstance(p, dict) and p.get("t") is not None
                and p.get("c") is not None]
        # Only when every drawn point can be read: a payload this code cannot
        # align is not one to decorate from, so the badge keeps its plain call.
        if drawn and len(drawn) == len(points):
            full = tail + drawn
            stamps = [int(p["t"]) for p in full]
            closes = [float(p["c"]) for p in full]
            volumes = [p.get("v") or 0.0 for p in full]
            yahoo_months = (S.SPAN_MONTHS.get(span)
                            if out.get("source") == "Yahoo" else None)
            call = onset_module.decorate(
                call, stamps, closes, volumes,
                months=yahoo_months,
                days=pse.RANGE_DAYS.get(span, pse.RANGE_DAYS["3mo"]))
    if out.get("yieldSeries"):
        # A bond yield's badge reads as a bond price, not as the yield's own
        # direction -- the same reversal the recent table's row makes, applied
        # here so a row and the chart its click opens cannot label one series
        # two ways. `yieldTrend` keeps the classifier's unreversed call beside
        # it, because "the yield rose" is the fact and "bonds bearish" is the
        # inference drawn from it.
        out["yieldTrend"] = call
        call = tv.bond_price_call(call)
    # A daily series the source has stopped printing is not a price now, and
    # nothing on this payload may say otherwise -- the same rule the table
    # applies before it judges a shelf name (see `recent.STALE_GAP_DAYS`, and
    # ATKR as the case that made it visible: three weeks of a frozen $94.96
    # charted as a close with a "leaning bullish" badge on it). The line is
    # still drawn -- it is the history that exists -- but the verdict and the
    # profit odds are withheld, because both are claims about now.
    #
    # Yahoo only, and daily only. The trading days of the US market are what
    # makes five days of silence meaningful; the PSE, the funds and the bonds
    # close for long holidays (see the constant), and a weekly bar is stamped
    # at the start of its week, so its age is not a session's.
    if interval == "1d" and out.get("source") == "Yahoo":
        drawn_stamps = [p["t"] for p in points
                        if isinstance(p, dict) and p.get("t") is not None]
        gap = recent.stale_gap(drawn_stamps)
        if gap is not None:
            out["staleDays"] = int(round(gap))
            out["staleBar"] = recent.utc_day(max(drawn_stamps))
            call = None
        elif "staleDays" in out:
            # A copy cannot keep a staleness claim it did not earn on this read
            # -- the same rule `lastBarBasis` follows: decided from the drawn
            # bars and the clock, never carried.
            out.pop("staleDays", None)
            out.pop("staleBar", None)
    out["trend"] = call
    out["range"] = span
    out["interval"] = interval
    # The last *finished* PSE session, in pesos: the newest drawn bar that is
    # not dated today in Manila, times its volume. Decided here, not in
    # `pse.chart`, for the same reason `lastBarBasis` is decided here -- a
    # payload fetched mid-session and served hours later (or tomorrow, from a
    # disk copy) must not keep reporting the day it was fetched on. Daily only:
    # a weekly bar's volume is a week's, so its product is not a trading day's
    # value. Every source but TradingView's PSE leg carries no `volumes`, and
    # `completed_trade` answers None for them, so the readout simply hides.
    if interval == "1d" and pse.is_pse_symbol(symbol):
        traded_day, traded_shares, traded_value = pse.completed_trade(
            out.get("points") or [],
            out.get("volumes") or [],
            now=time.time())
        out["tradedDay"] = traded_day
        out["tradedShares"] = traded_shares
        out["tradedTurnover"] = traded_value
    # Separate from the descriptive badge: project the drawn daily returns,
    # including mean-estimation uncertainty and assumed round-trip costs.
    # Withheld for a series that has stopped (`staleDays` above): an estimate
    # about the next three months of an instrument the source no longer prints
    # is an estimate about nothing.
    out["profitProbability"] = (None if out.get("staleDays") is not None
                                else probability.estimate(out))
    # What the newest bar's number is -- a live price, an extended-hours print
    # or a settled close -- decided from the payload and the clock *now*, so a
    # chart served from the memory memo or from a disk copy cannot claim to be
    # live on the strength of what was true when it was fetched.
    out["lastBarBasis"] = S.last_bar_basis(out)
    return out

