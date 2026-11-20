# asset-price-display

A local web page that charts an asset's last three months and labels the trend —
bullish, bearish or neutral — from a weighted-signal ensemble. Python 3 stdlib on
the server, vanilla JS in the page, **no `pip install`, no `npm install`, no build
step**. The only real dependency is the **Moli** browser (`~/.local/bin/moli`),
because Yahoo's chart API answers plain HTTP clients with a 429.

```sh
python3 server.py        # started from the project folder; http://127.0.0.1:8000/
```

`README.md` is the short guide; `docs/` is the full reference, one page per topic.
This file is the working notes: the invariants that must not drift, and what was
just built. `AGENTS.md` is a link to this file, so keep it under 24,000 bytes;
the older dated notes are in `docs/agent-notes-history.md`.


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
  Fewer than 3 closes read neutral (no drift t). A perfectly straight run gets a
  label from 4 closes; noisy series need more. `MIN_BARS` now only names the chart fallback.
- **Real time**: Binance keeps the forming day as its newest bar
  (`liveLastBar` → `lastBarBasis: "live"`, never from a disk copy); the page
  re-reads the chart every 60 s while `lastBarBasis` is live/pre/after
  (`CHART_LIVE_TTL`), 15 min otherwise, and at once when the tab returns.
- **Pullback tag (2026-11-16)**: `trend.pullback` → payload/row field
  `pullback`: a labelled window whose close is past the close 10 bars ago the
  wrong way and on the wrong side of its 20-bar mean. The badge and the recent
  row read "Bullish, pulling back" / "Bearish, bouncing". A tag only: it never
  changes a label (21% of labelled windows). See `docs/trend-call.md`.
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
- `export/trend.js` mirrors it; `python3 export/verify_parity.py` → 408
  cases, 0 mismatches.

## Fast price clock (2026-11-21)

`live_quote.py` + `/api/quote?symbol=`: newest Yahoo 1m print, 1 s memo. While a
Yahoo chart's `lastBarBasis` is live/pre/after, `main.js` polls it every 2 s and
patches only the newest point's close (hero, alarms). The badge is not re-scored
until the next full chart re-read (60 s), which replaces the patched point.

## Layout (2026-11-16) — read this before looking for a file

- `server.py` was split. It is still the core (caches, Yahoo proxy, chart building,
  the Philippine and recent sweeps) and **re-exports** the moved names, so
  `server.<name>` and `mock.patch.object(server, ...)` still work. Moved out:
  `moli_client.py`, `warm.py`, `netwatch.py`, `watchlist.py`, `http_handler.py`
  (handler + `main`). The moved modules reach back through `import server as S`;
  run as a script, `server.py` registers itself as `server` so there is one copy.
  A name a moved module *rebinds* (`_watch_online`, `_watch_union`, `_row_thread`)
  is **not** re-exported; read it from its own module (`netwatch._watch_online`).
- **Second pass, same day.** Out of `server.py`: `sweeps.py` (both background
  sweeps and their state), `yahoo_chart.py` (bars, sessions, live print,
  `yahoo_is_wrong`), `fx_charts.py`, `search_rank.py`. Out of `recent.py`:
  `recent_rows.py` (one function per market) and `recent_note.py`, through
  `import recent as R`. In these six, every function body reads the old module's
  names as `S.x` / `R.x` and rebinds state as `S._bullish_thread = ...`, so all
  their names **are** re-exported and `patch.object(server, ...)` reaches them.
  `server.py` keeps the caches and the warm-up.
- **Third pass, 2026-11-18**, same `S.x` / `P.x` pattern, all re-exported:
  `chart_route.py` (`chart_key`, `chart_data`) out of `server.py`; `pse_bars.py`
  (socket scripts, `history_many`, chart builders) out of `pse.py`, which keeps
  the universe, search, constants and runners.
- **2026-11-20**: `memo.py` (`cached`, `_stamp_copy`, `is_transient`) out of
  `server.py`, same `S.x` pattern; the memo's state stays in `server.py`.
  `sourcestats.py` tallies every source call (wrap new fetches in
  `sourcestats.timed(url)`); `/api/sources` + `status.html`. See `docs/source-status.md`.
- `faults.note(where, exc)` goes in any `except` that carries on past a failure:
  one console line per kind of failure per ten minutes. No bare `pass`.
- `research/market-history*.json` are kept gzipped; `lab/bigjson.BigJson` reads
  and writes them (first read ~13 s, once per server run).
- `index.html` is markup only. Code is in `static/*.js` (plain scripts, order
  matters, see the tags) and `static/app.css`. The handler serves only the page
  and `static/`.
