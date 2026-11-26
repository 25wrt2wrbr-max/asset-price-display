# Gumroad listing: Trend Badge

Copy each part into the matching box on Gumroad's product page.
This file is for you. It is not in the zip that buyers download.

---

## Name

Trend Badge: a bullish / bearish price widget for any website

## Product type

Digital product

## Price

$15.20 (Gumroad's fee is shown on its pricing page. Check it before you publish.)

## Summary (the short line under the title)

Add one script tag and show a three-month price line with a Bullish, Bearish or Neutral badge. You supply the prices.

## Description

Trend Badge puts a clean price card on your website: the last three months of prices, the latest price, the change, and a clear **Bullish**, **Bearish** or **Neutral** badge.

**One line to add it**

```
<script src="trend-widget.js"></script>
<trend-badge name="ACME" src="/prices/acme.json" currency="USD"></trend-badge>
```

**What you get**

- A card with a price line, the latest price and the change over three months
- A small badge that fits inside a sentence
- A price and date readout when visitors hover over or touch the line
- Light and dark mode, which follows the visitor's setting automatically
- Your own colours, font and corner radius through simple CSS settings
- Any currency and number style (USD, EUR, PHP and more)
- Reads JSON, CSV, a plain list of numbers, or data passed in from JavaScript
- A JavaScript event with the result, so your page can react to it
- An optional auto-refresh that re-reads your price file

**How the badge decides**

It scores the shape of the last 63 daily prices: how steady the move was, how straight, how efficient, and where the latest price sits in the range. A label needs a move that is too large and too steady to be random noise. Neutral is the most common result, on purpose. The same prices always give the same badge.

The badge describes what prices already did. It is not a forecast and not investment advice. Each card prints a short line saying so.

**Good for**

- Fund, ETF and stock pages on finance blogs
- Crypto project and community sites
- Client dashboards and investor update pages
- Newsletters with a web version

**What's in the zip**

- `trend-widget.js`: the widget, one file of about 42 KB with nothing else to install
- `demo.html`: a working demo page with made-up prices
- `README.md`: the full guide, with every option and price format
- `LICENSE.txt`: use it on unlimited sites of your own and for your clients

**Please note**

- No market data is included. Use prices you have the right to show: a paid data provider, your broker's export, or your own published prices.
- It needs one price per trading day (daily closes).
- It works in current Chrome, Edge, Safari and Firefox, on desktop and mobile.

## Call to action (button text)

I want this!

## Receipt / thank-you note

Thanks for buying Trend Badge! Unzip the file and open README.md to start. To see the demo, run `python3 -m http.server` in the unzipped folder and open http://127.0.0.1:8000/demo.html.

## Tags

stock widget, crypto widget, price chart, trend indicator, finance website, javascript widget, web component, bullish bearish

## Files

Upload: `widget/release/trend-badge-1.0.0.zip`

## Images

- Cover (1280 × 720): `widget/store/cover.png`
- Product image, Library and Discover (600 × 600): `widget/store/thumbnail-600.png`
- Profile picture (600 × 600): `widget/store/avatar-600.png`
- The 1200 × 1200 `thumbnail.png` and 1024 × 1024 `avatar.png` are the masters;
  `python3 widget/store/gumroad_images.py` makes the 600 × 600 copies.

Gumroad shows the product image and the profile picture as 600 × 600 squares, so
upload exactly those two. The cover stays wide.

## Landing page

Public page, free hosting: https://25wrt2wrbr-max.github.io/trend-badge/
Built from `widget/promo_build.py`; its buttons carry `utm_source=landing-*`.

## Promotion

Launch copy, listings and the $0 plan are in `~/Downloads/trend-badge-promo/`:
`plan.md`, `posts.md`, `article.md`, `outreach.md`.
