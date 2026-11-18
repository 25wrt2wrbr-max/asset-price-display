# How the trend call works

[Back to the README](../README.md)

### Three-month forecast research (2026-10-30)

The requested forecasting target is whether the price at the close on or
after three calendar months is higher than the signal close. This is **not**
the same as staying bullish throughout the period or earning a tradeable
return. The app's current badge remains a description of past prices; it has
**not** been changed into a forecast.

`forecast_collect.py` collected daily Yahoo closes through Moli for 74
currently selected instruments: 35 US equities, 18 funds, 11 cryptocurrencies
and 10 currency pairs. `research/market-history.json` holds the bars and
exchange time zones. The PSE comparison uses the existing 244-listing
`research/pse-history.json`. Samples use completed daily bars and the first
available close each month; an outcome is the close on or after the target,
at most ten calendar days late. An unchanged price is neither a correct
bullish nor a correct bearish call. Yahoo uses its three-calendar-month
lookback, PSE its 90-day lookback, and windows under 50 bars are omitted.

`forecast_validation.py` evaluates one **experimental**, pre-specified
candidate: it bins the existing score, then calibrates each bin on earlier
completed outcomes only, separately for each asset class. Annual walk-forward
folds embargo outcomes crossing into the evaluation year. Bins with too little
history or without a four-month block-bootstrap lower bound above 50% abstain.
This is one candidate, not a search over every possible model; the bootstrap
is approximate and the data is not an untouched prospective test.

The candidate does **not** meet the requested reliability goal: 2022 US
equity bullish calls were correct 40.24% of 420 observations, and fund bullish
calls were correct 29.80% of 151 observations. In the PSE folds it made no
bullish calls; its 2025 bearish calls were correct 48.66% of 1,790
observations. Observations share market shocks and overlapping horizons;
counts are not independent and these rates are not individual probabilities.
The current-selected universe excludes delisted instruments, the sample is
illustrative, history may contain corporate-action distortions, and same-close
entry, fees, taxes, dividends, and slippage are not accounted for. Results for
Yahoo crypto also do not validate the live Binance feed. Full yearly results,
coverage, and limitations are saved in `research/forecast-validation.json`.

To recollect and rerun: `python3 forecast_collect.py`, then
`python3 forecast_validation.py`. Collection needs Moli and internet access;
it does not change the live app's prices or classifier. A credible production
forecast still needs broader point-in-time histories, including delistings,
and a separately reserved prospective or untouched evaluation across market
regimes. Do not reinterpret the current bullish badge as a probability.

#### Expanded sample and 51% target

`forecast_collect_extended.py` requests a fixed list of 538 Yahoo symbols,
including the original research sample, with daily history back to 1990 where
available. It writes `research/market-history-extended.json` separately and
refuses to overwrite a previous collection. `forecast_extended_validation.py`
evaluates the same fixed candidate in expanding annual folds from 2011 through
2026, by asset class and including the existing PSE dataset. It writes
`research/forecast-validation-extended.json`; it too refuses to overwrite a
previous report. Both scripts run separately, in that order; collection uses
Moli and requires internet access.

The saved collection contains 517 of 538 requested histories: 346 US
equities, 92 funds, 37 cryptocurrencies and 42 currency pairs. The 21 Yahoo
404 responses are recorded as missing, not scored as forecasts. Depending on
the instrument, the available history starts as early as 1990; it does not
cover every instrument for that entire period.

The report compares each direction separately with a 51% observed hit-rate
target, reports the number of forecasts, abstentions, yearly results, an
always-up/always-down baseline and an approximate 90% time-block bootstrap
interval. Ties count as incorrect, and a signal cannot train on outcomes that
have not completed before its evaluation year. An observed accuracy over 51%
alone does not establish reliable future accuracy: these observations overlap,
parts of the period have already been inspected, and today-selected symbols
exclude most delisted assets. This research does not change the app's badge.

In the completed expanded evaluation, bullish forecasts for US equities were
correct in 60.77% of 62,535 observations, and bullish fund forecasts in 58.20%
of 13,166. But the equity candidate called **every** observation bullish,
matching the always-up baseline exactly; for funds, always-up also matches the
candidate on the cases it chose to forecast. In 2022 these bullish rates fell
to 45.09% for equities and 30.60% for funds. PSE bearish calls were correct in
55.86% of 6,921 observations, again exactly matching an always-down call on
those cases, and were 48.66% in 2025. The candidate produced no bullish PSE,
currency or crypto calls; currency bearish accuracy was 44.63%, and crypto
had no directional calls. These pooled results exceed 51% in some groups but
do **not** establish a useful or dependable asset-specific forecast. Full
counts, yearly breakdowns and uncertainty intervals are in the saved report.

#### Separate market and direction candidates

`market_forecasts.py` implements experimental separate binary models for US
bearish, PSE bullish, currency bullish/bearish, and crypto bullish/bearish
calls. It extracts return, volatility, range position, unchanged-close
frequency and the existing score from the chart window; it does not use future
bars. Each model is regularized logistic regression, with a threshold selected
on an earlier two-year validation period. Ties count as incorrect, calls that
conflict are withheld, and insufficient training or validation abstains.

`python3 market_forecast_backtest.py` runs the research evaluation and writes
`research/market-specific-forecast.json`, refusing to overwrite an existing
report. Each annual 2016–2026 fold fits on outcomes completed before the
validation period, chooses its threshold only on validation outcomes completed
before the test year, and reports test-year results and forecast coverage.
The sample has already been inspected, excludes delisted listings and omits
transaction costs; it is not a prospective test or evidence that an individual
call has a particular chance of success. These candidates are research-only and
do not alter the live badge, tables, or exported classifier.

The first evaluation withheld every call: no direction cleared the conservative
validation confidence-bound gate. `python3 market_forecast_exploratory.py`
tests a less restrictive research alternative, choosing from fixed validation
score quantiles when the validation *observed* hit rate reaches 51% and minimum
case/month/instrument counts are met. It saves
`research/market-specific-exploratory.json` and records rejected thresholds as
well as selected ones; this script also refuses to overwrite an existing
report. Because threshold selection uses a point estimate, crossing 51% in
validation is not evidence of reliable future accuracy. Subsequent annual
results remain exploratory because related historical periods were inspected.