- Research code is in `lab/`, all tests in `tests/`, data in `research/`.
  `labpath.py` / `lab/_paths.py` / `tests/__init__.py` put the folders on
  `sys.path`. **Run tests with `python3 run_tests.py`** (552 tests + parity).
- Do not run a `lab/` script to "see what it does": it rewrites its report in `research/`.
- `quality.py` flags bad bars on rows and charts (informational only). `nasdaq_bars.py`
  is the US fallback when Yahoo/Moli gives no answer at all (never for Yahoo's 404);
  such rows carry `source: "Nasdaq"`. `payload["markets"]` is the per-market status
  (live / partial / fallback / offline). `diskcache` is capped by files and bytes.
- `check_publish.py` scans for the account name without containing it.
- Port 8000 may already be held by the user's own server (a copy under Documents).
  Do not kill it; test on another port, `python3 server.py 8123`, and kill by
  `pkill -f "server.py 8123"`.

## Start the server only to check something, and stop it afterwards

`python3 server.py` is a verification tool, not a service. **Every time you start
it — to curl an API route, to read the rendered page through Moli, to take a
screenshot — shut it down again before you report back.** The user runs the page
in their own browser when they want it; a stray process on port 8000 also keeps a
background sweeper hitting upstream on its own.

```sh
pkill -f "server.py"          # argv is ".../Python server.py", not "python3 server.py"
sleep 2
curl -s -m 2 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/ \
  || echo "port closed"       # 000 / "port closed" means it is really down
```

Kill by `server.py` — patterning on `python3 server.py` matches nothing and the
server keeps running. Check the *port*, not only `pgrep`: a process mid-shutdown
can still be listed and still answer. If the user explicitly asks for it to stay
up ("leave it running so I can look"), that instruction wins — but then say which
port it is on.

## Files

| File | Role |
|---|---|
| `server.py` | Core: caches, Yahoo proxy, warm-up (`chart_data` is in `chart_route.py`; see Layout above for what moved out). `http_handler.py` has the routes: `/api/chart`, `/api/search`, `/api/top`, `/api/bullish`, `/api/cryptobull`, `/api/recent`, `/api/health`, `POST /api/watch`. |
| `trend.py` | The classifier. `classify(closes, volumes)` → bullish/bearish/neutral + score. Version 2: enter score ≥ 0.25 and t ≥ 1.96, hold ≥ 0.15 / t ≥ 1.0 for 10 bars, whole window, ramp-weighted. `trend_v1.py` is the frozen research copy. |
| `onset.py` | **The shared "since when" walk.** One window, one label, one answer to *when did this turn?* |
| `recent.py` | **The combined "recently bullish assets" table** — US stocks, Philippine stocks, crypto, US Treasury futures, Philippine bond yields, Philippine funds, each dated. |
| `rates.py` | **The US Treasury futures curve** — the contracts, their search rows and synonyms, the bare-ticker chart alias, and the quote precision. |
| `phfunds.py` | **The 47 Philippine funds** — daily NAVPU from TOAP's UITF register, PIFA's NAV history and BPI Wealth's own fund pages — and the chart a fund row opens. |
| `tv.py` | The Philippine government bond yields — which TradingView symbols they are, and their daily bars. |
| `bullish.py` | The Philippine sweep: every PSE name that is bullish now, dated to the bar its run began on. |
| `pse.py` | PSE universe (TradingView scanner) and bars (TradingView chart socket, browser-backed) — `history_many` is the socket `tv.py` borrows. |
| `markets.py` | The two most-traded tables and the PSE board-lot table; `us_universe()` is the US universe for the recent table. |
| `crypto.py` / `cryptobull.py` | Coin identity (CoinGecko) and bars (Binance); the 24-hour most-traded crypto table. |
| `ecb.py` | ECB reference rates (via Frankfurter) for currency crosses Yahoo fabricates. |
| `coinsph.py` | Coins.ph USDC/PHP daily bars: the peso pair's Saturdays and Sundays. |
| `ondo.py` / `ondolist.py` | The Ondo token Yahoo cannot spell (OUSG) and its `ONDO:` chart; which assets app.ondo.finance lists, the shelf both tables scan. |
| `us_bars.py` | The stored year of US daily bars: the month-over-year merge and the closed-market check. |
| `faults.py` | `note(where, exc)`: quiet failures said once on the console. |
| `market_days.py` | NYSE and PSE holidays; only the sweep paces read them. |
| `diskcache.py` | Durable on-disk copy of every upstream answer under `.cache/`. |
| `index.html` + `static/` | The frontend: markup, then `app.css` and the plain scripts. |

## Invariants — do not break these

1. **One definition of "bullish".** It is `trend.classify` on the window the chart
   draws (90 days / ~63 daily bars). There is no second classifier. A table row
   and the chart its click opens must be the same series and the same verdict.
   The chart's newest bar carries the extended-hours price where the source has
   one, patched in `yahoo_bars` so the badge and the row both score it. The chart
   also re-reads itself every 15 minutes (`CHART_TTL` in `index.html`).
2. **One definition of "since when".** It is `onset.py`. `bullish.py` and
   `recent.py` both ask it there. Two copies of the walk are two answers that
   disagree at the edges — that is exactly why `onset.py` was extracted.
3. **A missing fetch is not a negative verdict.** A ticker that did not answer is
   counted as missing and left out; treating an outage as "not bullish" would put
   an outage in the table as a fact about the stock.
4. **A run that reaches past the fetched history is `censored`** — "bullish for at
   least this long" — never dated to the oldest bar fetched.
5. **A run is measured in bars, not days.**
6. **Never report git state.** Say which files are on disk and what the user must
   do; commits are not part of the conversation.

## Recently bullish assets (built 2026-10-29)

**One table across six markets** — US stocks, Philippine stocks, crypto, the US
Treasury futures, the Philippine government bond yields and the Philippine funds —
every row dated to the day its current run began, sorted **newest-turn first**.

- `recent.py` builds it, `server.py` sweeps it, `/api/recent` serves it,
  `index.html` draws it in `<section class="leaders recent">`.
- Columns: **Market · Asset · Direction · Since · Run · Price**.
- The note line above the table is built server-side by `recent.summarize(payload)`
  and shipped as `payload["note"]` — so the note and the rows cannot disagree
  about what was scanned.

### How each market's bars are obtained

| Market | Source | Note |
|---|---|---|
| US stocks | Yahoo daily bars **through Moli** | `server.fetch_us_bars()`, `RECENT_BATCH = 20` per browser run, the Ondo shelf (474 names, 24 runs, ~22–28 s), judged on one year of bars. The year is stored (`us_bars.py`); see below. Plain HTTP clients get a 429 — never replace Moli with `curl`/`urllib` here. |
| Philippine stocks | the existing bullish sweep's rows | Reused from the sweep `server.py` already keeps warm (`bullish_state().get("rows")`). **No second sweep** — re-sweeping would make this table fresher than the sweep it is built from. |
| Crypto | Binance daily bars | `crypto.try_chart`, `CRYPTO_LIMIT = 25`, `CRYPTO_WORKERS = 8`. Plain HTTPS to Binance works. |
| Philippine bonds | TradingView chart socket | `TVC:PH02Y`, `TVC:PH05Y`, `TVC:PH10Y` via `tv.py` → `pse.history_many`. |
| US Treasury futures | Yahoo daily bars, same Moli path | `rates.CONTRACTS` — the seven contracts (ZT…UB), a fixed list rather than a ranking. A second `fetch_us_bars` call for 7 symbols. |
| Philippine funds | `phfunds.py`, plain HTTPS | 47 funds with no ticker: TOAP `uitf.com.ph` (`bank_id=3`), PIFA's NAV history, BPI Wealth's graph model for the four PERA funds. **No browser.** |

`recent.scan` takes `fetch_us_bars` as an **injected callable** (the browser lives
in `server.py`, which imports `recent.py`) — that keeps the module testable
without a browser. Full sweep ≈ 47 s (measured 2026-11-16); the US leg is about half.

### Stored US year, and the closed-market pace (2026-11-16)

- `us_bars.py` keeps each name's year of bars (one disk record,
  `recent:usbars:v1`, ~3.4 MB). A sweep asks Yahoo for `1mo` and
  `us_bars.merge` lays it over the stored year **by exchange day**; the full
  `1y` is asked once a day, or at once when the overlap's closes differ, a day
  is missing, or fewer than 3 stored bars are confirmed. Bars are stored, never
  rows: the walk re-runs every sweep.
