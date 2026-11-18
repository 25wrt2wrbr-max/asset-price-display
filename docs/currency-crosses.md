# Currency crosses

[Back to the README](../README.md)

## Currency crosses Yahoo fabricates

Ask Yahoo for `EURPHP=X` and it answers — with a series that was never traded.
Every week it prints a **"Sunday reopen" bar about three percent below** the
surrounding days (68.37 on 2026-10-04 against ~70.35 elsewhere; the same shape
on Sep 13, 20 and 27), then recovers Monday. FX does open Sunday evening, but
not at a 3% discount to Friday's close — the bars are an artifact of how Yahoo
composes a cross it has no real market for: it divides a stale peso quote by a
live euro quote, and over the weekend the peso leg goes stale while the euro
leg moves. `EURJPY=X` and `EURGBP=X` carry a milder version of the same
artifact.

Those crosses now take their **history from the ECB's daily reference rates**,
served keyless by the [Frankfurter](https://frankfurter.dev) API
(`api.frankfurter.dev`):

- **One fix per business day** — no weekend bars exist, so a phantom Sunday
  print is impossible. The chart shows weekdays only.
- **Any cross between the ~30 published currencies** works, because ECB
  quotes everything against the euro and the API triangulates
  (`JPYPHP=X` is the yen→peso cross, honestly composed).
- **Not a live quote.** The fix is one snapshot a day (~16:00 Frankfurt
  time), so the *headline price stays Yahoo's* — on a weekend it is the
  live quote, on a weekday evening it is fresher than Friday's fix — and
  only the bars beneath it come from the ECB. The chart's meta line reads
  `via ECB reference rates`.
- **Pairs with a dollar leg keep Yahoo** (`USDPHP=X`, `EURUSD=X`): their
  Sunday bars are genuine — the FX week really does open Sunday 21:05 GMT —
  and Yahoo's series for them is real. Pairs outside the ECB's 30
  currencies (e.g. `TWDPHP=X`) stay with Yahoo too. The peso pair's *weekend*
  is the one exception, and it is filled from a different venue — see the next
  section.

### Finding the crosses in search

Yahoo's *search* hides the same crosses its chart fabricates — differently.
Ask its search API for `krwphp` and it answers with `KRWPHP=X` (the
won→peso cross, a live quote and an ECB-charted history here). But ask it
for the currency alone and the cross vanishes: `krw` lists six other won
pairs (`KRW=X`, `JPYKRW=X`, `EURKRW=X`…) and not the peso cross; `jpy`
likewise lists `EURJPY=X`, `GBPJPY=X`… and omits `JPYPHP=X`. The omission is
Yahoo's index, not a search parameter — raising `quotesCount` or enabling
fuzzy matching returns the same seven rows — so `server.py` carries a small
hand-curated table (`FX_SEARCH_EXTRA`, the same approach as `pse.SYNONYMS`)
that adds the hidden cross when the query names one of its legs: `krw`,
`won`, `jpy`, `yen`, `php`, `peso`. Added rows are de-duplicated against
Yahoo's own and ranked by the same `relevance` sort as everything else, so
they surface where Yahoo showed nothing and never crowd a query Yahoo
already answers.

### Finding a ticker the index refuses (2026-11-02)

Yahoo's search does not only hide instruments — for some queries it **fails
outright**. Measured 2026-11-02, every spelling of `vtv` answered the search API
with **HTTP 500** on both query hosts, with and without parameters, and with
fuzzy matching on or off; the same instrument charted normally (`/v8/finance/
chart/VTV` → 200), resolved through `/v1/finance/quoteType/?symbol=VTV`, and
appeared third in the answer to `vt`. One index bug, not a missing instrument —
and 44 of 45 common tickers checked in the same pass answered normally, so it is
a quirk of that query rather than a general outage.

The search box had no way to reach it: the route raised on the 500 before any
supplement ran, so a reader typing `vtv` got an error, which the page renders as
no suggestions at all.

Two things changed, both in `server.py`:

- **A refused search is an empty answer, not a failed route.** The supplements
  (coins, PSE, funds, FX crosses, Treasury contracts) still answer, so one
  index hiccup can no longer blank a query they could have answered. A Moli
  failure — the browser itself — still raises, because that is not the index.
- **`probe_ticker` asks the chart route whether the query *is* a ticker.** It
  fires only when Yahoo returned no rows at all, only for a word shaped like a
  ticker (`VTV`, `BRK.B`, `BTC-USD`, `GC=F`, `^GSPC`, `JPYPHP=X`), and offers a
  row only for a symbol the chart route actually draws — with the name and venue
  that route reports (`Vanguard Morningstar Value ETF`, `NYSEArca`), and in the
  spelling it charts (`brk.b` is probed as `BRK-B`). A dead ticker still
  resolves to nothing, so this widens what is reachable without inventing rows.

A multi-word query is probed by its first word only when the rest names the
*kind* of thing wanted (`vtv etf`), so the fallback cannot turn prose into a
ticker: "the long bond" must never resolve to `THE`.

What this does **not** fix: a *name* query the index answers without the ticker.
`vanguard value` returns `VVIAX` and the tokenized `VTVON-USD` and no `VTV`,
because VTV is simply absent from that answer — no probe can recover a row the
index never offered.

### A token Yahoo has no spelling for (2026-11-02)

`OUSG` is Ondo's Short-Term U.S. Government Bond Fund token — a share of a T-bill
fund, traded on Ethereum and mirrored on Polygon and Solana. It is in **no** answer
Yahoo gives: `/v1/finance/search?q=ousg` returns an empty quote list, `/v1/finance/lookup?query=ousg`
reports `total: 0`, and the chart route 404s every spelling (`OUSG`, `OUSG-USD`,
`OUSG29256-USD`) — while the sibling `USDY29256-USD` does exist, so the index gap
is Yahoo's, not an outage. The VTV fallback above cannot help, because it asks the
chart route whether the query *is* a symbol and there is no symbol for this one to
be.

`ondo.py` supplies what Yahoo does not:

* **The price**, from DeFiLlama's coins API
  (`coins.llama.fi/chart/ethereum:<address>?span=N&period=1d`), plain HTTPS, no key.
  It agrees with CoinGecko to the sixth decimal (117.106259 on both, same minute);
  CoinGecko is only rejected as the bars source because its free tier allows five
  requests a minute. The endpoint caps a span at 500 days, so a longer range draws
  the 500 days that exist.
* **The search row**, shaped like Yahoo's own, carrying the `ONDO:` prefix — the
  same device `FUND:` and `TVC:` use, since a bare `OUSG` could one day be a real
  ticker. Every word of a query must appear in the token's ticker, name or aliases,
  so `ousg`, `ondo short term` and `short-term treasury` find it and `ondo qqq`
  (a Yahoo-listed Ondo stock) does not.
* **The chart**, keyed `ondo:ONDO:OUSG:<span>:<interval>`, routed before the Yahoo
  URL is built. A bare `OUSG` typed into the box charts too, but only after Yahoo
  refuses it — the `rates.chart_alias` rule — and the payload then names
  `ONDO:OUSG`, which the page's refresh clock and watchlist follow.

Two things the chart says about itself: its newest point is stamped at the request
and carries the price trading now, so the meta line reads *last bar is a live
price* (never from a disk copy — `server.last_bar_basis` refuses that word there);
and its profit odds use a `token` class — calendar days, a 0.20% round trip — because
a token trades every day and is swapped rather than subscribed. That number reads
**0.99**, which is the model applied to a series that steps upward almost in a
straight line, not a prediction; the tooltip carries the assumptions.

The instrument accrues, so a three-month window on it is essentially always
bullish — the same true statement the fund section makes about a money-market fund.

## The peso's weekend comes from Coins.ph (2026-11-01)

USD/PHP — `PHP=X`, which is also spelled `USDPHP=X` — is charted on the FX
week: Monday to Friday, closing Friday evening Manila time and reopening Monday
05:00. A reader who opens the peso on a Saturday or a Sunday therefore used to
see Friday's close and nothing after it, which is exactly when a Philippine
reader looks at the peso.

Those two days now come from **Coins.ph's USDC/PHP order book**
(`api.pro.coins.ph/openapi/quote/v1/klines`, Coinbase-Pro shaped): a venue that
trades every day, quoted in pesos, for the dollar-pegged token. `coinsph.py`
fetches 1,000 daily bars (back to 2024-02-06), keys each one by its **Manila
calendar day**, and splices in the Saturdays and Sundays Yahoo does not chart.

What was measured on 2026-11-01, so the number's standing is on the record:

- **Coverage:** 400 bars to 2025-09-28, every calendar day present — 57 of each
  weekday, Saturdays and Sundays included.
- **Level:** over 259 shared days the stablecoin ran a median **+0.09** and a
  mean **+0.13** pesos above the interbank rate (sd 0.20, range −0.29 to
  +1.50). That head is a domestic premium, not a rate; it is why a weekend bar
  carries the stablecoin's own price and the page names it, rather than being
  smoothed into Friday's close.
- **Movement, honestly:** across 51 measured weekends the stablecoin's
  Friday→Sunday change correlated **0.07** with the interbank's Friday→Monday
  change (same direction 27/51), with a 0.12% standard deviation against the
  interbank's 0.52%. The weekend book is quiet and domestic; the offshore
  market that reopens Monday is where the peso moves. The weekend bars say what
  a dollar cost in pesos on Coins.ph that day — they are not a forecast of the
  reopen.

Four rules the implementation keeps:

1. **Manila days decide what a weekend is.** Every stamp is read as the Manila
   calendar day it falls in, which is also what makes Yahoo's series line up:
   its Sunday 21:00 GMT reopen is *Monday* 05:00 in Manila, so a year of Yahoo
   bars holds 52 Mondays and 52 Fridays and no Sundays at all — and one stray
   Saturday, a forming bar carrying Friday's close under a Saturday stamp. That
   bar is **replaced**; a weekday never is. (Reading by UTC date instead gives
   22 Fridays and 30 Sundays in the same year — the off-by-one the Manila rule
   exists to avoid.)
2. **The fill runs to today, not to the last bar Yahoo drew.** On a Monday
   morning before 05:00 the FX series still ends on Friday, and a weekend that
   happened must not be missing because the other source has not caught up.
3. **The badge scores the bars the chart draws** (invariant 1). A three-month
   peso chart is 91 bars instead of 66 — 26 of them the stablecoin's — and
   `trend.classify` reads all 91. That is a longer window than the 63 daily
   bars the backtest validated, and it is stated here rather than hidden.
4. **The page says whose price a weekend point is.** `lastBarBasis` gains
   `weekend` on a weekend newest bar ("last bar is Coins.ph's USDC/PHP weekend
   price"), the meta line counts the proxy bars ("26 weekend bars are Coins.ph
   USDC/PHP"), a hovered weekend point reads `USDC/PHP` instead of "close", and
   the table caption says Saturday and Sunday rows are the stablecoin's price.

It is one fetch for every span (60 s, the chart's own clock; a week-old copy is
still served when the exchange does not answer, so the page can say how old the
weekend reading is). An outage is a no-op: the chart keeps the bars Yahoo drew.
Plain HTTPS answers this endpoint, so no browser is needed; `moli_fallback` is
registered as a net. A `2y` or `5y` chart is filled back as far as the 1,000
bars reach and stays Yahoo's before that.
