# asset-price-display — agent notes

## The leaning table sells only what Ondo sells (2026-11-06)

Asked for by name: "regarding 'Leaning bullish — not confirmed', remove US
stocks/funds not available @ app.ondo.finance". The table is a shortlist of
near-misses; a row for something the reader cannot buy is not a shortlist entry.

`ondolist.py` is the shelf: `app.ondo.finance/sitemap.xml` publishes one URL per
listed asset (`/assets/nvdaon`, and the two yield funds bare, `/assets/ousg`),
so membership is exact and no hand-kept list can drift. Measured 2026-11-06:
**476 assets** listed.

Five rules:

1. **The shelf is a fetch, cached, and its absence is an outage.** A copy under
   `CACHE_TTL` (6 h) skips the request; a failed request falls back to a copy
   under `CACHE_KEEP` (14 days) and marks it `cached`; with neither, `shelf()`
   answers None and **every row stays** — invariant 3, a missing fetch is not a
   listing fact. Plain HTTPS, no browser, no key.
2. **Spelling is compared with separators removed on both sides.** `BRK.B` is
   tried as `brk-b` and `brkb`, and the shelf's own `brk.bon` as `brkbon`, so a
   scanner's dot and Yahoo's dash and the site's spelling meet on one answer.
3. **Two markets are filtered, and only those.** A `US` row needs an Ondo
   token; `Philippine fund` keeps no row, because no Philippine fund is on that
   shelf. Philippines stocks, crypto and the bond yields are untouched — the
   request named the United States listings and the funds, not those.
4. **The filter is on the leaning list alone.** The bullish table above it is a
   statement about what turned, not a shopping list, and no market was asked to
   leave it.
5. **A seeded copy is re-filtered on read, from disk only.** `seed_recent` runs
   `recent.actionable` against `ondolist.saved()` (no socket at startup), so a
   table swept before this rule cannot put `GILD` back on screen. The payload
   carries `ondoShelf` (`count`, `fetchedAt`, `cached`) and the page prints the
   read time; with no shelf it says the list could not be read rather than
   implying nothing is listed.

Measured through the page 2026-11-06: the shelf read **476 assets**; the table
went 18 leaning rows → **15** — `US BRK.B` and `US GILD` are not on the shelf,
and the one fund row (`ALFM-PESO`) went with its leg — while every other row
stayed: `US ACN, PG, V, MA, ABBV, COST, ISRG`, `Philippines PHR, PNB, MWIDE,
FCG, PHA`, `Crypto NEARUSDT, ZECUSDT, UNIUSDT`. Card subtitle reads "15 rows ·
Ondo-listed", the note adds the shelf's read time, and the server note adds
"leaning rows are Ondo-listed only".

`test_ondolist.py` covers the parse, the membership spelling, both cache ages,
the no-shelf fallback and the filter's three answers (13 tests). Suite: 353
tests OK.

## The rail tag says which way a neutral row leans (2026-11-06)

Asked for by name: "also add \"leaning bullish\" or \"leaning bearish\" in the
watchlist section, color each light green and light red respectively." A row
could only ever say Bullish, Bearish or Neutral, so the rail was the one place
the chart's own "Neutral · leaning bullish" badge had no counterpart — even
though `trend.classify` has returned `lean` since the leaning table shipped, and
the payload therefore already carried it.

Five rules:

1. **The tag replaces `Neutral`; it is not a second pill beside it.** The first
   build drew both, and a 340 px rail (310 px of list) had 22 px left for the
   symbol: `USDPHP=X` rendered as `US…`, `PSE:PHR` as `P…`. "leaning bullish"
   already implies the verdict is neutral, so one tag carries both facts:
   measured 82 px for `leaning bullish` and 86 px for `leaning bearish`, against
   48.6 px for `Neutral`, and every real ticker then fitted with room to spare
   (at 310 px: `PSE:PHR` 53, `NVDA` 36, `USDPHP=X` 69, `SHIB-USD` 62 — none
   clipped, the row never overflows sideways).
2. **The lean is the classifier's field, not a second reading.** It is derived
   at paint time from the row's own quote — `trend.label === "neutral" &&
   trend.lean` — and that quote *is* the `/api/chart` payload. A row charting
   `TVC:PH10Y` still reads `Bearish`; a neutral row in no hold band still reads
   `Neutral`; a row whose fetch failed still reads nothing at all. The bond
   reversal comes along for free, because `tv.bond_price_call` already flips
   `lean` with the label.
3. **Light is a shade, and it is measured.** New tokens `--lean-up` /
   `--lean-down` per theme — light `#2a7134` / `#a8413c`, dark `#57c463` /
   `#ef8f88` — on the verdict pill's own construction (dashed border, 13% tint)
   so a lean is visibly softer than a confirmed Bullish/Bearish chip. Measured
   through the page: **4.74:1** and **4.73:1** on a light row, **7.23:1** and
   **6.88:1** on a dark one.
4. **The lit row needs one correction, and only one.** The charted row's tint
   is the palest base in the rail (18% of `--series-1`); a light green on it read
   **3.85:1**, under AA for 10 px text. `.watch-item.is-active .watch-trend
   .leaning` therefore mixes 70% of the shade with `--text-primary` — which
   darkens it in the light theme and lightens it in the dark one, so one rule
   fixes both: **5.84:1** light, **7.12:1** dark.
5. **The tag wraps instead of ellipsizing.** `FUND:ALFM-GMAI-USD` is 18
   characters and one of the nine funds that lean right now; with a leaning tag
   it needed 154 px in the 137 px the 396 px rail leaves it. Rather than cut
   either the symbol or the tag, `.watch-id:has(.watch-trend.leaning)` wraps, so
   only that row's tag drops to a second line (76 px → 97 px tall). Everything
   that fits stays on one line: at 310 px only the two long fund codes wrapped,
   and no row clipped a symbol at any width tested (1440, 1240, 1100, 520).

