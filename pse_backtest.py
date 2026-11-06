#!/usr/bin/env python3
"""Collect PSE history and evaluate fixed, pre-specified 3-month signals.

Usage: python3 pse_backtest.py collect
       python3 pse_backtest.py evaluate

The study uses currently listed shares, split-adjusted TradingView bars, and
monthly signals. It is not a point-in-time universe and excludes dividends.
The holdout and strategy definitions are fixed in advance; nothing is fitted
to holdout results. See reports/pse-backtest.json for full limitations.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import pathlib
import sys
from zoneinfo import ZoneInfo

import bullish
import onset
import pse
import trend_v1 as trend  # frozen: research models were fitted on its score scale

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "research" / "pse-history.json"
REPORT = ROOT / "research" / "pse-backtest.json"
MANILA = ZoneInfo("Asia/Manila")
HOLDOUT = dt.date(2025, 1, 1)
MAX_EXIT_DELAY = 10  # calendar days after the three-calendar-month target
LOOKBACK = 252


def _day(timestamp):
    return dt.datetime.fromtimestamp(timestamp, MANILA).date()


def _months_after(day, months):
    month = day.month + months
    year = day.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    import calendar
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def collect():
    # Import registers the existing Moli runners; no HTTP shortcut for history.
    import server  # noqa: F401
    today = dt.datetime.now(MANILA).date()
    universe = [r for r in pse.stocks_index()["ordered"] if r.get("kind") == "EQUITY"]
    symbols = sorted({r["symbol"] for r in universe})
    series = pse.history_many(symbols, count=pse.MAX_BARS, chunk=20, workers=4)
    # Last session is excluded if it is today's: a daily candle may still be
    # in progress, and outcomes must be known at the time of the study.
    clean = {}
    for symbol, rows in series.items():
        seen = set()
        out = []
        for row in rows:
            try:
                stamp, opening, close = int(row[0]), float(row[1]), float(row[4])
                volume = float(row[5]) if len(row) > 5 and row[5] is not None else None
                if stamp in seen or _day(stamp) >= today or not all(
                        math.isfinite(x) and x > 0 for x in (opening, close)):
                    continue
                seen.add(stamp)
                out.append([stamp, opening, close, volume])
            except (TypeError, ValueError, IndexError, OverflowError):
                continue
        out.sort(key=lambda x: x[0])
        if out:
            clean[symbol] = out
    DATA.parent.mkdir(parents=True, exist_ok=True)
    data = {"collected_at": dt.datetime.now(MANILA).isoformat(),
            "source": "TradingView PSE daily bars, split adjusted",
            "universe": symbols, "missing": sorted(set(symbols) - set(clean)),
            "bars": clean}
    DATA.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"Saved {len(clean)}/{len(symbols)} series to {DATA}; {len(data['missing'])} missing")


def summarize(samples):
    returns = [s["return"] for s in samples]
    if not returns:
        return {"n": 0}
    ordered = sorted(returns)
    n = len(returns)
    persistent = [s["persistent"] for s in samples if "persistent" in s]
    result = {"n": n, "stocks": len({s['symbol'] for s in samples}),
            "months": len({s['date'][:7] for s in samples}),
            "positive_pct": round(100 * sum(r > 0 for r in returns) / n, 2),
            "mean_return_pct": round(100 * sum(returns) / n, 2),
            "median_return_pct": round(100 * (ordered[(n-1)//2] + ordered[n//2]) / 2, 2),
            "loss_over_10_pct": round(100 * sum(r <= -.10 for r in returns) / n, 2)}
    if persistent:
        result["continuously_bullish_pct"] = round(100 * sum(persistent) / len(persistent), 2)
    return result


def evaluate(data):
    groups = {period: {name: [] for name in (
        "all", "bullish_3m", "bullish_3m_6m_up", "bullish_3m_12m_up",
        "bullish_3m_6m_12m_up")} for period in ("development", "holdout")}
    skipped = {"insufficient_history": 0, "incomplete_outcome": 0}
    evaluated = []
    examples = {}
    for symbol, rows in sorted(data["bars"].items()):
        stamps = [int(r[0]) for r in rows]
        opens = [float(r[1]) for r in rows]
        closes = [float(r[2]) for r in rows]
        dates = [_day(t) for t in stamps]
        seen_months = set()
        label_cache = {}

        def historical_label(index):
            if index not in label_cache:
                ids = onset.window(stamps, index, stamps[index])
                label_cache[index] = trend.classify([closes[j] for j in ids])["label"]
            return label_cache[index]

        for i, day in enumerate(dates):
            month = day.year, day.month
            if month in seen_months:
                continue
            seen_months.add(month)
            # Same minimum history for all rules, so comparisons share a base.
            if i < LOOKBACK:
                skipped["insufficient_history"] += 1
                continue
            target = _months_after(day, 3)
            end = bisect.bisect_left(dates, target, lo=i + 1)
            if (i + 1 >= len(rows) or (dates[i + 1] - day).days > MAX_EXIT_DELAY
                    or end >= len(rows) or (dates[end] - target).days > MAX_EXIT_DELAY):
                skipped["incomplete_outcome"] += 1
                continue
            # No development outcome is allowed to overlap the holdout.
            if day < HOLDOUT <= dates[end]:
                continue
            indices = onset.window(stamps, i, stamps[i])
            if len(indices) < 30:
                continue
            six_date, year_date = _months_after(day, -6), _months_after(day, -12)
            six_index = bisect.bisect_right(dates, six_date, 0, i) - 1
            year_index = bisect.bisect_right(dates, year_date, 0, i) - 1
            if (six_index < 0 or year_index < 0 or
                    (six_date - dates[six_index]).days > MAX_EXIT_DELAY or
                    (year_date - dates[year_index]).days > MAX_EXIT_DELAY):
                skipped["insufficient_history"] += 1
                continue
            call = trend.classify([closes[j] for j in indices])
            sample = {"symbol": symbol, "date": day.isoformat(),
                      "return": closes[end] / opens[i + 1] - 1}
            if symbol in ("PSE:SPNEC", "PSE:SMC"):
                examples.setdefault(symbol, []).append(sample)
            period = "holdout" if day >= HOLDOUT else "development"
            g = groups[period]
            g["all"].append(sample)
            if call["label"] == "bullish":
                sample = dict(sample)
                sample["persistent"] = all(historical_label(j) == "bullish"
                                           for j in range(i + 1, end + 1))
                g["bullish_3m"].append(sample)
                six_up = closes[i] > closes[six_index]
                year_up = closes[i] > closes[year_index]
                if six_up:
                    g["bullish_3m_6m_up"].append(sample)
                if year_up:
                    g["bullish_3m_12m_up"].append(sample)
                if six_up and year_up:
                    g["bullish_3m_6m_12m_up"].append(sample)
            evaluated.append(day)
    return {
        "collected_at": data["collected_at"],
        "source": data["source"],
        "universe_requested": len(data["universe"]),
        "series_received": len(data["bars"]), "missing": data["missing"],
        "sample_start": min(evaluated).isoformat() if evaluated else None,
        "sample_end": max(evaluated).isoformat() if evaluated else None,
        "holdout_start": HOLDOUT.isoformat(), "skipped": skipped,
        "example_stock_results": {symbol: {
            period: summarize([s for s in samples if (s["date"] >= HOLDOUT.isoformat()) == (period == "holdout")])
            for period in ("development", "holdout")}
            for symbol, samples in examples.items()},
        "method": "First available session each month; signal at close, enter next available session open, exit close on or after three calendar months. Gross split-adjusted price returns; no dividends, fees, tax or slippage. Minimum 252 prior bars for every rule.",
        "limitations": ["Current listed universe: survivorship and selection bias; delisted stocks are missing.",
                        "Monthly observations overlap and stocks share market shocks; counts are not independent.",
                        "Next-session open may not be achievable, especially for illiquid shares; results exclude all transaction costs and dividends.",
                        "Signal is based on historical daily closes, not the unfinished current session.",
                        "Continuous bullishness requires the same historical label on every available bar through the exit; missing trading sessions can hide changes. A positive return is a different outcome, and neither guarantees the future.",
                        "The holdout begins 2025-01-01, but data after it is used for outcome measurement; this is one retrospective holdout, not a prospective trial."],
        "results": {period: {name: summarize(samples) for name, samples in rules.items()}
                    for period, rules in groups.items()},
    }


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("collect", "evaluate"):
        raise SystemExit("Usage: python3 pse_backtest.py collect|evaluate")
    if sys.argv[1] == "collect":
        collect()
    else:
        data = json.loads(DATA.read_text(encoding="utf-8"))
        result = evaluate(data)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
