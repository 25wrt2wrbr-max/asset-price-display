# asset-price-display — agent notes

A local web page that charts an asset's last three months and labels the trend
(bullish / bearish / neutral). Python 3 stdlib server, vanilla-JS frontend, no
install step, no build step. The only dependency is the **Moli** browser, because
Yahoo answers plain HTTP clients with a 429.

## The Treasury curve is a price, and now it is reachable (2026-10-31)

The United States Treasury futures were chartable from the start — `ZB=F`
answers `/api/chart` with five years of bars — but nothing on the page could
*reach* them, which is the gap the reader hit:

- **No scan judged them.** The recent table's US leg is a turnover ranking
  (`markets.us_universe`: TradingView `common`/`etf`), and a futures contract
  has no place in it — the scanner cannot even name one.
- **Search could not find them by name.** Measured on the live route:
  "zb" ✓, "t-bond" ✓, "t-note" ✓, but "30-year treasury bond" answered with six
  Korean ETFs and "long bond" with three KB Asset Management funds. The
  contract's own Yahoo name is "U.S. Treasury Bond Futures,Dec-", which
  contains neither "30" nor "year", so no query built from the words a person
  uses can outrank an ETF whose marketing name *is* the query.
- **A bare ticker did not chart.** `zb` + Enter answered "No usable price data";
  the future is `ZB=F`.

`rates.py` is the curve as a **fixed list** (the shape `tv.BONDS` has for the
Philippine yields), not a ranking: ZT, Z3N, ZF, ZN, TN, ZB, UB. Four rules:

1. **Nothing is inverted.** A Treasury future *is* a price, so the classifier's
   own label is displayed. `tv.BONDS` inverts because it reads a yield; there is
   no yield here. All seven contracts' leg verdicts equal their chart badges
   (checked 2026-10-31, `months=` the same as the US leg).
2. **No turnover.** Close × contracts is not money, so `turnover: None` →
   exempt from the peso floor, dash in the volume column, reason on hover. The
   price carries `rates.price_hint` (2–8 decimals from the bars themselves,
   since a Treasury fraction is a 32nd/64th/128th).
3. **Search rows are Yahoo-shaped and de-duplicated**, and only a query that
   *names* a contract leads with it (`rates.named_contracts`): ticker, tenor
   (`10 year`, `30Y`), or desk name (`the long bond`, `t-bond`). The bare word
   "treasury" is the asset class — it fills in the curve behind Yahoo's answer
   and never reorders it. An exact ticker hit elsewhere still wins (`bond` →
   the `BOND` ETF).
