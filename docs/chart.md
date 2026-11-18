# The chart on screen

[Back to the README](../README.md)

### It re-reads itself — every minute while the price is moving

While the newest bar is a price still moving — `lastBarBasis` `live`, `pre`
or `after` (a US stock in or around its session, a coin at any hour, and a
PSE listing while the exchange is open: TradingView hands today's candle from
the opening bell, so the newest point *is* the last trade) — the chart and its
trend badge re-read every minute (`CHART_LIVE_TTL`, the server's own 60 s chart
cache), so the verdict follows the market in real time. Once the newest bar is
a settled close, the slow clock (`CHART_TTL = 900 * 1000`) is enough. Visible
tabs only; a tab brought back to the front re-reads at once. Binance coins now
keep the day still trading as their newest bar (`liveLastBar`), so a coin's
badge includes today's price.

Nothing in that loop invents a price: between one session's close and the next
one's first print the source has no newer number to give, so the newest point
stays the close it became, and the page says so (`close`). The one place a
figure could look stale while the market moves is a chart whose source has no
clock — which is why the PSE now ships one.

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
"bullish"](recently-bullish.md#one-definition-of-bullish-one-definition-of-since-when) survives: the
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
bond yield, a Binance bar kept only once its close time had passed — ship no
window and read as `close`; a fund prints `NAV`, because no trade happened at
that number. A **PSE row is the exception**: TradingView's daily payload carries
today's candle from the opening bell, so the chart ships the exchange's own
9:30-15:15 session (`pse.session_window`) and the bar reads `live` while it can
move — `close` from the bell, on a holiday, or from a disk copy. The same word rides the meta line ("last bar is the
after-hours price"), the table view's caption and the newest row's hover, so the
keyboard- and screen-reader-clean twin says what the plot says.

### A series the source stopped printing is drawn, but not judged (2026-11-07)

Reported by the reader: "ATKR last price was October. wtf. don't show me this."
Atkore had been taken over, the source had stopped printing, and the chart still
answered — 51 bars ending 2026-10-16, hero `$94.96`, `lastBarBasis: "close"` —
with a **Neutral · leaning bullish +0.46** badge on it. A verdict read off a
price that stopped moving is a verdict about the month it stopped in.

So a **Yahoo daily** series whose newest bar is more than `recent.STALE_GAP_DAYS`
(**5** — hours on an evening, two or three days across a weekend, never more than
four across a US holiday weekend) ships two extra fields and withholds two:

| Field | When | What it is |
|---|---|---|
| `staleDays` | the newest drawn bar is 5+ days old | how many days old it is |
| `staleBar` | the same | that bar's date, `YYYY-MM-DD` |
| `trend` | **null** when stale | the badge, the rail pill |
| `profitProbability` | **null** when stale | the three-month odds |

The line is still drawn — that history exists — and the page says why the badge
is gone. Measured on ATKR: meta line "newest bar is 21 days old (2026-10-16)", no
badge, no odds, and under the price "The source has not printed since 2026-10-16
— the newest bar is 21 days old. No three-month verdict and no profit odds are
shown: a label read off a price that stopped moving is a label about that month,
not about now."

Three exemptions, each for a reason: **weekly** bars (a weekly bar is stamped at
the start of its week, so its age is not a session's), **every other source**
(the PSE shuts from 23 December to 4 January, so a calendar gap there is the
exchange's calendar), and a **series with no bars at all** (that is `missing`,
counted as an outage, and an absent series is not a negative verdict). The same
rule keeps the name off the [recent tables](recently-bullish.md#recently-bullish-assets).

### The delta under the price is the window's move (2026-10-31)

The line under the hero price used to be the last session's move against the
previous close — a one-day figure sitting under a three-month chart. It is now
the **window's** move: the first bar the plot draws to the latest close, labelled
with the bar it starts from, because a bare "+12.95%" beside a price otherwise
reads as today.

> ▲ +$40.00 (+12.95%) three-month move, since Jul 31

The full span is on the line's hover ("Three-month change, Jul 31 to the latest
close"). Those are the same two bars the watchlist rail's percentage and the
[recent table](recently-bullish.md#recently-bullish-assets)'s rows already measure, so the headline
figure and the row for the same instrument cannot disagree about the three
months: charting AAPL shows +12.95% since Jul 31, and its rail row shows
▲ +12.95% with the same tooltip.

**A yield is different in wording, not in arithmetic.** A bond chart plots the
rate, so its delta prints percentage points (`+0.583 pt, +8.80%`) and reads
"yield move" rather than "three-month move" — a percentage of a percentage
would be a figure about nothing. The badge below still reads the series as a
bond price, so a rising yield is Bearish, and the trend note says why.
