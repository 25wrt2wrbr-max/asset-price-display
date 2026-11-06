#!/usr/bin/env python3
"""Audit the existing present-trend bullish label on saved PSE histories.

This is a descriptive snapshot, not a new classifier or a future-price test.
Only bars before the collection date in Manila are used, avoiding an assumed
completion time for a same-day bar. Data-quality filters are audit diagnostics,
not changes to live chart or table inclusion rules.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from collections import Counter
from zoneinfo import ZoneInfo

import forecast_validation as fv
import onset
import trend

REPORT = fv.ROOT / "research" / "pse-current-bullish-audit.json"
MANILA = ZoneInfo("Asia/Manila")
MAX_STALE_DAYS = 7  # Calendar-day audit warning, not an exchange calendar.


def inspect(symbol, rows, as_of):
    """Describe the existing classifier, or explain why data is unavailable."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    local_day = as_of.astimezone(MANILA).date()
    valid = {}
    malformed = 0
    for row in rows:
        try:
            stamp, close = int(row[0]), float(row[2])
            if not math.isfinite(close) or close <= 0:
                raise ValueError("invalid close")
            day = dt.datetime.fromtimestamp(stamp, MANILA).date()
        except (ValueError, TypeError, IndexError, OverflowError, OSError):
            malformed += 1
            continue
        if day < local_day and stamp <= as_of.timestamp():
            valid.setdefault(stamp, close)
    ordered = sorted(valid.items())
    cutoff = as_of.timestamp() - onset.WINDOW_DAYS * onset.DAY
    used = [(stamp, close) for stamp, close in ordered if stamp >= cutoff]
    base = {"symbol": symbol, "bars": len(used), "malformed_rows": malformed}
    if len(used) < 2:
        return {**base, "status": "insufficient_window", "trend": None}
    latest_day = dt.datetime.fromtimestamp(used[-1][0], MANILA).date()
    age = (local_day - latest_day).days
    if age > MAX_STALE_DAYS:
        return {**base, "status": "stale", "last_date": latest_day.isoformat(),
                "age_days": age, "trend": None}
    verdict = trend.classify([close for _, close in used])
    return {**base, "status": "ok" if len(used) >= trend.MIN_BARS else "short_window",
            "last_date": latest_day.isoformat(), "age_days": age,
            "first_close": used[0][1], "last_close": used[-1][1], "trend": verdict}


def evaluate(data):
    as_of = dt.datetime.fromisoformat(data["collected_at"])
    bars = data["bars"]
    symbols = sorted(set(data["universe"]) | set(bars))
    rows = [inspect(symbol, bars.get(symbol, []), as_of) for symbol in symbols]
    status = Counter(row["status"] for row in rows)
    labels = Counter(row["trend"]["label"] for row in rows if row["trend"])
    full = [row for row in rows if row["status"] == "ok"]
    full_labels = Counter(row["trend"]["label"] for row in full)
    bullish = [row for row in full if row["trend"]["label"] == "bullish"]
    return {"as_of": as_of.isoformat(), "source": data.get("source"),
            "method": "Snapshot uses bars dated before collection day in Asia/Manila and within the chart's trailing 90 calendar days. Applies trend.classify unchanged. Reports >=50 bars and <=7 calendar days since last bar as audit data-quality checks; shorter series are separately scored and stale/missing series are unavailable in this audit, not necessarily in the live app. A bullish label is present price trend, not an outcome forecast. The seven-day heuristic is not an exchange calendar.",
            "limitations": ["Saved histories cover current selected listings, not a point-in-time complete universe. Some bars may be revised; a timestamp alone cannot prove data quality.",
                            "No independent ground-truth labels exist here: price-change agreement is descriptive, not classifier accuracy. This does not establish future returns.",
                            "The live chart may include a current partial bar and can fall back to old bars; this conservative completed-bar snapshot intentionally differs from live behavior."],
            "requested": len(symbols), "received": len(bars), "status": dict(status),
            "all_scorable_labels": dict(labels), "full_window_labels": dict(full_labels),
            "full_bullish_net_rising": sum(row["last_close"] > row["first_close"] for row in bullish),
            "rows": rows}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    data = json.loads(fv.DATA.read_text(encoding="utf-8"))
    report = evaluate(data)
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))


if __name__ == "__main__":
    main()
