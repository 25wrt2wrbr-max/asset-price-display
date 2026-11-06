#!/usr/bin/env python3
"""Rebuild US peer/regime experiment with and without the PARA ticker.

This is a retrospective sensitivity audit, not identity verification or an
independent validation. Excluding a symbol after seeing results is hindsight.
"""
from __future__ import annotations

import json

import forecast_extended_validation as previous
import forecast_validation as fv
import peer_regime_forecast_research as peer_regime
import relative_forecast_research as relative
import targeted_forecast_research as targeted

REPORT = fv.ROOT / "research" / "us-symbol-sensitivity-research.json"
EXCLUDED = "PARA"


def evaluate_subset(raw, exclude):
    names = [s for s, market in raw["universe"].items() if market == "us_equity" and s not in exclude]
    subset = dict(raw)
    subset["bars"] = {s: raw["bars"][s] for s in names if s in raw["bars"]}
    samples, skipped = targeted.observations(subset)
    prepared = relative.prepare_bars(subset["bars"], raw.get("timezones", {}))
    result = peer_regime.evaluate_samples(samples, "bearish", prepared)
    result.update({"requested": len(names), "received": len(subset["bars"]),
                   "observation_n": len(samples), "skipped": skipped})
    return result


def main():
    if REPORT.exists():
        raise FileExistsError(f"Refusing to overwrite {REPORT}")
    raw = json.loads(previous.DATA.read_text(encoding="utf-8"))
    if EXCLUDED not in raw["bars"] or raw["universe"].get(EXCLUDED) != "us_equity":
        raise ValueError("PARA is not present in the original US equity dataset")
    print("Replaying original US sample", flush=True)
    original = evaluate_subset(raw, set())
    previous_report = json.loads((fv.ROOT / "research" / "peer-regime-forecast-research.json").read_text(encoding="utf-8"))
    expected = previous_report["markets"]["us_equity"]["momentum_contrarian"]
    actual = original["momentum_contrarian"]
    if (actual["n"], actual["correct"], original["test_n"]) != (expected["n"], expected["correct"], previous_report["markets"]["us_equity"]["test_n"]):
        raise ValueError("Original replay does not match the previously saved report")
    print("Rebuilding US sample without PARA", flush=True)
    excluded = evaluate_subset(raw, {EXCLUDED})
    report = {"method": "Rebuild the US equity observation set, local-history features, market-wide gate and peer ranks with PARA present and with PARA entirely excluded. Recompute all other calls and eligible denominators. Confirm original replay matches earlier report. Signal close versus first available close on or after three calendar months; unchanged outcomes count as misses.",
              "limitations": ["Excluding PARA was chosen after inspecting historical results; this is a post-selection sensitivity audit, not an independent or prospective test.",
                              "This does not verify corporate-action adjustment, historical ticker identity, or the integrity of other symbols. Previous-local-date peer closes do not guarantee cross-timezone availability.",
                              "Current selected listings omit many delisted assets; future outcome availability filters the sample, outcomes overlap and assets share shocks. No costs, slippage or executable same-close entry are assumed."],
              "excluded_symbol": EXCLUDED, "original_replay_matches": True,
              "original": original, "without_symbol": excluded}
    with REPORT.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({name: {"test_n": result["test_n"], "momentum_contrarian": result["momentum_contrarian"],
                              "asset_local": result["asset_local"]}
                      for name, result in (("original", original), ("without_symbol", excluded))}, indent=2))


if __name__ == "__main__":
    main()
