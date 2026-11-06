# Asset price display

A local web page that charts the last three months of an asset's price and
labels the trend — bullish, bearish, or neutral — from a weighted-signal
ensemble of four price-based signals, using the same weights at every window length.

Search any symbol Yahoo Finance knows: equities (`AAPL`), ETFs (`SPY`), crypto
(`BTC-USD`), currencies (`EURUSD=X`), indices (`^GSPC`), futures (`GC=F`, and
the Treasury curve — `ZB` or "30-year treasury bond").
Keep a watchlist in the sidebar with live quotes — chart anything, then press
**Add to watchlist**. Table view, tooltip crosshair, keyboard navigation,
light/dark mode.

Three things Yahoo cannot serve at all are charted from elsewhere: coins Yahoo
gets *wrong* (the ticker collision under
[Crypto that Yahoo gets wrong](#crypto-that-yahoo-gets-wrong)) come from
Binance, Philippine Stock Exchange listings (Yahoo carries none of them —
see [Philippine stocks](#philippine-stocks-yahoo-carries-none)) come from
TradingView, and currency crosses with no dollar leg (`EURPHP=X`, `EURJPY=X` —
see [Currency crosses Yahoo fabricates](#currency-crosses-yahoo-fabricates))
get their history from ECB reference rates. The chart's meta line always names
the source it used. One instrument Yahoo has no spelling for at all — `OUSG`,
Ondo's short-term Treasury fund token — is priced from its on-chain market
instead (see [A token Yahoo has no spelling for](#a-token-yahoo-has-no-spelling-for-2026-11-02)).

Below the chart: the two most-traded tables, [Most traded crypto — 24
hours](#most-traded-crypto--24-hours) — the day's heaviest coins, kept only
where the trend call is bullish and the rolling day is up —
[Bullish Philippine stocks](#bullish-philippine-stocks) — every PSE listing the
trend call likes right now, dated to the day its run started — and
[Recently bullish assets](#recently-bullish-assets), one table across US stocks,
Philippine stocks, crypto, the US Treasury futures and the Philippine
government bond yields, every row dated to the day its run began.

![stack](https://img.shields.io/badge/deps-none-brightgreen) Python 3 stdlib on
the server, vanilla JS in the page — no `pip install`, no `npm install`, no
build step.

## Run it

From the project directory:

```sh
python3 server.py
```

Then open **<http://127.0.0.1:8000/>** in your browser.

The page loads `BTC-USD` on start; type a symbol (or pick from the suggestions)
and press **Show chart**. There is one search box and one place to add: press
**Add to watchlist** in the chart header to save the charted asset, and press it
again to remove it.

Options:

```sh
python3 server.py 8080              # run on another port
MOLI_BIN=/path/to/moli python3 server.py   # point at a different Moli binary
```

Stop with `Ctrl-C`.

## Requirements

| | |
|---|---|
| **Python** | 3.8 or newer. Nothing to install. |
| **Moli** | Required for Yahoo price data, the PSE histories and the bond yields. Not needed for crypto (Binance, Kraken), currency fixes (ECB) or the Philippine funds — their registries answer plain HTTPS. Put the `moli` binary on `PATH`, or set `MOLI_BIN` to its path. |

Moli is the only real dependency, and it is not optional for Yahoo-sourced or
PSE symbols — see below. (The CoinGecko/Binance/Kraken crypto path does *not* use
it, and neither does PSE *search*, which needs no browser.)

### Why Moli is required

Yahoo's chart API cannot be reached by an ordinary HTTP client:

- `curl` and `urllib` get **HTTP 429 Too Many Requests**, with or without a
  browser User-Agent.
- Yahoo sends **no `Access-Control-Allow-Origin`** for an arbitrary origin, so
  the page cannot call it directly from the browser either.
- Moli — a real browser — gets **HTTP 200**.

So the browser asks `server.py`, and `server.py` asks Moli. Yahoo *does* allow
CORS from its own origins, so the server loads a cheap Yahoo page and calls the
API from inside it. That is also why the response keeps its true status code.

If Moli is missing, the page still loads but every chart shows a data error.
Check with the health route:

```sh
curl http://127.0.0.1:8000/api/health
# {"ok": true, "moli": "/Users/.../moli", "moliFound": true,
#  "online": true, "reconnections": 0, "watchlist": ["AAPL", "BTC-USD"]}
```

`"moliFound": false` means the path is wrong — set `MOLI_BIN`.

Install Moli from its latest release: <https://github.com/lexmount/moli/releases/latest>. The macOS installer is `moli-installer.sh` on that page.

## Files

| File | Role |
|---|---|
| `server.py` | Static file server + Yahoo proxy + the background sweeps. Routes: `/api/chart`, `/api/search`, `/api/top`, `/api/bullish`, `/api/cryptobull`, `/api/recent`, `/api/health`, and `POST /api/watch` (the page declaring its watchlist). |
| `markets.py` | The two most-traded tables (TradingView scanner) and the PSE board-lot table. |
| `crypto.py` | Coin identity (CoinGecko) and bars (Binance, or Kraken for a coin Binance has delisted) for coins Yahoo gets wrong. |
| `cryptobull.py` | The most-traded crypto of the last 24 hours, filtered to the bullish ones. |
| `ecb.py` | ECB daily reference rates (via the Frankfurter API, no key) for currency crosses Yahoo fabricates — the honest history for pairs with no dollar leg. |
| `coinsph.py` | Coins.ph's USDC/PHP daily bars — the peso pair's Saturdays and Sundays, the two days the FX week does not trade. |
| `ondo.py` | The Ondo tokens Yahoo has no spelling for — OUSG, the short-term Treasury fund token: its on-chain identity, the DeFiLlama price series, the `ONDO:` chart route and the search rows that make it findable. |
| `pse.py` | PSE universe (TradingView scanner) and bars (the browser-backed TradingView chart socket) for Philippine listings Yahoo does not carry — and the socket `tv.py` borrows for the bond yields. |
| `bullish.py` | Every PSE stock that is bullish now, each dated to the bar its run began on. |
| `onset.py` | The shared "since when" walk — one window, one label, one answer to *when did this turn?* — plus `turn`, which says *why* (`turn` / `flat` / `against`). |
| `recent.py` | The combined "recently bullish assets" table: US stocks, Philippine stocks, crypto, the US Treasury futures, the Philippine bond yields and the Philippine funds, each dated. |
| `rates.py` | The US Treasury futures curve — the seven contracts (ZT through UB), the search rows that make each one findable by ticker, tenor or desk name, and the bare-ticker chart alias. |
| `phfunds.py` | The Philippine funds (BPI Wealth UITFs, ALFM and Odyssey funds, the PERA funds): their daily NAVPU series, read from the registry that publishes each one, and the chart a fund row opens. |
| `tv.py` | The Philippine government bond yields — which TradingView symbols they are, their daily bars, and the chart a bond row opens. |
| `trend.py` | Classifies a price series as bullish / bearish / neutral. Stdlib math only. |
| `diskcache.py` | Durable on-disk copy of every upstream answer under `.cache/`, so a dead wire serves the last good result instead of an empty table. |
| `index.html` | The whole frontend — markup, CSS, chart rendering in vanilla JS. |
| `jpy-php.html` | Standalone single-page chart for one currency cross (`JPY→PHP`), separate from the main app. |
| `CLAUDE.md` | Working notes for an agent: the invariants that must not drift, where each market's bars come from, and how to verify a change. |
| `AGENTS.md` | The same working notes for a non-Claude agent. |

## The chart on screen

### It re-reads itself — every minute while the price is moving

While the newest bar is a price still moving — `lastBarBasis` `live`, `pre`
or `after` (a US stock in or around its session, a coin at any hour) — the
chart and its trend badge re-read every minute (`CHART_LIVE_TTL`, the
server's own 60 s chart cache), so the verdict follows the market in real
time. Once the newest bar is a settled close, the slow clock
(`CHART_TTL = 900 * 1000`) is enough. Visible tabs only; a tab brought back to
the front re-reads at once. Binance coins now keep the day still trading as
their newest bar (`liveLastBar`), so a coin's badge includes today's price.

A real-time badge would be useless if one print could flip it; the hold band
described under "The trend badge" is what makes it safe — a one-sigma move in
the newest price changes the label 0.4% of the time (version 1: 9.3%).

The refresh is silent: no dimmed plot, no "Loading…", no disabled button, and a
background refresh that *fails* changes nothing on screen, including the status
line. Every load carries a sequence number, so a slow answer that a newer request
has already replaced is dropped rather than drawn, and only the newest
reader-initiated request owns the busy state. A quiet refresh can still report one
thing: a disk fallback ("data last retrieved …"), because that is the fact the
reader must not miss.

The server's chart cache is 60 s (`CACHE_TTL`), so a tick of this timer always
reaches the source — this is a real refetch, not a re-render of a memo.

### The newest bar includes after-hours trading

Yahoo's daily bars are regular-session closes: the last bar stops at the 16:00
bell. The **newest** bar is drawn instead at Yahoo's `fulldayPrice` — that same
session with pre- and after-hours folded in — while every older bar keeps its
official close. Once a newer session exists, yesterday's bar reverts to its close
by itself; only the last bar is ever patched.

`server.full_day_close` decides, and leaves the plain close in three cases:

* the instrument has no extended session (`hasPrePostMarketData` is false —
  crypto, FX, futures, mutual funds, every PSE name);
* the payload carries no usable `fulldayPrice`;
* the extended print belongs to a **newer session than the last bar**. This is
  the pre-market case: on a Monday morning `fulldayPrice` can already be Monday's
  08:00 print while the daily series still ends at Friday. The guard compares
  `currentTradingPeriod.regular.start` with the bar's stamp as calendar dates in
  the exchange's own timezone, and refuses if it cannot do that comparison.

The patch lives in `yahoo_bars`, the one function the chart and the recent
table's US legs both read bars through, so [one definition of
"bullish"](#one-definition-of-bullish-one-definition-of-since-when) survives: the
badge scores the extended price exactly as the plot draws it. `slim_chart` ships
`extendedLastBar`, so a post-market print is never mistaken for the official
close — and, next to it, what the figure actually *is* at the moment you read it
(see below).

Two snapshots of a moving extended session can differ by cents — a row swept at
10:05 and a chart drawn at 10:07. On 2026-10-31 every direction agreed across all
29 US rows of the recent table, 26 prices agreed exactly, and three differed by a
few cents (widest: TSLA, 8.5¢).

### A finished session whose close Yahoo has not published (2026-10-31)

Yahoo can answer a **completed** session's daily bar with `open`, `high`, `low`
and `volume` filled in and `close` left **null**, while its own headline
`regularMarketPrice` already carries that session's close. Verified on
2026-10-31, the Saturday after the 2026-10-30 close: SPY, AAPL, MSFT, KO and XOM
all ended at a Friday bar with a null close, and the prior sessions were intact.

A null close used to be indistinguishable from a gap — a holiday row — so such a
bar was dropped. Dropping a *session* amputates the newest bar: the chart ended a
day early, the badge scored 64 bars ending 10-29, and every US table row was a
session behind. KO read **neutral +0.2183** while the same classifier on the same
window including Friday reads **bullish +0.2930** — the figure the same four
components produce on any other calculator.

`server.session_close` now fills the newest bar from the payload's own
`regularMarketPrice`, in `yahoo_bars`, so the chart, the badge, the recent table
and the watchlist all move together. It refuses rather than inventing a close:

* no usable positive `regularMarketPrice` or `regularMarketTime`;
* the price's **calendar day** in the exchange's timezone is not the bar's — this
  is what keeps a Monday pre-market print off Friday's bar, the mirror image of
  `full_day_close`'s guard;
* the bar shows no session at all (no volume, no high/low). A mutual fund is the
  one exception: its row is a published NAV, not a traded bar, and Yahoo can hold
  the day's NAV in `regularMarketPrice` for hours before filling the row (VFIAX on
  10-31: an all-null 10-30 row, `regularMarketPrice` 699.87 stamped 20:08 New York
  time). The day guard still has to pass, so a weekend row cannot borrow Friday's
  NAV;
* both `low` and `high` are usable and the price sits outside them.

Only the newest stamped bar may be filled: an older null close stays a gap.
Checked after the change: all 50 US tickers in the recent table's universe match
their own chart's badge and newest price, VFIAX and SWPPX gain their 10-30 NAV,
and the FX, futures, crypto, PSE, bond and fund paths are untouched.

### The session trading now has no bar yet (2026-11-03)

Both folds above only reach the newest *bar*, so they only work when that bar is
the session that is trading. From the 16:00 bell until the next day's daily bar
appears, the chart's newest bar belongs to an **older** session, and the market
moving on it was invisible: measured 2026-11-03 at 04:15 New York, AAPL had
printed **322.13** in pre-market against a Monday close of **338.32**, and the
page showed 338.32 labelled "close" while Ondo's `AAPLon` quoted 322.13 × 1.0034
shares per token = 323.2. `fulldayPrice` already held 322.13 — the day guard
correctly refused to date it to Monday's bar — and nothing drew it anywhere.

`server.live_print` takes that price out of the bars, and `server.live_point`
(pure read time, on a copy, next to the weekend proxy) appends it as the newest
point:

* stamped at the session's **regular open**, which is exactly where the day's
  real bar will land — so the real bar replaces it rather than sitting beside it;
* drawn only while one of *that session's* `pre`/`post` windows is open now. From
  20:00 to 04:00 New York Yahoo folds nothing and reports the regular close
  again, so nothing is added and the newest bar keeps its own close. That stretch
  is a gap in the source and is not papered over by repeating a close as a live
  price;
* worded by the clock, never "close": `pre` before/during the regular session,
  `after` once it has closed. A memo or disk copy served into the next window
  therefore cannot relabel it;
* never taken from a disk fallback (`cached`), which would invent a price for a
  session that copy never saw;
* refused when the newest bar is more than `LIVE_BAR_GAP_DAYS` (5) old — a halt
  or a dead listing is not a session that is trading.

Checked live 2026-11-03 04:15 New York: `/api/chart?symbol=AAPL` → 66 points,
`lastBarBasis: "pre"`, `livePrint {t: 1793716200, c: 323.2}`; the page reads
`$323.20`, "last bar is a pre-market price", badge Neutral +0.145, odds 0.66.
BTC-USD still `live`, PSE, bonds, funds still `close`. The recent table's US rows
keep scoring completed bars — a partial pre-market print is not a bar — so a row
and the chart can disagree on the newest *price* during an extended window; the
badge on both is still one `trend.classify` call over their own bars.

### Hovering a point says whether it is a close, a live price or after-hours (2026-10-31)

The tooltip under the crosshair used to label every point "close", which was
wrong twice over: the newest bar of a chart can be the price trading right now,
and it can be the last extended-hours print. Each point now says which:

| Label | When | The number is |
|---|---|---|
| `close` | any bar but the newest; or the newest one outside every session window while nothing is trading | that session's official close |
| `live` | the newest bar, its regular session is open, and a trade printed in the last 30 minutes | the last trade |
| `pre-market` | the newest bar, an extended print was folded in, and the pre-market window is open — or the newest *point* is today's date carrying the session's print before/during its regular hours | the last pre-market trade |
| `after-hours` | the same fold, with the post-market window open — or that point once the regular session has closed | the last after-hours trade of that session |

`server.last_bar_basis` makes the call from the payload's own
`currentTradingPeriod` — Yahoo's pre, regular and post windows — plus
`regularMarketTime` for the live case, and `slim_chart` ships the window as
`session`. Two things it deliberately does not do:

* **It does not trust the price to say it.** Once the extended session ends,
  Yahoo stops folding the after-hours print in and reports the regular close
  again — AAPL read `344.807` through the post session on 2026-10-30 and
  `344.63` after it — so a bar outside those windows is a close however it was
  fetched, even though `extendedLastBar` is still true.
* **It does not take an open window for an open market.** Yahoo models a
  nearly round-the-clock instrument as a whole calendar day, so a future's
  window still covers a Friday evening after the exchange has shut for the
  weekend; the 30-minute print bound (`LIVE_PRINT_MAX_AGE`) is what separates
  the two, and GC=F correctly reads `close` on that Friday night while BTC-USD
  reads `live`.

The call is made at **read** time, in `chart_data`, not at fetch time, so a
chart served from the 60-second memo or from a disk copy cannot still claim to
be live an hour later. Sources with no session of their own — a fund's NAVPU, a
bond yield, a PSE row, a Binance bar kept only once its close time had passed —
ship no window and read as `close`; a fund prints `NAV`, because no trade
happened at that number. The same word rides the meta line ("last bar is the
after-hours price"), the table view's caption and the newest row's hover, so the
keyboard- and screen-reader-clean twin says what the plot says.

### The delta under the price is the window's move (2026-10-31)

The line under the hero price used to be the last session's move against the
previous close — a one-day figure sitting under a three-month chart. It is now
the **window's** move: the first bar the plot draws to the latest close, labelled
with the bar it starts from, because a bare "+12.95%" beside a price otherwise
reads as today.

> ▲ +$40.00 (+12.95%) three-month move, since Jul 31

The full span is on the line's hover ("Three-month change, Jul 31 to the latest
close"). Those are the same two bars the watchlist rail's percentage and the
[recent table](#recently-bullish-assets)'s rows already measure, so the headline
figure and the row for the same instrument cannot disagree about the three
months: charting AAPL shows +12.95% since Jul 31, and its rail row shows
▲ +12.95% with the same tooltip.

**A yield is different in wording, not in arithmetic.** A bond chart plots the
rate, so its delta prints percentage points (`+0.583 pt, +8.80%`) and reads
"yield move" rather than "three-month move" — a percentage of a percentage
would be a figure about nothing. The badge below still reads the series as a
bond price, so a rising yield is Bearish, and the trend note says why.

## Crypto that Yahoo gets wrong

Yahoo's ticker namespace collides with the crypto one, and it resolves the
collision badly. `JUP-USD` on Yahoo is **Jupiter Project**, a dead 2017 token at
`$0.00036`; the instrument people mean by "Jupiter" is the Solana DEX token
(`jupiter-exchange-solana`, ~`$0.34`), which Yahoo does not carry at all. So the
symbol charts the wrong coin *and* the right one cannot be searched for.
Coinbase is no better — its `JUP-USD` is a third, delisted token.

So a second source fills the gap, split by what each is good at:

| | Source | Why |
|---|---|---|
| Identity | CoinGecko `/coins/markets` | ranks coins by market cap, which is what separates the real Jupiter (rank 78) from the dead one (~4234) |
| Bars | Binance `data-api.binance.vision/api/v3/klines` | OHLCV with real volume, no key, no rate limit |
| Bars, when Binance has delisted the pair | Kraken `/0/public/OHLC` | still trades the coin, and the bars say so |

Crypto asks Binance's **market-data mirror**, `data-api.binance.vision`, not
`api.binance.com`: the main host answers HTTP 451 *"Service unavailable from a
restricted location"* in some regions (above all, the US), and since the same
host serves the pair list, that one block used to look like "Binance lists
nothing" — every coin failed the `USDT` check, so the search box lost all crypto
additions and nothing ever rerouted. The mirror serves identical payloads on the
same paths, without the geo gate.

Neither needs Moli: both answer plain HTTP clients with permissive CORS, unlike
Yahoo.

**A listed pair is not a trading pair.** Binance keeps a delisted pair in
`ticker/price` at its last price forever, so `XMRUSDT` still answered `$118.70`
on 2026-11-03 while Monero traded at `$625.94` — and its newest kline was
`2024-02-20`. Because the ticker "resolved to a chartable coin", `XMR-USD` drew
that 2024 window under today's date. Measured the same day, 132 of the top 250
had a `USDT` pair and five were dead: XMR (2024-02-20), DAI (2020-08-12), BTT
(2022-01-17), BEAM (2023-01-26), LIT (2025-02-10). The fix is in the bars, not in
a list: `crypto.STALE_BAR_DAYS` (5) of silence means the pair is not trading, and
the coin is then read from **Kraken**, which answers for all five with a bar
stamped today (`XMRUSD` `$624.60`, `BTTUSD` `3.63e-07`, `BEAMUSD` `$0.004076`,
`LITUSD` `$0.0931`, `DAIUSD` `$0.99958`). When neither venue trades the coin,
nothing is drawn rather than something old — the chart route then keeps Yahoo,
which is current for `XMR-USD` and honest about having nothing for `BTT-USD`
(whose Yahoo series is three months of zeros).

**Only crypto Yahoo gets wrong is rerouted.** The test is objective, not a
name heuristic: Yahoo must report `instrumentType == CRYPTOCURRENCY` *and*
disagree with the venue's last close by more than 20% (`REROUTE_GAP` in
`server.py`). Jupiter is ~1000× off, so it reroutes; `BTC-USD`, `ETH-USD` and
`SOL-USD` agree to a fraction of a percent, so they stay on Yahoo — by design.
A symbol Yahoo 404s on but Binance lists (e.g. `PEPE-USD`) reroutes too, so this
fixes more than Jupiter. A delisted pair contributes no such comparison at all
(`crypto.latest_close` answers None), which is what stopped the frozen `$118.70`
from making Yahoo's live `$625.94` look like the wrong instrument.

Two limits worth knowing:

- **Binance lists ~133 of the top 250 coins** with a `USDT` pair. A coin in the
  index is not automatically chartable — `CRO` and `LEO` have no USDT pair and
  stay with Yahoo. The count is a snapshot; the pair list moves.
- **CoinGecko's free tier is 5 requests/minute** (`x-ratelimit-limit: 5`; a sixth
  rapid call returns 429). That is fine for one cached identity lookup and
  hopeless for type-ahead, so the index is fetched at most once an hour and
  Binance serves the per-request work. On a 429 the last good index is served
  rather than failing, so the search box never blanks.

A rerouted symbol keeps that identity when it is added to the watchlist: the
Add button takes its symbol and name from the chart payload, not from typed
text, so what lands in the rail is the same coin the chart drew.

Everything else — equities, ETFs, FX, indices, futures, and the crypto Yahoo
gets right — still comes from Yahoo through Moli.

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

## Philippine stocks Yahoo carries none of

Yahoo has **no PSE equities at all**. `TEL.PS`, `JFC.PS`, `ALI.PS`, `SM.PS`,
`BDO.PS` and every other Philippine listing return *"No data found, symbol may
be delisted"* — HTTP 404 — and searching the company names returns foreign
shells instead: `AYAAF` (Ayala, OTC), `BDOUY` (BDO, OTC), `PHI` (a NYSE
closed-end fund, for PLDT). The one survivor is the index itself, `PSEI.PS`,
which charts fine — which is why the gap reads as *"the index is there but no
stocks are"*.

TradingView carries the whole exchange, so it fills the gap, split by what each
route is actually able to do:

| | Route | Reached by |
|---|---|---|
| Universe / search | `POST scanner.tradingview.com/philippines/scan` | plain HTTP |
| Daily/weekly bars | `wss://data.tradingview.com/socket.io/websocket` | **Moli's browser only** |

That split is not a preference, it is what answers. Search backs a type-ahead
box, and the scanner replies to an ordinary HTTP client in half a second, so it
never pays for a browser. History has no HTTP route: stooq 403s on `tel.ph`,
`pse.com.ph` is behind Cloudflare (403, and it blocks the browser too), the old
`phisix-api` appspot service is discontinued (503), and investing.com is
Cloudflare-gated. The websocket is the only thing that returns daily bars.

**Symbols are keyed `PSE:TEL`, not `TEL.PS`.** A bare ticker is not globally
unique — `TEL` is TE Connectivity on the NYSE, which Yahoo charts correctly and
which TradingView resolves to as well — so the venue is part of the symbol. That
also routes before any fetch: `/api/chart` sees `PSE:` and goes straight to
TradingView rather than spending a Moli round trip on a URL guaranteed to 404.
The `.PS` form is accepted too (`TEL.PS` → `PSE:TEL`), since that is the suffix
Yahoo's own naming teaches, and it names the venue, so its stem is already the
PSE ticker.

The three Philippine bond yields route the same way, before any Yahoo URL is
built (`tv.is_bond_symbol`): `TVC:PH02Y`, `TVC:PH05Y` and `TVC:PH10Y` are read
off the same socket by `tv.py`. See "The bond chart" under the recent table.

Search ranks locally rather than asking the scanner to filter, because the
scanner's `match` operator is word-based and returns **zero** rows for `pldt`,
`globe`, `jollibee` and `metrobank`. One request returns all 261 securities and
ranking them here is both faster and better: exact ticker, then ticker prefix,
then name prefix, then name substring. Two wrinkles worth knowing:

- **PSE tickers are padded, so a prefix hit is not a match.** `SMC2P` starts
  with `sm`; listing it as an "SM Investments" suggestion is wrong, so a ticker
  only counts as a prefix hit if it is not much longer than what was typed.
- **Some companies are not listed under the name people use.** "Metrobank" is
  `Metropolitan Bank & Trust Co.` and "Meralco" is `Manila Electric Co.`, so no
  substring match can find them; a small synonym table in `pse.py` maps the
  colloquial names to their tickers. A PSE row that matches also leads when
  Yahoo's best answer is only a *resemblance* — `pldt` returns `PHI`, `PLDTX`,
  `PLO.HM` before the Manila listing, unless Yahoo's top hit is an exact ticker.

Typing `pse` or `philippines` returns the index and the largest listings rather
than Yahoo's `EPHE` ETF and a wall of `^NQPHLMT` index codes — those words name
the market, not a security.

Three limits worth knowing:

- **Bars are 15-minute delayed** (`delay: 900` upstream). The footer discloses
  this for all sources; it matters most here, where the delay is longest.
- **An index has no volume**, so the PSEi's bars carry five fields, not six. The
  ensemble's volume signal simply has nothing to say for it, and the trend call
  is made on price alone.
- **The PSEi is not in the scanner's universe** — that lists securities, not
  indices — so it is registered by hand in `pse.py` and added to the search
  results alongside the stocks it tracks.

A PSE symbol keeps its identity when added to the watchlist: the Add button
takes its symbol and name from the chart payload, so `PSE:TEL` in the rail is
exactly what the chart drew. Each chart costs one browser round trip (~3 s), so
the watchlist's parallel quote refresh is slower for a rail full of PSE rows
than for a rail of Yahoo ones.

## The two most-traded tables

Below the chart, `markets.py` answers one question for both markets: which ten
securities traded the most value today. The Philippine card is on the left, the
US card on the right, and each row is clickable — it loads that instrument into
the chart above.

### "Most traded" means turnover, not share count

The scanner reports `Value.Traded`, the session's traded value in the
instrument's own currency, and the ranking is on that. A share count would
answer a different and worse question: on the same session the PSE's
most-traded listing by value (PNB Holdings, ₱1.14bn) is only 69th by share
count, because 952 million shares at ₱1.20 are not one BDO share at ₱114.
Ranking on the count promotes penny stocks over blue chips, and the distortion
grows across markets — exactly what two side-by-side tables invite a reader to
compare.

That `Value.Traded` really is turnover was checked against the tape:
PNB Holdings' 952,828,000 shares × its ₱1.20 close = ₱1,143,393,600, the figure
the scanner reports exactly. The same arithmetic holds for SM (627,330 × ₱510)
and BDO (2,246,400 × ₱114).

### What each table asks the scanner

| | Endpoint | Filter |
|---|---|---|
| Philippines | `POST scanner.tradingview.com/philippines/scan` | none — the 261-row universe is securities already |
| United States | `POST scanner.tradingview.com/america/scan` | `typespecs has common`, then `typespecs has etf`, merged |
| Cross rate | `POST scanner.tradingview.com/forex/scan` | `name match USDPHP` |

Both are ordinary HTTP POSTs answered in under a second, which is the same
reasoning as `pse.py`'s search path — nothing here pays for a browser. The two
share the POST helper (`pse.post_json`) rather than repeating it.

The US filter is load-bearing rather than a nicety. The America section is
venue-wide, so an unfiltered query ranks OTC shells into the top ten; the
scanner's `in` operator is broken server-side (`"Expected one value, passed
2"`), so the two instrument types are fetched as two queries and merged in
Python. Funds are included by choice — at this session's turnover SPY and QQQ
take two of the top three US slots — so every row is labelled with its kind
(`Common stock`, `ETF`, …) from the finer `typespecs` field, which distinguishes
a fund from a share where the coarse `type` field does not.

### Both currencies, from a rate that is stated

Every row carries its turnover in pesos *and* in dollars, whichever market it is
in, so each table shows its own money first and the other market's underneath.
The cross rate is fetched per request and printed with the tables ("Converted at
USDPHP 63.77"), so the dollar column is a conversion at a named rate rather than
one frozen into the source. If the rate is missing the column is dropped and
said to be unavailable; neither table is lost, because the native figures are
the ranking and the conversion is an annotation on it. The same holds per
section: each card carries its own error, so one market's outage does not take
the other's table with it.

### The PSE board lot is why a Philippine price carries a minimum investment

Wherever the page shows a PSE price it can also show **Min. investment** — the
board lot multiplied by that price, i.e. the smallest cheque that can buy the
stock. Three places carry it: the chart card, under the price it has just drawn;
the Philippine most-traded table; and the bullish table. All three agree on the
figure for a given close because all three call `markets.minimum_investment`,
which is the one place the lot is paired with the price — the chart does not
redo arithmetic the tables already did.

The chart's readout is a body-scale stat under the hero, not a second hero: one
figure per view is the hero, and this is a supporting detail of it. It carries
the lot in a muted note beside the peso amount — "5-share board lot at
₱1,089.00" — so an eight-figure price does not read as a mistyped one. It is
shown only when both numbers are positive and finite, which is to say only for a
PSE series that priced: an index, or any non-PSE symbol, has no board lot and so
gets no readout at all rather than a dash.

The board lot is a market-wide rule keyed on price, and it is *not* the
`pricescale` the scanner reports: that is the tick size, and the two only
sometimes agree. PNB Holdings closes at ₱1.20 with a pricescale of 100, which
would read as a lot of 100 shares, while the exchange's published table puts
every stock between ₱0.50 and ₱4.99 in the 1,000-share bracket. So the table is
encoded in `markets.py` (`BOARD_LOTS`) from the exchange's published schedule
rather than guessed from a field that means something else. Its brackets are
half-open on the upper bound, `(lo, hi]`: the published ranges round their
halves — "₱20.00 to ₱49.95" means up to and including ₱49.999… — and each range
spans exactly one tick short of the next round price, so no price falls in a gap.

Only the PSE has a board lot, so only a PSE figure is paired with one; the
server leaves the lot null elsewhere rather than inventing a rule, and the page
reads a null as "no readout" rather than defaulting it to something plausible.

### Freshness

The tables are cached for 300 s (`TOP_TTL`) and refreshed while the tab is
visible, which is longer than the chart's 60 s on purpose: a leaderboard that
moves by the second is not worth three upstream round trips per poll. The data
is the same 15-minute-delayed feed the chart uses, which is why the note above
the tables reports when the page checked rather than implying a live tape.

## Bullish Philippine stocks

Under the two leaderboards is a third table: every PSE stock whose trend call is
bullish right now, each row dated to the bar its current run began on, newest
first. `bullish.py` answers it and the page draws it as one wide table rather
than a card per market — there were 29 rows on the last sweep, and a two-column
grid would make the reader choose a column before they could scan the list.

It carries the same **Min. investment** column as the Philippine leaderboard and
the chart, off the same helper (`markets.minimum_investment`), so the smallest
cheque that buys a name is the same figure wherever the page shows it.

### What breaks a tie on the date

Rows are sorted by onset, and several names turn on the same session whenever
the market moves as a whole — a market-wide move makes the date the *common*
case, not the exception, so the tie-break is most of the ordering.

Ties are broken by that session's **traded value**, heaviest first: the latest
bar's close times its volume, in pesos. That is deliberately not a new liquidity
measure. It is the same quantity the leaderboards rank on — the scanner's
`Value.Traded`, which [the section above](#most-traded-means-turnover-not-share-count)
checks against the tape — read off the bar the row is already priced from, so a
row's price and its turnover cannot come from different sessions and no second
upstream query is needed for a sort key.

A row whose latest bar carries no volume sorts last among its own date whatever
its run, since silence about liquidity is not evidence of it; the longer run and
then the ticker finish the order, so two scans agree on a total one.

**The label is the chart's own, not a lookalike.** "Bullish" here means what
`trend.classify` says, and a row is included when the label on the window *the
chart would draw right now* is bullish. That is the same verdict the chart badge
shows for that symbol, so clicking a row can never open a chart labelled
"Neutral" above a row that called it bullish.

### Dating the start of a run

The column the badge cannot give you is **Bullish since**, and the honest way to
produce it is to redraw the chart at each earlier bar and ask again:

| | Window | Measured from | Used for |
|---|---|---|---|
| `window_now` | the 90 days the chart draws today | now | **inclusion** — is this row in the table |
| `window_at` | the 90 days the chart would have drawn on that day | that day's bar | the **onset walk** |

(The Philippine exchange's chart really does draw ninety days. Yahoo's draws
three *calendar* months, so the United States rows ask `onset` for that shape
instead — see
[One definition of "bullish", one definition of "since when"](#one-definition-bullish-one-definition-since-when).)

Two windows rather than one because they answer different questions. A run is
dated by walking backwards from the latest bar and stopping at the first bar
that was not bullish. Reconstructing an earlier verdict means re-trimming the
window around *that* bar: measured from today instead, the window jumps from one
bar to fifty the moment the test bar crosses a fixed cutoff, and the label flips
for no reason.

Walking is also much cheaper than a full sweep. Classifying every bar of every
symbol would be ~53,000 calls; stopping at the first break costs ~2,700, for the
identical answer, because `classify` is the expensive part and the walk calls it
once per bar of the runs that exist rather than once per bar of history.

Runs are measured in **bars, not days**, and "Bullish since" is the session date
of that first bar in UTC. A run reaching the start of the fetched data is marked
`censored` — the date is a floor, not an exact start — and `boundary` counts the
rows where the two windows disagreed about the latest bar (a stale bar makes the
badge's window shorter than the anchored one). Both are reported in the note
rather than rounded away.

### Why a run began is a second question (added 2026-10-31)

The date says *when* a run began. It does not say *what changed*, and on a
rolling window two very different things produce the same flip:

* **The series turned.** The asset reversed: the recent bars moved in the new
  direction and the label followed them. This is the reversal a reader means by
  "it's bullish now".
* **The window's base moved.** The oldest bar is the denominator of the window's
  return (`P_end / P_start`). A crash that has aged out of the window lifts that
  return with the price standing still — the label improves because the starting
  point changed, not because anything happened.

`onset.onset` now reports `manner` beside the date, read over the twenty bars
**before the run's first bar** — the moment the label flipped, never today's
bars. It is a reading of the same bars, not a second classifier: the label, the
date and the run are exactly what they were, so a row is still the verdict its
own chart draws.

| `manner` | The last 20 bars before the flip | |
|---|---|---|
| `turn` | moved with the run (≥ +2%) | what a reversal looks like |
| `flat` | went nowhere (< 2% either way) | the run began as the base aged out |
| `against` | moved the other way (≤ −2%) | the least trustworthy of the three |

`turnMove` carries the number the word was cut from, **signed in the run's own
direction** so one rule holds for every caller — a bullish run on a price and a
bearish run on a bond yield (a falling yield, which is what a bond row asks for)
both read `turn` when the series itself moved the way the run says.

Measured on 2026-10-31 across 316 symbols, 663,174 bars and **2,496 bullish runs
that followed a bearish regime**:

| Mechanism | Share | Last 20 bars (median) | Close's place in the window |
|---|---|---|---|
| price-driven (`turn`) | **86.9%** | +9.4% | 1.00 — at the high |
| base-driven (`flat`) | 11.8% | +0.8% | 0.93 |
| still falling (`against`) | 1.3% | −3.6% | 0.79 |

So the artifact is real but uncommon: a flip is rarely describing something that
did not happen. The design helps here — `range` carries 0.15 weight and wants the
close near the window's high, so a pure aging artifact cannot flip the label
while the price is still near the bottom.

**What `manner` is not is a forecast.** The three groups' next three months were
49.7%, 49.8% and 53.1% up — a coin flip, like every other study in `research/`.
It says how much to trust the *flip*, not where the price goes. `flat` runs are,
however, 2.5× more likely to fall back to the label they came from within twenty
bars (6.1% vs 2.4%), so it is the sturdiness of the run being reported.

**It is counted, never filtered.** The sweep's payload totals `turns`, `flat`
and `against` beside `boundary` and `censored`, and every row carries `manner`
and `turnMove`. A row is *not* dropped for being `flat`: the manner does not
predict, so dropping rows would shrink the table without making it truer — and
a row must stay the verdict its own chart shows. The manner is a fact a reader
or a later filter may use; it is not a second opinion about the label.

`manner` is `None` when there are fewer than twenty bars behind the run's first
bar — a censored run has none at all, and a money-market fund's run reaches back
almost to the start of its history, because such a fund accrues and never marks
a loss. An absent reading is left absent rather than guessed.

### Why it is held warm by a background thread

This table cannot be fetched while a reader waits. It reads 270 daily bars for
each of ~261 PSE symbols over the socket, and a cold run takes about **35
seconds** — far too slow to sit in front of, and too expensive to redo per poll.

So nothing about it is lazy. One background thread sweeps on a loop, `BULL_TTL`
(900 s) apart, and a request only ever reads what that thread last produced. The
consequence worth knowing: the first request after a cold start returns instantly
with `pending: true` and an empty table, and the page says a sweep is running
rather than showing zero bullish stocks. `pending` is the same flag a refresh
sets for the duration of its work, and it is what stops an unswept table from
reading as *"no Philippine stock is bullish"*.

A failed refresh does not clear the rows. Fifteen-minute-old rows with a note
saying so are more useful than an empty section, so the failure travels beside
them as `staleError` and the page dates the table instead of blanking it. Rows
are also replaced wholesale rather than mutated, so a reader cannot see the
payload change mid-render.

### Reading the PSE universe over one socket

The sweep is what makes the websocket's limits matter, and two were worth
recording:

- **One series per chart session.** A second `create_series` on the same session
  fails with `critical_error: exceed limit of series in the session`, so each
  symbol gets its own `chart_create_session` — many sessions, one socket.
- **Forty sessions is the comfortable ceiling.** Up to 40 concurrent chart
  sessions answer reliably; past that, messages start going missing wholesale.
  So symbols are fetched in chunks of 40 across 4 workers, with a retry pass,
  which reads all 261 symbols and 270 bars each in about 35 seconds.

A symbol that does not answer is left out of the table and counted in `missing`
— treating a fetch failure as "not bullish" would put an outage in the table as
a fact about the stock. Two hundred and seventy bars are fetched per symbol
because the walk needs to redraw a 90-day window at each bar it tests: 90 days is
~63 trading bars, so 270 is four windows of history behind the latest bar.

## Most traded crypto — 24 hours

Between the two leaderboards and the bullish PSE table sits the crypto table:
the heaviest coins of the rolling last 24 hours, kept only where the trend is
bullish **and** the rolling day is up, ten rows at most. `cryptobull.py`
answers it, `/api/cryptobull` serves it, and the order is always the volume
ranking — the table is *not* "the ten heaviest coins, whatever their trend".

### What "most traded" ranks on

Binance's 24-hour ticker (`/api/v3/ticker/24hr`, through the same
`data-api.binance.vision` mirror as every other Binance call here) reports each
pair's `quoteVolume` — the value traded in the quote asset over the rolling day.
Ranking the `USDT` pairs on it is turnover ranking, the same measure the
leaderboards use. Three exclusions keep the ranking honest:

- **Stablecoins and fiat bases are dropped** (`USDC`, `FDUSD`, `BUSD`, `EUR`, …
  — explicit lists in `cryptobull.py`). `USDC/USDT` is the heaviest "volume" on
  any exchange, but moving dollars between two wrappers is not trading a coin.
  The lists are deliberate rather than a near-$1 price heuristic, which would
  misfire on a coin in a genuine depeg.
- **Only `USDT` pairs are ranked**, so a coin trading against several quotes
  (`BTCFDUSD`, `BTCTUSD`) is counted once. USDT is where the turnover is, and
  identity here requires a USDT pair anyway (`crypto.coin`).
- **Only coins the page can chart stay.** `crypto.coin` resolves each base
  through the top-250 CoinGecko index, so long-tail pairs the search box cannot
  name leave the candidate list before any bars are fetched. That is the same
  universe every crypto feature on the page lives in, not a filter on the trend.

### How the bullish filter and the expansion work

The label is the chart's own, by construction: each candidate goes through
`crypto.try_chart(base + "-USD", "3mo", "1d")` — the same function the chart
route ends in for a crypto symbol — and the row keeps that payload's trend call.
A row and the chart its click opens are the same classification over the same
bars; the row cannot say bullish above a chart whose badge does not.

On top of the label sits a day condition, and it exists because the first
build shipped without it: all ten of its rows were labeled bullish on the
three-month chart and *every one printed a negative 24-hour change*. A coin
three months into an uptrend can be down five percent today, and a "bullish"
row above a red change column reads as anything but bullish — the table
contradicting its own promise in the reader's eye. So a candidate is probed
only when its 24-hour change is strictly positive — the same live figure the
row itself prints, judged against the same green/red colouring the page gives
that column. Exactly zero is skipped with the reds: the change cell calls zero
flat, and bullish-that-prints-flat is the same contradiction one step softer.
This is a second filter, not a second definition of bullish; the chart label
is untouched, and the payload's `flat` count says how many candidates the day
condition turned away. The condition runs on the ticker the ranking came
from, so a skipped coin costs no bars request at all — which is also why the
walk can reach the whole chartable ranking without its worst case growing.

The walk starts at the top of the volume ranking and keeps going until **ten**
qualifying rows are filled. A bearish stretch at the top is the normal case, not an
error — the search simply expands down the ranking, which is the whole point of
the table. Two bounds keep that finite:

- **`MAX_CANDIDATES` (250)** caps how far down the ranking the walk may reach;
  that is the whole chartable universe (`crypto.coin` resolves through the
  top-250 index), and the day condition makes the reach nearly free — coins it
  skips cost no request — so past it the table ships short and the note says
  how many pairs were scanned.
- **A coin whose bars do not answer is skipped and counted in `missing`** — the
  same rule as the PSE sweep: a fetch failure is not a fact about the trend, and
  treating it as bearish would let one dead request delete a qualifying row.

The probes run eight at a time on a small thread pool (the shape
`markets.tables` uses for its independent scanner queries) and the answers are
walked *in volume order*, so batching changes the speed and not the order. A
cold scan costs seconds of plain HTTPS — no browser — so unlike the PSE sweep
this table *can* be fetched while a reader waits: it is cached on `TOP_TTL`
(300 s) through the same `cached()` path as the leaderboards, and prewarmed with
them at startup, rather than held warm by its own background thread.

### What the row shows

`turnover` is the 24-hour quote volume in dollars, with the peso figure beneath
it at `markets.php_per_usd` — the one rate the leaderboards state, so all three
money tables agree about what a dollar is worth; an unavailable rate costs the
annotation (`fxError`), not the ranking. The **price is the chart's own
`marketPrice`** — the latest *completed* daily close, not the ticker's live
print — so a row's price and its chart can never disagree, and it carries the
same `priceHint` the chart's readout uses, so a sub-cent coin does not print as
`$0.00`. The **24-hour change** is the one deliberately live figure: it
describes the rolling day the table ranks on, which is still in progress when
the table is drawn — and it doubles as the day condition: every row on screen
was strictly green on it at scan time, though a rolling day can turn before
the next rescan.

Rows are `BASE-USD` spellings, so the row warmer picks their charts up with the
Yahoo batch leg it already runs — no new warming path — and an offline reader
can still draw every coin the table names.

## Recently bullish assets

The last table on the page answers one question across six markets at once:
**what turned bullish most recently?** `recent.py` builds it, `/api/recent`
serves it, and the page draws it as a single table with a **Market** column —
US stocks, Philippine stocks, crypto, the US Treasury futures, the Philippine
government bond yields and the Philippine funds — sorted newest turn first.

The page already had three tables that each answered a piece of this and a
fourth that answered none of it. "Bullish Philippine stocks" is every PSE name
that is bullish, dated. "Most traded crypto" is the heaviest coins that are
bullish. "Most traded today" is the busiest listings in two markets, with no
verdict at all. None of them spans markets, and none of them had anything to
say about the Philippine government bond yield — which is read with the same
algorithm as everything else and wants the same thing said about it: when did
it turn?

On one recent sweep it produced **27 rows**: 8 Philippine stocks, 13 US stocks,
3 coins and the 3 bond tenors it read — and the note above the table says so, in
the same order, so a reader can tell at a glance what the sweep covered. The
bond leg reports its three tenors as scanned and keeps only the falling ones
(0 rows on the sweep this was written against, when the whole curve was rising).

### One definition of "bullish", one definition of "since when"

There is no second classifier here. "Bullish" means what `trend.classify` says,
on the window the chart draws — the same verdict the chart badge shows, so
clicking a row can never open a chart labelled "Neutral" above a row that
called itself bullish.

The window still matters: two windows that differ by a trading session can
produce different scores. The classifier now uses the same blend at every bar
count. "The window the chart draws" is not the same window for every source:

| Source | The window its chart draws | How the walk asks for it |
|---|---|---|
| Yahoo (the US stocks) | three **calendar** months back from today — `range=3mo` is three months, not ninety days | `onset.onset(..., months=3)` |
| Philippine exchange, Binance, the bond yields | ninety days | `onset.onset(...)` (the default) |

Previously SPY appeared bullish in the table and neutral on its chart when the
two used different windows and different scoring regimes. `onset.py` asks for each source's own
window shape, and the Yahoo chart path trims its payload by **asking the same
function** — `onset.window_now(..., months=3)` — so there is one cutoff rule,
not two copies of it, and a row and the chart its click opens read the same
bars by construction rather than by coincidence. Verified across the whole
universe — 130 US tickers as of 2026-10-31: every row's label and score equals
its chart's badge, to the last decimal.

The trim applies to **daily** bars only. Its cutoff is a day boundary, while a
weekly bar spans seven days and carries its stamp on the week's first day
(SPY `1wk` opens 2026-07-27) — cutting there amputated a bar that lies partly
inside the window and changed the verdict (SPY `1wk` +0.1262 → +0.0021). Weekly
charts keep Yahoo's own payload. Currency crosses are the one case where the
trim drops a bar: Yahoo's FX payload opens a session stamped on the prior day
(07-29 23:00 UTC), and across all eight crosses tested the label and score were
unchanged — a currency session boundary, not a verdict change.

The date was the harder half, because each table that wanted it had grown its
own copy of the walk, and two copies of a walk are two answers that disagree at
the edges. So the walk moved into **`onset.py`**, and every table that asks
"since when" asks it there. `bullish.py` (the Philippine sweep) is the first
caller and the recently-bullish table is the second; the refactor was verified
behaviour-identical on 300 randomized series.

`onset.py` holds the two windows the walk needs — `window_now` (the badge's own
window, which decides *inclusion*) and `window_at` (the window the chart
would have drawn on a given day, which the walk *measures with*) — plus the
labels, the runs and the censored flag. Each takes the shape of the window it
is asked for: `days` (ninety, the default) or `months` (Yahoo's calendar
months). The reasoning is unchanged from the
[section above](#dating-the-start-of-a-run); what changed is that it now has one
home.

### Where each row's bars come from

Every instrument is judged on the series the page's own chart would draw for it,
so a row's verdict and the chart its click opens are the same series:

| Market | Source | Why |
|---|---|---|
| US stocks | Yahoo daily bars, through the Moli browser path | the most-traded US listings from the TradingView scanner (`markets.us_universe`), judged on the bars the page's own chart draws for that ticker |
| Philippine stocks | the Philippine sweep's own rows (`bullish.py`) | read from the sweep the server already keeps warm — re-sweeping would make this table fresher than the sweep it is built from |
| Crypto | Binance daily bars | the chartable USDT ranking (`cryptobull.candidates`), judged on the same bars the crypto table and the crypto chart use |
| US Treasuries | Yahoo daily bars, through the same Moli browser path | the seven Treasury futures on the curve (`rates.CONTRACTS`), a fixed list rather than a ranking, judged on the bars the chart route draws for them — see [the Treasury futures](#the-united-states-treasury-futures-which-are-prices-2026-10-31) |
| Philippine bonds | TradingView chart socket | `TVC:PH02Y`, `TVC:PH05Y`, `TVC:PH10Y` — the 2-year, 5-year and 10-year government bond yields, as daily closes in percent |
| Philippine funds | the publisher's own NAVPU register (`phfunds.py`) | forty-seven funds with no ticker and no exchange; each one's daily net asset value per unit is read from TOAP's UITF register, PIFA's NAV history or BPI Wealth's own fund page — see [Philippine funds](#philippine-funds-on-their-published-navpu) |

The US leg is the expensive one: a year of daily bars for each of **130** tickers
(`recent.US_LIMIT`), fetched through the browser because Yahoo answers plain HTTP
clients with a 429. So this table is a **sweeper**, not a route, for the same
reason the Philippine sweep is: `RECENT_TTL` (900 s) apart on a background
thread, and a reader only ever reads what that thread last produced. The
Philippine rows come from the sweep above rather than a second one.

A full sweep measured about **10 seconds** with 130 tickers (2026-10-31), almost
all of it the US browser leg — twenty Yahoo URLs per browser run, seven runs for
a hundred and thirty tickers. So the payload is kept on disk under its own key
(`recent:scan`) and hydrated at startup, the same contract the Philippine sweep
has: an offline start still shows rows, and the note says the table is a saved
sweep rather than a live one. A failed refresh leaves the previous rows on
screen and reports the failure beside them; it never clears the table.

**Why 130 and not 50.** The cutoff is coverage, not a verdict: a name outside it
is never fetched, so the table has no opinion about it at all — which reads like
a bearish call. Fifty was a shortlist of the heaviest names, and it dropped two
that were bullish on their own charts: WMT ranked 57th by turnover and KO 124th,
so neither row existed while both were ▲ Bullish. The universe now reaches deep
enough to hold the large caps a reader would name, at the price of a longer US
leg (seven browser runs instead of three).

**A class share takes Yahoo's spelling.** The scanner names it with a dot
(`BRK.B`); Yahoo — and so the chart route — names it with a dash (`BRK-B`), and
`BRK.B` answers `/api/chart` with a 404. `markets.yahoo_symbol()` is the one
place that rule lives, and both the chart symbol on a row and the ticker the US
bars are fetched under go through it. Without it, a name inside the widened
universe would have been reported as "did not answer" on every sweep: a fetch
failure written into the table as a fact about a stock. The row still *displays*
the scanner's `BRK.B`, because that is the listing's own name.

### What each row says

Seven columns, and each one earns its place:

| Column | What it is |
|---|---|
| **Market** | which of the six markets the row belongs to — the table spans them, so it says so |
| **Asset** | ticker and name; a click opens that instrument's chart, unless it has none |
| **Direction** | the badge's own label — bullish, bearish or neutral — with the bond rows spelling out the yield's direction |
| **Since** | the day the current run began, in the row's own market's timezone |
| **Run** | how many bars the run has lasted — bars, not days, because that is the unit the label speaks in |
| **Price** | the latest close, a percentage for a yield and a currency amount for everything else |
| **Trading volume (in PHP)** | the latest bar's value traded in pesos — native for a Philippine stock, converted for a US stock or a coin at the same `markets.php_per_usd` rate the "most traded" tables annotate with, and empty for a yield, which trades no shares, and a futures contract, whose volume counts contracts rather than money. The exact figure (and, for a converted row, the native one) is on the cell's hover |

The **Since** column is the point of the table, and it is a different date for a
different reason on each row. The date is the first bar of an unbroken run of
like labels ending at the latest bar; a run that reaches back past the fetched
history is marked *censored* rather than dated to a bar that only happens to be
the oldest one fetched.

**A bond bar is a Manila bar.** The yields close at Manila 05:00, which is 21:00
UTC of the *previous* day, so a bond row's date is read in `Asia/Manila` while
every other row's is read in UTC. The row carries its own timezone with it
(`"tz": "Asia/Manila"`) and the page formats each row in the zone it was given,
so the 2-year's 2026-10-01 does not slip back a day into September.

The note above the table is built **server-side** by `recent.summarize(payload)`
and shipped as `payload["note"]` — the same module that knows what was judged
writes the line that says what was judged, so the note and the rows cannot
disagree: *"45 rows · Philippines: 29 · US: 50 scanned · Crypto: 25 scanned ·
Philippine bond: 3 scanned, 1 bullish · Converted at USDPHP 63.77"*. The
conversion is the TradingView scanner's `FX_IDC:USDPHP` quote; when it does not
answer the rate is named missing in the note and the peso column shows only what
needs no conversion — the Philippine rows. The bond leg judges all three tenors
but shows only the falling ones, so it reports both numbers: a curve with no row
reads as "nothing turned", not as "nothing was looked at".

### A yield is not a price

The same classifier reads the yield series, but the displayed direction and
score are inverted to reflect the usual price movement of an existing fixed-rate
bond: a falling yield reads as a **bullish bond price**, a rising one as a
bearish bond price. Only the falling kind is a row on this table. The date and
run refer to the underlying yield trend. This is an inference from yields, not a
measured bond-price trend or a forecast.

The bond rows follow the same rule as every other market, read on the
bond-price side: a **falling yield** is a row, and a rising or flat one is not.
(Before 2026-10-31 the three tenors were shown whatever their verdict; that was
reversed at the reader's request, because a table of "recently bullish assets"
listing rows marked bearish reads as a contradiction.)

A bond yield's row **is** a link: clicking it opens the yield's own chart, drawn
from the same TradingView series the row was judged on (see "The bond chart"
below).

### Why the yields come over the browser

The TradingView chart protocol is a websocket, and it can be driven by a plain
TLS socket with no browser at all. That was tried first, and the code was
correct — the handshake, the session, the symbol resolution, the series request
and the `timescale_update` frame all arrived. The problem was that **the
protocol drops most of the sessions it accepts**: a session is told to load a
series (`series_loading`) and then the series never comes, and whether it came
at all looked like a coin flip. It was worse for the 5-year yield than for the
others, and the flakiness came in bursts, so a sweep that worked could be
followed by one that did not.

Driving the same protocol from the browser instead is reliable: the same three
yields come back, every time, in **under a second**, with the same values the
plain socket produced when it did answer. So the switch cost nothing but the
flakiness, and the browser is not a new dependency — it is the one Moli-backed
path the whole project already runs on, and `pse.py` is its socket client.

`tv.py` is therefore deliberately thin: it owns the bond yields — which symbols
are the Philippine curve, what they are called — and borrows the socket.

### Keeping a copy of the curve

A yield is a daily close, so a copy a few hours old has missed at most one bar.
Each tenor's series is therefore kept on disk (`diskcache`, under a key of its
own) for six hours, which is most of a trading day and most of the sweeps; a
sweep fifteen minutes after the last one does not pay for the fetch again.

If a fetch does fail, a copy up to a week old is served instead of a gap in the
curve, and the row says so — the row carries the age of the reading it is
showing (`stale`, in seconds) and the page prints it beside the price. That is
the difference between the two ages: six hours is how long a copy is fresh
enough to *skip the fetch* for (`BOND_CACHE_TTL`), a week is how long it is
still worth *showing* when the fetch failed (`BOND_CACHE_KEEP`).

The chart reads the same copy. `tv.cached_bars` is the one reader of that disk
entry for both the row and the graph, so a bond chart cannot be drawn from a
different series — or a different age — than the row it was opened from. Both
ages live in `tv.py` for the same reason; `recent.py` imports them rather than
keeping a second set.

### The bond chart (2026-10-31)

Clicking a bond row opens the yield's own chart. Everything about it follows from
two rules:

* **The chart is the row's series.** `server.chart_data` routes a bond symbol
  before it builds a Yahoo URL (`tv.is_bond_symbol`), and `tv.chart` trims the
  series with `onset.window_now` — ninety days, the window the row's walk asks —
  and scores it with `trend.classify`. The badge and the row are one call on one
  series: checked 2026-10-31, all three tenors matched exactly (PH02Y −0.4708,
  PH05Y −0.6268, PH10Y −0.5559 on both sides).
* **The line is the yield; the label is a bond price.** Fabricating a
  bond-price series out of a yield would be inventing data, so the plot is the
  yield in percent (`currency` and `unit` `"%"`, axis "YIELD %"). The badge
  applies the same reversal the table row does (`tv.bond_price_call`: label
  flipped, score negated), and the payload keeps the classifier's own call as
  `yieldTrend`, which is what lets the page say *"the classifier reads the yield
  itself as bullish; the badge reads it as a bond price, so a rising yield is
  Bearish"*. (A yield used to hide the research-judgment box because that box
  reads price history; the box is gone from the page entirely.)

A bond chart has a cache key of its own, `tv:<SYMBOL>:<span>:<interval>`, kept
apart from the bars it is built from (`tv:bond:<SYMBOL>`) because the bars are
shared with the row and the finished chart is not. When the socket does not
answer and a bar copy older than six hours is used, the payload carries the same
stamps a disk rescue would (`cached`, `fetchedAt`, `cacheError`), so the page
dates the reading and a copy stored from it cannot later pass as fresh. The row
warmer warms these through one socket run per pass (`_warm_batch_bonds` →
`tv.charts_many`), so a bond chart is retrievable offline like every other row's.

### The United States Treasury futures, which are prices (2026-10-31)

The rate market is the sixth market on this table, and the first one added
because something was **missing** rather than because a source was new. The
United States Treasury futures had always been chartable — `ZB=F` (the 30-year
bond contract) answers `/api/chart` with five years of daily bars and a verdict
— but nothing on the page could reach them: the table's US leg is a *turnover
ranking* (`markets.us_universe`), and the TradingView scanner's `common` /
`etf` typespecs cannot even name a futures contract. So the whole curve sat
outside every sweep, whatever its chart said.

`rates.py` is the curve as a **fixed list** — the same shape `tv.BONDS` has for
the Philippine yields — because there is one 30-year contract, not a market of
them to be ranked:

| Yahoo | Row | Contract |
|---|---|---|
| `ZT=F` | ZT | 2-Year T-Note |
| `Z3N=F` | Z3N | 3-Year T-Note |
| `ZF=F` | ZF | 5-Year T-Note |
| `ZN=F` | ZN | 10-Year T-Note |
| `TN=F` | TN | Ultra 10-Year T-Note |
| `ZB=F` | ZB | 30-Year U.S. Treasury Bond (the "long bond", the "T-bond") |
| `UB=F` | UB | Ultra U.S. Treasury Bond |

Three things distinguish this leg from the Philippine bond one:

* **Nothing is inverted.** A Treasury future is a *price*: a higher `ZB` quote
  is a higher bond price is a bullish chart, so the classifier's own label is
  the row's and nothing is inferred. (`tv.BONDS` inverts because it reads a
  yield; there is no yield here to read.) Only a bullish contract is a row, like
  every other market.
* **No turnover.** A contract's volume counts contracts, and close times
  contracts is not a traded value in any currency, so the row carries
  `turnover: None` — exempt from the peso-volume floor the way a yield and a
  fund are, printed as a dash, and explained on the cell's hover.
* **Its own price precision.** A Treasury quote's fraction is a 32nd
  (0.03125), a 64th or a 128th, so `rates.price_hint` asks the fetched closes
  how many decimals they need (2 to 8) rather than hard-coding two. `ZB` at
  `107.65625` is 107-21; printed at two decimals it would read 107.66 and lose
  the fraction that moved.

The window is Yahoo's own three *calendar* months, exactly as the US stock leg
asks (`months=onset.WINDOW_MONTHS`), because that is the window the chart route
draws for these symbols. The bars come from the same injected browser fetch
(`server.fetch_us_bars`, a second call for seven symbols — one browser run), and
the row warmer needs nothing new: a contract is a Yahoo symbol, so it goes down
the existing Yahoo leg and its chart is retrievable offline like any other row's.
Checked 2026-10-31: all seven contracts' leg verdicts equal their chart badges
(all neutral or bearish that day, so the table correctly carried no rate row).

### Finding the Treasury curve in search (2026-10-31)

The same gap existed in the search box, and it was worse there because the
*contract's own Yahoo name* is the problem: `ZB=F` is called "U.S. Treasury Bond
Futures,Dec-", which contains neither "30" nor "year". Measured on the live
route before the fix:

| Query | Answer before | Answer now |
|---|---|---|
| `zb` | ZB=F, then Zebra, Zimmer… | unchanged (Yahoo's own row) |
| `t-bond` | ZB=F | unchanged |
| `30-year treasury bond` | six Korean ETFs (KODEX, ARIRANG, RISE, KIWOOM, KB) — no contract | **ZB=F first**, then the ETFs |
| `long bond` | three KB Asset Management funds and a Canadian index | **ZB=F first**, then those |
| `t-note` | ZN, ZT, ZF, ^TNX… | the five note contracts first, then Yahoo's |
| `treasury` | ZB, UB, TN and two TAS contracts | unchanged, plus ZT, Z3N, ZF the index omitted |

`rates.search_contracts` supplies the rows (Yahoo-shaped: `Chicago Board of
Trade`, type `FUTURE`, de-duplicated against what Yahoo returned) and
`rates.named_contracts` decides which of them *lead*. A query that names a
contract — a ticker (`zb`), a tenor (`10 year`, `30Y`), a desk name (`the long
bond`, `t-bond`, `treasury bond`) — leads with that contract, unless another row
is an exact ticker hit, which is what the reader typed: `bond` still finds the
`BOND` ETF first. The bare word `treasury` is **not** specific — it names the
asset class — so it only fills in what Yahoo left out and never reorders Yahoo's
own answer. "30 year" can never match the two-year, because phrases match whole
words ("12 year" is not "2 year").

**A bare ticker now charts.** Typing `zb` and pressing Enter without picking the
suggestion used to answer *"No usable price data for 'ZB'"* — the future is
`ZB=F`, and `ZB` is not a Yahoo symbol. `rates.chart_alias` retries the typed
ticker as the contract, **only after Yahoo has refused the bare spelling**, so a
listing that really does trade under it keeps its own chart (`UB` is Corgi's
FTSE U.S. Treasury Bond ETF, and `UB` still charts that ETF, not the ultra
bond). The payload names the symbol it actually drew, so the meta line reads
`ZB=F · CBOT · future · via Yahoo`.

### Philippine funds, on their published NAVPU

The last table's fifth market is the one a Philippine retail investor most
often actually holds: the **peso fund**. A BPI Wealth UITF, an ALFM or Odyssey
mutual fund, the Philippine Stock Index Fund, a PERA fund. Forty-seven of them,
listed in `phfunds.FUNDS`, and they join this table on the same terms as every
other market — a row is a fund whose three-month NAVPU series the classifier
calls bullish, dated by the same walk to the business day the run began, and a
click opens that series as a chart.

**A fund has no ticker, no exchange and no volume.** What it has is one number a
business day: the net asset value per unit (NAVPU; NAVPS for a mutual fund's
shares). `phfunds.py` reads that series from whichever registry publishes it,
keeps the business days, trims it to the ninety-day window the chart draws, and
hands the same bars to the row and to the chart — so the badge and the row are
one `trend.classify` call on one series, exactly as they are for a stock.

There is no single registry that holds them all, so there are three sources:

| Funds | Source | What it serves |
|---|---|---|
| The BPI Wealth UITFs (32) | TOAP's public UITF register, `uitf.com.ph` (`bank_id=3`) | one JSON document per fund, `{label, y}` points |
| ALFM (8), the Philippine Stock Index Fund (2), the Wealth Builder fund | PIFA's NAV history pages, `pifa.com.ph` | the daily series embedded in the page itself |
| The four PERA funds | BPI Wealth's own fund pages | the `dynamicgraph_copy.model.json` behind the NAVPU graph |

All three answer plain HTTPS, so unlike the US leg there is no browser involved
and no Moli round trip per fund. A full refresh of all forty-seven measured
**~35 s cold** (2026-10-31) — most of it PIFA, whose pages are ~2 MB each and
which closes the connection if several are read at once, so that source is read
one fund at a time. A warm pass is under five seconds, because a NAVPU is
published once a business day and each series is kept for six hours
(`phfunds.CACHE_TTL`), with a week's worth of fallback (`CACHE_KEEP`) when a
publisher does not answer — the same two ages, and the same `stale` seconds on
the row, as the bond yields.

Two facts about the raw data decide the shape of everything:

* **The publishers pad the calendar.** Both TOAP's endpoint and BPI's model
  repeat Friday's value across Saturday and Sunday, so a "daily series" arrives
  with two bars a week that never happened. `phfunds.clean` drops them rather
  than smoothing them: a padded Saturday is a non-session, and a bar that never
  happened must not vote in a sixty-three-bar window or be named as the day a
  run began. The same function de-duplicates timestamps (BPI's model ships
  repeated stamps) and drops anything stamped after today (BPI pads forward a
  couple of days).
* **A NAVPU is struck once, after the close.** The newest bar is usually
  yesterday's, and the chart's hero figure is that bar's value. There is no
  intraday price to wait for and no volume to report, so the row's turnover is
  `null` — the table prints a dash, and the peso-volume floor that keeps thin
  names off this table cannot apply, the same exemption a bond yield gets.

**A money market fund is always bullish, and that is not a bug.** Its NAVPU
accrues interest every business day and never marks to a loss, so a three-month
window on one is essentially always bullish and its run is *censored* — "at
least this long" — because the run reaches back past the bars fetched. Six of
the funds in this list are money market or short-term funds; they are in the
table because the reader asked for the funds they hold, and a cash fund's
permanent upward drift is a fact about cash funds, not a signal about markets.

**The chart a fund row opens** is the NAVPU series in its own currency, with the
fund's own precision (`priceHint` 2 to 4, taken from what the publisher prints:
`221.22` for a UITF, `48.1186` for an ALFM fund) — printing a four-decimal
NAVPU at two would round away the only digits that moved this month. The meta
line names the registry the numbers came from, and the axis is the fund's own
currency. (The research-judgment box a fund used to suppress is gone from the
page altogether: it weighed volume and peer universes this project holds for
traded instruments, and running it on a smooth daily asset value would have
printed a historical frequency about something the data never measured.)

A fund is discoverable by name as well as by its row: the search box asks Yahoo,
which has never heard of a Philippine fund, so `phfunds.search_funds` adds what
no other index has. A query that matches a fund's **code** (`alfm`, `BPI-HLTH`,
`pera`) leads with those funds — the competing Yahoo rows are near-misses like
`ALFMF` or Perak — while a name query such as `health` still finds the
health-care stocks first.

Recognition worth stating: a fund's `code` in this table (`BPI-INFRA`,
`ALFM-MM`, `BPI-PERA-MM`) is a **display code**, not an exchange ticker — no
Philippine fund has one. It is what a row prints and what a `FUND:` URL
carries, and it is defined once, in `phfunds.FUNDS`.

### What the table does not contain

Nothing that is not bullish is in it. A bearish US stock is not a row, because
the table is a table of things that are going up, and the Philippine sweep
already stands as the place to read about a name that is not. The bond yields
are read the same way, on the bond-price side: only a falling yield is a row,
so a rising or flat tenor is left out exactly as a bearish stock is. Fund rows
follow the price rule — a bearish fund is simply not a row.

A row whose ticker did not answer is left out and counted in `missing` —
treating a fetch failure as "not bullish" would put an outage in the table as a
fact about the stock.

## How the trend call works

### Three-month forecast research (2026-10-30)

The requested forecasting target is whether the price at the close on or
after three calendar months is higher than the signal close. This is **not**
the same as staying bullish throughout the period or earning a tradeable
return. The app's current badge remains a description of past prices; it has
**not** been changed into a forecast.

`forecast_collect.py` collected daily Yahoo closes through Moli for 74
currently selected instruments: 35 US equities, 18 funds, 11 cryptocurrencies
and 10 currency pairs. `research/market-history.json` holds the bars and
exchange time zones. The PSE comparison uses the existing 244-listing
`research/pse-history.json`. Samples use completed daily bars and the first
available close each month; an outcome is the close on or after the target,
at most ten calendar days late. An unchanged price is neither a correct
bullish nor a correct bearish call. Yahoo uses its three-calendar-month
lookback, PSE its 90-day lookback, and windows under 50 bars are omitted.

`forecast_validation.py` evaluates one **experimental**, pre-specified
candidate: it bins the existing score, then calibrates each bin on earlier
completed outcomes only, separately for each asset class. Annual walk-forward
folds embargo outcomes crossing into the evaluation year. Bins with too little
history or without a four-month block-bootstrap lower bound above 50% abstain.
This is one candidate, not a search over every possible model; the bootstrap
is approximate and the data is not an untouched prospective test.

The candidate does **not** meet the requested reliability goal: 2022 US
equity bullish calls were correct 40.24% of 420 observations, and fund bullish
calls were correct 29.80% of 151 observations. In the PSE folds it made no
bullish calls; its 2025 bearish calls were correct 48.66% of 1,790
observations. Observations share market shocks and overlapping horizons;
counts are not independent and these rates are not individual probabilities.
The current-selected universe excludes delisted instruments, the sample is
illustrative, history may contain corporate-action distortions, and same-close
entry, fees, taxes, dividends, and slippage are not accounted for. Results for
Yahoo crypto also do not validate the live Binance feed. Full yearly results,
coverage, and limitations are saved in `research/forecast-validation.json`.

To recollect and rerun: `python3 forecast_collect.py`, then
`python3 forecast_validation.py`. Collection needs Moli and internet access;
it does not change the live app's prices or classifier. A credible production
forecast still needs broader point-in-time histories, including delistings,
and a separately reserved prospective or untouched evaluation across market
regimes. Do not reinterpret the current bullish badge as a probability.

#### Expanded sample and 51% target

`forecast_collect_extended.py` requests a fixed list of 538 Yahoo symbols,
including the original research sample, with daily history back to 1990 where
available. It writes `research/market-history-extended.json` separately and
refuses to overwrite a previous collection. `forecast_extended_validation.py`
evaluates the same fixed candidate in expanding annual folds from 2011 through
2026, by asset class and including the existing PSE dataset. It writes
`research/forecast-validation-extended.json`; it too refuses to overwrite a
previous report. Both scripts run separately, in that order; collection uses
Moli and requires internet access.

The saved collection contains 517 of 538 requested histories: 346 US
equities, 92 funds, 37 cryptocurrencies and 42 currency pairs. The 21 Yahoo
404 responses are recorded as missing, not scored as forecasts. Depending on
the instrument, the available history starts as early as 1990; it does not
cover every instrument for that entire period.

The report compares each direction separately with a 51% observed hit-rate
target, reports the number of forecasts, abstentions, yearly results, an
always-up/always-down baseline and an approximate 90% time-block bootstrap
interval. Ties count as incorrect, and a signal cannot train on outcomes that
have not completed before its evaluation year. An observed accuracy over 51%
alone does not establish reliable future accuracy: these observations overlap,
parts of the period have already been inspected, and today-selected symbols
exclude most delisted assets. This research does not change the app's badge.

In the completed expanded evaluation, bullish forecasts for US equities were
correct in 60.77% of 62,535 observations, and bullish fund forecasts in 58.20%
of 13,166. But the equity candidate called **every** observation bullish,
matching the always-up baseline exactly; for funds, always-up also matches the
candidate on the cases it chose to forecast. In 2022 these bullish rates fell
to 45.09% for equities and 30.60% for funds. PSE bearish calls were correct in
55.86% of 6,921 observations, again exactly matching an always-down call on
those cases, and were 48.66% in 2025. The candidate produced no bullish PSE,
currency or crypto calls; currency bearish accuracy was 44.63%, and crypto
had no directional calls. These pooled results exceed 51% in some groups but
do **not** establish a useful or dependable asset-specific forecast. Full
counts, yearly breakdowns and uncertainty intervals are in the saved report.

#### Separate market and direction candidates

`market_forecasts.py` implements experimental separate binary models for US
bearish, PSE bullish, currency bullish/bearish, and crypto bullish/bearish
calls. It extracts return, volatility, range position, unchanged-close
frequency and the existing score from the chart window; it does not use future
bars. Each model is regularized logistic regression, with a threshold selected
on an earlier two-year validation period. Ties count as incorrect, calls that
conflict are withheld, and insufficient training or validation abstains.

`python3 market_forecast_backtest.py` runs the research evaluation and writes
`research/market-specific-forecast.json`, refusing to overwrite an existing
report. Each annual 2016–2026 fold fits on outcomes completed before the
validation period, chooses its threshold only on validation outcomes completed
before the test year, and reports test-year results and forecast coverage.
The sample has already been inspected, excludes delisted listings and omits
transaction costs; it is not a prospective test or evidence that an individual
call has a particular chance of success. These candidates are research-only and
do not alter the live badge, tables, or exported classifier.

The first evaluation withheld every call: no direction cleared the conservative
validation confidence-bound gate. `python3 market_forecast_exploratory.py`
tests a less restrictive research alternative, choosing from fixed validation
score quantiles when the validation *observed* hit rate reaches 51% and minimum
case/month/instrument counts are met. It saves
`research/market-specific-exploratory.json` and records rejected thresholds as
well as selected ones; this script also refuses to overwrite an existing
report. Because threshold selection uses a point estimate, crossing 51% in
validation is not evidence of reliable future accuracy. Subsequent annual
results remain exploratory because related historical periods were inspected.

The completed exploratory run produced these pooled three-month test results:

| Market and direction | Correct | Forecasts | Coverage | Approximate 90% interval |
|---|---:|---:|---:|---:|
| US stocks, bearish | 41.68% | 4,115 | 9.54% | Not computed: only 12 forecast months |
| PSE stocks, bullish | No calls | 0 | 0% | — |
| Currencies, bullish | 52.70% | 2,854 | 53.51% | 49.86%–56.38% |
| Currencies, bearish | 48.99% | 1,729 | 32.41% | 46.11%–51.87% |
| Crypto, bullish | 39.51% | 853 | 25.01% | 20.39%–48.94% |
| Crypto, bearish | 58.36% | 1,585 | 46.48% | 47.72%–71.53% |

Coverage is the fraction of eligible monthly observations given that direction;
the other observations are withheld or called in the opposite direction. The
intervals are approximate time-block bootstrap intervals and do not adjust for
model or threshold selection. In particular, both estimates over 51% have
intervals extending below 51%. All selected cases in each row trivially have
the same accuracy as an always-up or always-down call on those same cases; the
candidate has not established that it identifies individual winners or losers.
The full annual breakdown, models and validation diagnostics are saved in the
exploratory report. The production badge remains a past-trend description.

#### Targeted follow-up

`targeted_forecast_research.py` explores separate momentum, reversal, and
volatility rules for bearish currencies, bearish US stocks and bullish crypto.
It uses six- and twelve-month historical prices in addition to the chart window,
selects among 36 rule/threshold combinations using prior validation data, and
replays the earlier models on the same eligible 2020–2026 observations. Its
saved report is `research/targeted-forecast-research.json`. On that comparison
the candidates did not improve: currency bearish 43.53% versus 48.90% prior,
US bearish 41.16% versus 41.68%, and crypto bullish 35.44% versus 37.53%.
The earlier crypto figure of 39.51% included a different eligible population
and period. Forecast coverage differs too; these rates are not paired
same-call comparisons.

`asset_local_forecast_research.py` evaluates a separate asset-local approach
using only outcomes that were complete before the signal. It writes
`research/asset-local-forecast-research.json` when run. Both approaches are
exploratory: the historical period has already been inspected, observations
overlap, and current listings exclude most delisted assets. They are not live
classifiers or independently validated probability estimates.

The completed asset-local evaluation on that same eligible 2020–2026 sample
produced bearish currency accuracy of 48.79% (746 calls, 22.48% coverage),
bearish US stock accuracy of 44.87% (936 calls, 3.46% coverage), and bullish
crypto accuracy of 45.42% (491 calls, 18.41% coverage). The prior models on
the same eligible sample scored 48.90%, 41.68%, and 37.53%, respectively;
their selected calls and coverage were different. The new US and crypto
rates are higher in this retrospective comparison but remain below 51%, and
their approximate 90% intervals (36.02%–51.00% and 36.71%–56.32%) are wide.
Currency did not improve. None establishes an independently validated or
live-ready predictor; the app's existing classifier is unchanged.

`adaptive_forecast_research.py` runs a further combined candidate for those
three directions. It uses chart-window features, six- and twelve-month past
returns, and a score from that asset's already completed outcomes. Each yearly
fold fits on older outcomes, selects a threshold on a separate two-year
validation period, and tests on later observations. It compares with both
earlier approaches on the same eligible observations and saves
`research/adaptive-forecast-research.json`. The evaluation is exploratory:
earlier experiments already inspected the period, the selection process has
changed in response, and the reported intervals do not adjust for this
research selection. It is not a production classifier or prospective test.

The adaptive candidate's bearish currency accuracy was 50.76% over 461 calls
(14.77% coverage), with an approximate 90% interval of 38.95%–61.00%; it was
41.46% over 1,341 US bearish calls and produced no bullish crypto calls. It did
not establish a model above the 51% target. The results use a narrower eligible
population than the earlier tests and are not an untouched evaluation.

`benchmark_forecast_research.py` adds lagged market-benchmark features to that
candidate, using SPY for US stocks, EUR/USD for currencies and BTC/USD for
crypto. Only benchmark closes from a strictly earlier calendar date are used;
missing or stale benchmark data is omitted. It saves
`research/benchmark-forecast-research.json`, comparing prior approaches on the
same eligible observations. The benchmark is a coarse proxy, and this is
further retrospective research—not a live or independently validated model.

The completed benchmark experiment scored 50.00% for currency bearish calls
(552 calls), 41.10% for US stock bearish calls (3,219 calls) and made no crypto
bullish calls. It did not improve on the best preceding candidates. The full
results and annual breakdown are saved in the benchmark report.

`pooled_forecast_research.py` tests another fixed candidate: it combines a
rolling three-year market/regime win frequency with an asset's own recent
history, using only outcomes completed strictly before each signal. It
compares earlier models on the same eligible observations and writes
`research/pooled-forecast-research.json`. As with the earlier experiments, the
history is already inspected and the universe omits many delisted instruments;
the results are exploratory, not validation for use in the app.

The pooled candidate reached 47.92% on 912 bearish currency calls (29.22%
coverage), 41.76% on 3,781 bearish US stock calls (15.13% coverage), and
39.67% on 421 bullish crypto calls (26.56% coverage). On the same eligible
observations, the earlier adaptive currency candidate reached 50.76% on 461
calls (14.77% coverage), and the earlier asset-local candidate reached 44.87%
on 936 US calls (3.75% coverage) and 45.42% on 491 crypto calls (30.98%
coverage). The candidates select different calls; none met the 51% target.

`relative_forecast_research.py` explores cross-asset relative strength and
market breadth, using peer bars from a strictly earlier local calendar date
and a separate annual fit, validation and test. Peers come from available raw
bars rather than outcome-filtered observations, but the selected present-day
universe still introduces survivorship bias. A prior local date is not proof
that a peer's close was available at the signal time in every time-zone
combination. The saved `research/relative-forecast-research.json` is exploratory
research, not an independent test or a live model.

The relative-strength candidate produced 48.64% accuracy on 477 bearish
currency calls (15.28% coverage), 43.09% on 2,843 bearish US stock calls
(11.38% coverage), and 24.08% on 245 bullish crypto calls (15.46% coverage).
The US and crypto calls occurred in only one test year each. None surpassed
the best preceding model on the same eligible observations; the algorithms
select different calls.

`tree_forecast_research.py` evaluates separate shallow nonlinear decision
trees for the same three forecast tasks, using the adaptive candidate's
features and the same chronological fit/validation/test boundaries. It writes
`research/tree-forecast-research.json` and compares earlier candidates on the
same eligible observations. Previously inspected years, overlapping outcomes,
survivorship bias and research selection still limit the interpretation; it is
not a live or independently validated model.

The decision-tree candidate reached 47.81% on 640 bearish currency calls
(20.51% coverage), 37.24% on 2,425 bearish US stock calls (9.71% coverage),
and made no bullish crypto calls. It did not improve the best preceding
candidates on the same eligible observations.

`regime_gate_forecast_research.py` tests withholding asset-local calls when the
recent market-wide directional hit rate is below 50% or has too little
history. Its 18-month gate uses only outcomes completed strictly before each
signal. It writes `research/regime-gate-forecast-research.json`, compares the
earlier candidates on the same eligible observations, and is exploratory—not
an independent test or a production model.

The regime gate produced 41.38% on 319 bearish currency calls (10.22%
coverage), 46.98% on 149 bearish US stock calls (0.60% coverage), and 34.62%
on 234 bullish crypto calls (14.76% coverage). The US figure exceeds the
asset-local comparator's 44.87% on the same eligible population, but uses far
fewer, different calls and spans only 13 signal months. No candidate reached
51%; the improvement is exploratory and is not evidence of future accuracy.

`neighbor_forecast_research.py` explores asset-specific nearest neighbors from
the preceding five years, requiring each neighbor's outcome to have completed
before the signal. It writes `research/neighbor-forecast-research.json` and
compares earlier candidates on the same locally eligible observations. This is
another exploratory backtest, not independent or prospective validation.

The neighbor candidate scored 49.83% on 1,202 bearish currency calls (38.51%
coverage), 45.25% on 6,532 bearish US stock calls (26.14% coverage), and
40.73% on 685 bullish crypto calls (43.22% coverage). It increased coverage
compared with the asset-local candidate, but none reached 51%. These methods
select different calls on the same eligible observations.

`consensus_forecast_research.py` tests calling only when both the asset-local
and neighbor approaches agree, comparing both components, the regime gate and
adaptive candidate on the same eligible observations. It writes
`research/consensus-forecast-research.json`. This rule was conceived after
examining its components and historical results, so even a favorable result
would be exploratory rather than independent validation.

The consensus candidate scored 50.52% on 574 bearish currency calls (18.39%
coverage), 44.41% on 743 bearish US stock calls (2.97% coverage), and 44.91%
on 383 bullish crypto calls (24.16% coverage). It did not reach 51%; the
adaptive currency candidate, US regime gate and asset-local crypto candidate
had higher observed accuracy on the same eligible population, with different
calls and coverage.

`calibration_gate_forecast_research.py` explores a different filter: it
reconstructs earlier asset-local calls and permits new calls only when enough
previously completed calls have a recent hit rate of at least 50%. It writes
`research/calibration-gate-forecast-research.json`. The repeated use of the
same historical years makes this exploratory, not independent validation.

The calibration gate scored 46.96% on 526 bearish currency calls (16.85%
coverage), 36.89% on 225 bearish US stock calls (0.90% coverage), and 39.44%
on 213 bullish crypto calls (13.44% coverage). It was worse than the
asset-local comparator in all three markets on the same eligible population;
the two methods selected different calls.

`contrarian_gate_forecast_research.py` tests the opposite of the earlier
market-regime gate: it permits asset-local calls only when the prior completed
market hit rate is below 50%. It writes
`research/contrarian-gate-forecast-research.json`. This rule was proposed after
examining the same years and is exploratory, not independently validated.

The contrarian gate scored 54.33% on 427 bearish currency calls (13.68%
coverage), 44.47% on 787 bearish US stock calls (3.15% coverage), and 55.25%
on 257 bullish crypto calls (16.21% coverage). Its approximate 90% block
bootstrap intervals were 50.34%–59.94% for currencies and 44.92%–66.35% for
crypto; neither lower bound exceeded 51%, and these intervals do not account
for repeated model search. This is an observed retrospective result, not
evidence that either algorithm will reach 51% in future. Compared methods
share the eligible population but select different calls. Crypto uses Yahoo,
not Binance; current selected listings omit many delisted assets. The app's
labels are unchanged.

`neighbor_contrarian_research.py` explores the same lagged contrarian gate
applied to the broader-coverage nearest-neighbor candidate. It writes
`research/neighbor-contrarian-research.json` and replays comparators on the
same eligible observations. The rule was chosen after inspecting the earlier
contrarian result, and is exploratory rather than independent validation.

The gated-neighbor candidate scored 52.93% on 735 bearish currency calls
(23.55% coverage), 44.20% on 5,310 bearish US stock calls (21.25% coverage),
and 46.51% on 387 bullish crypto calls (24.42% coverage). For currencies the
local contrarian candidate had higher observed accuracy but lower coverage;
for crypto it also had higher observed accuracy. Calls differ despite the
shared eligible population. The results are exploratory, not validation.

`rolling_selector_forecast_research.py` tests selecting among the local,
nearest-neighbor and contrarian-gated approaches using only their previously
completed calls. It writes `research/rolling-selector-forecast-research.json`.
The selector and its candidates were designed after inspecting the same
history, so results remain exploratory rather than independent validation.

The rolling selector scored 48.54% on 478 bearish currency calls (15.32%
coverage), 38.16% on 836 bearish US stock calls (3.35% coverage), and 38.55%
on 275 bullish crypto calls (17.35% coverage). It did not improve on the best
preceding candidates on the same eligible observations; calls differ.

`shock_filter_forecast_research.py` tests whether a negative prior 20-bar
benchmark return improves local or nearest-neighbor calls. It writes
`research/shock-filter-forecast-research.json`. The benchmark's previous local
calendar date is not a guarantee of availability across time zones; EUR/USD
is also a coarse currency proxy. This post-selection test remains exploratory.

The shock-filtered local and neighbor models scored 44.37% and 48.16% for
bearish currencies (311 and 515 calls), 46.10% and 46.64% for bearish US
stocks (269 and 1,966 calls), and 45.09% and 40.00% for bullish crypto (275
and 400 calls). Their respective coverage was 9.96% and 16.50%, 1.08% and
7.87%, and 17.35% and 25.24%. None reached 51%. The benchmark-date caveat and
the previously inspected, survivorship-biased sample still apply.

`peer_filter_forecast_research.py` tests top- and bottom-quartile peer
relative-strength filters on the local and neighbor calls. Peer returns use
earlier local calendar dates and raw, rather than outcome-filtered, bars; the
current-listing universe and cross-timezone availability remain limitations.
It writes `research/peer-filter-forecast-research.json`. Because these
historical years have been repeatedly examined, results are exploratory.

Peer filters yielded a best currency result of 52.40% on 208 calls (6.66%
coverage; local reversal), a best US bearish result of 50.46% on 329 calls
(1.32% coverage; local momentum), and a best crypto bullish result of 51.61%
on 155 calls (9.78% coverage; local momentum). Their approximate 90% block
bootstrap intervals were 43.85%–61.63%, 41.54%–57.67%, and 41.29%–62.59%,
respectively; none accounts for searching many models. All are exploratory,
not independent evidence, and calls differ across methods. Prior local-date
peer prices do not guarantee cross-timezone availability.

`peer_regime_forecast_research.py` evaluates combinations of the peer-rank
and market-rate filters on asset-local calls, saving
`research/peer-regime-forecast-research.json`. The combinations were proposed
after inspecting their components and therefore are exploratory, not an
independent test. Small subsets and cross-timezone peer availability are
additional limitations.

The completed combined experiment exceeded 51% in the inspected historical
sample for all three requested directions: bearish currency reversal with the
contrarian gate scored 59.29% on 113 calls (3.62% coverage), bearish US stock
momentum with the contrarian gate scored 52.40% on 271 calls (1.08% coverage),
and bullish crypto momentum with the contrarian gate scored 54.64% on 97 calls
(6.12% coverage). The earlier local contrarian crypto model scored 55.25% on
257 calls (16.21% coverage). Approximate 90% block bootstrap intervals for
these three combined variants are 50.00%–71.13%, 41.83%–60.38%, and
43.62%–68.75%, respectively; none has a lower bound above 51%, and the
intervals do not correct for repeated selection. The filters were selected
after examining the same historical years. The result is not an independent
or prospective test, and peer bars' prior local dates do not guarantee that
their closes were available in all cross-timezone cases. Current-listing
survivorship, missing-outcome selection, overlapping outcomes and Yahoo rather
than Binance crypto further limit interpretation. The app remains unchanged.

`peer_regime_sensitivity_research.py` checks the selected combined rules with
peer data delayed an additional three calendar days and with a greedy
non-overlapping-per-asset subset. Its output is
`research/peer-regime-sensitivity-research.json`. These checks can expose
fragility but cannot undo historical model selection, survivorship bias or
cross-asset dependence, and they are not independent validation.

Sensitivity results: delaying peers an extra three calendar days yielded
60.38% over 106 currency calls (3.40% coverage), 52.14% over 280 US calls
(1.12%), and 50.50% over 101 crypto calls (6.37%). Keeping only the first
signal per asset until its previous selected outcome completed yielded, with
the original peer dates, 57.81% on 64 currency calls, 50.66% on 152 US calls,
and 57.69% on 52 crypto calls; with delayed peer dates it yielded 62.50% on
64, 49.37% on 158, and 52.83% on 53, respectively. Non-overlapping subsets
select different calls and remain correlated across assets. Currency's
reported delayed interval excludes 51%, but neither that interval nor these
checks correct for post-selection, missing outcomes, or survivorship; they do
not establish future performance.

`peer_regime_concentration_research.py` replays the selected original calls,
checks that counts match the combined report, and records breakdowns and
leave-one-group-out hit rates by year, month, and asset in
`research/peer-regime-concentration-research.json`. These are hindsight
diagnostics, not live filters or independent tests; subgroup results do not
correct for selection or shared market shocks.

The concentration audit reproduced the selected calls. Removing 2024 calls
from the US summary lowers observed accuracy from 52.40% (271 calls) to
48.82% (211 calls); removing `PARA` calls lowers it to 48.81% (252 calls).
These are retrospective exclusions of calls, not a re-run without the year or
symbol in training, market rates, or peer ranks. Crypto falls from 54.64% to
50.60% when `TRX-USD` calls are excluded; currency falls from 59.29% to 53.66%
without 2024. These examples do not prove causality or future performance.

On 2026-10-30 the Yahoo chart API identified `PARA` as **Parabolic
Technologies, Inc.**, first trade 2021-02-12, and reported four reverse split
events in its history (1:50, 1:10, 1:20, and 1:10). The saved history contains
only ticker, bars, and time zone—not a verified point-in-time company identity
or corporate-action record. The intended issuer and whether these events
distort the measured calls are not established. Do not identify this series
with another company solely from the ticker; audit historical identity and
adjustments for the universe and rebuild affected experiments before drawing
conclusions. In particular, the US result is not a validated 51% predictor.

`us_symbol_sensitivity_research.py` replays the US combined experiment and
rebuilds it with `PARA` excluded from observations, market-rate history and
peer ranks, writing `research/us-symbol-sensitivity-research.json`. This
post-selection sensitivity audit is not a point-in-time identity or
corporate-action verification and is not independent validation.

The completed rebuild reproduced 52.40% on 271 US bearish calls with PARA,
and obtained 48.81% on 252 calls (1.01% coverage) without PARA throughout the
inputs. Both experiments are retrospective, and excluding a ticker after
observing its influence is not an unbiased validation. Corporate-action and
point-in-time issuer identity issues remain unverified for the wider universe.

`peer_neighbor_regime_research.py` evaluates nearest-neighbor calls combined
with peer momentum/reversal and the prior market contrarian gate for all
three directions. It also rebuilds the US experiment with PARA entirely
excluded, replays the previous local comparator, and writes
`research/peer-neighbor-regime-research.json`. All results are post-selection
research on previously inspected years, not independent validation.

The peer/contrarian-filtered neighbor candidate scored 54.17% on 240 bearish
currency calls (7.69% coverage; reversal), 45.18% on 1,609 bearish US calls
(6.44% coverage; reversal), and 52.14% on 117 bullish crypto calls (7.38%
coverage; momentum). Rebuilding the US inputs without PARA produced 45.16%
on 1,610 reversal calls (6.45% coverage). These selected calls differ from
the local model's calls; the results are exploratory, not validation.

`peer_regime_baseline_research.py` evaluates peer rank plus market-rate gates
without requiring an asset-local call, while retaining the same local-history
eligibility for comparison. It rebuilds the US inputs without PARA and saves
`research/peer-regime-baseline-research.json`. The rules were developed after
repeatedly examining this history; they remain exploratory, not independently
validated, and peer timestamps remain a cross-timezone limitation.

The completed peer/market baseline did not reach 51% for US stocks: without
PARA, its best variant scored 48.78% on 1,023 calls (4.10% coverage), all
in only 13 signal months. The best baseline variants for bearish currencies
and bullish crypto scored 50.19% (528 calls, 16.92%) and 48.12% (320 calls,
20.19%), respectively. The baseline selected different calls on the same
eligible population. These are exploratory historical results.

`outcome_availability_audit.py` reconstructs valid-input monthly signals even
when their three-month outcomes are not yet known, and counts pending and
matured-missing outcomes separately from observed outcomes. It replays the
selected local/peer/contrarian research calls (with PARA excluded from US
inputs), never scores unresolved calls, and writes
`research/outcome-availability-audit.json`. This retrospective audit exposes
missing outcomes but cannot remove survivorship, selection, local-time or
corporate-action biases.

As of the dataset's 2026-10-30 UTC collection date, this audit reconstructed
16 bearish currency, 24 bearish US stock (without PARA), and 6 bullish crypto
calls whose exits were not yet due. The corresponding completed calls were
67 correct out of 113, 123 out of 252, and 53 out of 97. Pending calls are
unknown, not losses; this is retrospective reconstruction, not a record of
predictions actually made before their signal dates. The audit found no
additional matured-missing or within-grace outcomes among the valid-input
signals in these saved received histories. It does not capture instruments
missing from the dataset altogether.

`pending_outcome_bounds.py` writes `research/pending-outcome-bounds.json`,
which shows arithmetic extremes if every pending call were wrong or every one
were right. Including pending calls, the observed-reconstruction totals could
range from 51.94% to 64.34% for currencies, 44.57% to 53.26% for US stocks,
and 51.46% to 57.28% for crypto. These are not predictions, confidence
intervals, or prospective validation; outcomes are unknown. For US stocks,
18 of the 24 unresolved calls would need to be correct to reach 51% across
the combined 276 calls.

#### Bearish forecast research: PSE, US equities and funds

`bearish_forecast_research.py` tests a separate experimental three-calendar-month
price-direction forecast for each of these markets. It does not change the app's
descriptive trend labels. Each year it chooses among seven fixed candidate rules
using the prior two years' completed outcomes: asset-local historical outcomes,
local calls combined with relative-strength ranks and a market-outcome gate,
and weak- or strong-trend rules. To qualify, a candidate needs at least 60
validation calls, six signal months, ten instruments, 51% accuracy, and a
one-percentage-point advantage over always predicting down on the validation
population. If none qualifies it abstains. This is a heuristic, not a confidence
guarantee; yearly selections and diagnostics are saved in the report.

Run `python3 bearish_forecast_research.py` with the saved research histories to
write `research/bearish-forecast-research-comparable.json`; the script refuses
to overwrite that report. `research/bearish-forecast-research.json` records an
earlier run whose US coverage used a larger eligible population and must not be
compared directly with the older local-history US candidate. The comparable run
requires the same available asset-local score for the US comparison and excludes
PARA throughout US observations, peer ranks, and the market gate. PSE uses its
90-day chart window; Yahoo equities and funds use three calendar months. Peer
returns use calendar months in all markets. The fund universe includes other
exchange-traded products as well as conventional ETFs.

In the completed 2020–2026 evaluation the selected-rule candidate scored
52.00% on 1,275 PSE calls (12.38% coverage), 38.76% on 2,722 US calls
(10.90%), and 33.33% on 669 fund calls (9.25%). Always predicting down across
the same eligible populations scored 56.54%, 43.28%, and 42.02%, respectively;
these baselines select different cases. On the same eligible US population,
the previous momentum/contrarian local rule scored 48.81% on 252 calls (1.01%
coverage). The new candidate is not an improvement in observed US accuracy.
Applying that previous rule to funds scored 55.11% on 176 calls (2.43%
coverage); its approximate 90% time-block interval was 42.86%–64.14% and it
was highlighted after inspection, not selected in an independent test. The
corresponding interval for the PSE candidate was 42.35%–60.90%. None of these
results validates a forecast for an individual instrument.

Signal outcomes finishing on or after a forecast date cannot enter its local or
market history; validation outcomes finishing on or after a test year cannot
select its rule. The test uses first monthly closes and the first close on or
after three calendar months (at most ten days late); unchanged prices are
misses. Missing and pending outcomes are excluded, and past observations are
reconstructed from outcome-available histories. Current listings omit many
delisted securities, histories and corporate actions are unverified, peer local
dates do not guarantee real-time availability, and returns are not executable
trade returns. These repeatedly examined years are exploratory, not a fresh
holdout; intervals do not account for model search. A prospective, point-in-time
evaluation is needed before deployment.

#### The odds of profit, on the chart (2026-11-01)

Under the price the chart prints one figure: **the estimated probability, 0 to 1,
of a positive three-month price return after assumed round-trip costs**, using
only the daily prices displayed in the graph. This replaces the class base-rate
model at the reader's request. It is separate from the descriptive trend badge.

`probability.py` fits the sample mean `m` and standard deviation `s` of the `n`
drawn daily log returns. With `H` future sessions, it calculates:

```
P = normal_cdf((H*m - log(1 + cost)) / (s*sqrt(H + H*H/n)))
```

The predictive variance includes future price noise and uncertainty in the
estimated mean. Crypto uses every calendar day in the next three calendar
months; other supported assets use weekdays (exchange holidays are not modeled).
Class mappings supply only calendars and assumed costs, never return priors.
Results are bounded to 0.01–0.99. Short, invalid, constant-return and weekly
series receive no estimate; yields remain excluded. Futures now use their own
displayed returns and weekday calendar, with an assumed 0.20% round-trip cost
relative to notional value. Their estimate is for a long contract price gain,
not leveraged account profitability; expiry, rolls and margin are not modeled.

The page prints `3-month profit odds … · chart-based estimate, net of …% costs`.
Its tooltip states the independent stationary normal-log-return assumption and
limitations: this is not empirically calibrated, regimes and fat tails can break
the model, and taxes/currency conversion are excluded. Tests cover the formula,
response to chart returns, mean uncertainty, calendars, costs and missing data.

**The watchlist row prints the same figure** (added 2026-11-04), as a third line
under its name and its window's move — `3-month odds 0.69`, coloured above/below
0.5 like the stat-line. It is read from the row's own chart payload, so the rail
and the chart it opens cannot disagree about the odds; a yield, a refused series
or a row that has not answered yet draws no line at all rather than a default.

#### Research judgment on the chart

**The chart no longer shows a research-judgment line** (removed 2026-10-31 at the
reader's request). For any asset outside the studied universe it printed
"Bullish: could not be calculated … Bearish: could not be calculated" and then an
in-sample asset-history baseline — three lines that read as a verdict about the
asset while saying the research had nothing to say. The line, its renderer, its
markup and its stylesheet rules are gone; the page no longer calls
`/api/research-judgment`. The endpoint itself is unchanged and still answers
anyone asking directly, and nothing about the current-trend badge, the tables or
the sweep depends on it.

What follows describes the research the endpoint still serves.

The currently implemented research paths are the Philippine bullish local
filter, the frozen 2026 Philippine bearish local/peer filter, frozen 2026 US and fund bullish score bins, and the frozen 2026 currency
bullish model. The fund bearish 2026 selector abstained. These paths require
the studied instrument identity and source, completed daily prices, and the
first completed close of the current month; the latter matches the research
schedule rather than implying that daily calls were validated. A latest price
over seven calendar days old is unavailable. The frozen folds are unavailable
outside 2026. A currency conflict is withheld as in the original study, so its
reported rate is not attributed to an untested independent call.

US bearish, crypto bullish/bearish, currency bearish, and
other peer-dependent rules are not yet live: they require fresh, compatible
multi-year asset/peer histories and the exact annual selection procedure.
The crypto study used Yahoo, whereas this app commonly uses Binance and ticker
identity alone is not enough to establish equivalence. Unsupported assets,
sources, missing data and outages are explicitly unavailable. PSE histories
are fetched separately and may still lack the stock-local observations needed
for a call. Philippine bearish peer histories are fetched across the studied
universe, shared between requests for an hour, and not used when too many
fetches fail; a cold fetch can take time. Both Philippine signals can appear
together when their respective rules qualify. This is a partial integration,
not deployment of all researched rules.

Research history is fetched independently of the visible chart. If a
non-PSE research window has fewer than 50 completed bars, the server also
checks the same asset and source in two- and five-year daily histories. It
re-evaluates the original three-month window; older prices outside that window
do not count, and no extra prices are added to the graph. PSE research already
requests the provider's maximum history. Sparse trading, missing bars, outages,
and unsupported rules can still prevent a signal; the page explains why rather
than presenting a missing result as a market call.

When neither research rule signals, the server fetches and caches a longer
history of the same asset and source. With at least six completed monthly
three-calendar-month outcomes, it shows the more frequent direction as an
**asset-history baseline**, with counts of up, down, and unchanged outcomes.
The direction and its frequency come from the same data: this is descriptive,
not out-of-sample forecast accuracy or an individual probability. Overlapping
periods are correlated. The baseline is not a previously researched algorithm
and does not inherit its reported hit rate. Tied direction counts, missing or
stale prices, insufficient history and unknown time zones remain unavailable.
PSE histories and peer snapshots are cached in `.cache/`; other assets use the
existing cached chart-history path. An outage fallback is identified as cached.

The shown decimals are pooled, repeatedly inspected **historical hit rates**,
not probabilities for a particular asset or assurances of future performance.
The research used three-calendar-month price outcomes, not trading returns;
the history has selection and survivorship biases and no costs or dividends.
The Philippine bullish result is particularly unstable across years; the US
bearish candidate had only 13 calls. Applying historical monthly rules to new
conditions remains unvalidated.

#### Further US bearish refinement

`us_bearish_refinement_research.py` tests a model-based filter on the earlier
bearish US momentum/contrarian candidate. It excludes PARA from the complete
US observation and peer inputs and checks that its earlier-candidate replay
matches the saved PARA-free evaluation. Each yearly model trains only on
outcomes completed before a separate two-year validation period; threshold
selection uses earlier completed calls from the previous candidate. It makes
calls only where the previous candidate does and abstains if validation fails
its accuracy, lift and sample requirements. The report records annual choices,
the same-population previous candidate, and the previous candidate in active
test years. The script refuses to overwrite its saved report at
`research/us-bearish-refinement-research.json`.

In the completed 2020–2026 replay, the refinement scored 53.85% (7/13;
0.05% coverage) versus 48.81% (123/252; 1.01% coverage) for the previous
candidate on the same eligible population. In the two years where the new
model made calls, the previous candidate scored 41.51% (22/53). The new model
scored 33.33% (2/6) in 2021 and 71.43% (5/7) in 2026, with no calls in the
other five years. The candidates select different calls; 13 observations over
eight signal months are far too few to establish an improvement, and no block
interval was computed. One additional correct or incorrect result would change
the percentage substantially. Do not substitute this as a validated accuracy.

The years have already been inspected repeatedly, so this is exploratory, not
an independent holdout or a prospective forecast. Monthly outcomes overlap,
present-day listings omit many delisted stocks, historical ticker identity and
corporate actions remain unverified, and previous-local-date peer closes do
not prove availability at the signal time. The app labels remain unchanged.

### Philippine current-trend audit

The app already determines whether a Philippine stock is bullish now through
the shared `trend.classify` on the PSE chart's 90-day price window. The score
combines drift momentum (40%), regression trend (25%), price efficiency (20%),
and range position (15%); it calls bullish at +0.25 or higher *and* a drift
t-statistic of 1.96 or higher (see "The trend badge" below). Volume does not
vote. The audit, like the other research tools, scores with the frozen
version-1 classifier (`trend_v1.py`) its numbers were measured on. The same
classifier and window determine both the chart badge and bullish-table row;
the label describes past prices, not the next three months.

`pse_current_bullish_audit.py` separately audits that existing rule on the saved
PSE histories. It includes only bars before the Manila collection date, requires
at least two prices in the 90-day window, and flags a latest price more than
seven calendar days old; it reports fewer than 50 bars separately. These are
audit-only data checks, not new live inclusion rules. The live chart can include
an unfinished daily bar and fall back to older bars, so the audit and live
verdict can differ. Seven days is a heuristic, not an exchange-calendar check.

On the snapshot collected 2026-10-30, all 244 requested histories were received:
179 had at least 50 bars and a last bar within seven days, 57 had fewer than 50
bars, and eight were stale. Of the 179 full-window series, 17 were bullish, 57
bearish and 105 neutral. All 17 bullish series finished above their first
90-day close; that is a descriptive consistency check, **not** a measured
accuracy or proof of future gains. Full details are saved in
`research/pse-current-bullish-audit.json`; run
`python3 pse_current_bullish_audit.py` on a saved PSE collection to reproduce
it (the script refuses to overwrite an existing report).

#### Philippine bullish and fund bearish forecast filters

`pse_bull_fund_bear_research.py` explores three-month outcome filters for
existing PSE bullish labels and bearish fund calls, without changing the live
trend labels. PSE candidates can only select stocks the existing classifier
already labels bullish. The filter considers trend strength, local completed
outcomes, prior-date peer returns, and volatility. Fund candidates also consider
recent market-wide completed outcomes. Each year the selector uses the prior
two years of completed validation outcomes and abstains unless a rule meets its
minimum sample, accuracy, and baseline-lift gates. The test compares with the
existing PSE bullish label and the prior fund momentum/contrarian local rule on
the same eligible populations, though selected calls differ.

The completed 2020–2026 replay found no established improvement. The PSE
filter scored 45.54% (51/112; 1.09% coverage), versus 44.38% (789/1,778;
17.26% coverage) for all existing bullish calls across that full period. The
filter made calls only in 2025–2026, when all existing bullish calls scored
47.20% (278/589), higher than the filter. The new fund selector scored 33.33%
(223/669; 9.25% coverage); the prior fund rule scored 55.11% (97/176; 2.43%
coverage) on the same eligible population. Calls differ, and the fund result
was highlighted after earlier inspection; it is not independently validated.
The fund universe contains other exchange-traded products, not only ETFs.

These are retrospective, repeatedly inspected monthly observations; missing
and pending outcomes are excluded, the present-day universe omits most
delistings, and peer local dates do not ensure time-of-day availability. They
exclude costs, dividends and an executable entry assumption. The selected
historical percentages are not forecasts for individual stocks or funds.
Full annual results and validation choices are in
`research/pse-bull-fund-bear-research.json`; the script refuses to overwrite
the report. Future prospective testing is needed before deploying a filter.

`selective_bull_bear_research.py` tries narrower rolling filters: all PSE calls
must already be bullish under the app's shared classifier, and all fund calls
must already pass the earlier momentum/contrarian local rule. Each signal date
selects a filter using only the prior 36 months of already completed calls,
with sample-size, observed-hit-rate and baseline-lift requirements. The script
saves `research/selective-bull-bear-research.json`, including selection dates,
annual results and comparisons on the same dates. It refuses to overwrite the
report.

On the 2020–2026 population the rolling PSE candidate scored 44.44% (84/189;
1.83% coverage), compared with 44.38% (789/1,778; 17.26% coverage) for the
existing bullish labels across all dates and 43.18% (519/1,202) for those labels
on dates when the selector was active. Its results varied by year: 57.45% on
47 calls in 2024, 51.43% on 35 in 2025 and 31.82% on 22 in 2026. The rolling
fund candidate scored 53.12% (17/32; 0.44% coverage), versus 55.11% (97/176;
2.43%) for the earlier fund rule across all dates and 61.02% (36/59) on active
dates. The selected calls differ. These scores do not establish an improvement,
especially given the very small fund sample, overlapping calls, repeated
historical selection and lack of a prospective holdout; no app labels changed.

`pse_bullish_model_research.py` fits a regularized model only to past app
bullish labels and selects thresholds on an earlier validation period. It
scored 28.57% (16/56; 0.54% coverage) on 2020–2026; the app's bullish labels
scored 47.20% (278/589) in its active 2025–2026 test years. It is not an
improvement. Its annual diagnostics are in
`research/pse-bullish-model-research.json`.

`pse_bullish_local_research.py` instead evaluates stock-local filters on the
same actual app bullish labels, using only outcomes completed strictly before
each signal. The local regime filter requires 24 prior completed outcomes and
six observations matching the stock's current price-feature regime; it shrinks
that regime's historical positive-outcome rate toward the stock's recency-
weighted overall rate and calls only when the score is at least 55%. It scored
52.47% (117/223; 2.16% coverage) across the 2020–2026 eligible population,
versus 44.38% (789/1,778; 17.26%) for all bullish labels. The subsets differ.
An approximate 90% time-block interval for the local filter is 46.44%–60.09%,
and does not correct for research selection. Results by year were 33.33% (1/3)
in 2023, 61.05% (58/95) in 2024, 50.63% (40/79) in 2025, and 39.13% (18/46)
in the available 2026 outcomes; no calls occurred in 2020–2022. A neighbor
filter and intersection are also reported in
`research/pse-bullish-local-research.json`. These are post-inspection,
exploratory comparisons, not a probability for an individual stock or evidence
of a stable future edge. The app's labels remain unchanged.

### Philippine three-month outcome study

`pse_backtest.py` collected split-adjusted TradingView daily bars for 244
currently listed PSE equities. It tests signals on the first available session
of each month, buying at the next session's open and measuring the closing
price on or after three calendar months. Signals before 2025 are development;
the 2025-onward holdout is separated by an outcome embargo. All comparisons
require at least 252 previous bars and recent six- and twelve-month prices.

In the holdout, the current bullish signal had 614 observations: **46.42%**
finished above entry and **5.86%** stayed bullish on every available bar.
Requiring the price to be above both its six- and twelve-month reference prices
gave 476 observations: **47.90%** finished above entry and **6.30%** stayed
bullish. These are descriptive historical frequencies, not probabilities for
an individual stock. Observations overlap, the universe excludes delisted
stocks, returns exclude dividends and costs, and opening prices may not be
achievable. The test does not establish a reliable three-month predictor.

The PSE chart still draws only three months. It fetches additional history
privately for six- and twelve-month context, based on completed daily bars;
stale or insufficient history is marked unavailable. This context is not a
second bullish classifier, a promise, or an estimate of future returns. The
full report and raw data are `research/pse-backtest.json` and
`research/pse-history.json`. Rerun with `python3 pse_backtest.py collect`
then `python3 pse_backtest.py evaluate` (Moli and an internet connection are
needed to collect). The displayed historical percentages are a fixed snapshot
of this study, not automatically updated by re-running it.

**Version 2 (2026-10-31).** One score in `[-1, +1]` over **every bar the chart
draws** — 93 for a coin, 65 for a US stock, 38 for a thin PSE name:

| Weight | Signal | What it measures |
|---|---|---|
| 0.40 | momentum | The window's drift as a t-statistic: weighted mean log return over its standard error |
| 0.25 | trend | Weighted log-price regression slope × R2, normalized to a 30% window move |
| 0.20 | efficiency | Weighted net move over weighted path length — how directly price traveled |
| 0.15 | range | Where the last close sits in the window's low-to-high range |

A label needs **evidence**, and once given it **holds**:

| Band | Condition | Effect |
|---|---|---|
| enter | score ≥ 0.25 **and** drift t ≥ 1.96 | Bullish (mirror for Bearish) |
| hold | score ≥ 0.15 and drift t ≥ 1.0 | keeps a label that entered within the last 10 bars, through an unbroken run (`held: true`, confidence "holding") |
| — | anything else | Neutral |

- **Returns are ramp-weighted**: the oldest quarter of the window phases in,
  so the bar leaving the window barely moves the call.
- **Short windows need more evidence, not a damping curve**: the t is read
  against the Student-t critical value for the bars there are, so a 9-bar
  window needs a stronger drift than a 63-bar one to clear 1.96. Fewer than 4
  bars read Neutral.
- **Stale prints don't pass for a trend**: positive day-to-day correlation
  (a thin name repeating its price) widens the standard error.

Measured on the saved history (74 instruments, ~37,000 three-month windows),
version 1 → version 2:

| | v1 | v2 |
|---|---|---|
| Driftless random walks labelled | 49% | ~8% |
| Label changes per 100 bars | 8.1 | 0.8 |
| Changes reversed within 5 bars | 59% | 24% |
| A one-sigma move in the newest close changes the label | 9.3% | 0.4% |
| Dropping the oldest bar changes the label | 3.4% | 0.6% |

The cost of strictness: a real but modest trend is labelled less often — a
+0.25%/day drift in 1.5%/day noise is caught in ~30% of 63-bar windows — and
on real data ~5% of windows carry a label (v1: ~47%). **Neutral means "no
trend random movement would rarely produce", not "flat".** The payload carries
`significance` (the drift t) and `held` beside the label, and the page prints
both.

**The badge describes the observed price trend, not a forecast, probability,
or buy recommendation.** Version 1 lives on, frozen, as `trend_v1.py`, only
because the research models were fitted on its score scale. Details are in
the `trend.py` docstring.

## Notes

- **Range is fixed at 3 months, daily bars.** `RANGE` and `INTERVAL` at the top
  of the script block in `index.html` are the knobs. The server allowlists
  `1mo/3mo/6mo/1y/2y/5y` and `1d/1wk`, and rejects anything else, so nothing a
  client sends can reshape the upstream URL.
- **Responses are cached 60 seconds** in memory, keyed by upstream URL. Repeat
  loads of the same symbol do not re-shell out to Moli. PSE charts have no
  upstream URL, so they are keyed by symbol and range instead. The CoinGecko and
  TradingView indices are cached an hour on top of that, and a Binance close 5
  minutes. The most-traded tables cache 300 seconds (see `TOP_TTL`). The
  bullish table and the recently-bullish table are not cached at all — they are
  swept ahead of time and read from memory (see `BULL_TTL` / `RECENT_TTL` and
  [above](#why-it-is-held-warm-by-a-background-thread)).
- **Every cache answer is also kept on disk** under `.cache/` (30-day horizon,
  see `diskcache.py`), so with the internet down the page serves the last good
  copy dated "data last retrieved …" instead of empty tables. The guard runs in
  both directions: the most-traded tables report an outage *inside* the payload
  (one error card per dead section) rather than raising, so `cached` checks the
  answer for real rows before letting it overwrite the disk copy — a
  total-outage payload is never mistaken for an answer.
- **A disk fallback only helps if something was ever fetched**, and before the
  row warmer that meant "whatever a reader happened to click" — offline, the
  page could name every top stock and draw none of their graphs. So one
  background thread (`warm_rows_loop`) keeps the chart of **every symbol listed
  in the four tables, plus every symbol the page has ever declared**
  retrievable whether or not anyone clicks it: each pass it reads the
  leaderboards, the two sweeps and the crypto table through the same
  `tables_payload()` / `bullish_state()` / `recent_state()` / `cryptobull_payload()`
  calls the routes make — so a refresh a browser sees is the
  same one the warmer sees — and fetches, at the window the page draws
  (`WARM_SPAN`/`WARM_INTERVAL`, kept honest by `chart_key` being the one
  spelling both sides share), any listed symbol whose disk copy is older than
  `ROW_STALE_AFTER` (fifteen minutes — the same cadence the tables and the
  sweep run on, so no listed row can be meaningfully staler than its table).
  The declared list is
  the reader's own watchlist, which no source publishes and no table lists: the
  page hands it over with `POST /api/watch`, and the server keeps the *union* of
  every list ever declared, so a symbol saved on a phone is kept warm for the
  desktop page too, and a rebooted server still remembers the whole list (the
  union is stored as a plain record under `client:watchlist`, exempt from the
  30-day age-out that applies to fetched copies — a fact the server was *told*
  must not expire like a copy it *fetched*). Watchlist rows lead the queue:
  these are the symbols a human chose to keep, so they warm ahead of the PSE
  tail rather than waiting behind it. A symbol
  whose chart *landed* within the window is not re-tried — its fresh disk copy
  is adopted instead of re-fetched, so a restart costs zero browser runs.
  **Rows are warmed in batches, not one at a time.** The first version spent a
  full browser launch per row (~100 launches + `WARM_PACING` between them ≈
  215 s a pass — mostly the price of Chrome, not of data). Now the queue
  splits by upstream: PSE rows go through `pse.charts_many`, which warms forty
  of them over one shared TradingView socket per run (~3 runs for ~90 rows);
  everything else goes through one batched Moli run (`moli_batch_get`), which
  fetches twenty Yahoo chart URLs inside a single page (`Promise.all`,
  status code preserved per URL). Crypto rows still get the reroute test the
  live route applies (`yahoo_is_wrong` → Binance substitution, one cached
  close per coin). A full pass costs a handful of browser runs plus
  `WARM_PACING` between chunks — seconds, not minutes. An attempt that
  *raises* is remembered for the window too (no disk copy to protect, and
  retrying a dead wire ninety times costs ninety browser runs for the same
  answer): if a fetch cannot land, the rest of the queue is one outage
  wearing ninety rows — the pass stops, the broken chunk's stamps stay, the
  rows behind the break are re-queued on the next pass, and the thread sleeps
  `WARM_BACKOFF`. A row that Yahoo answers "no such instrument" (404 with
  `chart.error`, or `PseNotFound` from TradingView) is a *verdict* about a
  symbol a table vouched for, so it is stamped like a landing and not
  re-queued every pass. A live click on a
  symbol mid-warm shares the in-flight fetch rather than duplicating it
  (single-flight in `cached`).
- **Reconnecting refetches everything, unprompted.** The warmers refresh on
  schedules, and a schedule is a poor way to notice the internet coming back —
  a failed sweep would still sleep its remaining fifteen minutes, and an outage
  memo would keep serving its stamped copy until the TTL happened to expire. So
  a watch thread (`net_watch_loop`) asks a reachability question every five
  seconds — a bare TCP connect to Binance's market-data mirror on port 443, no
  HTTP, no browser, so it never queues behind the real fetches over Moli's
  profile lock — and the instant the answer flips from no to yes it empties the
  in-memory memo (every key's next read goes live; the disk copies stay, so a
  wire that drops again mid-refill still falls back), advances a reconnect
  epoch, wakes every sleeper, and re-runs the startup prewarm for the hero
  chart and the tables — including the declared watchlist, so a saved row is
  back on fresh data without the page being open at all. The epoch is what keeps
  the row warmer honest: each woken pass re-consults disk, so a row whose chart
  *failed* during the outage
  is due again at once, while a row whose chart *landed* re-adopts its fresh
  disk copy and costs no browser run — failed attempts forget, successes keep
  (above). `/api/health` reports
  `"online"` and `"reconnections"` — the edge is also logged to the console, so
  you can watch it fire by turning Wi-Fi off and on. The console gets a closing
  sentence too: `back online: re-fetching everything now` opens a report with
  three named parts — the first paint, the bullish sweep, and the row charts —
  each marked by its thread when its post-edge pass completes, *carrying
  whether the pass landed fresh data or merely ran*. When the last mark lands
  the server prints `back online: all refetches finished (Ns)` — or, if
  anything ended without new data, `refetch passes ended (Ns), but no fresh
  data for: <the parts>` and a promise to retry. A line claiming a refill the
  wire refused is worse than no line: it is how stale rows survive their own
  reconnection unnoticed. (If no page has ever declared a watchlist when the
  edge fires, the opening line comes with a note saying so — an empty union
  means "everything" contains no saved rows, and that is worth knowing at the
  moment it matters, not two log lines later.) An open page learns the same
  way: it polls `/api/health` every 30 seconds and refreshes its watchlist rows
  and active chart the moment `reconnections` moves.
- **Startup says when it is done fetching.** The boot runs the same three
  fetching passes a reconnection does — the first paint (hero chart and
  tables), the bullish sweep, and the row charts — so it opens and closes the
  same completion report: once all three first passes land, the console prints
  `startup warm: all refetches finished (Ns)`, or `startup warm: passes ended
  (Ns), but no fresh data for: <the parts> -- kept the saved copies; the next
  passes retry` when the wire was down at boot. Before the report existed the
  startup marks were dropped silently, and a reader watching the boot had no
  way to tell "still fetching" from "done" — the page opening was the only
  signal, which is also why data seemed to arrive only on visit: it was
  arriving all along, just without a line saying so.
- **The chart meta line names its source** (`via Yahoo` / `via Binance` /
  `via TradingView`) and, for crypto, the coin's market-cap rank — so a rerouted
  symbol is never mistaken for Yahoo's answer, and the rank is what tells the
  intended coin from a collision.
- **Crypto bars from Binance carry real volume**, so the ensemble's volume signal
  is meaningful for those symbols; on the Yahoo crypto path it is too.
- **Watchlist and theme persist in `localStorage`** — per browser, still the
  durable one. The saved symbol is the server's canonical one, so charting `jup`
  stores `JUP-USD`, and the row is the same instrument the chart drew. The list
  is also *declared* to the server (`POST /api/watch`, on page load and on every
  change) so its charts can be kept warm; the server-side union is for warming
  only — a row the reader deleted stops being drawn and is forgotten by every
  browser, even though its chart stays retrievable for a quarter-hour.
- **The watchlist has no length limit** (changed 2026-10-31, at the reader's
  request). It used to stop at 40 symbols on both sides — the page refused the
  41st with "Watchlist is full (40 symbols)", and `_clean_watch` truncated a
  longer declaration to 40 before the warmer saw it. The 40 was never a
  measurement; it was a number picked when the list was a convenience. Now the
  page keeps every row it is given, the server keeps the whole declared union
  on disk, and the only bound left is the request body's 2 MB ceiling in
  `read_json` — a memory guard, not a product limit.
- **Every watchlist row carries its verdict** — a small pill beside the symbol
  reading Bullish, Bearish or Neutral, plus the score on hover. It is read off
  the row's own quote, and that quote *is* the `/api/chart` payload, so the pill
  and the badge of the chart a click opens are one call of `trend.classify` on
  one set of bars. A row whose series cannot be scored, or that has not arrived,
  shows no pill — never a made-up "Neutral". The pill and the row's percentage
  answer different questions and may disagree on purpose: the pill is the
  classifier's verdict on the window, the percentage is how far the window
  actually moved.
- **And the row's odds** (added 2026-11-04) — `3-month odds 0.69` on a third
  line, read from the same payload's `profitProbability`, so the rail and the
  chart agree about the next three months exactly as they do about the last
  three. A yield, a series `probability.estimate` refuses, or a row still
  loading draws no line at all. See "The chart states the odds of profit".
- **Yahoo "no data" arrives as HTTP 404** with a `chart.error` object, so the
  server treats only 5xx as a transport failure. The message is surfaced on the
  page instead of a traceback.
- **The trend badge is an annotation, not the product.** If `trend.py` cannot
  score a series, the chart still draws.
- **Localhost only.** The server binds `127.0.0.1` and has no authentication.