The completed exploratory run produced these pooled three-month test results:

| Market and direction | Correct | Forecasts | Coverage | Approximate 90% interval |
|---|---:|---:|---:|---:|
| US stocks, bearish | 41.68% | 4,115 | 9.54% | Not computed: only 12 forecast months |
| PSE stocks, bullish | No calls | 0 | 0% | — |
| Currencies, bullish | 52.70% | 2,854 | 53.51% | 49.86%–56.38% |
| Currencies, bearish | 48.99% | 1,729 | 32.41% | 46.11%–51.87% |
| Crypto, bullish | 39.51% | 853 | 25.01% | 20.39%–48.94% |
| Crypto, bearish | 58.36% | 1,585 | 46.48% | 47.72%–71.53% |

Coverage is the fraction of eligible monthly observations given that direction;
the other observations are withheld or called in the opposite direction. The
intervals are approximate time-block bootstrap intervals and do not adjust for
model or threshold selection. In particular, both estimates over 51% have
intervals extending below 51%. All selected cases in each row trivially have
the same accuracy as an always-up or always-down call on those same cases; the
candidate has not established that it identifies individual winners or losers.
The full annual breakdown, models and validation diagnostics are saved in the
exploratory report. The production badge remains a past-trend description.

#### Targeted follow-up

`targeted_forecast_research.py` explores separate momentum, reversal, and
volatility rules for bearish currencies, bearish US stocks and bullish crypto.
It uses six- and twelve-month historical prices in addition to the chart window,
selects among 36 rule/threshold combinations using prior validation data, and
replays the earlier models on the same eligible 2020–2026 observations. Its
saved report is `research/targeted-forecast-research.json`. On that comparison
the candidates did not improve: currency bearish 43.53% versus 48.90% prior,
US bearish 41.16% versus 41.68%, and crypto bullish 35.44% versus 37.53%.
The earlier crypto figure of 39.51% included a different eligible population
and period. Forecast coverage differs too; these rates are not paired
same-call comparisons.

`asset_local_forecast_research.py` evaluates a separate asset-local approach
using only outcomes that were complete before the signal. It writes
`research/asset-local-forecast-research.json` when run. Both approaches are
exploratory: the historical period has already been inspected, observations
overlap, and current listings exclude most delisted assets. They are not live
classifiers or independently validated probability estimates.

The completed asset-local evaluation on that same eligible 2020–2026 sample
produced bearish currency accuracy of 48.79% (746 calls, 22.48% coverage),
bearish US stock accuracy of 44.87% (936 calls, 3.46% coverage), and bullish
crypto accuracy of 45.42% (491 calls, 18.41% coverage). The prior models on
the same eligible sample scored 48.90%, 41.68%, and 37.53%, respectively;
their selected calls and coverage were different. The new US and crypto
rates are higher in this retrospective comparison but remain below 51%, and
their approximate 90% intervals (36.02%–51.00% and 36.71%–56.32%) are wide.
Currency did not improve. None establishes an independently validated or
live-ready predictor; the app's existing classifier is unchanged.

`adaptive_forecast_research.py` runs a further combined candidate for those
three directions. It uses chart-window features, six- and twelve-month past
returns, and a score from that asset's already completed outcomes. Each yearly
fold fits on older outcomes, selects a threshold on a separate two-year
validation period, and tests on later observations. It compares with both
earlier approaches on the same eligible observations and saves
`research/adaptive-forecast-research.json`. The evaluation is exploratory:
earlier experiments already inspected the period, the selection process has
changed in response, and the reported intervals do not adjust for this
research selection. It is not a production classifier or prospective test.

The adaptive candidate's bearish currency accuracy was 50.76% over 461 calls
(14.77% coverage), with an approximate 90% interval of 38.95%–61.00%; it was
41.46% over 1,341 US bearish calls and produced no bullish crypto calls. It did
not establish a model above the 51% target. The results use a narrower eligible
population than the earlier tests and are not an untouched evaluation.

`benchmark_forecast_research.py` adds lagged market-benchmark features to that
candidate, using SPY for US stocks, EUR/USD for currencies and BTC/USD for
crypto. Only benchmark closes from a strictly earlier calendar date are used;
missing or stale benchmark data is omitted. It saves
`research/benchmark-forecast-research.json`, comparing prior approaches on the
same eligible observations. The benchmark is a coarse proxy, and this is
further retrospective research—not a live or independently validated model.

The completed benchmark experiment scored 50.00% for currency bearish calls
(552 calls), 41.10% for US stock bearish calls (3,219 calls) and made no crypto
bullish calls. It did not improve on the best preceding candidates. The full
results and annual breakdown are saved in the benchmark report.

`pooled_forecast_research.py` tests another fixed candidate: it combines a
rolling three-year market/regime win frequency with an asset's own recent
history, using only outcomes completed strictly before each signal. It
compares earlier models on the same eligible observations and writes
`research/pooled-forecast-research.json`. As with the earlier experiments, the
history is already inspected and the universe omits many delisted instruments;
the results are exploratory, not validation for use in the app.

The pooled candidate reached 47.92% on 912 bearish currency calls (29.22%
coverage), 41.76% on 3,781 bearish US stock calls (15.13% coverage), and
39.67% on 421 bullish crypto calls (26.56% coverage). On the same eligible
observations, the earlier adaptive currency candidate reached 50.76% on 461
calls (14.77% coverage), and the earlier asset-local candidate reached 44.87%
on 936 US calls (3.75% coverage) and 45.42% on 491 crypto calls (30.98%
coverage). The candidates select different calls; none met the 51% target.

`relative_forecast_research.py` explores cross-asset relative strength and
market breadth, using peer bars from a strictly earlier local calendar date
and a separate annual fit, validation and test. Peers come from available raw
bars rather than outcome-filtered observations, but the selected present-day
universe still introduces survivorship bias. A prior local date is not proof
that a peer's close was available at the signal time in every time-zone
combination. The saved `research/relative-forecast-research.json` is exploratory
research, not an independent test or a live model.

