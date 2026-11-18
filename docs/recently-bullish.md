# Recently bullish assets

[Back to the README](../README.md)

The page's one table answers one question across every market it follows:
**what is bullish right now, and since when?** `recent.py` builds it,
`/api/recent` serves it, and the page draws it as a single table with a
**Market** column — US stocks and ETFs on the Ondo shelf, Ondo's intelligent
portfolios, Philippine stocks, crypto, the US Treasury futures, the Philippine
government bond yields and the Philippine funds — sorted newest turn first.

The page used to carry three tables that each answered a piece of this.
"Bullish Philippine stocks" is every PSE name that is bullish, dated. "Most
traded crypto" is the heaviest coins that are bullish. "Most traded today" is
the busiest listings in two markets, with no verdict at all — the first of the
three that has left the page (2026-11-07, for being a volume table with nothing
to say about a trend). On 2026-11-07 the reader asked for the other two to be
folded in as well: "I think we can combine ... in one table/section", and then,
on what the table is for, "the idea is just to show me which assets are bullish
right now, easy to understand?"

Merging them changed three things, and only three:

- **The crypto rows now read the whole chartable ranking**, not its first 25
  candidates. The old crypto table walked the ranking until it had ten bullish
  coins, so a shallow read would have lost rows it was showing — measured that
  day, the only bullish coin (BEAMUSDT, $0.74M traded) sat around 200th. The
  walk costs ~8 s over ~120 candidates, and the **leaning** rows are still read
  from the first 25 only, so the leaning table is exactly what it was.
- **The crypto table's day condition is gone, and nothing replaces it.** It was
  a rule for a table of what was heavy *and* up today: a coin flat or down on
  the rolling day was skipped before any bars were fetched. This table is the
  three-month verdict, and the reader asked for that reading only — "i'm only
  interested in 3-month change bro" — so the rolling day is neither a filter nor
  a figure on the row.
- **The Philippine volume floor and the "inferred from the yield" bond wording
  are unchanged**, because they are rules about a market and about a series,
  not about a table.

The Philippine rows remain the floored subset of the sweep: a name under
₱1,000,000 of turnover is judged and hidden, and the note says how many were
hidden. The crypto rows carry `priceHint` from their own chart, so a sub-cent
coin prints `$0.004040` rather than `$0.00`.

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
| Binance (crypto) | three **calendar** months, since 2026-11-07 — one span is one window whichever venue draws it, so a coin's chart and its row hold the same bars | `onset.onset(..., months=3)` |
| Philippine exchange, the bond yields | ninety days | `onset.onset(...)` (the default) |

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

### A lean is shown only when it is steady (2026-11-07)

Asked for by name after a watchlist name flickered in and out of the leaning
tag: "is there a way to filter out 'fragile' stocks like AAPL from being shown
to me?", followed by "how about we make the filtering consistent: 'Recently
bullish assets', 'Leaning bullish - not confirmed', 'watchlist' and the main
price graph judgment".

`onset.steady_lean` is the rule; `onset.decorate` is the same rule applied to a
`trend.classify` call. A lean is shown only when

* its **drift clears 1.15**, not merely the 1.00 hold bar, and
* the **same call answers "leaning" on 4 of the last 5 bars** — the previous
  windows, trimmed exactly as the chart would have trimmed them that day.

Measured over 120 sessions on 464 shelf names before the rule was chosen: the
median name flipped its tag **4 times**, and among the names leaning on the day
measured the median was **10** (AAPL 14, its drift reading running 1.26, 1.42,
1.26, 1.01, 0.76, 1.19, 1.02, 1.01). With the rule the median name flips **0**
times and the number of tag episodes across the population falls from **1,024 to
359**, at the cost of 11 rows down to 5 on the day it was measured.