- This saves **download (~7x), not time**: a browser run costs ~1 s whatever
  the span. A failed month is still an outage (Nasdaq fallback or missing) —
  stored bars are never served in place of an answer that did not come.
- While New York is closed (outside 04:00–20:00 weekdays), a name read 15 min
  or more after the close is re-read **hourly**, not every sweep
  (`us_bars.settled`). Futures (`=F`) are always read.
- The Philippine sweep waits `bullish_pause()`: `BULL_TTL` from the bell to 20
  min past the close, else hourly (never past the next 9:30).
- Holidays (`market_days.py`, 2026-11-18) only slow these two paces. NYSE by
  fixed rules (tested against nyse.com 2026–28); PSE from TradingView's
  `session_holidays`, saved from any PSE socket read. An unlisted day reads open.
- `diskcache.prune` deletes `<hash> 2.json` duplicates (Finder/sync copies).
- `run_tests.py` points `APD_CACHE_DIR` at a temp folder; tests that call
  `fetch_us_bars` start with `us_bars.reset()`.

### The PSEi, and the scan's makeup in both notes (2026-11-09)

- **The PSEi is scanned with the stocks.** `bullish._universe` no longer drops
  `kind == "INDEX"`; the index goes through the same `onset` walk, so it appears
  on the recent table or the leaning one whenever its own chart says so. Its
  rows carry **no board lot, no minimum investment, no turnover** (an index is
  not bought and trades no shares); `pse.chart` withholds the "Min. investment"
  readout for `type == "index"` in both chart builders. `PSE:PSEI` opens the
  page's own chart.