The relative-strength candidate produced 48.64% accuracy on 477 bearish
currency calls (15.28% coverage), 43.09% on 2,843 bearish US stock calls
(11.38% coverage), and 24.08% on 245 bullish crypto calls (15.46% coverage).
The US and crypto calls occurred in only one test year each. None surpassed
the best preceding model on the same eligible observations; the algorithms
select different calls.

`tree_forecast_research.py` evaluates separate shallow nonlinear decision
trees for the same three forecast tasks, using the adaptive candidate's
features and the same chronological fit/validation/test boundaries. It writes
`research/tree-forecast-research.json` and compares earlier candidates on the
same eligible observations. Previously inspected years, overlapping outcomes,
survivorship bias and research selection still limit the interpretation; it is
not a live or independently validated model.

The decision-tree candidate reached 47.81% on 640 bearish currency calls
(20.51% coverage), 37.24% on 2,425 bearish US stock calls (9.71% coverage),
and made no bullish crypto calls. It did not improve the best preceding
candidates on the same eligible observations.

`regime_gate_forecast_research.py` tests withholding asset-local calls when the
recent market-wide directional hit rate is below 50% or has too little
history. Its 18-month gate uses only outcomes completed strictly before each
signal. It writes `research/regime-gate-forecast-research.json`, compares the
earlier candidates on the same eligible observations, and is exploratory—not
an independent test or a production model.

The regime gate produced 41.38% on 319 bearish currency calls (10.22%
coverage), 46.98% on 149 bearish US stock calls (0.60% coverage), and 34.62%
on 234 bullish crypto calls (14.76% coverage). The US figure exceeds the
asset-local comparator's 44.87% on the same eligible population, but uses far
fewer, different calls and spans only 13 signal months. No candidate reached
51%; the improvement is exploratory and is not evidence of future accuracy.

`neighbor_forecast_research.py` explores asset-specific nearest neighbors from
the preceding five years, requiring each neighbor's outcome to have completed
before the signal. It writes `research/neighbor-forecast-research.json` and
compares earlier candidates on the same locally eligible observations. This is
another exploratory backtest, not independent or prospective validation.

The neighbor candidate scored 49.83% on 1,202 bearish currency calls (38.51%
coverage), 45.25% on 6,532 bearish US stock calls (26.14% coverage), and
40.73% on 685 bullish crypto calls (43.22% coverage). It increased coverage
compared with the asset-local candidate, but none reached 51%. These methods
select different calls on the same eligible observations.

`consensus_forecast_research.py` tests calling only when both the asset-local
and neighbor approaches agree, comparing both components, the regime gate and
adaptive candidate on the same eligible observations. It writes
`research/consensus-forecast-research.json`. This rule was conceived after
examining its components and historical results, so even a favorable result
would be exploratory rather than independent validation.

The consensus candidate scored 50.52% on 574 bearish currency calls (18.39%
coverage), 44.41% on 743 bearish US stock calls (2.97% coverage), and 44.91%
on 383 bullish crypto calls (24.16% coverage). It did not reach 51%; the
adaptive currency candidate, US regime gate and asset-local crypto candidate
had higher observed accuracy on the same eligible population, with different
calls and coverage.

`calibration_gate_forecast_research.py` explores a different filter: it
reconstructs earlier asset-local calls and permits new calls only when enough
previously completed calls have a recent hit rate of at least 50%. It writes
`research/calibration-gate-forecast-research.json`. The repeated use of the
same historical years makes this exploratory, not independent validation.

The calibration gate scored 46.96% on 526 bearish currency calls (16.85%
coverage), 36.89% on 225 bearish US stock calls (0.90% coverage), and 39.44%
on 213 bullish crypto calls (13.44% coverage). It was worse than the
asset-local comparator in all three markets on the same eligible population;
the two methods selected different calls.

`contrarian_gate_forecast_research.py` tests the opposite of the earlier
market-regime gate: it permits asset-local calls only when the prior completed
market hit rate is below 50%. It writes
`research/contrarian-gate-forecast-research.json`. This rule was proposed after
examining the same years and is exploratory, not independently validated.

The contrarian gate scored 54.33% on 427 bearish currency calls (13.68%
coverage), 44.47% on 787 bearish US stock calls (3.15% coverage), and 55.25%
on 257 bullish crypto calls (16.21% coverage). Its approximate 90% block
bootstrap intervals were 50.34%–59.94% for currencies and 44.92%–66.35% for
crypto; neither lower bound exceeded 51%, and these intervals do not account
for repeated model search. This is an observed retrospective result, not
evidence that either algorithm will reach 51% in future. Compared methods
share the eligible population but select different calls. Crypto uses Yahoo,
not Binance; current selected listings omit many delisted assets. The app's
labels are unchanged.

`neighbor_contrarian_research.py` explores the same lagged contrarian gate
applied to the broader-coverage nearest-neighbor candidate. It writes
`research/neighbor-contrarian-research.json` and replays comparators on the
same eligible observations. The rule was chosen after inspecting the earlier
contrarian result, and is exploratory rather than independent validation.

The gated-neighbor candidate scored 52.93% on 735 bearish currency calls
(23.55% coverage), 44.20% on 5,310 bearish US stock calls (21.25% coverage),
and 46.51% on 387 bullish crypto calls (24.42% coverage). For currencies the
local contrarian candidate had higher observed accuracy but lower coverage;
for crypto it also had higher observed accuracy. Calls differ despite the
shared eligible population. The results are exploratory, not validation.

`rolling_selector_forecast_research.py` tests selecting among the local,
nearest-neighbor and contrarian-gated approaches using only their previously
completed calls. It writes `research/rolling-selector-forecast-research.json`.
The selector and its candidates were designed after inspecting the same
history, so results remain exploratory rather than independent validation.

The rolling selector scored 48.54% on 478 bearish currency calls (15.32%
coverage), 38.16% on 836 bearish US stock calls (3.35% coverage), and 38.55%
on 275 bullish crypto calls (17.35% coverage). It did not improve on the best
preceding candidates on the same eligible observations; calls differ.

