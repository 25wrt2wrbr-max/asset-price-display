# Source status

`status.html` (linked from the page footer) shows every outside source the
server reads: whether it is answering, when it last answered and last failed
(hover the failure time for the reason), and its calls, failure rate, average
and slowest time for today, the last 7 days and the last 30 days. It re-reads
`/api/sources` every 30 seconds while the tab is visible.

## How it is counted

- `sourcestats.py` keeps the tally. Each source's single fetch function wraps
  its call in `sourcestats.timed(url)`; the URL's host names the source
  (`sourcestats.HOSTS`). An unknown host is listed under its own host name.
- A source saying "no" (an HTTP 4xx such as "no such pair", or Yahoo's 404) is
  an **answer**, not a failure. 408 and 429 are failures.
- Yahoo is counted per URL from the statuses Yahoo sent (`moli_client._tally_yahoo`).
  A browser run that fails outright counts against **Moli browser** only:
  Yahoo was never asked.
- The TradingView chart socket counts one call per socket run; a run with no
  bars at all is a failure.
- A plain-HTTP attempt that fails and is rescued by the browser fallback
  counts as one answered call.

## Where it is kept

`<cache folder>/source-stats.json`, written at most once a minute and at
shutdown, 30 days kept. An unreadable file is moved to `source-stats.json.bad`
rather than overwritten. The temp file is `.writing`, not `.tmp`, because
`diskcache.prune` deletes `.tmp` files in that folder.
