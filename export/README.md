# Exported algorithm

The price-trend algorithm from the local project, packaged so it can be dropped
onto a hosted website.

| File | What it is |
|---|---|
| **`trend.js`** | **The algorithm.** Standalone JavaScript, no dependencies, no build step. A faithful port of the project's `trend.py` (the classifier) and `onset.py` (the "since when" walk). |
| `demo.html` | A tiny page that loads `trend.js` and classifies pasted closes — a working starting point for a hosted site. |
| `verify_parity.py` | The test that proves the JavaScript and the Python original agree, number for number. |

## Using it

As a plain script tag (exposes a global `Trend`):

```html
<script src="trend.js"></script>
<script>
  const { classify, onset } = Trend;
  const v = classify(closes, volumes);
  // { label: "bullish", score: 0.61, confidence: "strong", bars: 63, components: {...} }
</script>
```

Or as a module:

```js
import { classify, onset } from "./trend.js";
```

### API

- `classify(closes, volumes?)` → `{ label, score, confidence, bars, components }`.
  `closes` is oldest-first. `volumes` is accepted for compatibility but does
  not vote. Throws on an empty series or a non-positive price.
- `onset(stamps, closes, volumes?, want = "bullish", now?, months?)` → when the
  current run of like labels began: `{ since, run, censored, anchored, score,
  bars, last, price, turnover, window }`, or `null` when that run is not
  running. `stamps` are unix timestamps in seconds, oldest-first.
  `months` asks for a calendar-months window (Yahoo's own `range=3mo` rule)
  instead of the ninety-day one — the window a US listing's chart draws.
- `current(stamps, closes, volumes?, now?, months?)` → the verdict on the latest bar.
- `windowNow(stamps, end, now?, months?)`, `windowAt(stamps, end, months?)` → the
  bar indices of the window the chart would draw.
- `monthsBack(ts, months)` → the UTC midnight of the day `months` calendar
  months before `ts`'s day.
- `Trend.constants` → the thresholds and weight tables, if a page wants to
  show them.

## The algorithm in one paragraph

One score in `[-1, +1]`. At every window length the blend is the
ensemble: 0.40 vol-normalized momentum, 0.25 OLS slope × R², 0.20 Kaufman
efficiency ratio, 0.15 close's position in the window range. Below 50 bars the score is
damped by `sqrt(n / 50)`. A signal that cannot be computed is dropped and its
weight shared out. `|score| ≥ 0.25` is a directional call; confidence is
`strong` at `≥ 0.45`. This strength is not a probability. Short-window and
Philippine-stock performance have not been validated; this is not a forecast.

The full rationale, the backtest findings and the caveats are in the header
comment of `trend.js`.

## Verifying it still matches

```sh
python3 export/verify_parity.py
# 403 classify cases, 403 onset cases, 403 calendar-month onset cases, 0 mismatches
```

The test builds random series (up, down, flat, chop, tie-heavy, spiky;
lengths 3 to 250; with and without volume), runs both the Python original and
the JavaScript port on each, and compares label, score, confidence, bar count
and every component. The calendar-month cases run the same walk over Yahoo's
three-months window, so the month arithmetic is checked too.

## Note on data for a hosted site

The classifier itself needs nothing but the numbers. Fetching them is a
separate problem: Yahoo Finance answers plain browser-side `fetch` calls with
HTTP 429 and CORS errors, so a static hosted page will need either a small
serverless proxy in front of Yahoo (or Binance / TradingView, which are
CORS-friendlier) or a data API with an open CORS policy. The local project
solves this by routing Yahoo through a real browser (Moli); that part is not
part of the algorithm and is not part of this export.