`shock_filter_forecast_research.py` tests whether a negative prior 20-bar
benchmark return improves local or nearest-neighbor calls. It writes
`research/shock-filter-forecast-research.json`. The benchmark's previous local
calendar date is not a guarantee of availability across time zones; EUR/USD
is also a coarse currency proxy. This post-selection test remains exploratory.

The shock-filtered local and neighbor models scored 44.37% and 48.16% for
bearish currencies (311 and 515 calls), 46.10% and 46.64% for bearish US
stocks (269 and 1,966 calls), and 45.09% and 40.00% for bullish crypto (275
and 400 calls). Their respective coverage was 9.96% and 16.50%, 1.08% and
7.87%, and 17.35% and 25.24%. None reached 51%. The benchmark-date caveat and
the previously inspected, survivorship-biased sample still apply.

`peer_filter_forecast_research.py` tests top- and bottom-quartile peer
relative-strength filters on the local and neighbor calls. Peer returns use
earlier local calendar dates and raw, rather than outcome-filtered, bars; the
current-listing universe and cross-timezone availability remain limitations.
It writes `research/peer-filter-forecast-research.json`. Because these
historical years have been repeatedly examined, results are exploratory.

Peer filters yielded a best currency result of 52.40% on 208 calls (6.66%
coverage; local reversal), a best US bearish result of 50.46% on 329 calls
(1.32% coverage; local momentum), and a best crypto bullish result of 51.61%
on 155 calls (9.78% coverage; local momentum). Their approximate 90% block
bootstrap intervals were 43.85%–61.63%, 41.54%–57.67%, and 41.29%–62.59%,
respectively; none accounts for searching many models. All are exploratory,
not independent evidence, and calls differ across methods. Prior local-date
peer prices do not guarantee cross-timezone availability.

`peer_regime_forecast_research.py` evaluates combinations of the peer-rank
and market-rate filters on asset-local calls, saving
`research/peer-regime-forecast-research.json`. The combinations were proposed
after inspecting their components and therefore are exploratory, not an
independent test. Small subsets and cross-timezone peer availability are
additional limitations.

The completed combined experiment exceeded 51% in the inspected historical
sample for all three requested directions: bearish currency reversal with the
contrarian gate scored 59.29% on 113 calls (3.62% coverage), bearish US stock
momentum with the contrarian gate scored 52.40% on 271 calls (1.08% coverage),
and bullish crypto momentum with the contrarian gate scored 54.64% on 97 calls
(6.12% coverage). The earlier local contrarian crypto model scored 55.25% on
257 calls (16.21% coverage). Approximate 90% block bootstrap intervals for
these three combined variants are 50.00%–71.13%, 41.83%–60.38%, and
43.62%–68.75%, respectively; none has a lower bound above 51%, and the
intervals do not correct for repeated selection. The filters were selected
after examining the same historical years. The result is not an independent
or prospective test, and peer bars' prior local dates do not guarantee that
their closes were available in all cross-timezone cases. Current-listing
survivorship, missing-outcome selection, overlapping outcomes and Yahoo rather
than Binance crypto further limit interpretation. The app remains unchanged.

`peer_regime_sensitivity_research.py` checks the selected combined rules with
peer data delayed an additional three calendar days and with a greedy
non-overlapping-per-asset subset. Its output is
`research/peer-regime-sensitivity-research.json`. These checks can expose
fragility but cannot undo historical model selection, survivorship bias or
cross-asset dependence, and they are not independent validation.

Sensitivity results: delaying peers an extra three calendar days yielded
60.38% over 106 currency calls (3.40% coverage), 52.14% over 280 US calls
(1.12%), and 50.50% over 101 crypto calls (6.37%). Keeping only the first
signal per asset until its previous selected outcome completed yielded, with
the original peer dates, 57.81% on 64 currency calls, 50.66% on 152 US calls,
and 57.69% on 52 crypto calls; with delayed peer dates it yielded 62.50% on
64, 49.37% on 158, and 52.83% on 53, respectively. Non-overlapping subsets
select different calls and remain correlated across assets. Currency's
reported delayed interval excludes 51%, but neither that interval nor these
checks correct for post-selection, missing outcomes, or survivorship; they do
not establish future performance.

`peer_regime_concentration_research.py` replays the selected original calls,
checks that counts match the combined report, and records breakdowns and
leave-one-group-out hit rates by year, month, and asset in
`research/peer-regime-concentration-research.json`. These are hindsight
diagnostics, not live filters or independent tests; subgroup results do not
correct for selection or shared market shocks.

The concentration audit reproduced the selected calls. Removing 2024 calls
from the US summary lowers observed accuracy from 52.40% (271 calls) to
48.82% (211 calls); removing `PARA` calls lowers it to 48.81% (252 calls).
These are retrospective exclusions of calls, not a re-run without the year or
symbol in training, market rates, or peer ranks. Crypto falls from 54.64% to
50.60% when `TRX-USD` calls are excluded; currency falls from 59.29% to 53.66%
without 2024. These examples do not prove causality or future performance.

On 2026-10-30 the Yahoo chart API identified `PARA` as **Parabolic
Technologies, Inc.**, first trade 2021-02-12, and reported four reverse split
events in its history (1:50, 1:10, 1:20, and 1:10). The saved history contains
only ticker, bars, and time zone—not a verified point-in-time company identity
or corporate-action record. The intended issuer and whether these events
distort the measured calls are not established. Do not identify this series
with another company solely from the ticker; audit historical identity and
adjustments for the universe and rebuild affected experiments before drawing
conclusions. In particular, the US result is not a validated 51% predictor.

`us_symbol_sensitivity_research.py` replays the US combined experiment and
rebuilds it with `PARA` excluded from observations, market-rate history and
peer ranks, writing `research/us-symbol-sensitivity-research.json`. This
post-selection sensitivity audit is not a point-in-time identity or
corporate-action verification and is not independent validation.

