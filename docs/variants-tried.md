# Classifier variants tried

Keep every variant here, including the ones dropped. Picking the best of many
tries flatters the winner even when none has a real edge, so the count of
tries belongs next to the result. Append a row for each new variant or
threshold change before judging it.

All figures are on `research/market-history.json.gz` (74 assets, collected
2026-10-30). That file was seen while thresholds were chosen, so these are
tuning-era numbers, not holdout numbers.

| Version | What changed | Labelled share (driftless random walks) | Label changes per 100 bars | Newest-close one-sigma nudge flips label |
|---|---|---|---|---|
| v1 (`trend_v1.py`, frozen) | 63-bar window, `sqrt(n/50)` damping, bare ±0.25 score | 49% | 8.1 | 9.3% |
| v2 (`trend.py`) | score ≥ 0.25 and drift t ≥ 1.96, hold band 0.15 / t ≥ 1.0 for 10 bars, ramped weights, whole window | ~8% | 0.8 | 0.4% |

Only two full versions are recorded because earlier intermediate threshold
trials were not logged. From now on, log each one here.

## Consistency check across eras

`python3 lab/holdout_stability.py` splits each asset's own history 70/30 and
compares the two eras (63-bar windows, every bar). Run 2026-11-23:

| Era | Windows | Labelled | Bullish | Bearish | Changes per 100 bars |
|---|---|---|---|---|---|
| Early 70% | 249,632 | 6.5% | 4.6% | 1.9% | 0.96 |
| Late 30% | 109,069 | 5.8% | 4.6% | 1.3% | 0.84 |

The label rate and the flicker rate hold in the later era. This is a
consistency check only. A true holdout is bars collected after the file's
`collected_at`; refresh the history, then compare those bars alone. The label
describes the chart and never predicts, so no returns are tested here.
