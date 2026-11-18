# The most-traded tables

[Back to the README](../README.md)

## The two most-traded tables

**Not drawn on the page any more (removed 2026-11-07).** The reader asked for
the section to go, so `index.html` no longer has the "Most traded today" card,
its loader or its timer. `markets.py` still builds both rankings and
`/api/top` still serves them, and the section below is kept as the record of
how they are computed — nothing on the page asks for them now.

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
| Philippines | `POST scanner.tradingview.com/philippines/scan` | none — the 262-row universe is securities already (the PSEi is added by hand) |
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

## Most traded crypto — 24 hours

> **This table has no section of its own on the page any more.** Since
> 2026-11-07 the coins it found are the crypto rows of [Recently bullish
> assets](recently-bullish.md#recently-bullish-assets). `/api/cryptobull` and `cryptobull.py`
> still exist and still answer — nothing was removed server-side — but the
> page no longer asks for them. What follows documents the ranking they build,
> which `recent.crypto_rows` now reads directly.

The heaviest coins of the rolling last 24 hours, kept only where the trend is
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
