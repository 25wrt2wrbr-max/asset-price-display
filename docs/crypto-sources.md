# Crypto that Yahoo gets wrong

[Back to the README](../README.md)

Yahoo's ticker namespace collides with the crypto one, and it resolves the
collision badly. `JUP-USD` on Yahoo is **Jupiter Project**, a dead 2017 token at
`$0.00036`; the instrument people mean by "Jupiter" is the Solana DEX token
(`jupiter-exchange-solana`, ~`$0.34`), which Yahoo does not carry at all. So the
symbol charts the wrong coin *and* the right one cannot be searched for.
Coinbase is no better — its `JUP-USD` is a third, delisted token.

So a second source fills the gap, split by what each is good at:

| | Source | Why |
|---|---|---|
| Identity | CoinGecko `/coins/markets` | ranks coins by market cap, which is what separates the real Jupiter (rank 78) from the dead one (~4234) |
| Bars | Binance `data-api.binance.vision/api/v3/klines` | OHLCV with real volume, no key, no rate limit |
| Bars, when Binance has delisted the pair | Kraken `/0/public/OHLC` | still trades the coin, and the bars say so |

Crypto asks Binance's **market-data mirror**, `data-api.binance.vision`, not
`api.binance.com`: the main host answers HTTP 451 *"Service unavailable from a
restricted location"* in some regions (above all, the US), and since the same
host serves the pair list, that one block used to look like "Binance lists
nothing" — every coin failed the `USDT` check, so the search box lost all crypto
additions and nothing ever rerouted. The mirror serves identical payloads on the
same paths, without the geo gate.

Neither needs Moli: both answer plain HTTP clients with permissive CORS, unlike
Yahoo.

**A listed pair is not a trading pair.** Binance keeps a delisted pair in
`ticker/price` at its last price forever, so `XMRUSDT` still answered `$118.70`
on 2026-11-03 while Monero traded at `$625.94` — and its newest kline was
`2024-02-20`. Because the ticker "resolved to a chartable coin", `XMR-USD` drew
that 2024 window under today's date. Measured the same day, 132 of the top 250
had a `USDT` pair and five were dead: XMR (2024-02-20), DAI (2020-08-12), BTT
(2022-01-17), BEAM (2023-01-26), LIT (2025-02-10). The fix is in the bars, not in
a list: `crypto.STALE_BAR_DAYS` (5) of silence means the pair is not trading, and
the coin is then read from **Kraken**, which answers for all five with a bar
stamped today (`XMRUSD` `$624.60`, `BTTUSD` `3.63e-07`, `BEAMUSD` `$0.004076`,
`LITUSD` `$0.0931`, `DAIUSD` `$0.99958`). When neither venue trades the coin,
nothing is drawn rather than something old — the chart route then keeps Yahoo,
which is current for `XMR-USD` and honest about having nothing for `BTT-USD`
(whose Yahoo series is three months of zeros).

**Only crypto Yahoo gets wrong is rerouted.** The test is objective, not a
name heuristic: Yahoo must report `instrumentType == CRYPTOCURRENCY` *and*
disagree with the venue's last close by more than 20% (`REROUTE_GAP` in
`server.py`). Jupiter is ~1000× off, so it reroutes; `BTC-USD`, `ETH-USD` and
`SOL-USD` agree to a fraction of a percent, so they stay on Yahoo — by design.
A symbol Yahoo 404s on but Binance lists (e.g. `PEPE-USD`) reroutes too, so this
fixes more than Jupiter. A delisted pair contributes no such comparison at all
(`crypto.latest_close` answers None), which is what stopped the frozen `$118.70`
from making Yahoo's live `$625.94` look like the wrong instrument.

Two limits worth knowing:

- **Binance lists ~133 of the top 250 coins** with a `USDT` pair. A coin in the
  index is not automatically chartable — `CRO` and `LEO` have no USDT pair and
  stay with Yahoo. The count is a snapshot; the pair list moves.
- **CoinGecko's free tier is 5 requests/minute** (`x-ratelimit-limit: 5`; a sixth
  rapid call returns 429). That is fine for one cached identity lookup and
  hopeless for type-ahead, so the index is fetched at most once an hour and
  Binance serves the per-request work. On a 429 the last good index is served
  rather than failing, so the search box never blanks.

A rerouted symbol keeps that identity when it is added to the watchlist: the
Add button takes its symbol and name from the chart payload, not from typed
text, so what lands in the rail is the same coin the chart drew.

Everything else — equities, ETFs, FX, indices, futures, and the crypto Yahoo
gets right — still comes from Yahoo through Moli.
