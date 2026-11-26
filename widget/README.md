# Trend Badge

Trend Badge is a small widget for websites. It draws a three-month price line
and a **Bullish**, **Bearish** or **Neutral** badge from prices you give it.

- One file, `trend-widget.js`. No other libraries and no build step.
- You supply the prices: a JSON or CSV file on your own site, a list of
  numbers, or data passed in from JavaScript.
- It works in light mode and dark mode, on phones, and with your own colours.
- It runs in the visitor's browser and sends nothing anywhere.

Open `demo.html` to see it working. Your browser may block the demo's
example files when you open the page straight from disk. If it does, run
`python3 -m http.server` in this folder and open http://127.0.0.1:8000/demo.html.

## Quick start

```html
<script src="trend-widget.js"></script>

<trend-badge name="ACME" src="/prices/acme.json" currency="USD"></trend-badge>
```

Prices can also go straight into the tag, oldest first:

```html
<trend-badge name="ACME" closes="101.2, 102.0, 103.5, 102.9, 104.1, ..."></trend-badge>
```

## What the badge means

The badge looks at the shape of the most recent 63 prices (about three
months of trading days):

- **Bullish**: prices have climbed steadily, and the climb is too large and
  too consistent to be random noise.
- **Bearish**: the same, going down.
- **Neutral**: there is no clear direction. **This is the most common
  result.** The test is strict on purpose, so a choppy chart reads Neutral.
- A short note can follow the label: "pulling back" (bullish, but the last
  two weeks fell), "bouncing" (bearish, but the last two weeks rose), or
  "leaning bullish / bearish" (neutral, but close to a label).

The badge describes what the prices already did. **It is not a forecast and
not investment advice.** Each card prints a short line saying so. If you hide
that line (`note="off"`), please make the same point somewhere on your page.

The same prices always give the same badge.

## Price formats

`src` (a file) and `.data` (from JavaScript) accept any of these:

```js
[101.2, 102.0, 103.5]                                   // prices, oldest first
[["2026-08-25", 101.2], ["2026-08-26", 102.0]]          // [date, price] pairs
[{ "date": "2026-08-25", "close": 101.2 }, ...]         // objects
{ "dates": ["2026-08-25", ...], "closes": [101.2, ...] } // two lists
```

A CSV file works too, with or without a header row:

```
date,close
2026-08-25,101.2
2026-08-26,102.0
```

With a header row, the price is taken from the `close` column (or
`adj close`, `price`, `value`, `nav`) and the date from the `date` column.
Without one, a single column is read as prices, and two columns as date then
price.

- Dates can be `YYYY-MM-DD` text or unix times (in seconds or milliseconds).
- A newest-first file is turned around automatically.
- Rows with a missing, zero or negative price are skipped.
- Use one price per trading day (daily closes). The badge is tuned for daily
  prices.

## Options

| Attribute | What it does | Default |
|---|---|---|
| `src` | Address of a JSON or CSV price file | — |
| `closes` | Prices written into the tag, oldest first | — |
| `dates` | Dates matching `closes`, same order | — |
| `name` | Title shown on the card | none |
| `currency` | Currency code, e.g. `USD`, `EUR`, `PHP` | plain number |
| `locale` | Number and date style, e.g. `en-US`, `de-DE` | the visitor's |
| `bars` | How many recent prices to judge, or `all` | `63` |
| `layout` | `card` (line and badge) or `badge` (small badge only) | `card` |
| `theme` | `light`, `dark`, or leave it out to follow the visitor | follows visitor |
| `note` | `off` hides the line under the chart | shown |
| `refresh` | Re-read `src` every this many seconds (30 or more) | off |

If a file fails to load, the card says "Prices could not be loaded". A
failed load is never shown as Neutral.

## Colours and font

Set any of these CSS variables on `trend-badge` or on a parent element:

```css
trend-badge {
  --trend-up: #157a43;      /* bullish colour */
  --trend-down: #c0392b;    /* bearish colour */
  --trend-flat: #5f6873;    /* neutral colour */
  --trend-bg: #ffffff;      /* card background */
  --trend-fg: #1d2330;      /* main text */
  --trend-muted: #5f6873;   /* small text */
  --trend-border: #dfe3e8;
  --trend-radius: 12px;
  --trend-font: system-ui, sans-serif;
}
```

You can also style the parts of the card directly with `::part()`. The parts
are `card`, `name`, `badge`, `price`, `change` and `note`:

```css
trend-badge::part(badge) { text-transform: uppercase; }
```

## JavaScript

```js
// Put a widget into a page element.
const el = TrendWidget.mount("#slot", prices, { name: "ACME", currency: "USD" });

// Change the data later.
el.data = newPrices;

// Listen for the result.
el.addEventListener("trend", (e) => {
  console.log(e.detail.label);  // "bullish", "bearish" or "neutral"
  console.log(e.detail.words);  // "Bullish, pulling back"
});
el.addEventListener("trenderror", (e) => console.warn(e.detail.error));

// Score prices without drawing anything.
const v = TrendWidget.judge(prices);         // v.label, v.words, v.change, v.bars
const w = TrendWidget.judge(prices, { bars: "all" });
```

`el.verdict` holds the latest result, and `el.reload()` reads `src` again.
Each widget also gets a `data-label` attribute (`bullish`, `bearish` or
`neutral`), so your own CSS can react to it.

For the full numbers behind a badge, use `Trend.classify(closes)`. It returns
the score, the four signals and the confidence.

## Browser support

The widget works in current Chrome, Edge, Safari and Firefox, on desktop and
mobile. It uses standard Web Components and needs no polyfills.

## Where to get prices

This package contains no market data. Use a price source whose terms allow
you to show its prices on your site, for example a paid data provider, your
broker's export, or your own fund's published daily prices.