4. **A bare ticker charts the contract only after Yahoo refuses it**
   (`rates.chart_alias`, called in `chart_data`'s `produce`). `UB` is Corgi's
   FTSE U.S. Treasury Bond ETF — it resolves, so it keeps its own chart.

The leg is a second call to the injected `fetch_us_bars` (7 symbols, one browser
run), not merged into the US leg's call: one market's outage must not take the
other. The row warmer needs nothing new — a contract is a Yahoo symbol, so it
goes down the existing Yahoo leg. Tested in `test_rates.py`.

## Classifier version 2 (2026-10-31) — read this first

`trend.classify` was rewritten to fix four measured flaws; the older notes
below that mention the 63-bar window, `sqrt(n/50)` damping or a bare ±0.25
threshold describe version 1.

- **Evidence**: a label needs score ≥ 0.25 **and** drift t ≥ 1.96
  (`ENTER_SCORE`, `ENTER_T`). Driftless random walks: ~8% labelled (v1 49%).
- **Hold band**: score ≥ 0.15 and t ≥ 1.0 (`HOLD_SCORE`, `HOLD_T`) keeps a
  label that entered within `HOLD_BARS` = 10 bars through an unbroken run.
  The payload says `held: true`. Read from the drawn series' own prefixes,
  so the label is still a pure function of the bars on screen (invariant 1).
- **Ramp weights**: the oldest `FADE_IN` = 25% of the window phases in, so
  the bar leaving the window barely matters (label change 0.6%, v1 3.4%).
- **Whole window**: every drawn bar is scored (`RETURN_WINDOW` is gone; a
  coin's 93 bars all count). Short windows face the Student-t critical value
  for their size; positive lag-1 autocorrelation widens the standard error.
  Under 4 bars reads neutral. `MIN_BARS` now only names the chart fallback.
- **Real time**: Binance keeps the forming day as its newest bar
  (`liveLastBar` → `lastBarBasis: "live"`, never from a disk copy); the page
  re-reads the chart every 60 s while `lastBarBasis` is live/pre/after
  (`CHART_LIVE_TTL`), 15 min otherwise, and at once when the tab returns.
- New payload fields: `significance` (drift t; ±99 for a series every bar
  of which moved one way), `held`, confidence `holding`.
- **`trend_v1.py` is frozen** and used only by the research modules
  (`forecast_validation`, `market_forecasts`, `pse_backtest`,
  `pse_bull_fund_bear_research`, `research_judgment`), whose fitted bins are
  on its score scale. Never use it for a label.
- Sweep cache keys gained `:t2`, so a version-1 table on disk is never
  served as a current verdict.
- Measured v1 → v2 on `research/market-history.json`: label changes per 100
  bars 8.1 → 0.8; a one-sigma nudge to the newest close flips 9.3% → 0.4%.
  The cost is strictness: ~5% of real windows carry a label.
- `export/trend.js` mirrors it; `python3 export/verify_parity.py` → 406
  cases, 0 mismatches. Suite: 188 tests OK.

## Leaning bullish (2026-10-31)

A second table under "Recently bullish assets": **"Leaning bullish — not
confirmed"**. A row is an asset whose own chart reads **Neutral** but whose
window sits in the bullish **hold band** (score ≥ 0.15, t ≥ 1.0) without
meeting the entry bar. It is not a second classifier: `trend.classify` now
also returns `lean` (the hold-band side of a neutral window, else None) and
`progress` (min(score/0.25, t/1.96) on the score's side; ≥ 1 once entered),
and `onset.leaning` asks it on the badge's own window. The badge reads
"Neutral · leaning bullish" for such a chart.

- `recent.scan` returns `leaning` beside `rows`, sorted by `progress`, after
  the same peso floor. Lean rows have no `since`/`run` (no label was given).
- PSE leaning names come from the sweep (`bullish.scan` → `leaning`), passed
  in as `ph_sweep_leaning`; bonds lean on a falling yield (sign reversed,
  `tv.bond_price_call` flips `lean` too).
- Measured on `research/market-history.json`, 63-bar windows: 4.7% bullish,
  15.2% leaning, and 24.4% of leaning windows became bullish within ~20 bars.
- A longer window (6 mo / 1 y) was measured and **declined** by the user: it
  gives fewer labels (bullish 4.7% → 4.1% → 3.8%), not more — the t ≥ 1.96
  gate is the binding one (score-only passes 25–32% of windows; both 2.6–2.8%).
- `export/trend.js` mirrors `lean`/`progress`; parity checks both.
  `test_leaning.py` covers it. Suite: 195 tests OK.

## Classifier update (2026-10-30)

The old 62/63-bar formula cliff described in historical notes below was removed.
`trend.classify` now uses the four full-window price signals at all lengths;
volume does not vote and fewer than 50 bars are damped. Short-window and PSE
forecast performance are unvalidated. A bullish label is not a promise about
the next three months. The sweep cache keys are versioned so old classifier
rows are not served as current; chart fallback points are re-scored on read.
The Python and exported JavaScript implementations must stay in parity.

PSE charts fetch longer history privately for `pse_outlook.context`, a separate
completed-bar 6-/12-month comparison, not a second classifier. The three-month
chart and all table labels still use the shared window classifier. A PSE
historical outcome study and its raw data live in `pse_backtest.py` and
`research/`; its holdout showed no reliable three-month predictor. Do not
present the reported frequencies as individual-stock probabilities.

```sh
python3 server.py        # from the project directory; http://127.0.0.1:8000/
```

`README.md` is the full reference. This file is the working notes: invariants that
must not drift, and what was just built.

## Start the server only to check something, and stop it afterwards

The server is a tool for verification, not a service to leave running. **Every
time you start `python3 server.py` — to curl a route, read a rendered table
through Moli, take a screenshot — stop it again before you report back.** The
user opens the page in their own browser when they want it and does not want a
stray process holding port 8000 (and a background sweeper hitting upstream).

```sh
pkill -f "server.py"          # the process runs as ".../Python server.py"
sleep 2
curl -s -m 2 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/ \
  || echo "port closed"       # 000 / "port closed" means it is really down
```

Pattern the kill on `server.py`, not `python3 server.py`: the argv is
`/Library/.../Python server.py`, so the `python3` spelling matches nothing and
the server survives. Confirm with the port, not with `pgrep` alone — a process
can be mid-shutdown and still answering.

The only exception is a case the user asks for by name ("start it and leave it
up"); then say plainly that it is still running and on which port.

## Classifier + walk fixes (2026-10-31, second pass)

Three measured defects fixed, none of which change a single badge label on
live data — they change what the walk *admits* about its dates, and what a
degenerate series reports:

1. **`censored` was unreachable; invariant 4 could never fire.**
   `window_at(0)` is always a 1-bar window → always neutral → the walk could
   never include bar 0, so `censored = (start == 0)` was dead code. A
   money-market fund whose every window is bullish walked into the short
   prefix (windows under ~11 bars cannot carry the momentum signal, and the
   damping floors the rest below 0.25), stopped at bar 9, and reported an
   exact-looking date 13 days after its history began: ALFM-MM, BPI-MM and
   BPI-ST all said `censored: false, since 2025-10-09`. Now `onset` flags
   `censored = start <= trend.MIN_RETURNS` — a stop inside the data floor is
   the walk running out of judgable history, so the date reads as "at least".
   Verified on the cached fund bars: the three MM funds now censor correctly,
   and genuine mid-history runs (ALFM-PESO 63 bars, BPI-USEQ-P 9, BPI-HLTH 1)
   are untouched. `test_a_censored_run_has_no_manner` was vacuous (`if
   call["censored"]:` was always False); it now asserts the censoring.
2. **Float noise defeated the flat-series guard in `_vtsmom`.** A perfectly
   uniform series has log-return variance ~1e-16, not 0, so `sigma <= 0`
   passed and z exploded into the ±1 clamp — a steady payer read
   `momentum: 1.0` off rounding noise. The check is now `sigma <= 1e-9`
   (far below the quietest real asset's ~1e-4 daily log-return σ, far above
   the noise). The uniform payer now reads `momentum: None` and scores an
   honest 0.61 instead of 0.76 — still bullish, carried by efficiency/range.
3. **`_rng` broke the unknown-vs-zero convention.** A dead-flat window has no
   [low, high] to sit in; it returned 0.0 ("measured mid-range") while the
   other three components correctly said None. It now returns None; a flat
   series reports all four components as None and still reads neutral 0.0.

Also documented, not changed: the weekly-badge policy. `slim_chart`'s
docstring now carries the measurement behind the rule "the badge reads the
bars the chart draws": SPY `3mo` daily scores 63 daily bars through the
backtested ensemble (−0.1985) while `3mo` weekly scores 15 weekly bars
through the short-window damping ×0.55 (−0.0091). Same words, different
machinery — the backtest validated 63 *daily* bars only. The page requests
`1d` exclusively; anyone hitting the API with `1wk` should know what the
badge is.

`export/trend.js` mirrors all three code changes; parity passes (403 cases,
0 mismatches); full suite 178 tests OK.

## Files

| File | Role |
|---|---|
| `server.py` | Static server + Yahoo proxy + background sweeps. Routes: `/api/chart`, `/api/search`, `/api/top`, `/api/bullish`, `/api/cryptobull`, `/api/recent`, `/api/health`, `POST /api/watch`. |
| `trend.py` | The classifier: `classify(closes, volumes)`. Version 2: enter score ≥ 0.25 and t ≥ 1.96, hold ≥ 0.15 / t ≥ 1.0 for 10 bars, whole window, ramp-weighted. `trend_v1.py` is the frozen research copy. |
| `onset.py` | The shared "since when" walk — one window, one label, one answer to *when did this turn?* — and `turn`, which says *why* it turned (`turn` / `flat` / `against`). The window's **shape** is per source: `months=` for Yahoo, days for the rest. |
| `recent.py` | The combined "recently bullish assets" table: US stocks, Philippine stocks, crypto, US Treasury futures, Philippine bond yields, Philippine funds, each dated. |
| `rates.py` | The US Treasury futures curve (ZT…UB): the contracts, the search rows and synonyms that make each findable, the bare-ticker chart alias, and the quote precision. |
| `phfunds.py` | The 47 Philippine funds — daily NAVPU from TOAP's UITF register, PIFA's NAV history and BPI Wealth's own pages — and the chart a fund row opens. |
| `tv.py` | The Philippine government bond yields — the TradingView symbols, their names, their daily bars, and the chart a bond row opens. |
| `bullish.py` | The Philippine sweep: every PSE name that is bullish now, dated to the bar its run began on. |
| `pse.py` | PSE universe (TradingView scanner) and bars (browser-backed TradingView chart socket); `history_many` is the socket `tv.py` borrows. |
| `markets.py` | The two most-traded tables and the PSE board-lot table; `us_universe()` feeds the recent table. |
| `crypto.py` / `cryptobull.py` | Coin identity (CoinGecko), bars (Binance), and the 24-hour most-traded crypto table. |
| `ecb.py` | ECB reference rates via Frankfurter, for currency crosses Yahoo fabricates. |
| `diskcache.py` | Durable on-disk copy of every upstream answer under `.cache/`. |
| `index.html` | The whole frontend — markup, CSS, charts, tables. |

## Invariants

1. **One definition of "bullish"** — `trend.classify` on the window the chart draws
   (90 days / ~63 daily bars). No second classifier exists, and none may be
   introduced. A row and the chart its click opens are the same series and verdict.
   **The window is per source** — see "The window is the chart's window" below.
   **The newest bar is the extended-hours price** where the source has one, applied
   in `yahoo_bars` so the badge and the row both score it — see "The chart
   refreshes itself" below.
2. **One definition of "since when"** — `onset.py`. `bullish.py` and `recent.py`
   both ask it there. Two copies of the walk are two answers that disagree at the
   edges, which is why the walk was extracted in the first place. `onset.turn` is
   the one place that answers *why* a run began, and it never changes the label or
   the date.
3. **A missing fetch is not a negative verdict.** Unanswered tickers are counted
   as missing and left out; an outage must never appear as a fact about a stock.
4. **A run reaching past the fetched history is `censored`** ("bullish for at
   least this long"), never dated to the oldest bar fetched.
5. **A run is measured in bars, not days.**
6. **Report saved state in plain terms** — which files changed on disk, what the
   user must do next. Never mention git, commits, or branches.

## The window is the chart's window (fixed 2026-10-30)

The classifier is one, but the **window** is not the same for every source, and
the difference is not cosmetic — `trend.classify` changes regime at 63 bars, so
two windows a session apart can be two different answers.

| Source | The window its chart draws | How the walk asks for it |
|---|---|---|
| Yahoo (the US stocks) | **three calendar months** back from today — `range=3mo` is three months, not ninety days | `onset.onset(..., months=3)` |
| PSE, Binance, the bond yields | ninety days | `onset.onset(...)` (the default) |

`onset.months_back()` is Yahoo's own rule (verified 2026-10-30: `range=3mo`
answered from 2026-07-30, `range=6mo` from 2026-04-30, `range=1y` from
2025-10-30, `range=2y` from 2024-10-30, `range=5y` from 2021-11-01 — the cutoff
is 2021-10-30 and no bar falls on it, so `5y` drops nothing). `server.SPAN_MONTHS`
maps every span to months, and `slim_chart` trims the Yahoo payload to the same
window, so the chart and the table read the same bars by construction.

**The trim is daily-only, and it does not re-derive the rule.** `slim_chart`
asks `onset.window_now(stamps, last, months=months)` — the same function the
walk asks — so a third copy of the cutoff rule cannot appear here. It trims
only when `interval == "1d"`: the cutoff is a day boundary, and a **weekly** bar
spans seven days with its stamp on the week's first day (SPY `1wk` first bar
2026-07-27), so comparing that stamp against a day boundary amputated a bar
that lies partly inside the window and moved the verdict (SPY `1wk` +0.1262 →
+0.0021). Weekly charts keep Yahoo's own payload, and their badge is read from
the bars they draw.

**FX straddles the session, and it does not matter.** Yahoo's FX `3mo` payload
starts one bar early (07-29 23:00 UTC, a session stamped on the prior day), and
the trim drops it — for all eight crosses tested, the label and score were
unchanged (EURUSD=X bearish −0.3728, GBPUSD=X, USDJPY=X, EURJPY=X, AUDUSD=X,
USDPHP=X bullish +0.5139, EURPHP=X, USDCHF=X). Equities and crypto drop 0 bars.
The trim is a safety net, not the mechanism: Yahoo's own payload already matches
the window today, and trimming makes the agreement structural rather than a
coincidence of how many bars a span happened to return.

**What it fixed:** SPY sat in "Recently bullish assets" (bullish, +0.27) while
its own chart said **Neutral** (+0.20). The table judged ninety days — 62 bars,
the short-window regime — and the chart judged Yahoo's window — 64 bars, the
backtested ensemble. Same series, same classifier, different weight tables.
SPY is now correctly neutral and is no longer a row.

**The rule:** a row's verdict must be computable from the chart's window. When
a new source is added, ask what window *its* chart draws and pass that shape
(`months=` or the default days). Checked after the fix: all 50 US tickers, all
29 PSE sweep rows and every crypto row match their chart badge exactly.

**The watchlist row's percentage is the window's move (changed 2026-10-31).**
`quoteSummary` measures first drawn close → latest close, the same bars the row's
chart draws, instead of the day's move against the previous close. Its tooltip
names the first bar it starts from, because a bare "-9.34%" beside a price reads
as today until told otherwise.

**The chart's hero delta measures the same pair (changed 2026-10-31, by name).**
The line under the price used to be the day's move against the previous close —
a one-day figure under a three-month chart. It is now first drawn bar → latest
close, labelled with that starting date ("+12.95% three-month move, since Jul
31") and with the full span on hover, so the headline figure, the rail row and
the recent table all speak about the same bars. Rendering it is
`renderAll()`'s `heroDelta` block; the pair comes from the same `d.points`.
A yield prints points (`+0.583 pt`) and says "yield move", because a percentage
of a percentage is a figure about nothing; the badge still reads it as a bond
price, so a rising yield stays Bearish.

## The chart refreshes itself (2026-10-31)

Two changes, both asked for by name. Before them the chart was a still photo —
it was last read when the asset was clicked, and its newest bar was the 16:00
close, so a tab left open over a session showed a frozen price.

### Fifteen minutes, quietly

`index.html` registers `CHART_TTL = 900 * 1000` — the recent table's own clock —
and re-asks for the chart that is on screen. Visible tab only.

The refresh is **quiet**: it does not dim the plot, does not write "Loading…",
does not disable the button, and a *failed* background refresh changes nothing on
screen — it never overwrites a status line the reader is reading. The one status
a quiet refresh may write is the disk-fallback one ("data last retrieved …"),
because that is the fact the reader must not miss.

`loadChart(symbol, {quiet})` carries a sequence number (`state.chartSeq`). A slow
answer that a newer request has already replaced is dropped instead of drawn, and
only the newest non-quiet request owns the busy state. `state.chartSymbol` is set
on success only, so a failed search cannot make the timer re-ask for the symbol
that failed.

Nothing else changed cadence: the server caches charts 60 s (`CACHE_TTL`), so a
tick of this timer always reaches the source; the tables keep their own 300 s /
900 s clocks.

### The newest bar carries after-hours trading

Yahoo's daily bars are regular-session closes. The **newest** bar is now drawn at
`meta.fulldayPrice` — that session with pre- and after-hours folded in — while
every older bar keeps its official close. Verified 2026-10-31: AAPL's 10-30 bar
read 344.63 at the 16:00 bell and 344.807 after hours, and `fulldayPrice` tracked
the after-hours print (equal to the last bar of `interval=1m&includePrePost=true`)
on AAPL, MSFT, BRK-B and SPY.

`server.full_day_close` decides and refuses in three cases, leaving the plain
close: no extended session (`hasPrePostMarketData` false — crypto, FX, futures,
mutual funds, every PSE name), no usable `fulldayPrice`, or an extended print
that belongs to a **newer session than the last bar** (the Monday pre-market
case, where the daily series still ends at Friday while `fulldayPrice` is already
Monday's 08:00 print). That last guard compares `currentTradingPeriod.regular.start`
with the bar's stamp as calendar dates in `exchangeTimezoneName`; an unknown zone
or an out-of-range stamp also refuses.

The patch is applied in `yahoo_bars` — the one function `slim_chart` and
`fetch_us_bars` both read bars through — so invariant 1 still holds: the badge
scores the extended price exactly as the plot draws it, and a recent-table US row
and its chart are still one series, not two. `slim_chart` ships
`extendedLastBar`, so the hero figure is never mistaken for an official close.

**Naming that figure (2026-10-31).** A hovered point now says whether it is a
`close`, a `live` price, a `pre-market` or an `after-hours` print — see "A point
says what it is" below. The meta line follows the same verdict instead of
printing "last bar includes after-hours" whenever the fold merely *ran*: on a
Friday night the fold returns Friday's close, and a line claiming after-hours
there would name a price the chart is not showing.

**What to expect:** two snapshots of a moving extended session can differ by
cents — a row swept at 10:05 and a chart drawn at 10:07. Checked 2026-10-31 over
all 29 US rows of the recent table: every direction matched, 26 prices matched
exactly, three differed by a few cents (widest: TSLA, 8.5¢). A verdict flip from
that is possible in principle and has not been observed.

### A finished session Yahoo left without a close (fixed 2026-10-31)

Yahoo sometimes answers a **completed** session's daily bar with open, high, low
and volume present and `close` **null**, while `meta.regularMarketPrice` already
holds that session's close. Seen on 2026-10-31 (Saturday, after the Friday
2026-10-30 close) on every US symbol tried — SPY, AAPL, MSFT, KO, XOM — with the
earlier sessions intact. History: KO charted **neutral +0.2183** while the same
classifier with Friday's bar reads **bullish +0.2930**, which is what the user's
other calculator showed (same four components: momentum 0.35, trend 0.04,
efficiency 0.16, range 0.74, r2 0.26).

Cause: `yahoo_bars` drops a bar with no close as a gap, which is right for a
holiday row and wrong for a session Yahoo has not published as a bar yet. The
whole US side — chart, badge, recent table, watchlist — was one session behind.

Fix: `server.session_close` fills **only the newest stamped bar** from the
payload's `regularMarketPrice`, inside `yahoo_bars`, so invariant 1 still holds.
It refuses on: no usable price/time; a price whose **calendar day in the
exchange's timezone** differs from the bar's (which keeps a Monday pre-market
print off Friday's bar, the mirror of `full_day_close`'s guard); a bar with no
volume and no high/low; and a price outside the bar's own `[low, high]`. A mutual
fund is the one exception to the "no volume, no high/low" rule — its row is a
published NAV, not a traded bar (VFIAX 10-31: all-null 10-30 row, NAV 699.87
stamped 20:08 New York) — and the day guard still applies.

Older null closes stay gaps. Checked after the fix: all 50 US tickers match their
own chart's badge and newest price, VFIAX/SWPPX gained their 10-30 NAV, and the
FX, futures, crypto, PSE, bond and fund legs are unchanged.

## A point says what it is (2026-10-31)

Hovering the plot used to label every point "close", which was wrong twice over:
the newest bar of a chart can be the price trading **right now**, and it can be
the last **extended-hours** print. Each point now says which, from
`server.last_bar_basis`, and the page only spells the answer out (`basisWord`).

| `lastBarBasis` | The number drawn there |
|---|---|
| `close` | that session's official close — every bar but the newest, and the newest one outside every session window |
| `live` | the last trade: the newest bar, its regular session open, a print within `LIVE_PRINT_MAX_AGE` (30 min) |
| `pre` | the last pre-market trade (an extended print folded in, pre window open) |
| `after` | the last after-hours trade of that session (same fold, post window open) |

- **The clock decides, not the price.** Once the extended session ends, Yahoo
  stops folding the after-hours print in and reports the regular close again
  (AAPL read 344.807 through the post session on 10-30 and 344.63 after it), so
  `extendedLastBar` being true is *not* the same claim as the bar carrying an
  after-hours figure. That is why the meta line no longer prints "last bar
  includes after-hours" on the strength of the fold alone.
- **An open window is not an open market.** `currentTradingPeriod.regular` for a
  future (`GC=F`) is a whole calendar day, so it still covers a Friday evening
  after the exchange has shut; the 30-minute print bound is what separates them.
  Checked 2026-10-31 (Friday 22:43 New York): GC=F and USDPHP=X read `close`,
  BTC-USD and ETH-USD `live`, SPY/AAPL/KO/VFIAX `close`.
- **The call is made at read time**, in `chart_data`, not at fetch time: a chart
  served from the 60 s memo or from a disk copy must not still claim to be live
  an hour later. `slim_chart` ships the window as `session` (`pre`/`regular`/
  `post` stamps, `coversLastBar`, `lastPrint`) and the decision is one function
  over it.
- **No session, no claim.** A fund's NAVPU, a bond yield, a PSE row and a
  Binance bar kept only once it had closed ship no window and read `close`; a
  fund prints **NAV**, because no trade happened at that number. PSE has no clock
  in its payload, so a PSE bar during the PSE session reads `close` — the one
  remaining imprecision, and it needs a PSE session table to fix.
- **The same word everywhere**: the tooltip, the meta line ("last bar is the
  after-hours price"), the table view's caption and the newest row's hover.

## The watchlist row says its verdict (2026-10-31)

Each row in the rail now carries a **pill** beside the symbol — Bullish, Bearish
or Neutral, colored with the same `--delta-up` / `--delta-down` tokens as the
chart's badge, score in the tooltip. It is not a second classifier: `quoteSummary`
already stores the `/api/chart` payload for the row, and the pill reads
`quote.data.trend` off it, so the row and the chart a click opens are one
`trend.classify` call on one set of bars (invariant 1).

- **No data, no pill.** A loading or failed row shows nothing rather than a
  defaulted "Neutral" — invariant 3, a missing fetch is not a verdict.
- **The pill and the percentage are allowed to disagree.** SPY's row can read
  Neutral (score −0.19) while the window's move is +1.22%: the pill is the
  classifier's verdict, the number is the window's move. Both used to be the
  same fact only by accident; do not "fix" one to match the other.
- **The symbol gives way, not the pill.** `.watch-id` groups symbol + pill and
  the price keeps `flex: none`; measured at the rail's real content width with
  `BRK-B $543.70` and `SHIB-USD $0.00001`, nothing overflows.
- **The hint explains the pill once one exists** — "Each tag is that row's
  three-month verdict" — and says nothing when the list is still empty.

### The rail is 396 px (2026-10-31)

The rail was 318 px and the fund rows in the recent table read `FUND:B…` /
`ALFM Money Marke…` — the code and the name both ellipsized, so a row said
nothing a reader could recognise. `.layout` is now
`minmax(0, 1fr) clamp(340px, 32%, 396px)`: 396 px on a full-width page, 340 in
the 1001–1240 px band before the layout stacks, and `.wrap` went 1180 → 1240 so
the chart card pays 18 px of the 78 instead of all of it. The stack breakpoint
moved 900 → 1000 px for the same reason — at 900 the chart had already been
squeezed by the wider rail.

Checked 2026-10-31 at 396 and at 340 with `FUND:BPI-INFRA` ("BPI Philippine
Infrastructure Fund"), `FUND:ALFM-MM`, `BRK-B`, `SHIB-USD` and `PSE:PHR`: no
symbol, name, price or percentage is truncated, and no viewport from 520 to 1920
overflows sideways. A longer name than these would still ellipsize at the 340
narrow end; that is the row's shape, not a regression.

### The watchlist has no length limit (2026-10-31)

The 40-symbol cap was a number picked when the list was a convenience, and it
lived in three places: `addToWatch` refused the 41st with "Watchlist is full (40
symbols)", `loadWatch` sliced a longer stored list to 40 on read, and the
server's `_clean_watch` truncated every declaration to 40 before the warmer saw
it (with a 320 `WATCH_UNION_CAP` above it). All four are gone at the reader's
request — the list is theirs, and a cap only ever meant "you may keep exactly
this many".

- The page keeps every row it is given; the rail already scrolled (`max-height:
  60vh`), so a long list grows a scrollbar, not the layout.
- The server keeps the whole declared union on disk; `_clean_watch` still
  normalises, de-dupes and rejects non-symbols, but no longer counts.
- The one bound left is `read_json`'s body ceiling, raised 64 KB → 2 MB — a
  memory guard in front of `json.loads`, not a product limit. Ten thousand
  `{symbol, name}` pairs fit inside it.
- Cost that is real, and intentional: every row fetches its own chart when the
  page opens, so a very long list fills in over several seconds (the browser
  queues six per host; the server serialises uncached Yahoo fetches through
  Moli's profile lock). Nothing is capped to hide that.

## Recently bullish assets (built 2026-10-29)

One table across five markets — US stocks, Philippine stocks, crypto, the
Philippine government bond yields and the Philippine funds — every row dated to
the day its current run began, sorted **newest-turn first**.

- `recent.py` builds it, `server.py` sweeps it, `/api/recent` serves it,
  `index.html` draws it in `<section class="leaders recent">`.
- Columns: **Market · Asset · Direction · Since · Run · Price · Trading volume
  (in PHP)**. The volume is each row's `turnover` in pesos (`turnoverPhp`),
  converted at `markets.php_per_usd` for the USD rows; bond rows and fund rows
  have none.
- The note line is built server-side by `recent.summarize(payload)` and shipped as
  `payload["note"]`, so the note and the rows cannot disagree about what was scanned.

### Where each market's bars come from

| Market | Source | Note |
|---|---|---|
| US stocks | Yahoo daily bars **through Moli** | `server.fetch_us_bars()`, `RECENT_BATCH = 20` per browser run, `US_LIMIT = 130`, one year of bars (`RECENT_SPAN = "1y"`). Never swap Moli for `curl`/`urllib` — Yahoo answers those with a 429. |
| Philippine stocks | the existing bullish sweep's rows | Reused from the sweep `server.py` keeps warm (`bullish_state().get("rows")`). **No second sweep.** |
| Crypto | Binance daily bars | `crypto.try_chart`, `CRYPTO_LIMIT = 25`, `CRYPTO_WORKERS = 8`. Plain HTTPS works here. |
| Philippine bonds | TradingView chart socket | `TVC:PH02Y`, `TVC:PH05Y`, `TVC:PH10Y` via `tv.py` → `pse.history_many`. |
| Philippine funds | `phfunds.py`, plain HTTPS | 47 funds: TOAP `uitf.com.ph` (`bank_id=3`) for the BPI UITFs, PIFA's NAV history for ALFM/PSIF/Wealth Builder, BPI Wealth's graph model JSON for the four PERA funds. **No browser.** |

`recent.scan` receives `fetch_us_bars` as an **injected callable** (the browser
lives in `server.py`, which imports `recent.py`), which keeps the module testable
without a browser. A full sweep is ≈ 29 s; the US browser leg dominates.

### Bond yields read the other way, and say so out loud

A yield is not a price. The classifier reads the yield, but the displayed
direction and score are inverted to reflect the usual movement of an existing
fixed-rate bond's price:

- Rising yield → `Bearish (yield rising)`.
- Falling yield → `Bullish (yield falling)`.
- Neutral yield → `Neutral (yield flat)`.
- The date and run belong to the underlying yield trend; this is an inference,
  not a measured price trend or a forecast.
- Bond rows follow the same rule as every other market: **only a falling yield
  is a row** (a rising yield reads as a falling bond price, and a flat one has
  no run to date). Changed 2026-10-31 at the reader's request — the three
  tenors used to be shown whatever their verdict. The note still reports
  "Philippine bond: 3 scanned" with the number kept beside it, so a curve with
  no row reads as "nothing turned", not as "nothing was looked at". The bond
  chart route is untouched (`/api/chart?symbol=TVC:PH10Y` still draws a rising
  yield); the search box has never listed the tenors, so a table row was the
  only in-page way to reach one.
- PH yield rows **are links**, and the chart they open plots the yield from the
  same TradingView series the row was judged on (added 2026-10-31 — see "A bond
  row opens its own chart" below).

### The bond socket: browser, not a raw websocket

The TradingView chart protocol can be driven by a plain TLS socket — that was
tried first, and the code was correct (handshake, session, symbol resolution,
series request, `timescale_update` all arrived). The protocol **drops most of the
sessions it accepts**: a session is told `series_loading` and the series never
comes, roughly a coin flip per attempt, worse for `TVC:PH05Y`, and bursty.
Retrying hard enough to win took ~40 s for three symbols with one often missing.

The browser-backed socket (`pse.history_many`) is reliable: all three tenors, every
time, in **~1.1 s**, with identical values. `tv.py` was rewritten deliberately
**thin** — it owns the bond symbols and names and borrows `pse.py`'s socket
(`BATCH_SYMBOLS = 40` per socket, 4 workers, 3 attempts; `create_series` once per
`chart_create_session`).

### Bond cache, and the two different ages

`diskcache` under `tv:bond:<symbol>`:

- `BOND_CACHE_TTL = 6h` — fresh enough to **skip the fetch** (a yield is a daily
  close, so a copy a few hours old has missed at most one bar).
- `BOND_CACHE_KEEP = 7d` — still worth **showing** if the fetch failed; the row
  then carries `stale` (seconds) and reports how old the reading is.

### Time zones

Bond bars are stamped at Manila 05:00 (= 21:00 UTC of the prior day), so bond rows
carry `"tz": "Asia/Manila"` and the front end reads their dates in that zone via
`rowDate()`. Every other row stays UTC. The timezone belongs on the row — do not
shift timestamps inside the data.

### The sweep is a background job, not a route

- `RECENT_KEY = "recent:scan:v3"` on disk; `RECENT_TTL = 900` s. A v2
  fallback is converted on startup to the bond-price direction.
- `recent_loop()` runs on the refresh thread. `recent_state()` never blocks, and
  the payload is **replaced wholesale**, never mutated, so a reader cannot see it
  change mid-render.
- The row warmer (`warm_rows_loop`) reads the recent table too, through
  `due_rows(..., recent=...)`, so a row it lists stays retrievable offline like
  any other table's row. Bond rows carry a `chartSymbol` and are warmed on their
  own leg (`_warm_batch_bonds`, below).
- `seed_recent()` hydrates from disk at startup, so an offline start still has rows
  (the note then says "— source offline").
- A failed refresh leaves the previous rows on screen and reports the failure in
  the note. It never clears the table.
- The front end polls at the same 900 s (`RECENT_TTL` in `index.html`).

## Why a run began, not just when (added 2026-10-31)

`onset.onset` returns `manner` and `turnMove` beside the date, answering the
second half of the question a reader actually asks: *it's bullish now — did it
reverse, or did it just stop falling?*

The window's return is `P_end / P_start`, so the oldest bar is the denominator.
Two different things produce the same flip, and only one of them is a reversal:

- **the series turned** — the recent bars moved into the new direction;
- **the base aged out** — a crash left the window, so the return improved with
  the price standing still.

`onset.turn(closes, start, want)` reads the twenty bars **before the run's first
bar** (never today's) and signs the move in the run's own direction, so one rule
covers a price and a bond yield alike. `turn` / `flat` / `against` at ±2%
(`TURN_BARS`, `TURN_MOVE`). Measured 2026-10-31, 316 symbols, 663,174 bars,
2,496 bullish runs that followed a bearish regime: **86.9% turn (last 20 bars
+9.4% median, close at the window high), 11.8% flat (+0.8%), 1.3% against
(−3.6%)**. `range`'s 0.15 weight demanding a close near the window high is why
the artifact is uncommon — it cannot flip the label while price sits at the
bottom.

Three rules that must hold:

1. **It never changes the label, the date or the run.** It is a reading of the
   same bars, not a second classifier — invariant 1 and 2 both still apply.
2. **It is counted, never filtered.** Payloads total `turns` / `flat` /
   `against` beside `boundary` and `censored`; every row carries `manner` and
   `turnMove`. Do not drop `flat` rows from a table: the manner does not predict
   (next three months: 49.7% / 49.8% / 53.1% up), so filtering would shrink the
   table without making it truer and would break "a row is the verdict its own
   chart shows".
3. **No reading is `None`, not a guess.** Fewer than `TURN_BARS` bars behind the
   run's first bar — a censored run, or a money-market fund whose run reaches
   back to the start of its history — reports `None`. The five `None` rows in the
   recent table are exactly those funds.

What it does say: `flat` runs revert to their previous label within twenty bars
2.5× as often as `turn` runs (6.1% vs 2.4%). That is the sturdiness of the run,
not a forecast.

`export/trend.js` mirrors both fields and `export/verify_parity.py` compares
them, so the JS copy cannot drift.

## A bond row opens its own chart (2026-10-31)

Clicking `PH02Y`, `PH05Y` or `PH10Y` in the recent table used to do nothing: the
row carried `chartSymbol: null` and the `no-chart` class, because the chart route
drew what Yahoo draws and Yahoo quotes no Philippine yield. The rows are now
links, and the chart behind one is built by `tv.chart` off the same TradingView
socket the PSE rows use.

- `server.chart_data` routes a bond symbol **before** it builds a Yahoo URL
  (`tv.is_bond_symbol`), exactly as it does for `PSE:`. A bond chart's cache key
  is `tv:<SYMBOL>:<span>:<interval>` — deliberately *not* the key its raw bars
  live under (`tv:bond:<SYMBOL>`), because the bars are shared with the table row
  and the finished chart is not.
- **The chart is the row's series.** `recent.bond_rows` and `tv.chart` read the
  same disk copy (`tv.cached_bars`), trim it with the same function
  (`onset.window_now`, ninety days) and score it with the same classifier, so the
  badge and the row agree by construction. Checked 2026-10-31: all three tenors
  matched exactly (PH02Y −0.4708, PH05Y −0.6268, PH10Y −0.5559 on both the row
  and the chart).
- **The plot is the yield; the label is a bond price.** Inventing a bond-price
  series out of a yield would be a fabrication, so the line is the yield in
  percent (`currency` `"%"`, `unit` `"%"`, `priceHint` 3, axis "YIELD %"). The
  badge applies the same reversal the row does (`tv.bond_price_call`: label
  flipped, score negated), and the payload keeps the classifier's own call as
  `yieldTrend` so the page can say *"the classifier reads the yield itself as
  bullish"* above *"the badge reads it as a bond price"*. `chart_data` re-applies
  that reversal after its usual re-score, so a stale disk copy cannot resurrect a
  differently-signed verdict.
- **No research-judgment box anywhere any more** (removed 2026-10-31 at the
  reader's request — see "The research line left the chart" in the README). A
  yield used to skip it because it reads price history; the page no longer asks
  for it at all, for a yield or anything else.
- **A failed fetch is dated, not passed off as fresh.** When the socket does not
  answer and a bar copy older than `BOND_CACHE_TTL` is used, the payload carries
  the rescue stamps (`cached`, `fetchedAt`, `cacheError` — `tv._mark_stale`), so
  the page prints "Source unreachable — showing data last retrieved …" and a copy
  stored from that payload cannot later read as a fresh answer.
- **The warmer has a bond leg.** `warm_rows_loop` used to send these rows down
  the Yahoo batch leg, where each pass earned a guaranteed 404. `_warm_batch_bonds`
  now reads the three tenors from one socket run (`tv.charts_many`) and stores
  each chart under its own key, so a bond chart is retrievable offline like every
  other row's.

## A fund row opens its own chart (2026-10-31)

The fifth market on the recent table is the **Philippine fund** — 47 of them, in
`phfunds.FUNDS`: the BPI Wealth UITFs, the ALFM and Odyssey funds, the Philippine
Stock Index Fund and the four PERA funds. A fund has no ticker, no exchange and
no volume; what it has is one **NAVPU** (net asset value per unit) a business
day, and that is a daily close, so `trend.classify` reads it exactly as it reads
a price. The row and the chart are one series by construction: both call
`phfunds.series(code)` (`recent.fund_rows` for the row, `phfunds.chart` for the
graph), trim with `onset.window_now(..., days=90)` and score the same bars.

**Three registries, no single one.** `phfunds` reads each fund from whichever
publisher holds it, and all three answer plain HTTPS — **no Moli, no browser**:

| Funds | Source |
|---|---|
| 32 BPI Wealth UITFs | `uitf.com.ph/daily_navpu_details_json.php?bank_id=3&fund_id=…` |
| 8 ALFM, 2 PSIF, the Wealth Builder fund | `pifa.com.ph/facts-figures/nav-history/?fund_id=…` (dataset inline in the page) |
| 4 PERA funds | BPI Wealth's `<fund page>/jcr:content/root/container/dynamicgraph_copy.model.json` |

**Two facts about the raw data.** Both TOAP's endpoint and BPI's model **pad the
calendar**: Friday's value is repeated across Saturday and Sunday, and BPI ships
duplicate stamps and stamps a day or two in the future. `phfunds.clean` drops
weekends, de-duplicates by day (last value wins), drops anything after today, and
trims to `HISTORY_DAYS = 400` — a padded Saturday is a non-session, and a bar
that never happened must not vote in a 63-bar window or be named as the day a run
began. Do not "smooth" or forward-fill the gaps instead: that is what the
publisher already did, and it is the thing being undone.

**A money market fund is always bullish.** Its NAVPU accrues interest and never
marks to a loss, so its window is always bullish and its run is always censored
("at least this long"). Six of the 47 are money-market or short-term funds. That
is a true statement about a cash fund, not a classifier bug — do not "fix" it.

**Costs and caching.** A cold pass over all 47 is ~35 s, most of it PIFA — its
pages are ~2 MB each and it **closes the connection** if several are read at
once (`FAST_WORKERS` never includes it; PIFA is read one fund at a time with
`PIFA_PAUSE`). Each series is kept six hours (`phfunds.CACHE_TTL`) with a
week's fallback (`CACHE_KEEP`), the same two ages as the bond yields, and a
fallback row carries `stale` seconds like a bond row does. A warm pass is <5 s.

**The chart.** `server.chart_data` routes `phfunds.is_fund_symbol` **before** it
builds a Yahoo URL (key `fund:FUND:<CODE>:<span>:<interval>`, deliberately
apart from the bars' own `fund:<CODE>` key). The payload carries the fund's
currency, `priceHint` 2–4 (taken from the decimals the publisher prints — a
NAVPU printed at two when the fund quotes four rounds away the digits that
moved), `fundSeries: true`, and `exchange` "Philippine fund" / `type` "Net asset
value". The chart note says the line is a NAVPU set once a business day; the
research-judgment box that a fund used to have to suppress is gone from the page
altogether. A fund row's turnover is `null`, so it is exempt from
`MIN_TURNOVER_PHP` like a bond row, and the volume column prints a dash.

**The warmer has a fund leg** (`_warm_batch_funds`, `FUND_WARM_CHUNK = 12`),
because a fund row sent down the Yahoo leg would earn a 404 per pass. It needs
no browser, so the batch is a concurrency limit rather than a page budget.

**Recognition.** A fund **code** (`BPI-INFRA`, `ALFM-MM`, `BPI-PERA-MM`) is a
**display code, not a ticker** — no Philippine fund has one. It is defined once,
in `phfunds.FUNDS`, and it is what a row prints and a URL carries. Search
supplements it: `phfunds.search_funds` adds funds (Yahoo has never heard of
them), and a query matching a fund **code** (`alfm`, `pera`, `BPI-HLTH`) leads
with those funds unless another row is an exact ticker hit. Name queries are not
promoted — "health" still finds the health-care stocks first.

## Data-source gotchas

- **Micro-priced coins need 8 decimals.** `crypto.py` rounds Binance closes and
  `price_hint` picks display decimals; both must keep two significant figures
  for prices under $0.001 (PEPE ~$0.0000034). Six decimals collapsed PEPE's
  chart onto exactly three levels — $0.000003/4/5 — a staircase that looked
  like data. The front end's `digitsFor` clamp and the y-axis tick formatter
  (significant digits below $1) were widened the same day.
- **Yahoo** → Moli only (`server.moli_get` / `moli_batch_get` keep the true status
  code by calling the API from inside a Yahoo-origin page). `curl`/`urllib` → 429.
- **A US class share is `BRK-B`, not `BRK.B`.** The TradingView scanner spells it
  with a dot and Yahoo with a dash, and the dotted spelling answers `/api/chart`
  with a 404. `markets.yahoo_symbol()` is the one place that rule lives; a row
  displays the scanner's `BRK.B` but charts and fetches under `BRK-B`.
- **TradingView bond symbols need zero padding**: `TVC:PH02Y`, `TVC:PH05Y`,
  `TVC:PH10Y`. `TVC:PH5Y` is not the instrument.
- **Binance** → plain HTTPS is fine (`data-api.binance.vision` mirror).
- **ECB** → Frankfurter API, no key.
- **Philippine listings** are absent from Yahoo entirely; they come from the
  TradingView scanner and the chart socket.
- **Philippine funds are absent from both** — no ticker, no exchange. Their
  NAVPU comes from three plain-HTTPS registries (`phfunds.py`), and the raw
  series is **calendar-padded**: weekends repeat Friday's value, BPI's model
  ships duplicate stamps and a day or two of future ones. `phfunds.clean` is
  what makes it a business-day series; never read the raw points directly.
- **PIFA closes the connection** when several of its ~2 MB fund pages are
  requested at once (`RemoteDisconnected`). Read one fund at a time.

## Verifying a change

```sh
python3 server.py &
curl -s http://127.0.0.1:8000/api/recent | python3 -m json.tool | head -40
# expect ~55 rows, errors {}, the three bond tenors with stale=0, and fund rows
# whose "Philippine fund" stat reads 47 scanned with no missing

# Every row must carry a manner, and the only None rows should be funds whose
# run reaches back past TURN_BARS (the money-market funds) or a censored run.
curl -s http://127.0.0.1:8000/api/recent | python3 -c '
import json,sys
from collections import Counter
rows=json.load(sys.stdin)["rows"]
print(Counter((r["market"],r.get("manner")) for r in rows))
print("missing field:",[r["ticker"] for r in rows if "manner" not in r])'

node --check <extracted js>                       # front-end syntax
export PATH="$HOME/.local/bin:$PATH"
moli fetch --eval-file /tmp/eval-recent.js --wait domstable "http://127.0.0.1:8000/"

pkill -f "server.py"                              # and stop it again — see above
```

A cold start pays the fund leg once (~35 s, PIFA dominates) before
`/api/recent` has rows; `.cache/` keeps it warm after that, so an offline start
still serves rows.

Use `--eval-file` (not `--dump`) to read the rendered table: it returns the live
headings, row count and the bond rows' text. For layout, `moli fetch --layout
--dump screenshot_full` gives a full-page PNG — `--dump` and `--eval` cannot be
combined in one call, so scrolling-and-shooting takes two passes.

When a point's label changes, check the basis the page words against the clock —
each of these numbers is what the payload and the moment say it is, not what the
fold did:

```sh
python3 - <<'EOF'
import json, urllib.request, urllib.parse
def get(p): return json.load(urllib.request.urlopen("http://127.0.0.1:8000" + p))
for s in ["SPY", "BTC-USD", "GC=F", "USDPHP=X", "PSE:PHR", "TVC:PH10Y", "FUND:BPI-INFRA"]:
    d = get(f"/api/chart?symbol={urllib.parse.quote(s)}&range=3mo&interval=1d")
    print(f"{s:14s} {d.get('lastBarBasis'):6s} session={d.get('session')}")
# in the regular session a US name reads live; on a Friday night it reads close;
# BTC-USD reads live at any hour; PSE, bonds and funds read close
EOF
```

When a window or a verdict changes, check the **agreement** between every table
and every chart it can open — not just that the table looks right:

```sh
python3 - <<'EOF'
import json, urllib.request
def get(p): return json.load(urllib.request.urlopen("http://127.0.0.1:8000" + p))
rows = {r["ticker"]: r for r in get("/api/recent")["rows"] if r.get("market") == "US"}
import markets
for t in [r["ticker"] for r in markets.us_universe(50)]:
    chart = get(f"/api/chart?symbol={t}&range=3mo&interval=1d")
    badge = (chart.get("trend") or {}).get("label")
    row = rows.get(t)
    if (row or {}).get("direction") != badge and not (row is None and badge != "bullish"):
        print("MISMATCH", t, row and row.get("direction"), badge)
EOF
# expect no output
```

The same check for the funds — every fund's row (where there is one) must be the
verdict its own chart shows, and the price must be the chart's newest bar:

```sh
PYTHONPATH=. python3 - <<'EOF'
import json, urllib.request, phfunds
def get(p): return json.load(urllib.request.urlopen("http://127.0.0.1:8000" + p))
rows = {r["symbol"]: r for r in get("/api/recent")["rows"]
        if r.get("market") == "Philippine fund"}
for code, *_ in phfunds.FUNDS:
    chart = get("/api/chart?symbol=%s&range=3mo&interval=1d" % phfunds.symbol_for(code))
    badge = (chart.get("trend") or {}).get("label")
    row = rows.get(phfunds.symbol_for(code))
    if (row or {}).get("direction") != badge and not (row is None and badge != "bullish"):
        print("MISMATCH", code, row and row.get("direction"), badge)
    if row and round(row["price"], 6) != round(chart["points"][-1]["c"], 6):
        print("PRICE MISMATCH", code, row["price"], chart["points"][-1]["c"])
EOF
# expect no output
```
