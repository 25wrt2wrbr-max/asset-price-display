# Long-term test: does version 2 behave the same on data it never saw?

**DO NOT DELETE OR "CLEAN UP" THIS PAGE, `lab/holdout_stability.py`, OR
`tests/test_long_term_test.py`.** This test cannot be rebuilt later: its whole
value is that the new bars were hidden while the thresholds were chosen.

## The idea

A *holdout* is data kept out of sight while rules are tuned, then used once to
check them. Version 2's thresholds were tuned on `research/market-history.json.gz`
(collected 2026-10-30). Prices dated **after 2026-10-30** were never seen, so
they are the holdout. They arrive on their own; nothing has to be logged.

The label describes the chart and never predicts, so this checks that the
label *behaves the same*. It does not test returns.

## Baseline to compare against (tuning-era data, run 2026-11-23)

| Measure | Value |
|---|---|
| Windows that carry a label | about 6% (early era 6.5%, late era 5.8%) |
| Label changes per 100 bars | about 0.9 (early 0.96, late 0.84) |

## How to run it

1. Not before about **2026-12-30** (a month of new bars; more is better).
2. Refresh the history. `lab/forecast_collect.py` rewrites
   `research/market-history.json.gz` from 2006 on, through Moli. It is a
   lab script that overwrites a report, so back up the old file first. Adjusted
   prices can shift slightly when a dividend lands; that is expected.
3. Run `python3 lab/holdout_stability.py --since 2026-10-30`.
4. Compare with the baseline above. Close (label share within about 2 points,
   flips within about 0.3 per 100 bars) means version 2 held on unseen data.
   Far off means the thresholds were fitted to the past; log it in
   `docs/variants-tried.md` and rethink.

## Rules

- **Run it once per set of thresholds.** If the result is disliked and the
  thresholds change, those bars are no longer hidden. Wait for fresh bars and
  move the `--since` date forward to the day of the change.
- Record every run's date and numbers below.

## Runs

| Date | `--since` | New bars | Labelled | Changes per 100 | Verdict |
|---|---|---|---|---|---|
| (none yet) | 2026-10-30 | | | | |