**One rule, every surface.** `server.chart_data` applies `decorate` after its
read-time re-score, so a chart served from the 60-second memo or from a disk
copy gets the same treatment as a fresh fetch — and everything that prints a
verdict reads `trend.lean` from that one payload: the main price graph's badge,
the watchlist rail's tag, and the leaning table. A name withheld from the table
is a name whose chart reads plain "Neutral" too, and the chart's note says why
("It would lean bullish — 52% of the way — but the reading is not steady: held on
4 of the last 5 sessions"). `leanRaw` keeps the classifier's own reading beside
the verdict, so nothing is lost by withholding it.

**Two things it never does.** It never touches `label`, `score` or
`significance` — a Besarish chart is still Bearish, and no label is earned or
removed. And it never guesses: a series with no history behind its window
answers `steady: null` and keeps its lean, because an unanswerable question is
not a negative one (invariant 3). To give every chart that history, a Yahoo
chart now fetches **one range wider than it draws** (`FETCH_SPAN`: 3mo → 6mo,
…, 5y → 10y); `slim_chart` trims back to the asked span, so the drawn bars and
the badge are unchanged, and the five bars the trim drops ride along as
`historyTail`. The PSE, bond, fund, crypto and Ondo producers ship the same
five-bar tail from the history they already hold (crypto asks five bars more
than it draws).

`onset.py` holds the two windows the walk needs — `window_now` (the badge's own
window, which decides *inclusion*) and `window_at` (the window the chart
would have drawn on a given day, which the walk *measures with*) — plus the
labels, the runs and the censored flag. Each takes the shape of the window it
is asked for: `days` (ninety, the default) or `months` (Yahoo's calendar
months). The reasoning is unchanged from the
[section above](philippine-stocks.md#dating-the-start-of-a-run); what changed is that it now has one
home.

### Where each row's bars come from

Every instrument is judged on the series the page's own chart would draw for it,
so a row's verdict and the chart its click opens are the same series:

| Market | Source | Why |
|---|---|---|
| Ondo stocks and ETFs | Yahoo daily bars, through the Moli browser path | every stock and ETF listed at app.ondo.finance (`ondolist.tickers`), judged on the bars the page's own chart draws for that ticker — the shelf is the universe (2026-11-07) |
| Ondo portfolios | the token's own daily price from DeFiLlama (`ondo.py`) | the seven intelligent portfolios the same shop sells, judged on the series the chart a click opens draws |
| Philippine stocks | the Philippine sweep's own rows (`bullish.py`) | read from the sweep the server already keeps warm — re-sweeping would make this table fresher than the sweep it is built from |
| Crypto | Binance daily bars | the chartable USDT ranking (`cryptobull.candidates`), judged on the same bars the crypto table and the crypto chart use |
| US Treasuries | Yahoo daily bars, through the same Moli browser path | the seven Treasury futures on the curve (`rates.CONTRACTS`), a fixed list rather than a ranking, judged on the bars the chart route draws for them — see [the Treasury futures](#the-united-states-treasury-futures-which-are-prices-2026-10-31) |
| Philippine bonds | TradingView chart socket | `TVC:PH02Y`, `TVC:PH05Y`, `TVC:PH10Y` — the 2-year, 5-year and 10-year government bond yields, as daily closes in percent |
| Philippine funds | the publisher's own NAVPU register (`phfunds.py`) | forty-seven funds with no ticker and no exchange; each one's daily net asset value per unit is read from TOAP's UITF register, PIFA's NAV history or BPI Wealth's own fund page — see [Philippine funds](#philippine-funds-on-their-published-navpu) |

The Ondo leg is the expensive one: a year of daily bars for each of **474**
stocks and ETFs, fetched through the browser because Yahoo answers plain HTTP
clients with a 429. So this table is a **sweeper**, not a route, for the same
reason the Philippine sweep is: `RECENT_TTL` (900 s) apart on a background
thread, and a reader only ever reads what that thread last produced. The
Philippine rows come from the sweep above rather than a second one.

A full sweep measured about **23 seconds** for the 474 shelf symbols (2026-11-07,
twenty-four browser runs of twenty URLs each, none missing), measured on the
same machine that took 10 seconds for 130 names on 2026-10-31. So the payload is kept on disk under its own key
(`recent:scan`) and hydrated at startup, the same contract the Philippine sweep
has: an offline start still shows rows, and the note says the table is a saved
sweep rather than a live one. A failed refresh leaves the previous rows on
screen and reports the failure beside them; it never clears the table.

**Why the shelf and not a turnover ranking (2026-11-07).** The universe used to
be the 50, then 130, most-traded United States listings. Both were coverage
decisions taken by a number the reader never asked for, and both cut real names
off: WMT ranked 57th and KO 124th when 50 was the limit, and ACN ranked **172nd**
by turnover at $420M when 130 was — bullish on its own chart at +0.56, and
invisible. The reader's instruction replaced the ranking altogether: "the limit
is just what's available at app.ondo.finance — no longer trading volume, for both
bullish list and 'leaning bullish — not confirmed'", then "include all stocks &
ETFs, and intelligent portfolios". So the universe is `ondolist.tickers` — every
stock and ETF the shop lists — and the portfolios are judged beside them.

Two things changed on the same instruction, and one of them came back a
different shape:

* **the peso-volume floor now applies to Philippine stocks only** (`recent.
  FLOOR_MARKETS`). Asked for by name, 2026-11-07: "there should still be a
  volume floor for philippines stocks. PHP1M". PAL is the case it decides:
  bullish at +0.77 with a 14-bar run since 2026-10-19 on ₱311,040, so the sweep
  judges it and the table hides it — and the note counts what it hid ("4 below
  ₱1,000,000 volume hidden"), because a name that is bullish on its own chart
  and absent with no explanation is worse than either answer. The Ondo rows are
  not floored -- the shelf is their limit -- and neither are the coins.
* **the turnover ranking stopped being a universe.** With no readable shelf
  there is no universe at all, so the leg falls back to the ranking
  (`recent.US_FALLBACK_LIMIT`) and the note says "US (turnover universe)"
  rather than implying the shelf. An outage must not empty the table.

**A class share takes Yahoo's spelling.** The shelf names it with a dot
(`brk.bon`, so `BRK.B`); Yahoo — and so the chart route — names it with a dash
(`BRK-B`), and `BRK.B` answers `/api/chart` with a 404. `markets.yahoo_symbol()`
is the one place that rule lives, and both the chart symbol on a row and the
ticker the bars are fetched under go through it. Without it, a name on the shelf
would be reported as "did not answer" on every sweep: a fetch failure written
into the table as a fact about a stock. The row still *displays* `BRK.B`,
because that is the shelf's own spelling.

**Two slugs are not scanned, and it is a measured decision.** OUSG and USDY are
listed bare (no `on` suffix) and are T-bill tokens, not stocks, ETFs or
portfolios. A Treasury token accrues and never marks to a loss, so its window is
always bullish — the money-market property, not a finding — and the reader's
instruction named stocks, ETFs and portfolios.

**A name whose source stopped printing is on neither table (2026-11-07).** The
reader's complaint was `ATKR`: priced **$94.96** in "Leaning bullish — not
confirmed" with a newest bar of **2026-10-16**, three weeks dead, because the
company had been taken over. It was a row for a reason worth stating — the series
*answered*, 51 bars of a frozen price, so it was not `missing`, and the
classifier read it as neutral +0.46 with a steady bullish lean.

So the leg tests the bars **before** it judges them. `recent.stale_gap` answers
how far the newest bar falls behind the clock, and a gap over `STALE_GAP_DAYS`
(5) leaves the name out of **both** tables and into `stats["US"]["stale"]`, which
the note prints: *"1 stale series hidden: ATKR (last bar 2026-10-16)"* — the same
"count what you hide" rule the peso floor follows. A copy hydrated from disk is
re-filtered against **its own** `fetchedAt`, so a restart cannot put the row back
for the seconds before the first sweep lands.

Measured the same day: 473 of the shelf's **474** names answered with a bar
**0.3 days** old and ATKR with one **21.3 days** old, so there was no threshold
to tune — five days is a weekend plus a market holiday, and everything else was
three weeks away. Not applied to the Philippine legs, the funds or the bonds:
their exchanges close for long holidays, so a calendar gap is the calendar.

### What each row says

Eight columns, and each one earns its place:

| Column | What it is |
|---|---|
| **Market** | which of the six markets the row belongs to — the table spans them, so it says so |
| **Asset** | ticker and name; a click opens that instrument's chart, unless it has none |
| **Direction** | the badge's own label — bullish, bearish or neutral — with the bond rows spelling out the yield's direction |
| **Since** | the day the current run began, in the row's own market's timezone |
| **Run** | how many bars the run has lasted — bars, not days, because that is the unit the label speaks in |
| **Price** | the latest close, a percentage for a yield and a currency amount for everything else |
| **3-month** | the window's move, first close to newest — the same pair the chart prints under the price ("+12.95% three-month move, since Jul 31"), so the row and the chart cannot disagree about how the window went. **A yield gets none**, by name ("for bonds, the most important thing is yield. changes don't mean shit. + the bearish or bullish judgment"): its yield is the price column and its bond-price call is the direction column, so the cell is a dash with the reason on hover rather than a points change between them |
| **Trading volume (in PHP)** | the latest bar's value traded in pesos — native for a Philippine stock, converted for a US stock or a coin at the same `markets.php_per_usd` rate the "most traded" tables annotate with, and empty for a yield, which trades no shares, and a futures contract, whose volume counts contracts rather than money. The exact figure (and, for a converted row, the native one) is on the cell's hover |

The **3-month** figure is `onset`'s, not a second calculation: `onset.onset`
returns the scored window's first close beside the newest one it has always
returned as `price`, and each leg turns that pair into its own unit. That is
why a US stock's row and its chart print the same percentage — both read one
window, decided by `onset.window_now` and nothing else.

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
— but nothing on the page could reach them: the table's US leg was a *turnover
ranking* at the time (`markets.us_universe`), and the TradingView scanner's
`common` / `etf` typespecs cannot even name a futures contract. So the whole
curve sat outside every sweep, whatever its chart said. (The US leg is the Ondo
shelf since 2026-11-07, which does not carry a futures contract either — the
reason this leg exists is unchanged.)

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
  `turnover: None` — printed as a dash like a yield's and a fund's, and
  explained on the cell's hover.
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
  `null` — the table prints a dash in the volume column.

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