- **Both notes print what was scanned.** `bullish.scan` ships
  `payload["kinds"]` (`{EQUITY, PREFERRED, ETF, CLOSEDEND, INDEX}` counts over
  its universe); `server.recent_loop` passes the sweep's `universe`/`kinds` into
  `recent.scan(ph_sweep_stats=...)`; `recent.kinds_line` writes
  "249 common shares, 11 preferred shares, 1 ETF, 1 closed-end fund, 1 index".
  `recent.summarize` puts it in the recent note, and the identical sentence
  ships as `payload["phScan"]` for the leaning note (`drawLeaningNote`). One
  string, so the two notes cannot disagree. An older disk copy has no `kinds`;
  the note then drops the makeup rather than guessing it.
- Counts drift with listings: 262 scanner securities on 2026-11-09, plus the
  index added by hand = 263 scanned.

### Philippine funds (2026-10-31)

A fund has no ticker, no exchange and no volume; it publishes one **NAVPU** a
business day, which is a daily close, so the classifier reads it like any price.
The row and the chart are one series: both go through `phfunds.series(code)`.

- The raw series is **calendar-padded** (weekends repeat Friday, BPI's model
  repeats stamps and stamps a day or two ahead). `phfunds.clean` keeps business
  days only — never read raw points.
- A **money market fund is always bullish** (its NAVPU only accrues). Six of the
  47 are money-market/short-term funds; that is not a classifier bug.
- Cold pass ~35 s (PIFA dominates; it refuses parallel reads), warm pass <5 s.
  Six-hour cache, one-week fallback, `stale` seconds on the row.
- `FUND:<CODE>` symbols route in `server.chart_data` before Yahoo; the warmer has
  its own leg (`_warm_batch_funds`). Fund turnover is `null` (exempt from the
  peso-volume floor).

### US Treasury futures (2026-10-31)

The rate market, added because it was **missing** rather than new: `ZB=F` was
always chartable, but the US leg is a turnover ranking (`common`/`etf` typespecs)
that cannot name a futures contract, and search could not answer "30-year
treasury bond" or "long bond" (Korean ETFs and KB funds came back instead).

- `rates.CONTRACTS` is the curve as a **fixed list**: ZT, Z3N, ZF, ZN, TN, ZB, UB.
- **A future is a price** — nothing is inverted (unlike the bond yields). Only a
  bullish contract is a row.