The words are in the row's accessible name (`Chart NVIDIA Corporation (NVDA),
trend Neutral, leaning bearish, three-month profit odds 0.25`), the tooltip
spells out *"Neutral on the chart, leaning bearish: inside the band that keeps a
bearish label, 51% of the way to earning one — not confirmed"*, and the rail
hint gained one clause: "Each tag is that row's three-month verdict, and a
lighter tag is a lean it has not confirmed."

Page-only change: `index.html` (two token pairs, the leaning pill rules, the lit
row correction, the wrap rule, the tag builder, the hint clause). No Python
module touched; suite: 334 tests OK. Verified on a real browser through Moli's
CDP endpoint (`moli serve --layout`, 1440×900 light and dark, 1240×900,
1100×900 and 520×1400) — note that Moli reports compatibility geometry until a
paint: `Page.captureScreenshot` is what turns `getBoundingClientRect` into real
boxes, and every number above is from a run that painted first.

## The rail lights the chart you are looking at (2026-11-04)

Asked for by name: "if shown price graph asset is in watchlist, there should be a
highlight on that asset in the watchlist section." A row was already tinted when
its asset was charted, but the tint was 12% of `--series-1` — the weakest mark in
the rail — and the state behind it was a **snapshot taken in `loadChart`**, so it
was only right for the instant the chart answered. Measured through the page
before the change: chart MSFT, press Add to watchlist, and the row now holding
the asset on screen stayed dark; a row saved as `USDPHP=X` never lit for the
`PHP=X` chart the search box offers for the same series.

Seven rules:

1. **The highlight is derived, never remembered.** `state.watchActive` is gone;
   `isWatchActive(item)` compares the row against `state.chartSymbol` at paint
   time, and `drawWatchList` is the only painter. That one change is what makes
   the highlight survive an add, a reload from disk, a reorder, a rename to the
   server's spelling, and a quote arriving after the chart.
2. **The instrument is compared, not the letters.** `sameInstrument` matches a
   row's own `/api/chart` payload to the chart on screen on `name`, `exchange`,
   `type` and `currency` — the four fields that name a listing. `USDPHP=X` and
   `PHP=X` are one price line (`coinsph.SYMBOLS` says so server-side) and both
   read `USD/PHP` / `CCY` / `CURRENCY` / `PHP`, while their last closes differed
   in the sixth decimal — a fetch a minute apart, not a different asset. Two
   different instruments sharing all four is not a case: same venue, same name,
   same type, same currency and two prices does not exist. A payload missing any
   of the four matches nothing.
3. **No data, no highlight** — invariant 3's shape. A chart that failed leaves
   nothing lit, and a chart of an asset that is not on the list lights nothing
   (checked: `TSLA` against a list without it, `KO` against a one-row list).
4. **The tint was not enough to be a highlight.** It is now 18% plus a 4 px
   inset accent bar in `--series-1`, through `box-shadow` so no row shifts
   sideways. Colour and shape, and the name in the row's `aria-current`, since a
   tint is not available to a screen reader.
5. **The lit row is brought into view — inside the rail only.** `revealActiveRow`
   moves the *list's* `scrollTop`; it never scrolls the page, because in the
   stacked layout the rail sits under the chart and a page-level reveal would
   push the chart off screen to show a row. When the rail has no overflow of its
   own (the stacked layout sets `max-height: none`) it does nothing at all:
   verified at 520 px, `pageY` stayed 0 and `overflowX` 0. A row already on
   screen is left exactly where it is, so clicking a visible row never moves the
   rail. It stands down during a drag, whose own loop owns the scroll position.
6. **It waits for layout instead of trusting the first frame.** A cold load reads
   `clientHeight`/`scrollHeight`/`getBoundingClientRect` as **0/0/0** — the rows
   are in the DOM, the frame is not laid out — and the first version therefore
   bailed on every cold load with twenty rows in the rail. It now re-asks frame
   by frame for `REVEAL_PATIENCE` = 4 s and gives up quietly. Measured: 6–10
   frames of `norect` before the geometry appeared, then `scrollTop` 908 of a
   908 max with the row flush inside the box and `pageY` 0.
7. **A repaint is not a scroll.** `drawWatchList` empties the list to rebuild it,
   which drops the container's `scrollTop` to 0 for the length of that frame — so
   a quote arriving yanked a long rail back to its first row, undoing the reveal.
   It now captures `scrollTop` before clearing and restores it before returning
   (measured: 300 set by hand survived a repaint). The active row's own quote
   re-reveals it afterwards, because that row grows by its price and odds lines —
   the only quote arrival allowed to touch the rail's position.

Also added: the rail hint says "The highlighted row is the chart on screen."
while a row is lit, so the mark explains itself.

Page-only change: `index.html` (one CSS rule, the derived matcher, the reveal,
the scroll memory in the repaint). No Python module touched. Verified on a real
browser through Moli's CDP endpoint (`moli serve --layout`, 1440×900 and 520×900)
because Moli's `fetch --eval` path reports compatibility geometry — every number
above is from that run: chart of a saved row at position 20 of 20 revealed it to
908/908; chart of `AAPL` at position 1 left the rail at 0; `TSLA`, `KO` lit
nothing; the alias pair lit the `PHP=X` row for the `USDPHP=X` chart and vice
versa; a click, a keyboard reorder and the Add button all lit the right row;
removing the charted symbol cleared it; dark theme read
`rgba(57,135,229,.18)` with the `#3987e5` bar.

## The rail row carries the odds too (2026-11-04)

Asked for by name: "add 3-month profit odds figure in watchlist section." The
chart has printed that number since 2026-11-01, as a stat-line under the price
(`drawProfitOdds`); every watchlist row now prints the same figure on a third
line, under its name and its window's move:

> **AAPL** [Neutral] ········································ **$332.50**
> Apple Inc. ················································ ▲ +7.47%
> 3-month odds **0.69**

Five rules:

1. **It is the chart's own number, off the chart's own payload.** A watch quote
   *is* the `/api/chart` response (`quoteSummary` keeps `data`), so the row reads
   `quote.data.profitProbability`. No second estimate, no second fetch, and no
   way for a row and the chart its click opens to disagree about the odds — the
   same property the pill has had since 2026-10-31.
