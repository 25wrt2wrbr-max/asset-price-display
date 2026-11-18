# Philippine stocks

[Back to the README](../README.md)

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
`globe`, `jollibee` and `metrobank`. One request returns all 262 securities and
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
  results and to the sweep's universe alongside the stocks it tracks.

A PSE symbol keeps its identity when added to the watchlist: the Add button
takes its symbol and name from the chart payload, so `PSE:TEL` in the rail is
exactly what the chart drew. Each chart costs one browser round trip (~3 s), so
the watchlist's parallel quote refresh is slower for a rail full of PSE rows
than for a rail of Yahoo ones.

## Bullish Philippine stocks

> **This table has no section of its own on the page any more.** Since
> 2026-11-07 the PSE names it found are the Philippine rows of [Recently
> bullish assets](recently-bullish.md#recently-bullish-assets), judged by the same sweep. What
> follows documents the sweep, which `bullish.py` still runs every fifteen
> minutes and `recent.py` still reads.

Every PSE stock whose trend call is
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
`Value.Traded`, which [the section above](most-traded.md#most-traded-means-turnover-not-share-count)
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
three *calendar* months, and since 2026-11-07 Binance's does too, so a coin's
row and its chart hold the same bars. The United States and crypto rows therefore
ask `onset` for the calendar-months shape — see
[One definition of "bullish", one definition of "since when"](recently-bullish.md#one-definition-of-bullish-one-definition-of-since-when).)

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
each of 263 PSE symbols over the socket, and a cold run takes about **35
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
  which reads all 263 symbols and 270 bars each in about 35 seconds.

A symbol that does not answer is left out of the table and counted in `missing`
— treating a fetch failure as "not bullish" would put an outage in the table as
a fact about the stock. Two hundred and seventy bars are fetched per symbol
because the walk needs to redraw a 90-day window at each bar it tests: 90 days is
~63 trading bars, so 270 is four windows of history behind the latest bar.

### The PSEi is scanned with the stocks (2026-11-09)

The index used to be dropped from the sweep's universe, which meant its own
chart could never put it on either table however it trended. The reader asked
for it by name — *"i think you should still include PSEi in the appropriate
sections if it is currently bullish or leaning bullish"* — so it now goes
through the same walk as the stocks, and lands on whichever table its own chart
belongs to. That is the only way the row and the chart it opens can agree
(invariant 1).

An index is not a security, and three facts follow:

- **No board lot and no minimum investment.** It is not bought in lots of five,
  so `bullish.py` leaves both fields empty and `pse.chart` withholds the
  "Min. investment" readout rather than inventing a cheque.
- **No traded value.** The socket's index bars carry five fields, not six (no
  volume), so the row's turnover is `None` — never zero — and the peso floor
  does not hide it. The volume column shows a dash with the reason on hover.
- **It is chartable.** `PSE:PSEI` resolves over the same socket and opens the
  page's own chart, which is the point of including it at all.

### The notes say how much was scanned (2026-11-09)

*"The user has no way of knowing if you really scanned many philippines stocks
and not just 10"* — so both tables now print the makeup of the scan. The
sweep's payload carries `kinds` (`{EQUITY: 249, PREFERRED: 11, ETF: 1,
CLOSEDEND: 1, INDEX: 1}` on the day it was built), and
`recent.ph_scan_line` turns it into one sentence:

```
Philippines: 263 scanned (249 common shares, 11 preferred shares, 1 ETF,
1 closed-end fund, 1 index)
```

`recent.summarize` prints it in the note under **Recently bullish assets**, and
the same string travels as `payload.phScan` so the page can print it under
**Leaning bullish — not confirmed** too. One string for both notes, so the two
cannot describe the same sweep differently. A table read from an older disk copy
has no `kinds`; the note then says "262 scanned" and leaves the makeup out
rather than guessing it.