The completed rebuild reproduced 52.40% on 271 US bearish calls with PARA,
and obtained 48.81% on 252 calls (1.01% coverage) without PARA throughout the
inputs. Both experiments are retrospective, and excluding a ticker after
observing its influence is not an unbiased validation. Corporate-action and
point-in-time issuer identity issues remain unverified for the wider universe.

`peer_neighbor_regime_research.py` evaluates nearest-neighbor calls combined
with peer momentum/reversal and the prior market contrarian gate for all
three directions. It also rebuilds the US experiment with PARA entirely
excluded, replays the previous local comparator, and writes
`research/peer-neighbor-regime-research.json`. All results are post-selection
research on previously inspected years, not independent validation.

The peer/contrarian-filtered neighbor candidate scored 54.17% on 240 bearish
currency calls (7.69% coverage; reversal), 45.18% on 1,609 bearish US calls
(6.44% coverage; reversal), and 52.14% on 117 bullish crypto calls (7.38%
coverage; momentum). Rebuilding the US inputs without PARA produced 45.16%
on 1,610 reversal calls (6.45% coverage). These selected calls differ from
the local model's calls; the results are exploratory, not validation.

`peer_regime_baseline_research.py` evaluates peer rank plus market-rate gates
without requiring an asset-local call, while retaining the same local-history
eligibility for comparison. It rebuilds the US inputs without PARA and saves
`research/peer-regime-baseline-research.json`. The rules were developed after
repeatedly examining this history; they remain exploratory, not independently
validated, and peer timestamps remain a cross-timezone limitation.

The completed peer/market baseline did not reach 51% for US stocks: without
PARA, its best variant scored 48.78% on 1,023 calls (4.10% coverage), all
in only 13 signal months. The best baseline variants for bearish currencies
and bullish crypto scored 50.19% (528 calls, 16.92%) and 48.12% (320 calls,
20.19%), respectively. The baseline selected different calls on the same
eligible population. These are exploratory historical results.

`outcome_availability_audit.py` reconstructs valid-input monthly signals even
when their three-month outcomes are not yet known, and counts pending and
matured-missing outcomes separately from observed outcomes. It replays the
selected local/peer/contrarian research calls (with PARA excluded from US
inputs), never scores unresolved calls, and writes
`research/outcome-availability-audit.json`. This retrospective audit exposes
missing outcomes but cannot remove survivorship, selection, local-time or
corporate-action biases.

As of the dataset's 2026-10-30 UTC collection date, this audit reconstructed
16 bearish currency, 24 bearish US stock (without PARA), and 6 bullish crypto
calls whose exits were not yet due. The corresponding completed calls were
67 correct out of 113, 123 out of 252, and 53 out of 97. Pending calls are
unknown, not losses; this is retrospective reconstruction, not a record of
predictions actually made before their signal dates. The audit found no
additional matured-missing or within-grace outcomes among the valid-input
signals in these saved received histories. It does not capture instruments
missing from the dataset altogether.

`pending_outcome_bounds.py` writes `research/pending-outcome-bounds.json`,
which shows arithmetic extremes if every pending call were wrong or every one
were right. Including pending calls, the observed-reconstruction totals could
range from 51.94% to 64.34% for currencies, 44.57% to 53.26% for US stocks,
and 51.46% to 57.28% for crypto. These are not predictions, confidence
intervals, or prospective validation; outcomes are unknown. For US stocks,
18 of the 24 unresolved calls would need to be correct to reach 51% across
the combined 276 calls.

#### Bearish forecast research: PSE, US equities and funds

`bearish_forecast_research.py` tests a separate experimental three-calendar-month
price-direction forecast for each of these markets. It does not change the app's
descriptive trend labels. Each year it chooses among seven fixed candidate rules
using the prior two years' completed outcomes: asset-local historical outcomes,
local calls combined with relative-strength ranks and a market-outcome gate,
and weak- or strong-trend rules. To qualify, a candidate needs at least 60
validation calls, six signal months, ten instruments, 51% accuracy, and a
one-percentage-point advantage over always predicting down on the validation
population. If none qualifies it abstains. This is a heuristic, not a confidence
guarantee; yearly selections and diagnostics are saved in the report.

Run `python3 bearish_forecast_research.py` with the saved research histories to
write `research/bearish-forecast-research-comparable.json`; the script refuses
to overwrite that report. `research/bearish-forecast-research.json` records an
earlier run whose US coverage used a larger eligible population and must not be
compared directly with the older local-history US candidate. The comparable run
requires the same available asset-local score for the US comparison and excludes
PARA throughout US observations, peer ranks, and the market gate. PSE uses its
90-day chart window; Yahoo equities and funds use three calendar months. Peer
returns use calendar months in all markets. The fund universe includes other
exchange-traded products as well as conventional ETFs.

In the completed 2020–2026 evaluation the selected-rule candidate scored
52.00% on 1,275 PSE calls (12.38% coverage), 38.76% on 2,722 US calls
(10.90%), and 33.33% on 669 fund calls (9.25%). Always predicting down across
the same eligible populations scored 56.54%, 43.28%, and 42.02%, respectively;
these baselines select different cases. On the same eligible US population,
the previous momentum/contrarian local rule scored 48.81% on 252 calls (1.01%
coverage). The new candidate is not an improvement in observed US accuracy.
Applying that previous rule to funds scored 55.11% on 176 calls (2.43%
coverage); its approximate 90% time-block interval was 42.86%–64.14% and it
was highlighted after inspection, not selected in an independent test. The
corresponding interval for the PSE candidate was 42.35%–60.90%. None of these
results validates a forecast for an individual instrument.

Signal outcomes finishing on or after a forecast date cannot enter its local or
market history; validation outcomes finishing on or after a test year cannot
select its rule. The test uses first monthly closes and the first close on or
after three calendar months (at most ten days late); unchanged prices are
misses. Missing and pending outcomes are excluded, and past observations are
reconstructed from outcome-available histories. Current listings omit many
delisted securities, histories and corporate actions are unverified, peer local
dates do not guarantee real-time availability, and returns are not executable
trade returns. These repeatedly examined years are exploratory, not a fresh
holdout; intervals do not account for model search. A prospective, point-in-time
evaluation is needed before deployment.