2. **Above/below 0.5 is the only colour it adds**, through the same
   `--delta-up` / `--delta-down` tokens `.stat-value.above` / `.below` use, so
   green in the rail and green under the price mean one thing without a key.
   The label stays muted: it is a footnote to the row, not a third hero.
3. **Missing is missing, three ways.** A yield (`TVC:PH10Y` — no estimate by
   design), a series the model refuses (short, weekly, constant-return), and a
   row still loading or failed all render **no line at all**, so the row keeps
   its two-line 58 px shape instead of a defaulted 0.50 or a dash. `probability
   .estimate` is the only source, and where it answers nothing the rail says
   nothing.
4. **One paragraph of claim, two tooltips.** The long "what this number is and
   is not" text was lifted out of `drawProfitOdds` into `profitOddsClaim(r)`,
   and both the stat-line and the row's odds line call it. Two copies of a
   paragraph that specific are two paragraphs that would eventually disagree.
5. **The figure is in the row's accessible name** — `Chart Apple Inc. (AAPL),
   trend Neutral, three-month profit odds 0.69` — because a tooltip is not
   available to a screen reader, and the line is now part of what the row says.

Measured 2026-11-04 through the page (five rows seeded: AAPL, `PSE:PHR`,
`FUND:BPI-INFRA`, `TVC:PH10Y`, BTC-USD) against the same symbols' `/api/chart`
payloads: **0.69 / 0.81 / 0.18 / none / 0.77**, matching `probability.estimate`
(0.6942 / 0.8125 / 0.1798 / null / 0.7686) exactly; the bond row drew no line and
stayed 58 px tall while the other four grew to 76 px. No row overflowed at the
396 px rail or wrapped at the 340 px one, and the name never had to ellipsize.
`ZB=F` (0.39) and `USDPHP=X` (0.85) carry one too — futures and currency pairs
are classes the model covers — so only a yield or a refused series loses the
line. Page-only change: `index.html` (one CSS block, the row builder, the
extracted tooltip). No Python module touched.

## A PSE chart says what traded — on a finished day (2026-11-04)

Asked for by name: "for PSE / Philippines stocks, on the main price display also
show last trading day's volume in PHP", then pinned twice — "does this the
volume only shows for the trading day that has only been completed", and "when
3:15pm comes, will the trading volume now give me the volume for today?" It is
now a fourth stat-line under the price, and it reports **only finished
sessions**, switching at the exchange's own 3:15 p.m. bell:

> Trading volume **₱55.40M** · 49.5K shares · Nov 3, last completed session

The figure is `close × volume` on the newest drawn bar that is a finished
session, in pesos — the same product `bullish.py` and `onset.py` rank the tables
on. Checked live 2026-11-04 (04:49 Manila, market shut, newest bar Nov 3)
against the "Most traded Philippines" table, which ranks the TradingView
scanner's `Value.Traded` from a different endpoint: **ICT 1,901,441,880, BDO
375,081,872, BPI 217,171,600, AC 215,339,520 — identical to the peso on all four**
(ratio 1.0000), which settles both the formula and the units: the socket's volume
field is shares.

Six rules:

1. **The bell decides, from the exchange's own published schedule.** `pse.com.ph`
   (read 2026-11-04) closes the market at **3:15 p.m.**, after a 15:00–15:15
   closing VWAP session; `SESSION_CLOSE` is that clock and `CLOSING_PRINT_DELAY`
   (2 min) is the moment the closing print needs to reach the daily bar. Before
   the bell today's bar is the session so far and the figure is the previous
   session's; from it, today's closing volume is the figure. Demonstrated on live
   TEL bars with a synthetic Nov 4 bar carrying 9,999 shares: **09:31, 12:30,
   15:05 and 15:16 all reported Nov 3 (49,465 shares, ₱55,400,800) — 15:18 and
   16:40 reported Nov 4 (9,999 shares)**. Asking at 15:15 exactly is asking during
   the closing print, which is why the delay exists.
2. **No holiday calendar is invented.** On a holiday there is no bar dated today,
   so the walk falls through to the last day that actually traded, before and
   after the bell alike. A suspension behaves the same way.
3. **Decided at read time, in `chart_data` — not frozen into the payload.**
   `pse.chart` and `_build_chart` ship `volumes` aligned with `points` (the
   `crypto.chart` shape), and the route picks the bar with `now`. A chart fetched
   at 10:30 and served at 16:00, or tomorrow from a disk copy, therefore reports
   the freshest finished session the bars actually hold instead of the day it was
   fetched on. `test_the_decision_is_made_at_read_time_not_fetch_time` pins that
   the bar which was "today" at fetch time becomes the answer the next day.
4. **Missing is missing, never ₱0.00.** The PSE index ships no volume (five-field
   bars), a bar whose volume field did not parse ships none, and a **zero-volume**
   bar is silence too — `onset`'s own rule that "a missing volume is not a
   zero-volume session". All read `None` and the page hides the line:
   `PSE:PSEI` answered `tradedDay: null`, `tradedShares: null`,
   `tradedTurnover: null`, while `TEL` and `PHR` did not.
5. **Daily only.** A weekly bar's volume is a week's, so close times volume is not
   a *trading day*'s value; the route refuses `interval != "1d"`.
6. **It leaves no stale figure behind.** The line is *cleared*, not just hidden,
   for a non-PSE chart — `AAPL` and `TVC:PH10Y` carry no `tradedTurnover` and the
   readout is empty in the DOM, one inspector away from misreading a peso number
   as a claim about a bond. The day is formatted in **UTC**, because a PSE bar is
   stamped at the Manila open (01:30 UTC) and local-time formatting would name
   the previous day for a reader west of Manila.

Scope: the chart's own display only. The recent table and the leaderboards already
carry the same peso figure in their volume column, computed from their own fetch
of the same bars; nothing there changed. `test_pse_volume.py` covers it (15 tests,
wire mocked, every one pinning the clock it means to test so none of them depends
on when the suite runs); suite: 334 tests OK.

## A delisted pair is not a price (2026-11-03)

The reader said XMR's graph was old. It was — by two years and eight months —
and the cause was not Yahoo:

- Binance keeps a **delisted** pair in `/api/v3/ticker/price` at its last price
  forever, so `XMRUSDT` still answered **$118.70**, and its newest kline was
  **2024-02-20 02:59:59** while Monero traded at **$625.94** (Kraken `XMRUSD`
  625.63, CoinGecko 625.39, measured 12:00 UTC).
- `crypto.coin("XMR-USD")` therefore said "chartable", `crypto.chart` drew the
  90 daily bars ending Feb 2024, and the hero read `$118.70` — a 2023-11 →
  2024-02 date range under today's page.
- Worse, `crypto.latest_close` returned that frozen $118.70, so
  `server.yahoo_is_wrong` compared it with Yahoo's *correct* live $625.94, found
  a 425% gap, and **threw the good chart away** for the dead one (`REROUTE_GAP`
  is 20%). Yahoo alone was right; the reroute was the bug.

Measured the same day across the index: 132 of the top 250 coins had a `USDT`
pair and **five were dead** — XMR (2024-02-20), DAI (2020-08-12), BTT
(2022-01-17), BEAM (2023-01-26), LIT (2025-02-10).

Five rules:

1. **The bars are the evidence.** `_is_trading(rows)` reads the newest bar's
   close stamp; `STALE_BAR_DAYS` = 5 means the pair has stopped. A live daily
   pair's newest bar closes in the future (it is forming), so the test is
   one-sided — only silence fails. Apply it wherever bars are read (`chart`
   *and* `latest_close`), because a per-symbol grudge list would go stale the
   day Binance delists the next pair.
2. **A dead pair gets Kraken, not Yahoo, when Kraken trades the coin.**
   `/0/public/OHLC`, plain HTTPS, no key, 720 rows per request whatever the
   interval (so a `5y` daily request draws two years and claims no more, the
   same honest cap as `ondo.MAX_SPAN_DAYS`). Kraken answered for all five dead
   ones with a bar stamped today; the payload names `Kraken` as its source and
   exchange. Two quotes are tried, `USD` then `USDT` (`BTTUSD` exists,
   `BTTUSDT` does not). Its rows are rewritten into Binance's shape (close =
   open + one interval) so one drawing loop, one freshness test and one
   `last_bar_date` serve both venues.
3. **An unknown Kraken pair is a 200 with an error list, not a failure
   status** — "not listed" is read from the body, and a transport failure on one
   quote falls through to the next. Both failing is "no Kraken series", never an
   exception: the caller still has Yahoo.
4. **No venue trading means no chart, not an old one.** `chart()` raises, so the
   route keeps Yahoo (current for `XMR-USD`) rather than drawing 2024.
5. **A delisted pair is not a second opinion.** `latest_close` answers None, so
   `yahoo_is_wrong` returns False and Yahoo's live series stands — the exact
   inversion that started this. Verified after the fix: `XMR-USD` → Yahoo CCC,
   93 bars 2026-08-03 → 2026-11-03, hero **$623.63**, `lastBarBasis: live`,
   badge Neutral · leaning bullish +0.626, odds 0.92; `BTT-USD`, `BEAM-USD`,
   `LIT-USD` → **Kraken** with today's bar (`BTT-USD` was drawing three months
   of zeros from Yahoo, whose series for it is broken while its live price is
   not); `PEPE-USD` still Binance; `BTC-USD` still agrees with Yahoo and stays
   there.

Also fixed while in the file: `_klines` **quotes** the ticker. Binance lists
pairs whose base asset is not ASCII (`币安人生USDT`), and pasting the name into
the URL raised inside urllib, so the pair read as an outage.

One poisoned disk copy existed (`.cache/…`: the Binance payload stored under the
Yahoo chart key, newest point 2024-02-20) and was deleted — a live fetch
overwrites that key, but nothing should rescue it offline. `test_crypto.py`
covers all of this (22 tests, wire mocked); suite: 319 tests OK.

## The session trading now has no bar yet (2026-11-03)

The reader asked why AAPL's newest point read "close" at Nov 2's price on the
morning of Nov 3 — "Nov 3 trading day hasn't begun yet" — with Ondo's `AAPLon`
quoting a live price. Measured at 04:15 New York the same morning, so the
numbers are on the record:

- `/api/chart?symbol=AAPL&range=3mo&interval=1d` ended at **2026-11-02 14:30Z,
  338.32**, `lastBarBasis: "close"`, `session.coversLastBar: false`, `lastPrint`
  Nov 2 16:00:01 New York.
- Yahoo's daily payload carried `fulldayPrice: **322.13**` — the pre-market
  print, from the 5-minute pre/post series 322.40 → 323.47 → 322.33 → 322.13 at
  04:00–04:15. `full_day_close` correctly refused to date that Tuesday price to
  Monday's bar.
- Ondo agreed with it: header **323.39**, and 1 AAPLon = 1.0034 AAPL, so
  322.13 × 1.0034 = 323.2 — the token was quoting the same pre-market print, not
  a premium.

So nothing was mislabelled (338.32 really is Monday's close), but the live price
was nowhere on screen: both folds only ever touch the newest *bar*, and between
one session's close and the next session's first bar the newest bar belongs to
an older session. Fixed at the reader's direction — draw the print as a point of
its own, from **Yahoo**, not from Ondo (their choice on both counts).

Five rules:

1. **`live_print` (fetch time) keeps the print out of the bars.** The stamp is
   the session's **regular open** — exactly where the day's real bar will land —
   so the real bar replaces the point instead of doubling it. It refuses
   without an extended session, without a usable `fulldayPrice`, without a
   schedule, when the newest bar is already that session's (`full_day_close`
   owns that case), and when the newest bar is more than `LIVE_BAR_GAP_DAYS` = 5
   old (a halt is not a session that is trading).
2. **`live_point` (read time) draws it only while that session trades.** Applied
   in `chart_data` beside `weekend_proxy`, on the copy, before the re-score, so
   the badge reads the drawn bars. Drawn only when `now` is inside the payload's
   own `pre` or `post` window; from 20:00 to 04:00 New York Yahoo folds nothing
   and reports the regular close again, so **nothing is added** and the newest
   bar keeps its close. That stretch is a gap in the source — do not fill it by
   repeating the close as a live price, and do not reach for Ondo to fill it
   without being asked.
3. **It reads `pre` or `after`, never `close`.** A `livePointStamp` matching the
   newest point short-circuits `last_bar_basis`: before the regular close it is
   "pre", after it "after". That is what stops a memo entry fetched at 09:28 from
   labelling a pre-market price "close" when it is served at 09:31.
4. **A disk copy adds nothing.** `cached` is refused: a copy fetched hours ago
   must not invent a price for a session it never saw. It draws the bars it
   stored and says how old they are.
5. **The point is real but not a bar.** The recent table's US rows still score
   completed bars (`yahoo_bars` is untouched), so during an extended window a
   row's price is the last bar's close while the chart's newest point is the
   print. Stated rather than hidden; if the reader ever wants the table to carry
   it too, that is a change in `recent.scan`, not in `live_print`.

Checked live 2026-11-03 04:15 New York through the page: hero `$323.20`, meta
`AAPL · NasdaqGS · equity · via Yahoo · last bar is a pre-market price`, badge
Neutral +0.145, odds 0.66, 66 points. Same sweep: BTC-USD `live`, PSE `close`,
`TVC:PH10Y` `close`, `FUND:BPI-INFRA` `close`, `USDPHP=X` `live` — all
unchanged. `test_live_point.py` covers it (14 tests, wire mocked); suite: 297
tests OK.

## A token Yahoo has no spelling for (2026-11-02)

The reader typed `ousg` into the search box and it answered nothing. Measured
the same day, so the gap is on the record:

- `query2/v1/finance/search?q=ousg` → **200 with an empty quote list**, fuzzy off,
  on both query hosts; `q=ondo` answers seven Ondo tokenized *stocks* (`ONDO-USD`,
  `QQQON-USD`, `USOON-USD`, ...) and never this one.
- `v1/finance/lookup?query=ousg` → `total: 0` across every type.
- The **chart route 404s every spelling**: `OUSG`, `OUSG-USD`, `OUSG-OND`,
  `OUSG29256-USD`.
- Yahoo does carry the sibling token — `usdy` resolves to `USDY29256-USD`, "Ondo
  US Dollar Yield USD" — so this is one instrument the index does not hold, not
  an outage.

So the VTV fix cannot reach it: `probe_ticker` asks the chart route whether the
query *is* a symbol, and there is no symbol for this one to be.

**What it is.** OUSG is Ondo's **Short-Term U.S. Government Bond Fund** token: a
share of a T-bill fund, traded on Ethereum (`0x1b19c1...bee92`) and mirrored on
Polygon and Solana. It accrues — 90 days ran 116.12 → 117.11, about 2.4%
annualised — so a three-month window on it is essentially always bullish, the
same true statement `phfunds` makes about a money-market fund.

**Where the price comes from.** `ondo.py`, reading DeFiLlama's coins API
(`coins.llama.fi/chart/ethereum:<address>?span=N&period=1d`) over plain HTTPS,
no key. Two checks before it was trusted:

- The number **agrees with CoinGecko to the sixth decimal** (117.106259 on both,
  same minute) — the same on-chain market underneath. CoinGecko was rejected as
  the *bars* source only because its free tier is 5 requests/minute, fine for one
  cached index lookup and not for a chart the page re-reads every minute.
- The **span is capped at 500 days**: `span=500` answers, `span=600` is HTTP 400.
  So a `2y` or `5y` request draws the 500 days that exist and claims no more.

Five rules:

1. **The prefix is ours, because Yahoo has no spelling to borrow.** `ONDO:OUSG`
   is the symbol a row carries and a URL keys on (the `FUND:`/`TVC:` pattern).
   A bare `OUSG` typed into the box still charts — but only after Yahoo refuses
   it (`ondo.alias`, called in `chart_data`'s Yahoo branch exactly as
   `rates.chart_alias` is), so a listing that one day trades under the bare
   ticker keeps its own chart. The payload then names `ONDO:OUSG`, and the page's
   refresh clock and watchlist follow that spelling.
2. **The newest point is `liveLastBar`.** DeFiLlama stamps the last point at the
   moment of the request and carries the current price, so the bar says live —
   and `server.last_bar_basis` refuses that word for any copy served from disk.
   Verified: `/api/chart?symbol=ONDO:OUSG` → `lastBarBasis: "live"`, the same
   payload with `cached: true` → `"close"`.
3. **Search rows are shaped like Yahoo's and de-duplicated**, added beside the
   coin, PSE and fund supplements. Every word of the query must appear in the
   token's ticker, name or aliases, so `ousg`, `ondo`, `ondo short term` and
   `short-term treasury` all find it while `ondo qqq` (a Yahoo-listed Ondo stock)
   does not. An exact ticker hit (`ONDO:OUSG` for "ousg", relevance 0) leads on
   its own; the bare word "treasury" leaves it behind the futures curve.
4. **The warmer has a token leg** (`_warm_batch_tokens`), because an `ONDO:`
   symbol sent down the Yahoo leg is a guaranteed 404 per pass. Confirmed on
   disk: `ondo:ONDO:OUSG:3mo:1d` is stored after the page added it to the
   watchlist.
5. **The odds line needs a class, and gets a new one: `token`.** Calendar days
   (a token trades every day, so three months is ~92 sessions, not ~65) and the
   crypto round trip (0.20% — it is swapped, not subscribed). The number comes
   out **0.99**: the drawn window is almost a straight line that steps up, and
   under a stationary normal-log-return model that is near-certain. That is the
   model being what it is, not a bug, and the tooltip still says it is not a
   calibrated success rate.

Checked live 2026-11-02 through the page: the dropdown shows
`ONDO:OUSG | Ondo Short-Term U.S. Government Bond Fund | Ondo`; the chart reads
`ONDO:OUSG · Ondo · tokenized fund · via DeFiLlama · last bar is a live price`,
hero `$117.1063`, `+0.85% three-month move, since Aug 5`, badge **Bullish +0.757**
(90 bars), odds **0.99**; the watchlist row carries a Bullish pill and `+0.85%`.

Not done, deliberately: OUSG is on no table and in no sweep — this fixes the
search box and the chart. `test_ondo.py` covers all of it (21 tests, wire
mocked); suite: 283 tests OK.

## A ticker Yahoo's search refuses is still reachable (2026-11-02)

The reader reported VTV missing from the search box. The cause was not a filter
or a table: `query2.finance.yahoo.com/v1/finance/search?q=vtv` answers **HTTP
500** on both query hosts, every parameter shape, fuzzy on or off — while VTV
charts normally, `/v1/finance/quoteType/?symbol=VTV` resolves it, and `q=vt`
lists it third. Measured across 45 common US tickers the same day: 44 answered
normally, so this is one index quirk, not an outage. The route raised on the 500
*in `produce()`, before any supplement ran*, so the page showed no suggestions.

- `api_search`'s producer now treats a refused search as an **empty answer**,
  not a failed route, so the coin/PSE/fund/FX/rates supplements still answer. A
  Moli failure (the browser) still raises: that is not the index.
- `server.probe_ticker` + `_chart_meta_row`: when Yahoo returned no rows and the
  query *is* a ticker (`TICKER_RE`), the query is resolved through the **chart
  route** — the same route a click uses — and offered only if it draws. The row
  carries the route's `longName`, `fullExchangeName` and `instrumentType`, which
  must be in `KEEP_QUOTE_TYPES`; there must be at least one bar.
- `markets.yahoo_symbol` supplies the spelling (`brk.b` → `BRK-B`), so the row
  probed is the chart that answers.
- Multi-word queries are probed by their first word **only when every other word
  is in `INSTRUMENT_WORDS`** (`etf`, `fund`, `stock`, `index`, …) — `vtv etf`
  resolves, "the long bond" must never resolve to `THE` (Target Hospitality).
  Prose is never guessed at.
- Not fixed, deliberately: a *name* query the index answers without the ticker.
  `vanguard value` returns `VVIAX` and the tokenized `VTVON-USD` and no `VTV`;
  no probe can recover a row the index never offered. Say so rather than adding
  a curated alias unless the reader asks for one.

`test_search.py` covers the probe (11 tests, browser mocked); the live route was
checked end to end — `/api/search?q=vtv` → one row, the page's dropdown shows
`VTV | Vanguard Morningstar Value ETF | NYSEArca`, and clicking it charts VTV
(64 points, neutral, odds 0.69). Suite: 262 tests OK.

## Chart-only profit probability correction (2026-11-01)

The reader explicitly replaced the class-base-rate model described below.
`probability.estimate` now uses only the displayed daily log returns: sample mean
`m`, sample standard deviation `s`, count `n`, and future three-calendar-month
session count `H`. `P = Φ((H*m − log(1+cost))/(s*sqrt(H+H²/n)))`; the variance
includes uncertainty in the estimated mean. Crypto uses calendar days, others
weekdays (no holiday calendar). Classes supply only cost/calendar, no up-rates.
The UI says “chart-based estimate”, with model assumptions in the tooltip.
This is an uncalibrated stationary independent normal-log-return model, not a
validated success frequency. Do not claim otherwise. Keep it separate from the
badge. Short/invalid/constant-return/weekly series receive no estimate; yields
remain excluded. Futures now receive the same chart-only estimate (weekday
calendar, assumed .20% notional round trip), at the reader's request after the
missing RBJ27.NYM readout. This estimates a long contract price gain, not account
profitability; expiry/rolls/margin are not modeled. Results are bounded to .01–.99.
The older “shape is not an input” rule, class constants and old test description
below are historical and superseded by this explicit user request.

A local web page that charts an asset's last three months and labels the trend
(bullish / bearish / neutral). Python 3 stdlib server, vanilla-JS frontend, no
install step, no build step. The only dependency is the **Moli** browser, because
Yahoo answers plain HTTP clients with a 429.

## The chart states the odds of profit (2026-11-01)

Under the price the chart now prints one number: **the probability, 0 to 1, that
this asset is higher in three months.** Asked for by name — "just give me a
number from 0 to 1 ... mention this number in the main price graph".

`probability.py` computes it; `server.chart_data` attaches it to every payload as
`profitProbability` (one insertion point, after the badge is re-scored, so every
source — Yahoo, Binance, TradingView, ECB, funds, bonds — carries it);
`index.html`'s `drawProfitOdds` renders it as

> 3-month profit odds **0.41** · crypto base rate, net of 0.20% costs

Five rules:

1. **The chart's shape is not an input, deliberately.** Twenty research modules
   in this repo looked for a three-month edge inside the drawn window and landed
   between 41% and 52%; the ones that cleared 51% had intervals straddling it and
   mostly matched an always-up call on the same cases. Feeding the badge's score
   into this number would dress that coin flip back up as a forecast. So two US
   stocks of similar volatility carry the same number, and
   `test_the_charts_shape_is_not_an_input` fails if anyone ever wires the trend
   in. **This is not the badge reinterpreted** — `trend.py` says the score is not
   a probability, and that still holds; this is a separate number beside it.
2. **The number is a measured base rate, adjusted — never invented.** Each class
   carries its own three-month up-rate and its own typical volatility, both taken
   from saved studies:

   | class | up-rate | windows | σ (3 mo) | round trip |
   |---|---:|---:|---:|---:|
   | US equity / ETF / index | 60.77% | 62,535 | 13.40% | 0.25% |
   | fund (incl. the 47 PH funds) | 59.46% | 16,738 | 7.71% | 0.50% |
   | currency pair | 52.22% | 7,854 | 4.25% | 0.05% |
   | crypto | 43.92% | 3,436 | 36.86% | 0.20% |
   | PSE stock | 40.92% | 10,706 | 21.23% | 1.20% |

   The up-rates are `research/forecast-validation-extended.json`'s `baseline`
   blocks (`forecast_extended_validation.py`), PSE's included, and
   `test_probability.py` reads that file and fails if `CLASSES` drifts from it.
   The σ column is the median rolling 63-day realised volatility over every
   saved daily history of that class — `research/market-history-extended.json`
   (517 symbols) and `research/pse-history.json` (244). Recompute it with:

   ```sh
   cd research && python3 - <<'EOF'
   import json, math, statistics
   from collections import defaultdict
   for path, only in (("market-history-extended.json", None), ("pse-history.json", "PSE")):
       d = json.load(open(path)); by = defaultdict(list)
       for sym, rows in d["bars"].items():
           cls = "PSE" if only else d["universe"][sym]
           cl = [r[1] for r in rows if r[1]]
           rets = [math.log(b / a) for a, b in zip(cl, cl[1:]) if a > 0 and b > 0]
           for s in range(0, len(rets) - 62, 21):
               w = [r for r in rets[s:s + 63] if r is not None]
               if len(w) >= 50: by[cls].append(statistics.pstdev(w) * math.sqrt(63))
       for cls, v in by.items(): print(cls, round(statistics.median(v), 4), len(v))
   EOF
   ```

   The model is `μ = σ_class · Φ⁻¹(p_up)`, then `P = Φ((μ − cost) / σ)`, with σ
   the asset's own realised volatility shrunk halfway to its class's. That makes
   a typical member reproduce its own class's up-rate less costs — the property
   `test_a_typical_member_reproduces_its_class_base_rate` pins — and makes a
   wilder asset read nearer 0.5. `μ` is bookkeeping that turns a measured
   frequency into a probability at a measured volatility; it is **not** an
   expected return and must never be printed as one.
3. **Two classes ship no number at all: a yield and a futures contract.** No
   three-month up-rate has been measured for Philippine yields, and a borrowed
   0.50 anchor would print a figure driven only by the cost term; a futures
   contract has no long-run drift to measure and the equity rate would overstate
   it. The readout is hidden and its text cleared — invariant 3 in spirit, a
   missing number rather than a defaulted 0.5. `/api/chart?symbol=TVC:PH10Y` and
   `ZB=F` both answer `profitProbability: null`.
4. **It may disagree with the badge, and that is correct.** BTC-USD reads
   `Neutral` with the odds at 0.41; PHR reads `Neutral · leaning bullish` at 0.45.
   One describes the last three months, the other describes a population. Do not
   "fix" either to match the other.
5. **The tooltip carries the whole claim**, because the bare figure would read as
   a forecast for *this* asset: the population size, how the windows were
   measured, the volatility adjustment, the cost, and the survivorship warning
   (today's listed instruments only — delisted losers are missing, so the
   up-rates read high).

`.`stat-line` is the shared style for "a stat readout, not a second hero" — the
minimum-investment line and the odds line both use it. The odds line sits between
the price's delta and the trend note, so the number is one of the first things
under the price without becoming a second headline.

