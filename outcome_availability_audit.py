#!/usr/bin/env python3
"""Audit observed and unresolved signals without fabricating outcomes.

Reconstruct input-valid first-of-month signals, including those omitted by the
historical observation builder for missing outcomes. Scores use strictly
completed prior outcomes. This retrospective audit is not a live forecast or
an independent validation; unresolved outcomes remain unknown.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
from collections import defaultdict
from zoneinfo import ZoneInfo

import asset_local_forecast_research as local
import forecast_extended_validation as previous
import forecast_validation as fv
import market_forecasts as model
import onset
import regime_gate_forecast_research as regime
import relative_forecast_research as relative
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "outcome-availability-audit.json"
START_YEAR = 2020


def outcome_status(day, target, exit_date, exit_price, as_of):
    """Classify without inventing losses or declaring still-pending data missing."""
    if exit_date is not None and exit_date <= as_of and (exit_date - target).days <= fv.MAX_DELAY:
        return "observed" if math.isfinite(exit_price) and exit_price > 0 else "invalid_exit_price"
    if target > as_of:
        return "not_due"
    if as_of < target + dt.timedelta(days=fv.MAX_DELAY):
        return "within_exit_grace"
    return "matured_missing"


def reconstruct(data, as_of):
    """Rebuild valid-input monthly signals, whether or not an exit exists."""
    result, skipped = [], defaultdict(int)
    for symbol, rows in sorted(data["bars"].items()):
        zone = ZoneInfo(data.get("timezones", {}).get(symbol, "UTC"))
        stamps = [int(row[0]) for row in rows]
        prices = [float(row[2]) for row in rows]
        dates = [dt.datetime.fromtimestamp(t, zone).date() for t in stamps]
        seen = set()
        for i, day in enumerate(dates):
            month = (day.year, day.month)
            if month in seen:
                continue
            seen.add(month)
            if day.year < START_YEAR or day > as_of:
                continue
            start = bisect.bisect_left(stamps, onset.months_back(stamps[i], 3), 0, i + 1)
            if i - start + 1 < fv.MIN_WINDOW_BARS:
                skipped["short_window"] += 1
                continue
            try:
                six = targeted.reference(dates, prices, i, 6)
                year = targeted.reference(dates, prices, i, 12)
                if six is None or year is None:
                    skipped["insufficient_long_history"] += 1
                    continue
                features = model.features(prices[start:i + 1])
            except (ValueError, OverflowError):
                skipped["invalid_input"] += 1
                continue
            target = fv.months_after(day, 3)
            end = bisect.bisect_left(dates, target, lo=i + 1)
            exit_date = dates[end] if end < len(rows) else None
            exit_price = prices[end] if end < len(rows) else None
            status = outcome_status(day, target, exit_date, exit_price, as_of)
            sample = {"symbol": symbol, "date": day, "target": target,
                      "features": features, "status": status}
            if status == "observed":
                sample["exit"] = exit_date
                sample["outcome"] = (exit_price > prices[i]) - (exit_price < prices[i])
            result.append(sample)
    return result, dict(skipped)


def analyze(data, market, direction, as_of):
    signals, skipped = reconstruct(data, as_of)
    completed = [s for s in signals if s["status"] == "observed"]
    # The existing builder contains older pre-2020 observations needed to
    # reconstruct point-in-time local scores and market gates.
    old, _ = targeted.observations(data)
    original_keys = {(s["symbol"], s["date"], s["exit"], s["outcome"]) for s in old if s["date"].year >= START_YEAR}
    new_keys = {(s["symbol"], s["date"], s["exit"], s["outcome"]) for s in completed}
    if original_keys != new_keys:
        raise ValueError(f"{market}: observed signal reconstruction does not match historical builder")
    by_symbol = defaultdict(list)
    for s in old:
        by_symbol[s["symbol"]].append(s)
    prepared = relative.prepare_bars(data["bars"], data.get("timezones", {}))
    peer_cache, gate_cache = {}, {}
    counts = defaultdict(lambda: defaultdict(lambda: {"input_valid": 0, "local_eligible": 0, "rule_calls": 0, "observed_correct": 0}))
    target_outcome = 1 if direction == "bullish" else -1
    for s in signals:
        month = s["date"].strftime("%Y-%m")
        bucket = counts[month][s["status"]]
        bucket["input_valid"] += 1
        estimate = local.estimate(by_symbol[s["symbol"]], s, direction)
        if estimate is None:
            continue
        bucket["local_eligible"] += 1
        day = s["date"]
        if day not in peer_cache:
            peer_cache[day] = relative.peer_returns(prepared, day)
            gate_cache[day] = regime.market_gate(old, day, direction)
        peer = relative.relative_features(s, peer_cache[day])
        gate = gate_cache[day]
        rank = peer[1] if peer is not None else None
        if rank is None or gate is None:
            continue
        rank_pass = rank >= .75 if market == "currency" or direction == "bullish" else rank <= .25
        if estimate["score"] >= local.CALL_THRESHOLD and rank_pass and gate < regime.GATE_THRESHOLD:
            bucket["rule_calls"] += 1
            if s["status"] == "observed" and s["outcome"] == target_outcome:
                bucket["observed_correct"] += 1
    aggregates = defaultdict(lambda: {"input_valid": 0, "local_eligible": 0, "rule_calls": 0, "observed_correct": 0})
    for statuses in counts.values():
        for status, bucket in statuses.items():
            for key, value in bucket.items():
                aggregates[status][key] += value
    # Correct counts are meaningful only for observed outcomes.
    for statuses in list(counts.values()) + [aggregates]:
        for status, bucket in statuses.items():
            if status != "observed":
                bucket.pop("observed_correct")
    return {"observed_reconstruction_matches": True, "input_skipped": skipped,
            "statuses": dict(aggregates), "monthly": {month: dict(statuses) for month, statuses in sorted(counts.items())}}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    as_of = dt.datetime.fromisoformat(raw["collected_at"]).date()
    report = {"as_of_utc_date": as_of.isoformat(),
              "method": "Reconstruct monthly signals with valid three-month price windows and six/twelve-month references even if the three-month outcome is not yet observable. Recompute the selected local+peer+contrarian rule using only completed historical outcomes and prior-local-date peer data. Classify exit outcomes as observed, not yet due, within the ten-day exit grace, matured missing, or invalid exit. Report calls on unresolved cases without assigning correctness. Verify observed cases match the original builder. Counts cover signals from 2020 through the saved dataset's collection date; local-history eligibility remains required.",
              "limitations": ["Retrospective reconstruction and present-day selected universe do not recover delisted or uncollected assets, and are not point-in-time identity or split verification.",
                              "Saved data can contain gaps or stale histories. UTC collection date is used as the global as-of date; latest completed close and local day can differ by timezone. Some unresolved data may reflect vendor or corporate-action issues.",
                              "The gate and local historical features still depend on observable completed outcomes, so the audit exposes but does not remove outcome-selection bias. Peer prior local dates do not prove time-zone availability; Yahoo crypto is not Binance. Rules were selected after inspecting years; no future accuracy claim."],
              "markets": {}}
    for market, direction in targeted.TASKS.items():
        names = [s for s, category in raw["universe"].items() if category == market and not (market == "us_equity" and s == "PARA")]
        subset = dict(raw)
        subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
        print(f"Auditing {market} {direction}: {len(subset['bars'])} histories", flush=True)
        result = analyze(subset, market, direction, as_of)
        result.update({"received": len(subset["bars"]), "requested": len(names),
                       "excluded": ["PARA"] if market == "us_equity" else []})
        report["markets"][market] = result
        print(json.dumps({"market": market, "statuses": result["statuses"],
                          "recent_months": {k: v for k, v in result["monthly"].items() if k >= "2026-06"}}, indent=2), flush=True)
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
