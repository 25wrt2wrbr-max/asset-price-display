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

**Changes since your last visit** compares each watchlist badge with its last
successful reading in this browser. The first visit sets the baseline. A failed
request or an offline copy never counts as a change. Neutral charts explain
why the readings did not confirm a trend.

To **compare two assets**, open the first chart and enter the second symbol in
the comparison form below it. Both lines start at 100 on their first shared
trading date. A value of 105 means that series rose 5% from its own starting
value. Only dates present in both series appear; the table lists each pair.

Three things Yahoo cannot serve at all are charted from elsewhere: coins Yahoo
gets *wrong* (the ticker collision under
[Crypto that Yahoo gets wrong](docs/crypto-sources.md#crypto-that-yahoo-gets-wrong)) come from
Binance, Philippine Stock Exchange listings (Yahoo carries none of them —
see [Philippine stocks](docs/philippine-stocks.md#philippine-stocks-yahoo-carries-none-of)) come from
TradingView, and currency crosses with no dollar leg (`EURPHP=X`, `EURJPY=X` —
see [Currency crosses Yahoo fabricates](docs/currency-crosses.md#currency-crosses-yahoo-fabricates))
get their history from ECB reference rates. The chart's meta line always names
the source it used. One instrument Yahoo has no spelling for at all — `OUSG`,
Ondo's short-term Treasury fund token — is priced from its on-chain market
instead (see [A token Yahoo has no spelling for](docs/currency-crosses.md#a-token-yahoo-has-no-spelling-for-2026-11-02)).

Below the chart: [Recently bullish assets](docs/recently-bullish.md#recently-bullish-assets), one
table across every market the page follows — US stocks and ETFs on the Ondo
shelf, Ondo's intelligent portfolios, Philippine stocks, crypto, the US
Treasury futures, the Philippine government bond yields and the Philippine
funds — every row dated to the day its run began, newest turn first. It
absorbed the two tables that used to sit beside it, "Most traded crypto — 24
hours" and "Bullish Philippine stocks" (2026-11-07), because both were narrow
views of the same scan.

![stack](https://img.shields.io/badge/deps-none-brightgreen) Python 3 stdlib on
the server, vanilla JS in the page — no `pip install`, no `npm install`, no
build step.

## Run it

From inside the project folder:

```sh
cd asset-price-display     # wherever you put it
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

Run every test, and the check that `export/trend.js` agrees with `trend.py`:

```sh
python3 run_tests.py                    # everything
python3 run_tests.py "test_trend*.py"   # only matching files
python3 check_publish.py [--history]   # before publishing: scan for the account name
```

## Requirements

| | |
|---|---|
| **Python** | 3.8 or newer. Nothing to install. |
| **Moli** | Required for Yahoo price data, the PSE histories and the bond yields. Not needed for crypto (Binance, Kraken), currency fixes (ECB) or the Philippine funds — their registries answer plain HTTPS. Already at `~/.local/bin/moli` (v1.1.10) on this machine. |

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

To install Moli, see `~/.claude/skills/moli-webfetch/SKILL.md`.

## Files

| File | Role |
|---|---|
| `server.py` | The core: caches, the Yahoo proxy, the first-paint warm-up and the chart route (`chart_data`). Imports the parts below and re-exports their names, so `server.<name>` still works. |
| `sweeps.py` | The two background sweeps and their state: the Philippine bullish sweep and the recent table. |
| `yahoo_chart.py` | Yahoo's answer turned into the page's chart: bars, sessions, the live print, and the check for a coin Yahoo gets wrong. |
| `fx_charts.py` | Currency charts Yahoo cannot be trusted with: the ECB crosses and the peso's weekend proxy. |
| `search_rank.py` | Search helpers: ranking, the extra currency rows, the ticker probe. |
| `faults.py` | `note(where, exc)`: a failure the code carries on past is printed once on the console (then at most every ten minutes, with a count) instead of swallowed. |
| `http_handler.py` | The HTTP handler and `main`. Routes: `/api/chart`, `/api/search`, `/api/top`, `/api/bullish`, `/api/cryptobull`, `/api/recent`, `/api/health`, and `POST /api/watch`. Serves only `index.html`, `jpy-php.html` and `static/` — not the source or the cache. |
| `moli_client.py` | The Moli browser client (`moli_get`, `moli_batch_get`, …) and `health`, what the last browser run did. |
| `warm.py` | The row warmer: keeps every table row's chart fetched so it opens offline. |
| `netwatch.py` | Notices a dropped and restored connection and re-reads what went stale. |
| `watchlist.py` | The watchlist the page declares, kept for the warmers. |
| `quality.py` | Data-quality checks on a daily series (gap, jump, frozen run, missing volume…). They flag; they never change a label. |
| `nasdaq_bars.py` | The fallback source for US daily closes (Nasdaq's public quote API, plain HTTPS) when Yahoo or Moli does not answer. |
| `labpath.py` | Puts `lab/` on `sys.path` so the app can import the research modules kept there. |
| `run_tests.py` | One command for every test plus the JS/Python parity check. |
| `check_publish.py` | Scans for the machine's account name before anything is published. |
| `markets.py` | The two most-traded tables (TradingView scanner) and the PSE board-lot table. The tables are still built and served at `/api/top`, but no longer drawn on the page (removed 2026-11-07 at the reader's request). |
| `crypto.py` | Coin identity (CoinGecko) and bars (Binance, or Kraken for a coin Binance has delisted) for coins Yahoo gets wrong. |
| `cryptobull.py` | The most-traded crypto of the last 24 hours, filtered to the bullish ones. |
| `ecb.py` | ECB daily reference rates (via the Frankfurter API, no key) for currency crosses Yahoo fabricates — the honest history for pairs with no dollar leg. |
| `coinsph.py` | Coins.ph's USDC/PHP daily bars — the peso pair's Saturdays and Sundays, the two days the FX week does not trade. |
| `ondo.py` | The Ondo tokens Yahoo has no spelling for — OUSG, the short-term Treasury fund token: its on-chain identity, the DeFiLlama price series, the `ONDO:` chart route and the search rows that make it findable. |
| `pse.py` | PSE universe (TradingView scanner) and bars (the browser-backed TradingView chart socket) for Philippine listings Yahoo does not carry — and the socket `tv.py` borrows for the bond yields. |
| `bullish.py` | Every PSE stock that is bullish now, each dated to the bar its run began on. |
| `onset.py` | The shared "since when" walk — one window, one label, one answer to *when did this turn?* — plus `turn`, which says *why* (`turn` / `flat` / `against`). |
| `recent_rows.py`, `recent_note.py` | Split out of `recent.py` and re-exported from it: the rows, one function per market, and the status and note lines. |
| `recent.py` | The combined "recently bullish assets" table: US stocks, Philippine stocks, crypto, the US Treasury futures, the Philippine bond yields and the Philippine funds, each dated. |
| `rates.py` | The US Treasury futures curve — the seven contracts (ZT through UB), the search rows that make each one findable by ticker, tenor or desk name, and the bare-ticker chart alias. |
| `phfunds.py` | The Philippine funds (BPI Wealth UITFs, ALFM and Odyssey funds, the PERA funds): their daily NAVPU series, read from the registry that publishes each one, and the chart a fund row opens. |
| `tv.py` | The Philippine government bond yields — which TradingView symbols they are, their daily bars, and the chart a bond row opens. |
| `trend.py` | Classifies a price series as bullish / bearish / neutral. Stdlib math only. |
| `diskcache.py` | Durable on-disk copy of every upstream answer under `.cache/`, so a dead wire serves the last good result instead of an empty table. |
| `index.html` | The page's markup. |
| `static/` | The page's code: `app.css`, and the scripts `core.js` (state, formatting, loading), `page.js` (suggestions, readouts), `chart.js` (trend badge, chart), `watchlist.js`, `events.js`, `tables.js` (recent and leaning tables, with sorting, filtering and per-market status), `main.js` (start-up and timers). Plain scripts loaded in that order; no build step. |
| `lab/` | The forecast-research modules (`*_research.py`, `forecast_*`, `research_judgment.py`, …). Their data is in `research/`. Run one as `python3 lab/<name>.py`. |
| `tests/` | Every `test_*.py`. |
| `research/` | Data and reports the research modules read and write (not code). The two large market histories are kept gzipped (`*.json.gz`); `lab/bigjson.py` reads and writes them. |
| `docs/` | The full reference, one page per topic (see [More detail](#more-detail)), and `agent-notes-history.md`, the older dated agent notes. |
| `jpy-php.html` | Standalone single-page chart for one currency cross (`JPY→PHP`), separate from the main app. |
| `CLAUDE.md` | Working notes for an agent: the invariants that must not drift, where each market's bars come from, and how to verify a change. |
| `AGENTS.md` | A link to `CLAUDE.md`: one file, two names, for a non-Claude agent. |

## More detail

The full reference is in `docs/`, one page per topic:

- [The chart on screen](docs/chart.md) — what the chart draws, the live price, the newest bar and how it refreshes
- [Crypto that Yahoo gets wrong](docs/crypto-sources.md) — coins whose Yahoo ticker is a different coin, and where their bars come from
- [Currency crosses](docs/currency-crosses.md) — ECB reference rates for crosses with no dollar leg, and the peso's weekend
- [Philippine stocks](docs/philippine-stocks.md) — the PSE source and the bullish sweep
- [The most-traded tables](docs/most-traded.md) — the US and Philippine turnover tables and the 24-hour crypto table
- [Recently bullish assets](docs/recently-bullish.md) — the one table across every market, and each market's rules
- [How the trend call works](docs/trend-call.md) — how a chart is labelled bullish, bearish or neutral
- [Notes](docs/notes.md) — everything else