`test_probability.py` covers it (22 tests: the distribution functions, class
mapping, the base-rate reproduction, the vol monotonicity, the clamps, the
no-yield/no-futures rule, and the constants agreeing with the saved studies).
Suite: 257 tests OK.

## The peso's weekend comes from Coins.ph (2026-11-01)

`PHP=X` (which is also `USDPHP=X` — one series, two spellings) is charted on the
FX week: Monday to Friday, shut from Saturday morning Manila to Monday 05:00. So
a weekend chart ended at Friday's close, which is when a Philippine reader is
most likely to look. Those two days now come from **Coins.ph's USDC/PHP book** —
`coinsph.py`, `api.pro.coins.ph/openapi/quote/v1/klines`, 1,000 daily bars,
Coinbase-Pro shaped, plain HTTPS (a `moli_fallback` net is registered, not needed).

Measured 2026-11-01 before the change was made, so the number's standing is on
the record:

- **Coverage** 400 bars to 2025-09-28 with every calendar day present; demand
  went to the reader who asked for "Sat and Sun data from Coins" rather than to
  the delta-splice alternative, which the correlation below rules out.
- **Level** USDC/PHP ran median **+0.09** / mean **+0.13** pesos above the
  interbank over 259 shared days (sd 0.20, range −0.29…+1.50). A domestic
  premium, not a rate — so a weekend bar carries the stablecoin's price and the
  page names it.
