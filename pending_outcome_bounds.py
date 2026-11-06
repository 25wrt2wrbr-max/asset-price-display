#!/usr/bin/env python3
"""Descriptive best/worst bounds for reconstructed, unresolved outcomes.

These are arithmetic extremes, not forecasts, confidence intervals, or an
independent test. Pending records have unknown outcomes and must not be
classified as losses or successes.
"""
from __future__ import annotations

import json

import forecast_validation as fv

SOURCE = fv.ROOT / "research" / "outcome-availability-audit.json"
REPORT = fv.ROOT / "research" / "pending-outcome-bounds.json"
PENDING = ("not_due", "within_exit_grace", "matured_missing", "invalid_exit_price")


def summarize(statuses):
    observed = statuses.get("observed", {})
    n = observed.get("rule_calls", 0)
    correct = observed.get("observed_correct", 0)
    if n < 0 or correct < 0 or correct > n:
        raise ValueError("invalid observed counts")
    unresolved = {status: statuses.get(status, {}).get("rule_calls", 0) for status in PENDING}
    if any(value < 0 for value in unresolved.values()):
        raise ValueError("invalid unresolved count")
    unknown = sum(unresolved.values())
    total = n + unknown
    return {"observed_calls": n, "observed_correct": correct,
            "observed_hit_pct": round(100 * correct / n, 2) if n else None,
            "unresolved_calls": unresolved, "all_calls": total,
            "all_unresolved_miss_pct": round(100 * correct / total, 2) if total else None,
            "all_unresolved_correct_pct": round(100 * (correct + unknown) / total, 2) if total else None,
            "additional_correct_needed_for_51_pct": max(0, (51 * total + 99) // 100 - correct) if total else None,
            "target_possible": correct + unknown >= (51 * total + 99) // 100 if total else None}


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    report = {"as_of_utc_date": raw["as_of_utc_date"],
              "method": "Arithmetic extremes for the selected retrospectively reconstructed calls: combine observed correct counts with all unresolved calls hypothetically wrong or hypothetically right. Flat outcomes are misses. Count minimum additional correct outcomes needed for at least 51% over combined calls. Unresolved outcomes are never classified as wins or losses.",
              "limitations": ["These are worst/best arithmetic scenarios, not confidence intervals, forecasts, or prospective validation. The reconstructed calls were not necessarily made at their signal dates.",
                              "Matured-missing and invalid outcomes may never resolve; future outcomes may not fall within exit grace. Current listing survivorship, identity and corporate actions, cross-timezone timing, and repeated model selection remain unresolved."],
              "markets": {market: summarize(result["statuses"]) for market, result in raw["markets"].items()}}
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
