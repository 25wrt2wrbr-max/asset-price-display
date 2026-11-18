# Notes

[Back to the README](../README.md)

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
  [above](philippine-stocks.md#why-it-is-held-warm-by-a-background-thread)).
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
- **A neutral row can lean** (added 2026-11-06) — a row whose window is Neutral
  but sits inside one side's hold band shows `leaning bullish` or
  `leaning bearish` in place of the plain `Neutral` tag, in a lighter green or
  red with a dashed border. The number behind it is the same payload's
  `trend.lean`, which `trend.classify` has returned since the leaning table
  shipped, so the tag and the chart's "Neutral · leaning bullish" badge are one
  call on one set of bars; the label itself stays Neutral, and the tooltip says
  how far along the band the window sits. Only rows that need the extra width
  wrap it onto a second line — see the working notes.
- **Yahoo "no data" arrives as HTTP 404** with a `chart.error` object, so the
  server treats only 5xx as a transport failure. The message is surfaced on the
  page instead of a traceback.
- **The trend badge is an annotation, not the product.** If `trend.py` cannot
  score a series, the chart still draws.
- **Localhost only.** The server binds `127.0.0.1` and has no authentication.