- `recent.rate_rows(fetch_us_bars)` judges them on Yahoo's daily bars with
  `months=` (Yahoo's 3mo window, like the US leg), a second call for 7 symbols.
  `turnover: None` (a contract's volume is a count, not money) and
  `rates.price_hint` for the 32nds.
- Search: `rates.search_contracts` adds Yahoo-shaped rows; `named_contracts`
  leads with the contract a query *names* (ticker, tenor, "long bond"), and the
  bare word "treasury" only fills in the curve behind Yahoo's answer.
- `rates.chart_alias` makes a bare `ZB` chart `ZB=F` — retried **only after**
  Yahoo refuses the bare spelling (`UB` is a real ETF and keeps its chart).

### Bond yields read the other way, and say so

The classifier reads the yield, but direction and score are inverted to reflect
the usual price movement of an existing fixed-rate bond:

- A **rising** yield → `Bearish (yield rising)`.
- A **falling** yield → `Bullish (yield falling)`.
- A neutral yield → `Neutral (yield flat)`.
- The date and run track the underlying yield trend. The price direction is
  inferred from yield, not measured from a bond-price chart.
- Bond rows follow the same rule as every other market: only a falling yield is
  a row (changed 2026-10-31 — a rising yield is a falling bond price, and a flat
  one has no run to date).
- Bond rows open a chart (since 2026-10-31): `tv.chart` draws the same yield
  series the row was judged on, with the badge reversed to the bond price.

### The bond socket: browser, not a raw websocket

The TradingView chart protocol *can* be driven by a plain TLS socket — that was
tried first and the code was correct (handshake, session, symbol resolution,
series request, `timescale_update` all arrived). The protocol **drops most of the
sessions it accepts**: a session is told `series_loading` and the series never
comes, a coin flip per attempt, worse for `TVC:PH05Y`, and bursty. Retrying hard
enough to win took ~40 s for three symbols with one often missing.

Driving the same protocol from the browser (`pse.history_many`) is reliable:
all three tenors in ~1.1 s. `tv.py` is thin: it owns the bond symbols and
borrows `pse.py`'s socket.

### Bond cache, and the two ages

`diskcache` under `tv:bond:<symbol>`:
- `BOND_CACHE_TTL = 6h` — fresh enough to **skip the fetch** (a yield is a daily
  close, so a copy a few hours old has missed at most one bar).
- `BOND_CACHE_KEEP = 7d` — still worth **showing** when the fetch failed; the row
  then carries `stale` (seconds) and says how old the reading is.

### Time zones

Bond bars are stamped at Manila 05:00 (= 21:00 UTC of the prior day), so bond rows
carry `"tz": "Asia/Manila"` and the front end reads their dates in that zone via
`rowDate()`. Every other row stays UTC. Do not "fix" this by shifting timestamps in
the data — the timezone belongs on the row.

### The sweep is a background job, not a route

- `RECENT_KEY = "recent:scan"` on disk, `RECENT_TTL = 900` s.
- `recent_loop()` runs on the refresh thread; `recent_state()` never blocks and the
  payload is **replaced wholesale**, never mutated, so a reader cannot see it change
  mid-render.
- The row warmer (`warm_rows_loop`) reads the recent table too, through
  `due_rows(..., recent=...)`, so a row it lists stays retrievable offline like any
  other table's row. Bond charts are warmed too (`_warm_batch_bonds`).
- **The sweeps keep running with no page open, on purpose** (user rule
  2026-11-16: "there is a reason that's there"). Do not pause, slow or gate
  them on page activity, and do not propose it.
- `seed_recent()` hydrates from disk at startup, so an offline start still has rows
  (the note then reads "— source offline").
- A failed refresh leaves the previous rows on screen with the failure in the note;
  it never clears the table. Same contract as the Philippine sweep.
- The front end polls at the same 900 s (`RECENT_TTL` in `index.html`) — polling
  faster than the sweep runs just re-renders the same payload.

## Data-source gotchas (hard-won — re-read before changing any fetch)

- **Yahoo** → Moli only. `curl`/`urllib` → HTTP 429. `server.moli_get` /
  `moli_batch_get` keep the true status code by calling the API from inside a
  Yahoo-origin page.
- **TradingView bond symbols need the zero padding**: `TVC:PH02Y`, `TVC:PH05Y`,
  `TVC:PH10Y`. `TVC:PH5Y` is not the instrument.
- **Binance** → plain HTTPS is fine (`data-api.binance.vision` mirror).
- **ECB** → Frankfurter API, no key.
- **Philippine listings** are not on Yahoo at all — they come from the TradingView
  scanner and the chart socket.
- **Philippine funds** are on neither — three plain-HTTPS registries
  (`phfunds.py`), and their raw series is calendar-padded. PIFA also closes the
  connection when several of its ~2 MB pages are read at once.

## Verifying a change

```sh
# 1. restart the server, then:
curl -s http://127.0.0.1:8000/api/recent | python3 -m json.tool | head -40
# expect 45 rows, errors {}, and the three bond tenors with stale=0

# 2. front end: syntax check and a live DOM read
node --check <extracted js>
export PATH="$HOME/.local/bin:$PATH"
moli fetch --eval-file /tmp/eval-recent.js --wait domstable "http://127.0.0.1:8000/"
```

The Moli `--eval-file` route (not `--dump`) is how the rendered table is verified:
it returns the live headings, row count and the bond rows' text. A full-page
screenshot (`moli fetch --layout --dump screenshot_full`) confirms the layout; note
that `--dump` and `--eval` cannot be combined in one call, so scroll-and-shoot
needs two passes.
