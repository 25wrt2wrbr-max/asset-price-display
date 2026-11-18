"""Currency charts Yahoo cannot be trusted with: ECB crosses and the weekend proxy.

Split out of server.py; behaviour unchanged. Every name here is re-exported from
`server`, and the code reaches its names through `S.`, so a test that patches
`server.<name>` still reaches it.
"""

from __future__ import annotations

import coinsph
import ecb
import trend

import server as S


def fx_cross_chart(symbol: str, span: str, interval: str,
                   snapshot: dict | None = None) -> dict:
    """Chart a currency cross Yahoo quotes but has no history for.

    `JPYPHP=X` answers with a live price and a single bar: a pair with no
    dollar leg has no series upstream. The legs that compose it do -- `PHP=X`
    and `JPY=X` are fully charted -- so the cross is divided out of them, both
    expressed per dollar: value of one quote-unit over value of one base-unit.
    Where Yahoo did answer with its own snapshot, that quote's name, currency
    and live price ride along, so the headline number stays Yahoo's even though
    the bars beneath it are composed.

    Raises LookupError when the legs share too few days to draw, and lets
    UpstreamError / ZeroDivisionError through from the legs; the caller treats
    every failure as "serve what Yahoo gave" rather than failing the symbol.
    """
    base, quote = symbol[:3], symbol[3:6]

    def per_usd(code: str) -> list[dict]:
        # `JPY=X` quotes yen *per* dollar, but `EUR=X` quotes dollars *per*
        # euro -- market convention, not a Yahoo quirk -- so those legs invert.
        data = S.chart_data(f"{code}=X", span, interval)
        return [{"t": p["t"], "c": 1.0 / p["c"]} if code in S.USD_QUOTED_BASES else p
                for p in data["points"]]

    base_pts, quote_pts = per_usd(base), per_usd(quote)
    quote_by_t = {p["t"]: p["c"] for p in quote_pts}
    points = [{"t": p["t"], "c": round(quote_by_t[p["t"]] / p["c"], 6)}
              for p in base_pts if p["t"] in quote_by_t]

    # Each leg's forming daily bar is stamped at its own fetch instant, so the
    # final stamps differ and strict alignment drops today's price. Both last
    # closes *are* today for a daily FX series, so re-append their cross.
    if base_pts and quote_pts:
        live_t = max(base_pts[-1]["t"], quote_pts[-1]["t"])
        if not points or points[-1]["t"] < live_t:
            points.append({"t": live_t,
                           "c": round(quote_pts[-1]["c"] / base_pts[-1]["c"], 6)})

    if len(points) < 2:
        raise LookupError(f"No shared history for {symbol!r}.")

    out = dict(snapshot or {})
    try:
        out["trend"] = trend.classify([p["c"] for p in points])
    except ValueError:
        out["trend"] = None
    out.update({
        "symbol": out.get("symbol") or symbol,
        "name": out.get("name") or f"{base}/{quote}",
        "currency": out.get("currency") or quote,
        "exchange": out.get("exchange") or "CCY",
        "type": "CURRENCY",
        "priceHint": out.get("priceHint") or 4,
        "previousClose": out.get("previousClose") or points[-2]["c"],
        "marketPrice": out.get("marketPrice") or points[-1]["c"],
        "points": points,
        "source": "Yahoo (USD legs)",
    })
    return out


def ecb_route(symbol: str, span: str, interval: str,
              yahoo: dict | None = None) -> dict | None:
    """The ECB payload for a no-USD-leg cross, with Yahoo's headline kept.

    Yahoo fabricates a weekly "Sunday reopen" bar for crosses it does not
    really chart (`EURPHP=X` printed 68.37 on 2026-10-04 against ~70.35
    elsewhere -- a three percent dip that no market ever traded). The ECB's
    daily fix is the honest series: one rate per business day, so a phantom
    Sunday bar is impossible, and Frankfurter serves it keyless. `ecb.chart`
    raises EcbError on a wire failure (an outage -- rescued from disk like any
    other) and LookupError when the pair is outside the ECB's 30 currencies
    (a verdict -- None, and the Yahoo chart stands).

    The bars are ECB's; the headline stays Yahoo's where Yahoo has one. The
    fix is a once-a-day snapshot, so a weekend headline Yahoo quotes live --
    today's 70.266 -- is more current than Friday's fix, and the payload keeps
    Yahoo's name and currency so the page renders the instrument identically.
    Yahoo's *trend* is not kept: it was scored over the fabricated bars, and
    a badge scored on phantom dips is the artifact the reader is looking at.

    Returns None when ECB has nothing (or the wire failed), and the caller
    serves Yahoo's answer -- the same contract `crypto.try_chart` speaks.
    """
    try:
        data = ecb.chart(symbol, span, interval)
    except LookupError:
        return None
    except ecb.EcbError:
        return None
    if yahoo:
        keep = yahoo.get("marketPrice")
        if isinstance(keep, (int, float)) and keep > 0:
            data["marketPrice"] = keep
        # `previousClose` deliberately not kept: it belongs to the same
        # fabricated snapshot the bars do (Yahoo quoted 72.518 against a
        # series that closed 70.475), and a headline change computed from it
        # would show the phantom dip the ECB bars exist to remove. The ECB
        # payload's own `previousClose` -- the second-to-last fix -- stands.
        for field in ("name", "currency", "symbol", "priceHint"):
            if yahoo.get(field) is not None:
                data[field] = yahoo[field]
    return data


def weekend_proxy(card: dict) -> dict:
    """Fill a peso-pair chart's Saturdays and Sundays from Coins.ph's USDC/PHP book.

    The FX week is Monday to Friday, so a USD/PHP chart drawn on a weekend ends
    on Friday's close and shows nothing of the two days since -- which is
    exactly when a Philippine reader looks at the peso. `coinsph.py` supplies
    those two days from the stablecoin's own peso book: the same instrument's
    question ("what is a dollar worth in pesos?") answered by a venue that
    trades through the weekend, at its own price rather than Yahoo's.

    Three rules, all of them the reader's to check against the payload:

    * The bars are the stablecoin's closes, and `weekendProxy.stamps` names every
      one of them, so the page can say whose price a point is instead of letting
      it pass for an interbank close.
    * A weekday is never touched, and a *weekend* day Yahoo drew is replaced --
      that bar carries Friday's close under a Saturday stamp (see `coinsph`),
      which is the gap being filled.
    * An outage is a no-op. Nothing here can turn a working chart into an error,
      and a chart that cannot be filled is still the chart Yahoo drew.

    The badge is re-scored downstream, on the points this returns, so the label
    and the line stay one series (invariant 1). The window is longer for it --
    a three-month FX chart gains about 26 bars -- and that is stated here rather
    than hidden, because a 91-bar window is not a 63-bar one.
    """
    points = card.get("points") or []
    if not points:
        return card
    try:
        filled, stamps, age = coinsph.fill(points)
    except coinsph.CoinsError:
        return card               # an outage, not a verdict: draw what Yahoo gave
    if not stamps:
        return card

    out = dict(card)
    out["points"] = filled
    out["weekendProxy"] = {
        "source": "Coins.ph",
        "pair": "USDC/PHP",
        "stamps": stamps,
        "price": next(p["c"] for p in reversed(filled) if p["t"] == stamps[-1]),
        # Seconds since the stablecoin series was read: a weekend reading is a
        # daily close, so an old copy is reported as old rather than reprinted
        # as this minute's.
        "age": int(age),
    }
    return out