- **Movement** corr(USDC/PHP Fri→Sun, USD/PHP Fri→Mon) = **0.07** across 51
  weekends, same direction 27/51, sd 0.12% against the interbank's 0.52%. Do not
  present a weekend bar as a forecast of the Monday reopen, and do not
  "improve" the fill by applying the stablecoin's *change* to Friday's close —
  that was option B and it injects movement measured as noise.

Four rules:

1. **Manila days decide the weekend.** `coinsph.manila_day` buckets every stamp
   by UTC+8, so Yahoo's Sunday 21:00 GMT reopen is *Monday* and a year of bars
   holds 52 Mondays, 52 Fridays, no Sundays and one stray Saturday (a forming
   bar carrying Friday's close). That Saturday bar is **replaced**, a weekday
   never is. UTC-date bucketing gives 22 Fridays / 30 Sundays in the same year —
   the off-by-one this rule exists to avoid.
2. **The fill runs to today, not to the last bar Yahoo drew** — on a Monday
   before 05:00 the FX series still ends Friday and the weekend must still show.
3. **The badge scores the drawn bars** (invariant 1): a 3-month peso chart is
   91 bars, not 66 (26 proxy). Longer than the 63 backtested daily bars; stated,
   not hidden.
4. **The page names the price.** `lastBarBasis` gains `weekend`, the meta line
   counts proxy bars, a hovered weekend point reads `USDC/PHP`, and the table
   caption says what those rows are.

One fetch serves every span (60 s TTL — the chart's own clock; 7-day fallback so
the page can say how old the reading is). An outage is a no-op: Yahoo's bars
stand. The kline rows are stamped in **milliseconds** — read as seconds they
land in the year 58,000 and every weekend falls outside every window (this was a
real bug here, caught only by the live route: `test_coinsph.py` now pins the
scaling). Tested in `test_coinsph.py` (24 tests); suite 235 tests, one
pre-existing failure in `test_leaning` unrelated to this work (its synthetic
91-bar series is 90 days long, so `onset.leaning`'s window trim drops the oldest
bar and scores one bar fewer than `trend.classify`).

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
cd ~/Documents/asset-price-display
python3 server.py        # http://127.0.0.1:8000/
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
| `probability.py` | The 0–1 chance the asset is higher in three months: the asset class's measured up-rate, adjusted for the asset's own volatility and the round trip. Deliberately not a function of the chart's shape. No number for a yield or a futures contract. |
| `recent.py` | The combined "recently bullish assets" table: US stocks, Philippine stocks, crypto, US Treasury futures, Philippine bond yields, Philippine funds, each dated. |
| `rates.py` | The US Treasury futures curve (ZT…UB): the contracts, the search rows and synonyms that make each findable, the bare-ticker chart alias, and the quote precision. |
| `phfunds.py` | The 47 Philippine funds — daily NAVPU from TOAP's UITF register, PIFA's NAV history and BPI Wealth's own pages — and the chart a fund row opens. |
| `coinsph.py` | Coins.ph's USDC/PHP daily bars — the peso pair's Saturdays and Sundays, the two days the FX week does not trade. `is_usd_php`, `manila_day`, `fill`. |
| `ondo.py` | The Ondo tokens Yahoo has no spelling for — OUSG, the short-term Treasury fund token: its on-chain identity, the DeFiLlama price series, the `ONDO:` chart route and the search rows. |
| `tv.py` | The Philippine government bond yields — the TradingView symbols, their names, their daily bars, and the chart a bond row opens. |
| `bullish.py` | The Philippine sweep: every PSE name that is bullish now, dated to the bar its run began on. |
| `pse.py` | PSE universe (TradingView scanner) and bars (browser-backed TradingView chart socket); `history_many` is the socket `tv.py` borrows. `completed_trade` is the last finished session's peso turnover the chart prints. |
| `markets.py` | The two most-traded tables and the PSE board-lot table; `us_universe()` feeds the recent table. |
| `crypto.py` / `cryptobull.py` | Coin identity (CoinGecko), bars (Binance, and Kraken for a pair Binance has stopped trading), and the 24-hour most-traded crypto table. |
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

## A dragged row scrolls the rail itself (2026-11-02)

Rearranging a long watchlist was done by hand. The rail does scroll (`max-height:
60vh`), but a drag reports where the pointer is only while the pointer **moves**,
so a row carried to the bottom edge sat there and the list never followed. A row
can also only be dropped where a row already is — rows reflow under the pointer —
so a target below the fold could not be reached at all without lifting the row,
scrolling, and dragging again.

`dragScrollStep` is a `requestAnimationFrame` loop with its own clock, started by
`dragover` and stopped by `endDrag`, by a `dragleave` of the list itself, or by
reaching an end. Five rules:

1. **The band is 56 px inside the visible slice of the rail**, and the speed ramps
   linearly from 120 px/s on entering it to 900 px/s at the edge. Distance is per
   *second*, not per frame: the same gesture must travel the same way at 25 Hz as
   at 60, and the first version (24 px per frame) crawled at 550 px/s under Moli's
   headless layout renderer.
2. **Each push re-places the row** through `dragPlaceAt` — the body of the old
   dragover handler, extracted so the event and the loop are one rule. Without it
   the list would scroll *past* a stationary pointer and the row would stay where
   the pointer last was.
3. **The scroller is whichever box actually moves**: the list on a wide page, the
   page itself in the stacked layout under 1000 px, where the rail has no
   `max-height` and only the document scrolls. The band is measured on the rail's
   on-screen slice, so a stacked rail taller than the window still has an edge to
   aim at.
4. **It stops at an end rather than spinning** — a frame whose `scrollTop` did not
   move ends the loop, and the next `dragover` restarts it.
5. **Nothing survives the gesture.** `endDrag` cancels the frame and clears the
   pointer, so a drag ended by Escape or by a release outside the window leaves no
   loop running, and the cancel path still restores the original order. The commit
   is also untouched: the order is mutated live as a preview and `drop` is still
   the only thing that writes it.

Checked live 2026-11-02 through Moli, 40 rows (2,320 px of rows in a 648 px rail,
1,672 px of travel), **one** synthetic `dragover` in the bottom band and the
pointer then held still: the rail scrolled to the end on its own, `TEST1` arrived
at position 40 of 40, and `drop` saved it. The top band carried a row back to
position 1; the middle of the list neither scrolled nor reordered; a `dragleave`
to the document stopped the loop while one with a row as `relatedTarget` did not;
the stacked branch scrolled the page by 695 px; a cancelled drag restored the
original order and left `dragScrollRaf`/`dragPointY`/`dragSymbol` at zero/null.
Keyboard reorder (↑/↓/Home/End) and the quote rows were re-checked unchanged.
Page-only change; no Python module touched.

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
- **DeFiLlama** → plain HTTPS is fine (`coins.llama.fi`), and it prices the Ondo
  tokens Yahoo does not carry. Its chart endpoint **caps a span at 500 days**
  (`span=500` answers, `span=600` is HTTP 400), which is why `ondo.MAX_SPAN_DAYS`
  clips a longer request rather than failing the symbol.
- **Coins.ph** → plain HTTPS is fine for the kline and ticker endpoints, but the
  rows are stamped in **milliseconds** (`1793491200000`), and the page's own JS
  is CORS-blocked from them.
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
