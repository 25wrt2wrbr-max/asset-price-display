# Trend Badge

The public page for [Trend Badge](https://juniverse8031.gumroad.com/l/trend-badge): a
single-file web component that puts a three-month price line and a Bullish, Bearish or
Neutral badge on any website. You supply the prices.

This repository is only the landing page. The widget itself is a paid product and is
not included here. The example cards on the page are drawn from made-up prices.

- One 42 KB JavaScript file, no dependencies, no build step.
- Reads JSON, CSV, a plain list of numbers, or data passed in from JavaScript.
- Light and dark mode, your own colours, font and corner radius.
- One-time $15.20, unlimited websites of your own and client sites.

Not investment advice. The badge describes prices that already happened; it is not a
forecast.

## Run the page locally

```sh
python3 -m http.server 8123
```

Then open http://127.0.0.1:8123/ . There is nothing to build and nothing to install.
`widget/promo_build.py` in the private project regenerates this folder from
`widget/store/landing.html`.