#### The odds of profit, on the chart (2026-11-01)

Under the price the chart prints one figure: **the estimated probability, 0 to 1,
of a positive three-month price return after assumed round-trip costs**, using
only the daily prices displayed in the graph. This replaces the class base-rate
model at the reader's request. It is separate from the descriptive trend badge.

`probability.py` fits the sample mean `m` and standard deviation `s` of the `n`
drawn daily log returns. With `H` future sessions, it calculates:

```
P = normal_cdf((H*m - log(1 + cost)) / (s*sqrt(H + H*H/n)))
```

The predictive variance includes future price noise and uncertainty in the
estimated mean. Crypto uses every calendar day in the next three calendar
months; other supported assets use weekdays (exchange holidays are not modeled).
Class mappings supply only calendars and assumed costs, never return priors.
Results are bounded to 0.01–0.99. Short, invalid, constant-return and weekly
series receive no estimate; yields remain excluded. Futures now use their own
displayed returns and weekday calendar, with an assumed 0.20% round-trip cost
relative to notional value. Their estimate is for a long contract price gain,
not leveraged account profitability; expiry, rolls and margin are not modeled.

The page prints `3-month profit odds … · chart-based estimate, net of …% costs`.
Its tooltip states the independent stationary normal-log-return assumption and
limitations: this is not empirically calibrated, regimes and fat tails can break
the model, and taxes/currency conversion are excluded. Tests cover the formula,
response to chart returns, mean uncertainty, calendars, costs and missing data.

**The watchlist row prints the same figure** (added 2026-11-04), as a third line
under its name and its window's move — `3-month odds 0.69`, coloured above/below
0.5 like the stat-line. It is read from the row's own chart payload, so the rail
and the chart it opens cannot disagree about the odds; a yield, a refused series
or a row that has not answered yet draws no line at all rather than a default.

#### Research judgment on the chart

