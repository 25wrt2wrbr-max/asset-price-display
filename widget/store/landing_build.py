#!/usr/bin/env python3
"""Build widget/store/landing.html, the Gumroad landing page.

    python3 widget/store/landing_build.py

The example cards are drawn as static SVG from the demo's made-up prices.
The widget code itself is never put on the page (the page source is public).
"""

import csv
import io
import json
import pathlib

STORE = pathlib.Path(__file__).resolve().parent
DATA = STORE.parent / "demo-data"
W, H, PAD = 320, 84, 4


def closes_rising():
    return [p["close"] for p in json.loads((DATA / "rising.json").read_text())]


def closes_falling():
    rows = list(csv.DictReader(io.StringIO((DATA / "falling.csv").read_text())))
    return [float(r["close"]) for r in reversed(rows)]  # file is newest first


def closes_sideways():
    return json.loads((DATA / "sideways.json").read_text())["closes"]


def points(closes):
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1
    n = len(closes)
    return [(round(i / (n - 1) * W, 1), round(PAD + (1 - (c - lo) / span) * (H - 2 * PAD), 1))
            for i, c in enumerate(closes)]


def card(name, closes, label, tone, symbol, extra_class=""):
    pts = points(closes)
    line = " ".join(f"{x},{y}" for x, y in pts)
    area = f"0,{H} {line} {W},{H}"
    last, first = closes[-1], closes[0]
    change = (last / first - 1) * 100
    sign = "+" if change > 0 else "−" if change < 0 else ""
    change_txt = f"{sign}{abs(change):.1f}% over {len(closes)} days"
    price = f"{symbol}{last:,.2f}"
    aria = f"{name}: {label}. Last price {price}, {change_txt}."
    return f"""
      <figure class="card {extra_class}" aria-label="{aria}">
        <div class="card-top"><span class="card-name">{name}</span><span class="pill {tone}">{label}</span></div>
        <div class="card-price"><span class="card-last">{price}</span><span class="card-chg">{change_txt}</span></div>
        <svg class="spark {tone}" viewBox="0 0 {W} {H}" preserveAspectRatio="none" aria-hidden="true">
          <polygon class="area" points="{area}"/>
          <polyline class="line" points="{line}"/>
        </svg>
        <figcaption class="card-note">Trend of the last {len(closes)} days. Describes the past, not a forecast.</figcaption>
      </figure>"""


CARDS = (card("Rising example", closes_rising(), "Bullish", "up", "$", "c1")
         + card("Falling example", closes_falling(), "Bearish", "down", "€", "c2")
         + card("Sideways example", closes_sideways(), "Neutral", "flat", "₱", "c3"))

