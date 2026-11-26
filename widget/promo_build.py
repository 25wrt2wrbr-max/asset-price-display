#!/usr/bin/env python3
"""Build the public promo site from widget/store/landing.html.

    python3 widget/promo_build.py

Writes widget/promo/: index.html (the landing page with real head metadata and
working buy links), og.png, favicon.svg, robots.txt, sitemap.xml and README.md.
The paid file (trend-widget.js) is NOT copied here on purpose: this folder is
published, and the widget is only sold.
"""

import pathlib
import shutil

HERE = pathlib.Path(__file__).resolve().parent
STORE = HERE / "store"
OUT = HERE / "promo"

SITE = "https://25wrt2wrbr-max.github.io/trend-badge/"
PRODUCT = "https://juniverse8031.gumroad.com/l/trend-badge"
TITLE = "Trend Badge — a bullish / bearish price card for any website"
DESC = ("One script tag adds the last three months of prices with a clear Bullish, Bearish or "
        "Neutral badge to any web page. You supply the prices. One 42 KB file, no dependencies, "
        "unlimited sites, $15.20.")
BRAND = "Juni Labs"

HEAD = f"""<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE}</title>
<meta name="description" content="{DESC}">
<link rel="canonical" href="{SITE}">
<meta name="theme-color" content="#0f172a">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<meta property="og:type" content="product">
<meta property="og:site_name" content="Trend Badge">
<meta property="og:title" content="{TITLE}">
<meta property="og:description" content="{DESC}">
<meta property="og:url" content="{SITE}">
<meta property="og:image" content="{SITE}og.png">
<meta property="og:image:width" content="1280">
<meta property="og:image:height" content="720">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{TITLE}">
<meta name="twitter:description" content="{DESC}">
<meta name="twitter:image" content="{SITE}og.png">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Trend Badge",
  "description": "{DESC}",
  "url": "{SITE}",
  "image": "{SITE}og.png",
  "brand": {{ "@type": "Brand", "name": "{BRAND}" }},
  "offers": {{
    "@type": "Offer",
    "price": "15.20",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock",
    "url": "{PRODUCT}"
  }}
}}
</script>
"""


def buy(src: str) -> str:
    return (f"{PRODUCT}?utm_source={src}&amp;utm_medium=site&amp;utm_campaign=launch")


def build_page() -> str:
    page = (STORE / "landing.html").read_text()
    assert page.count("<head>\n<style>") == 1, "landing.html head changed shape"
    page = page.replace("<head>\n<style>", HEAD + "<style>")
    # Buy buttons: the landing page shipped with href="#buy" placeholders.
    buttons = [
        ('<a class="buy small" data-gumroad-action="buy" href="#buy">', buy("landing-header")),
        ('<a class="buy" data-gumroad-action="buy" href="#buy">', buy("landing-hero")),
    ]
    assert page.count(buttons[0][0]) == 1, "header button changed"
    assert page.count(buttons[1][0]) == 2, "hero/final buttons changed"
    page = page.replace(buttons[0][0], f'<a class="buy small" href="{buttons[0][1]}">')
    page = page.replace(buttons[1][0], f'<a class="buy" href="{buttons[1][1]}">', 1)
    page = page.replace(buttons[1][0], f'<a class="buy" href="{buy("landing-footer")}">', 1)
    assert 'href="#buy"' not in page.replace('id="buy"', ""), "a buy link still points at #buy"
    acct = Path.home().name.lower()
    assert acct not in page.lower(), "account name in page"
    return page


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(build_page())
    shutil.copyfile(STORE / "cover.png", OUT / "og.png")
    shutil.copyfile(STORE / "avatar.svg", OUT / "favicon.svg")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}sitemap.xml\n")
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemap.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{SITE}</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>\n"
        "</urlset>\n".replace("sitemap.org", "sitemaps.org"))
    (OUT / "README.md").write_text(README)
    print("built", OUT.relative_to(HERE.parent), "->", ", ".join(sorted(p.name for p in OUT.iterdir())))


README = """# Trend Badge

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
"""

if __name__ == "__main__":
    main()