**The chart no longer shows a research-judgment line** (removed 2026-10-31 at the
reader's request). For any asset outside the studied universe it printed
"Bullish: could not be calculated … Bearish: could not be calculated" and then an
in-sample asset-history baseline — three lines that read as a verdict about the
asset while saying the research had nothing to say. The line, its renderer, its
markup and its stylesheet rules are gone; the page no longer calls
`/api/research-judgment`. The endpoint itself is unchanged and still answers
anyone asking directly, and nothing about the current-trend badge, the tables or
the sweep depends on it.

What follows describes the research the endpoint still serves.

The currently implemented research paths are the Philippine bullish local
filter, the frozen 2026 Philippine bearish local/peer filter, frozen 2026 US and fund bullish score bins, and the frozen 2026 currency
bullish model. The fund bearish 2026 selector abstained. These paths require
the studied instrument identity and source, completed daily prices, and the
first completed close of the current month; the latter matches the research
schedule rather than implying that daily calls were validated. A latest price
over seven calendar days old is unavailable. The frozen folds are unavailable
outside 2026. A currency conflict is withheld as in the original study, so its
reported rate is not attributed to an untested independent call.

US bearish, crypto bullish/bearish, currency bearish, and
other peer-dependent rules are not yet live: they require fresh, compatible
multi-year asset/peer histories and the exact annual selection procedure.
The crypto study used Yahoo, whereas this app commonly uses Binance and ticker
identity alone is not enough to establish equivalence. Unsupported assets,
sources, missing data and outages are explicitly unavailable. PSE histories
are fetched separately and may still lack the stock-local observations needed
for a call. Philippine bearish peer histories are fetched across the studied
universe, shared between requests for an hour, and not used when too many
fetches fail; a cold fetch can take time. Both Philippine signals can appear
together when their respective rules qualify. This is a partial integration,
not deployment of all researched rules.

Research history is fetched independently of the visible chart. If a
non-PSE research window has fewer than 50 completed bars, the server also
checks the same asset and source in two- and five-year daily histories. It
re-evaluates the original three-month window; older prices outside that window
do not count, and no extra prices are added to the graph. PSE research already
requests the provider's maximum history. Sparse trading, missing bars, outages,
and unsupported rules can still prevent a signal; the page explains why rather
than presenting a missing result as a market call.

When neither research rule signals, the server fetches and caches a longer
history of the same asset and source. With at least six completed monthly
three-calendar-month outcomes, it shows the more frequent direction as an
**asset-history baseline**, with counts of up, down, and unchanged outcomes.
The direction and its frequency come from the same data: this is descriptive,
not out-of-sample forecast accuracy or an individual probability. Overlapping
periods are correlated. The baseline is not a previously researched algorithm
and does not inherit its reported hit rate. Tied direction counts, missing or
stale prices, insufficient history and unknown time zones remain unavailable.
PSE histories and peer snapshots are cached in `.cache/`; other assets use the
existing cached chart-history path. An outage fallback is identified as cached.

The shown decimals are pooled, repeatedly inspected **historical hit rates**,
not probabilities for a particular asset or assurances of future performance.
The research used three-calendar-month price outcomes, not trading returns;
the history has selection and survivorship biases and no costs or dividends.
The Philippine bullish result is particularly unstable across years; the US
bearish candidate had only 13 calls. Applying historical monthly rules to new
conditions remains unvalidated.

#### Further US bearish refinement

`us_bearish_refinement_research.py` tests a model-based filter on the earlier
bearish US momentum/contrarian candidate. It excludes PARA from the complete
US observation and peer inputs and checks that its earlier-candidate replay
matches the saved PARA-free evaluation. Each yearly model trains only on
outcomes completed before a separate two-year validation period; threshold
selection uses earlier completed calls from the previous candidate. It makes
calls only where the previous candidate does and abstains if validation fails
its accuracy, lift and sample requirements. The report records annual choices,
the same-population previous candidate, and the previous candidate in active
test years. The script refuses to overwrite its saved report at
`research/us-bearish-refinement-research.json`.

In the completed 2020–2026 replay, the refinement scored 53.85% (7/13;
0.05% coverage) versus 48.81% (123/252; 1.01% coverage) for the previous
candidate on the same eligible population. In the two years where the new
model made calls, the previous candidate scored 41.51% (22/53). The new model
scored 33.33% (2/6) in 2021 and 71.43% (5/7) in 2026, with no calls in the
other five years. The candidates select different calls; 13 observations over
eight signal months are far too few to establish an improvement, and no block
interval was computed. One additional correct or incorrect result would change
the percentage substantially. Do not substitute this as a validated accuracy.

The years have already been inspected repeatedly, so this is exploratory, not
an independent holdout or a prospective forecast. Monthly outcomes overlap,
present-day listings omit many delisted stocks, historical ticker identity and
corporate actions remain unverified, and previous-local-date peer closes do
not prove availability at the signal time. The app labels remain unchanged.

### Philippine current-trend audit

The app already determines whether a Philippine stock is bullish now through
the shared `trend.classify` on the PSE chart's 90-day price window. The score
combines drift momentum (40%), regression trend (25%), price efficiency (20%),
and range position (15%); it calls bullish at +0.25 or higher *and* a drift
t-statistic of 1.96 or higher (see "The trend badge" below). Volume does not
vote. The audit, like the other research tools, scores with the frozen
version-1 classifier (`trend_v1.py`) its numbers were measured on. The same
classifier and window determine both the chart badge and bullish-table row;
the label describes past prices, not the next three months.

`pse_current_bullish_audit.py` separately audits that existing rule on the saved
PSE histories. It includes only bars before the Manila collection date, requires
at least two prices in the 90-day window, and flags a latest price more than
seven calendar days old; it reports fewer than 50 bars separately. These are
audit-only data checks, not new live inclusion rules. The live chart can include
an unfinished daily bar and fall back to older bars, so the audit and live
verdict can differ. Seven days is a heuristic, not an exchange-calendar check.

On the snapshot collected 2026-10-30, all 244 requested histories were received:
179 had at least 50 bars and a last bar within seven days, 57 had fewer than 50
bars, and eight were stale. Of the 179 full-window series, 17 were bullish, 57
bearish and 105 neutral. All 17 bullish series finished above their first
90-day close; that is a descriptive consistency check, **not** a measured
accuracy or proof of future gains. Full details are saved in
`research/pse-current-bullish-audit.json`; run
`python3 pse_current_bullish_audit.py` on a saved PSE collection to reproduce
it (the script refuses to overwrite an existing report).

#### Philippine bullish and fund bearish forecast filters

`pse_bull_fund_bear_research.py` explores three-month outcome filters for
existing PSE bullish labels and bearish fund calls, without changing the live
trend labels. PSE candidates can only select stocks the existing classifier
already labels bullish. The filter considers trend strength, local completed
outcomes, prior-date peer returns, and volatility. Fund candidates also consider
recent market-wide completed outcomes. Each year the selector uses the prior
two years of completed validation outcomes and abstains unless a rule meets its
minimum sample, accuracy, and baseline-lift gates. The test compares with the
existing PSE bullish label and the prior fund momentum/contrarian local rule on
the same eligible populations, though selected calls differ.

The completed 2020–2026 replay found no established improvement. The PSE
filter scored 45.54% (51/112; 1.09% coverage), versus 44.38% (789/1,778;
17.26% coverage) for all existing bullish calls across that full period. The
filter made calls only in 2025–2026, when all existing bullish calls scored
47.20% (278/589), higher than the filter. The new fund selector scored 33.33%
(223/669; 9.25% coverage); the prior fund rule scored 55.11% (97/176; 2.43%
coverage) on the same eligible population. Calls differ, and the fund result
was highlighted after earlier inspection; it is not independently validated.
The fund universe contains other exchange-traded products, not only ETFs.

These are retrospective, repeatedly inspected monthly observations; missing
and pending outcomes are excluded, the present-day universe omits most
delistings, and peer local dates do not ensure time-of-day availability. They
exclude costs, dividends and an executable entry assumption. The selected
historical percentages are not forecasts for individual stocks or funds.
Full annual results and validation choices are in
`research/pse-bull-fund-bear-research.json`; the script refuses to overwrite
the report. Future prospective testing is needed before deploying a filter.

`selective_bull_bear_research.py` tries narrower rolling filters: all PSE calls
must already be bullish under the app's shared classifier, and all fund calls
must already pass the earlier momentum/contrarian local rule. Each signal date
selects a filter using only the prior 36 months of already completed calls,
with sample-size, observed-hit-rate and baseline-lift requirements. The script
saves `research/selective-bull-bear-research.json`, including selection dates,
annual results and comparisons on the same dates. It refuses to overwrite the
report.

On the 2020–2026 population the rolling PSE candidate scored 44.44% (84/189;
1.83% coverage), compared with 44.38% (789/1,778; 17.26% coverage) for the
existing bullish labels across all dates and 43.18% (519/1,202) for those labels
on dates when the selector was active. Its results varied by year: 57.45% on
47 calls in 2024, 51.43% on 35 in 2025 and 31.82% on 22 in 2026. The rolling
fund candidate scored 53.12% (17/32; 0.44% coverage), versus 55.11% (97/176;
2.43%) for the earlier fund rule across all dates and 61.02% (36/59) on active
dates. The selected calls differ. These scores do not establish an improvement,
especially given the very small fund sample, overlapping calls, repeated
historical selection and lack of a prospective holdout; no app labels changed.

`pse_bullish_model_research.py` fits a regularized model only to past app
bullish labels and selects thresholds on an earlier validation period. It
scored 28.57% (16/56; 0.54% coverage) on 2020–2026; the app's bullish labels
scored 47.20% (278/589) in its active 2025–2026 test years. It is not an
improvement. Its annual diagnostics are in
`research/pse-bullish-model-research.json`.

`pse_bullish_local_research.py` instead evaluates stock-local filters on the
same actual app bullish labels, using only outcomes completed strictly before
each signal. The local regime filter requires 24 prior completed outcomes and
six observations matching the stock's current price-feature regime; it shrinks
that regime's historical positive-outcome rate toward the stock's recency-
weighted overall rate and calls only when the score is at least 55%. It scored
52.47% (117/223; 2.16% coverage) across the 2020–2026 eligible population,
versus 44.38% (789/1,778; 17.26%) for all bullish labels. The subsets differ.
An approximate 90% time-block interval for the local filter is 46.44%–60.09%,
and does not correct for research selection. Results by year were 33.33% (1/3)
in 2023, 61.05% (58/95) in 2024, 50.63% (40/79) in 2025, and 39.13% (18/46)
in the available 2026 outcomes; no calls occurred in 2020–2022. A neighbor
filter and intersection are also reported in
`research/pse-bullish-local-research.json`. These are post-inspection,
exploratory comparisons, not a probability for an individual stock or evidence
of a stable future edge. The app's labels remain unchanged.

### Philippine three-month outcome study

`pse_backtest.py` collected split-adjusted TradingView daily bars for 244
currently listed PSE equities. It tests signals on the first available session
of each month, buying at the next session's open and measuring the closing
price on or after three calendar months. Signals before 2025 are development;
the 2025-onward holdout is separated by an outcome embargo. All comparisons
require at least 252 previous bars and recent six- and twelve-month prices.

In the holdout, the current bullish signal had 614 observations: **46.42%**
finished above entry and **5.86%** stayed bullish on every available bar.
Requiring the price to be above both its six- and twelve-month reference prices
gave 476 observations: **47.90%** finished above entry and **6.30%** stayed
bullish. These are descriptive historical frequencies, not probabilities for
an individual stock. Observations overlap, the universe excludes delisted
stocks, returns exclude dividends and costs, and opening prices may not be
achievable. The test does not establish a reliable three-month predictor.

The PSE chart still draws only three months. It fetches additional history
privately for six- and twelve-month context, based on completed daily bars;
stale or insufficient history is marked unavailable. This context is not a
second bullish classifier, a promise, or an estimate of future returns. The
full report and raw data are `research/pse-backtest.json` and
`research/pse-history.json`. Rerun with `python3 pse_backtest.py collect`
then `python3 pse_backtest.py evaluate` (Moli and an internet connection are
needed to collect). The displayed historical percentages are a fixed snapshot
of this study, not automatically updated by re-running it.

**Version 2 (2026-10-31).** One score in `[-1, +1]` over **every bar the chart
draws** — 93 for a coin, 65 for a US stock, 38 for a thin PSE name:

| Weight | Signal | What it measures |
|---|---|---|
| 0.40 | momentum | The window's drift as a t-statistic: weighted mean log return over its standard error |
| 0.25 | trend | Weighted log-price regression slope × R2, normalized to a 30% window move |
| 0.20 | efficiency | Weighted net move over weighted path length — how directly price traveled |
| 0.15 | range | Where the last close sits in the window's low-to-high range |

A label needs **evidence**, and once given it **holds**:

| Band | Condition | Effect |
|---|---|---|
| enter | score ≥ 0.25 **and** drift t ≥ 1.96 | Bullish (mirror for Bearish) |
| hold | score ≥ 0.15 and drift t ≥ 1.0 | keeps a label that entered within the last 10 bars, through an unbroken run (`held: true`, confidence "holding") |
| — | anything else | Neutral |

- **Returns are ramp-weighted**: the oldest quarter of the window phases in,
  so the bar leaving the window barely moves the call.
- **Short windows need more evidence, not a damping curve**: the t is read
  against the Student-t critical value for the bars there are, so a 9-bar
  window needs a stronger drift than a 63-bar one to clear 1.96. Fewer than 3
  closes read Neutral; a perfectly straight run gets a label from 4 closes, and
  noisy series need more.
- **Stale prints don't pass for a trend**: positive day-to-day correlation
  (a thin name repeating its price) widens the standard error.

Measured on the saved history (74 instruments, ~37,000 three-month windows),
version 1 → version 2:

| | v1 | v2 |
|---|---|---|
| Driftless random walks labelled | 49% | ~8% |
| Label changes per 100 bars | 8.1 | 0.8 |
| Changes reversed within 5 bars | 59% | 24% |
| A one-sigma move in the newest close changes the label | 9.3% | 0.4% |
| Dropping the oldest bar changes the label | 3.4% | 0.6% |

The cost of strictness: a real but modest trend is labelled less often — a
+0.25%/day drift in 1.5%/day noise is caught in ~30% of 63-bar windows — and
on real data ~5% of windows carry a label (v1: ~47%). **Neutral means "no
trend random movement would rarely produce", not "flat".** The payload carries
`significance` (the drift t) and `held` beside the label, and the page prints
both.

**The badge describes the observed price trend, not a forecast, probability,
or buy recommendation.** Version 1 lives on, frozen, as `trend_v1.py`, only
because the research models were fitted on its score scale. Details are in
the `trend.py` docstring.

### The pullback tag (2026-11-16)

A label can stay while the newest bars run against it: on the saved history
(74 instruments, 179,183 windows) 30% of labelled windows had the last 10 bars
against the label, and 21% were also on the wrong side of the 20-bar average.
That is the hold band doing its job, so the label is left alone and the badge
says what the last two weeks did instead: **"Bullish, pulling back"** or
**"Bearish, bouncing"**.

- `trend.pullback(closes, sign)` is true when the newest close is past the
  close `PULLBACK_BARS` (10) bars ago the wrong way **and** on the wrong side
  of the mean of the last `PULLBACK_AVG` (20) closes. Both, on a labelled
  window of at least 20 bars; never on a neutral one.
- It ships as `pullback` on the `trend` payload and on every recent-table
  row (through `onset.onset`), so a row and the chart it opens say it together.
- It never earns, removes or delays a label, and it is not a forecast.
- A bond chart's badge is the price reading of the yield, so a falling-yield
  "Bullish" whose yield rose for two weeks reads "pulling back".
- Checked in the same study and left alone: the four-signal score almost never
  decides a label (of 6,003 windows that passed the entry drift test, none
  failed the entry score; of 52,456 past the hold drift bar, 3 failed the hold
  score), and one outsized day hid a label in 96 of ~168,000 neutral windows.