LOGO = """<span class="logo" aria-hidden="true"><span class="logo-txt">JL</span><svg viewBox="0 0 64 64"><polyline points="14,50 22,47 28,49 36,43 42,45 50,38" fill="none" stroke="#4cc38a" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="50" cy="38" r="3.6" fill="#4cc38a"/></svg></span>"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<style>
  :root {
    --bg: #f6f7f9; --surface: #ffffff; --fg: #111827; --muted: #4b5563; --border: #e2e6eb;
    --code-bg: #0f172a; --code-fg: #cbd5e1; --code-hl: #7dd3a8;
    --up: #157a43; --down: #b42318; --flat: #4b5563;
    --accent: #ff90e8; --accent-fg: #111827; --hero: #0f172a; --hero-fg: #f1f5f9; --hero-muted: #c3cbd6;
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0b1017; --surface: #141b24; --fg: #e8ecf1; --muted: #a3adba; --border: #273140;
      --code-bg: #070b11; --up: #4cc38a; --down: #ff7a6b; --flat: #a3adba;
      --hero: #0a1220; color-scheme: dark;
    }
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  @media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 17px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  a { color: inherit; }
  .wrap { max-width: 1120px; margin: 0 auto; padding: 0 20px; }
  .skip { position: absolute; left: -999px; top: 8px; background: var(--surface); padding: 8px 12px; border-radius: 8px; }
  .skip:focus { left: 8px; z-index: 10; }
  :focus-visible { outline: 3px solid #60a5fa; outline-offset: 3px; border-radius: 6px; }

  /* Buttons */
  .buy {
    display: inline-flex; align-items: center; justify-content: center; gap: 10px;
    font: inherit; font-weight: 700; font-size: 17px; text-decoration: none; cursor: pointer;
    background: var(--accent); color: var(--accent-fg); border: 2px solid #111827; border-radius: 10px;
    padding: 13px 22px; box-shadow: 4px 4px 0 #111827; transition: transform .12s ease, box-shadow .12s ease;
  }
  .buy:hover { transform: translate(-2px, -2px); box-shadow: 6px 6px 0 #111827; }
  .buy:active { transform: translate(2px, 2px); box-shadow: 2px 2px 0 #111827; }
  .buy .price { font-variant-numeric: tabular-nums; padding-left: 10px; border-left: 2px solid rgba(17,24,39,.35); }
  .buy.small { font-size: 15px; padding: 8px 14px; box-shadow: 3px 3px 0 #111827; }

  /* Header */
  header.top { position: sticky; top: 0; z-index: 5; background: color-mix(in srgb, var(--hero) 92%, transparent);
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); color: var(--hero-fg);
    border-bottom: 1px solid rgba(255,255,255,.08); }
  header.top .wrap { display: flex; align-items: center; justify-content: space-between; gap: 12px; height: 64px; }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; text-decoration: none; }
  .logo { position: relative; width: 34px; height: 34px; border-radius: 9px; background: #0f172a; box-shadow: 0 0 0 1px rgba(255,255,255,.14); flex: none; }
  .logo svg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .logo-txt { position: absolute; left: 0; right: 0; top: 4px; text-align: center; font: 900 12px/1 "Arial Black", Arial, sans-serif; color: #f1f5f9; letter-spacing: -.5px; }
  .brand small { font-weight: 500; color: var(--hero-muted); }

  /* Hero */
  .hero { background: radial-gradient(1000px 520px at 85% 0%, #1e3a5f 0%, var(--hero) 62%); color: var(--hero-fg); padding: 72px 0 88px; overflow: hidden; }
  .hero .wrap { display: grid; grid-template-columns: 1.05fr 1fr; gap: 56px; align-items: center; }
  .kicker { color: #7dd3a8; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; font-size: 13px; margin: 0 0 14px; }
  .hero h1 { font-weight: 800; font-size: clamp(36px, 5.2vw, 60px); line-height: 1.04; letter-spacing: -.02em; margin: 0; }
  .hero .lede { font-size: clamp(18px, 2vw, 21px); color: var(--hero-muted); margin: 20px 0 30px; max-width: 34em; }
  .hero-cta { display: flex; flex-wrap: wrap; align-items: center; gap: 16px 22px; }
  .facts { list-style: none; padding: 0; margin: 26px 0 0; display: flex; flex-wrap: wrap; gap: 8px; }
  .facts li { font-size: 14px; font-weight: 600; padding: 6px 12px; border-radius: 999px; background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.16); }
  .rating { font-size: 15px; color: var(--hero-muted); }

  /* Cards (static pictures of the widget) */
  .stage { position: relative; min-height: 520px; }
  .card {
    position: absolute; width: min(360px, 88%); margin: 0; background: #fff; color: #1d2330;
    border: 1px solid #dfe3e8; border-radius: 14px; padding: 14px 16px 12px;
    box-shadow: 0 22px 48px rgba(0,0,0,.35); --up: #157a43; --down: #c0392b; --flat: #5f6873;
    animation: rise .7s cubic-bezier(.2,.7,.2,1) both;
  }
  .c1 { left: 0; top: 0; } .c2 { right: 0; top: 185px; animation-delay: .12s; } .c3 { left: 4%; top: 370px; animation-delay: .24s; }
  /* The two back cards are covered by the one in front; their note line would collide with it. */
  .c1 .card-note, .c2 .card-note { display: none; }
  .card-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .card-name { font-weight: 650; font-size: 15px; }
  .pill { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 650; line-height: 1;
    padding: 5px 10px; border-radius: 999px; border: 1px solid currentColor; }
  .pill::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
  .up { color: var(--up); } .down { color: var(--down); } .flat { color: var(--flat); }
  .card-price { margin-top: 8px; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
  .card-last { font-size: 22px; font-weight: 650; font-variant-numeric: tabular-nums; }
  .card-chg { font-size: 13px; color: #5f6873; }
  .spark { display: block; width: 100%; height: 76px; margin-top: 8px; }
  .spark .area { fill: currentColor; opacity: .11; }
  .spark .line { fill: none; stroke: currentColor; stroke-width: 2.2; vector-effect: non-scaling-stroke;
    stroke-linejoin: round; stroke-linecap: round; }
  .spark { clip-path: inset(0 100% 0 0); animation: draw 1.4s .35s ease-out forwards; }
  .card-note { margin-top: 8px; font-size: 11.5px; color: #5f6873; }
  @keyframes draw { to { clip-path: inset(0 0 0 0); } }
  @keyframes rise { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
  @media (prefers-reduced-motion: reduce) {
    .card { animation: none; } .spark { animation: none; clip-path: none; }
  }

  /* Sections */
  section.band { padding: 80px 0; }
  section.band.alt { background: var(--surface); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
  h2 { font-weight: 750; font-size: clamp(28px, 3.4vw, 38px); line-height: 1.15; letter-spacing: -.01em; margin: 0 0 14px; }
  .sub { color: var(--muted); margin: 0 0 36px; max-width: 42em; font-size: 18px; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 48px; align-items: start; }
  pre.code {
    margin: 0; background: var(--code-bg); color: var(--code-fg); border-radius: 14px; padding: 20px 22px;
    font: 14.5px/1.7 ui-monospace, Menlo, Consolas, monospace; overflow-x: auto; border: 1px solid #23324a;
  }
  pre.code b { color: var(--code-hl); font-weight: 500; }
  pre.code i { color: #8391a5; font-style: normal; }
  .steps { list-style: none; counter-reset: s; padding: 0; margin: 0; display: grid; gap: 18px; }
  .steps li { counter-increment: s; display: grid; grid-template-columns: 40px 1fr; gap: 14px; align-items: start; }
  .steps li::before { content: counter(s); width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center;
    font-weight: 700; background: var(--fg); color: var(--bg); }
  .steps strong { display: block; }
  .steps span { color: var(--muted); }

  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
  .feat { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 22px; }
  section.alt .feat { background: var(--bg); }
  .feat h3 { font-weight: 700; margin: 12px 0 6px; font-size: 18px; }
  .feat p { margin: 0; color: var(--muted); font-size: 16px; }
  .ico { width: 40px; height: 40px; border-radius: 10px; display: grid; place-items: center; background: color-mix(in srgb, var(--up) 14%, transparent); color: var(--up); }
  .ico svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

  .verdicts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 26px 0; }
  .verdict { border: 1px solid var(--border); border-radius: 12px; padding: 16px; background: var(--surface); }
  .verdict .pill { margin-bottom: 10px; }
  .verdict p { margin: 0; color: var(--muted); font-size: 15.5px; }
  .notice { border-left: 4px solid var(--flat); padding: 12px 16px; background: color-mix(in srgb, var(--flat) 9%, transparent); border-radius: 0 10px 10px 0; color: var(--fg); }

  .zip { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
  .zip li { display: flex; gap: 14px; align-items: baseline; padding: 14px 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
  .zip code { font: 600 14.5px ui-monospace, Menlo, Consolas, monospace; white-space: nowrap; }
  .zip span { color: var(--muted); font-size: 15.5px; }

  .faq { display: grid; gap: 10px; max-width: 820px; }
  .faq details { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); padding: 0 18px; }
  section.alt .faq details { background: var(--bg); }
  .faq summary { cursor: pointer; font-weight: 650; padding: 16px 0; list-style: none; display: flex; justify-content: space-between; gap: 12px; }
  .faq summary::-webkit-details-marker { display: none; }
  .faq summary::after { content: "+"; font-size: 22px; line-height: 1; color: var(--muted); transition: transform .2s; }
  .faq details[open] summary::after { transform: rotate(45deg); }
  .faq details p { margin: 0 0 16px; color: var(--muted); }

  .final { text-align: center; background: radial-gradient(900px 420px at 50% 0%, #1e3a5f 0%, var(--hero) 70%); color: var(--hero-fg); padding: 84px 0; }
  .final h2 { color: var(--hero-fg); }
  .final p { color: var(--hero-muted); margin: 0 auto 28px; max-width: 34em; font-size: 18px; }
  footer { padding: 28px 0 40px; color: var(--muted); font-size: 14px; }
  footer .wrap { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px; }

  /* Content is visible by default; it only fades in when the script runs. */
  html.rv .reveal { opacity: 0; transform: translateY(14px); transition: opacity .6s ease, transform .6s ease; }
  html.rv .reveal.in { opacity: 1; transform: none; }
  @media (prefers-reduced-motion: reduce) { html.rv .reveal { opacity: 1; transform: none; transition: none; } }

  @media (max-width: 900px) {
    .hero .wrap, .two { grid-template-columns: 1fr; gap: 40px; }
    .grid, .verdicts { grid-template-columns: 1fr 1fr; }
    .stage { min-height: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
    .card { position: static; width: auto; }
  }
  @media (max-width: 600px) {
    body { font-size: 16px; }
    .wrap { padding: 0 16px; }
    .hero { padding: 48px 0 56px; }
    .grid, .verdicts { grid-template-columns: 1fr; }
    .c3 { display: none; }
    .brand small { display: none; }
    section.band { padding: 56px 0; }
    .zip li { flex-direction: column; gap: 4px; }
  }
</style>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>

<header class="top">
  <div class="wrap">
    <span class="brand">__LOGO__<span><span data-gumroad-field="name">Trend Badge</span> <small>by Juni Labs</small></span></span>
    <a class="buy small" data-gumroad-action="buy" href="#buy">Buy · <span data-gumroad-field="price">$15.20</span></a>
  </div>
</header>

<main id="main">
  <section class="hero" aria-labelledby="hero-title">
    <div class="wrap">
      <div>
        <p class="kicker">Website widget</p>
        <h1 id="hero-title">A bullish / bearish price card for any website.</h1>
        <p class="lede">Add one script tag and show the last three months of prices with a clear Bullish, Bearish or Neutral badge. You supply the prices. It works in light and dark mode and on phones.</p>
        <div class="hero-cta" id="buy">
          <a class="buy" data-gumroad-action="buy" href="#buy">I want this! <span class="price" data-gumroad-field="price">$15.20</span></a>
          <span class="rating"><span data-gumroad-field="rating">Be the first to review</span> <span data-gumroad-field="review-count"></span></span>
        </div>
        <ul class="facts" aria-label="Key facts">
          <li>One 42 KB file</li><li>No dependencies</li><li>Unlimited websites</li><li>JSON or CSV</li>
        </ul>
      </div>
      <div class="stage" aria-label="Three example cards with made-up prices">
        __CARDS__
      </div>
    </div>
  </section>

  <section class="band" aria-labelledby="how-title">
    <div class="wrap two">
      <div class="reveal">
        <h2 id="how-title">Live on your page in a minute</h2>
        <p class="sub">No build step, no framework, nothing to install. If your site lets you add your own HTML, it can show a Trend Badge.</p>
        <ol class="steps">
          <li><div><strong>Add the script</strong><span>Upload trend-widget.js to your site and link it once.</span></div></li>
          <li><div><strong>Point it at your prices</strong><span>A JSON or CSV file of daily closes, or a list written straight into the tag.</span></div></li>
          <li><div><strong>Style it your way</strong><span>Set your colours, font and corner radius with simple CSS settings.</span></div></li>
        </ol>
      </div>
      <div class="reveal">
<pre class="code" aria-label="Example code"><i>&lt;!-- once per page --&gt;</i>
&lt;script src="<b>trend-widget.js</b>"&gt;&lt;/script&gt;

<i>&lt;!-- one card per asset --&gt;</i>
&lt;<b>trend-badge</b>
  name="ACME"
  src="/prices/acme.json"
  currency="USD"&gt;
&lt;/<b>trend-badge</b>&gt;

<i>&lt;!-- or a small badge inside text --&gt;</i>
&lt;<b>trend-badge</b> layout="badge"
  src="/prices/fund.csv"&gt;&lt;/<b>trend-badge</b>&gt;</pre>
      </div>
    </div>
  </section>

  <section class="band alt" aria-labelledby="feat-title">
    <div class="wrap">
      <h2 id="feat-title" class="reveal">Everything a price card needs</h2>
      <p class="sub reveal">Built as a standard web component, so it works next to whatever else is on your page.</p>
      <div class="grid">
        <div class="feat reveal"><div class="ico"><svg viewBox="0 0 24 24"><polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/></svg></div><h3>Price line and badge</h3><p>The last three months, the latest price, the change, and a clear label.</p></div>
        <div class="feat reveal"><div class="ico"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></div><h3>Light and dark</h3><p>Follows each visitor's setting automatically, or set it yourself.</p></div>
        <div class="feat reveal"><div class="ico"><svg viewBox="0 0 24 24"><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></svg></div><h3>Phone friendly</h3><p>Fits any width, with a price readout when visitors touch the line.</p></div>
        <div class="feat reveal"><div class="ico"><svg viewBox="0 0 24 24"><path d="M12 22a10 10 0 1 1 10-10c0 3-2 4-4 4h-2a2 2 0 0 0-1 3.7c.5.6.3 2.3-3 2.3z"/><circle cx="7.5" cy="10.5" r="1"/><circle cx="12" cy="7" r="1"/><circle cx="16.5" cy="10.5" r="1"/></svg></div><h3>Your brand</h3><p>CSS settings for colours, font and corners, plus ::part() for anything more.</p></div>
        <div class="feat reveal"><div class="ico"><svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg></div><h3>Reads your data</h3><p>JSON, CSV, a list of numbers, or data from JavaScript. Newest-first files are fine.</p></div>
        <div class="feat reveal"><div class="ico"><svg viewBox="0 0 24 24"><path d="M3 12h4l3 8 4-16 3 8h4"/></svg></div><h3>Any currency</h3><p>USD, EUR, PHP and more, in your visitors' number and date style.</p></div>
      </div>
    </div>
  </section>

  <section class="band" aria-labelledby="decide-title">
    <div class="wrap">
      <h2 id="decide-title" class="reveal">How the badge decides</h2>
      <p class="sub reveal">It scores the shape of the last 63 daily prices: how steady the move was, how straight, how efficient, and where the latest price sits in its range. The same prices always give the same badge.</p>
      <div class="verdicts">
        <div class="verdict reveal"><span class="pill up">Bullish</span><p>Prices climbed, and the climb is too large and too steady to be random noise.</p></div>
        <div class="verdict reveal"><span class="pill down">Bearish</span><p>The same test, going down.</p></div>
        <div class="verdict reveal"><span class="pill flat">Neutral</span><p>No clear direction. This is the most common result, on purpose: the test is strict.</p></div>
      </div>
      <p class="notice reveal">The badge describes what prices already did. It is not a forecast and not investment advice, and every card prints a short line saying so.</p>
    </div>
  </section>

  <section class="band alt" aria-labelledby="zip-title">
    <div class="wrap two">
      <div class="reveal">
        <h2 id="zip-title">What's in the zip</h2>
        <p class="sub">One download, ready to use. The license covers unlimited websites of your own and the sites you build for clients.</p>
      </div>
      <ul class="zip reveal">
        <li><code>trend-widget.js</code><span>The widget: one file, nothing else to install.</span></li>
        <li><code>demo.html</code><span>A working demo page with made-up prices.</span></li>
        <li><code>README.md</code><span>The full guide, with every option and price format.</span></li>
        <li><code>LICENSE.txt</code><span>Unlimited sites, client work included.</span></li>
      </ul>
    </div>
  </section>

  <section class="band" aria-labelledby="faq-title">
    <div class="wrap">
      <h2 id="faq-title" class="reveal">Questions</h2>
      <div class="faq">
        <details class="reveal"><summary>Does it include price data?</summary><p>No. You supply the prices, so you choose the source: a paid data provider, your broker's export, or your own published prices. Use prices you have the right to show.</p></details>
        <details class="reveal"><summary>What kind of prices does it need?</summary><p>One price per trading day (daily closes), oldest or newest first. It judges the most recent 63 by default, about three months.</p></details>
        <details class="reveal"><summary>Will it work on my site?</summary><p>It works on any page where you can add your own HTML and a script tag, in current Chrome, Edge, Safari and Firefox, on desktop and mobile.</p></details>
        <details class="reveal"><summary>Does the badge predict prices?</summary><p>No. It labels the shape of past prices. It is not a forecast and not investment advice.</p></details>
        <details class="reveal"><summary>How many websites can I use it on?</summary><p>As many as you own or run, plus the sites you build for clients. You may not resell or share the widget itself.</p></details>
        <details class="reveal"><summary>What if a price file fails to load?</summary><p>The card says the prices could not be loaded. A failed load is never shown as a Neutral reading.</p></details>
      </div>
    </div>
  </section>

  <section class="final" aria-labelledby="final-title">
    <div class="wrap">
      <h2 id="final-title">Put a clear trend on your price pages</h2>
      <p>One file, unlimited websites, and a one-time price.</p>
      <a class="buy" data-gumroad-action="buy" href="#buy">I want this! <span class="price" data-gumroad-field="price">$15.20</span></a>
    </div>
  </section>
</main>

<footer>
  <div class="wrap">
    <span>© 2026 Juni Labs</span>
    <span>Example cards use made-up prices. Not investment advice.</span>
  </div>
</footer>

<script>
  (function () {
    if (!("IntersectionObserver" in window)) return;
    var els = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
    function showAll() { els.forEach(function (e) { e.classList.add("in"); }); }
    document.documentElement.classList.add("rv");
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); } });
    }, { rootMargin: "0px 0px -8% 0px" });
    els.forEach(function (e) { io.observe(e); });
    // Safety net: never leave a section hidden.
    setTimeout(showAll, 2500);
  })();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    html = PAGE.replace("__LOGO__", LOGO).replace("__CARDS__", CARDS)
    out = STORE / "landing.html"
    out.write_text(html)
    print(f"wrote {out.name}: {len(html):,} characters (limit 500,000)")
