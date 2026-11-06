#!/usr/bin/env python3
"""Research-only asset judgments alongside, never instead of, chart trends.

Historical hit rates are not individual probabilities. Models are frozen
historical folds, and unavailable inputs must not become negative verdicts.
"""
from __future__ import annotations

import datetime as dt
import bisect
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import asset_local_forecast_research as local
import forecast_validation as fv
import market_forecasts
import onset
import trend_v1 as trend  # frozen: research models were fitted on its score scale

ROOT = Path(__file__).resolve().parent
_references = None
TOO_FEW_WINDOW_BARS = "Fewer than 50 completed bars in the research window"


def references():
    """Load the saved study universe and frozen annual folds on demand."""
    global _references
    if _references is None:
        def load(name):
            with (ROOT / "research" / name).open(encoding="utf-8") as f:
                return json.load(f)
        history = load("market-history-extended.json")
        _references = {"universe": history["universe"], "timezones": history.get("timezones", {}),
                       "pse_universe": set(load("pse-history.json")["universe"]),
                       "extended": load("forecast-validation-extended.json"),
                       "models": load("market-specific-exploratory.json"),
                       "fund_bear": load("pse-bull-fund-bear-research.json"),
                       "pse_bear": load("bearish-forecast-research-comparable.json")}
    return _references


def market_for(symbol, data, refs):
    symbol = symbol.upper()
    if symbol in refs.get("pse_universe", ()) and data.get("source") == "TradingView":
        return "PSE"
    # Only studied identities are eligible. A ticker or a crypto symbol alone
    # does not establish that an unrelated instrument is the same asset.
    category = refs["universe"].get(symbol)
    source, kind = data.get("source"), str(data.get("type") or "").upper()
    # Yahoo crypto ticker/type alone cannot prove token identity across feeds.
    if category in ("currency", "fund", "us_equity") and source == "Yahoo":
        allowed = {"crypto": ("CRYPTOCURRENCY",), "currency": ("CURRENCY",),
                   "fund": ("ETF", "MUTUALFUND"), "us_equity": ("EQUITY",)}
        if kind in allowed[category]:
            return category
    return None


def result(status, reason=None, rate=None, calls=None):
    value = {"status": status}
    if reason:
        value["reason"] = reason
    if rate is not None:
        value["historicalRate"] = rate
        value["historicalCalls"] = calls
    return value


def unavailable(reason):
    return result("unavailable", reason)


def historical_baseline(points, symbol, timezone, now):
    """Fallback: choose the more frequent completed 3-month outcome for this asset.

    Both direction and frequency are selected from the same history: these are
    descriptive in-sample frequencies, not a backtested accuracy or probability.
    """
    try:
        zone = ZoneInfo(timezone)
    except (TypeError, ValueError, KeyError):
        return unavailable("Exchange timezone is unavailable")
    clean = completed_points(points, zone, now)
    if not clean:
        return unavailable("No completed daily prices")
    days = [dt.datetime.fromtimestamp(p["t"], zone).date() for p in clean]
    if (now.astimezone(zone).date() - days[-1]).days > 7:
        return unavailable("Latest completed price is more than seven days old")
    seen, outcomes = set(), []
    for i, day in enumerate(days):
        month = (day.year, day.month)
        if month in seen:
            continue
        seen.add(month)
        # A series that starts in the middle of a month doesn't establish that
        # its first sample is the first available session of that month.
        if i == 0:
            continue
        target = fv.months_after(day, 3)
        end = bisect.bisect_left(days, target, lo=i + 1)
        if end >= len(days) or (days[end] - target).days > fv.MAX_DELAY:
            continue
        outcomes.append((clean[end]["c"] > clean[i]["c"]) - (clean[end]["c"] < clean[i]["c"]))
    if len(outcomes) < 6:
        return unavailable("Fewer than six completed three-month outcomes")
    up, down = outcomes.count(1), outcomes.count(-1)
    if up == down:
        return unavailable("Historical upward and downward counts are tied")
    direction = "bullish" if up > down else "bearish"
    hits = up if direction == "bullish" else down
    return {"status": "signaled", "direction": direction, "historicalRate": hits / len(outcomes),
            "historicalCalls": len(outcomes), "up": up, "down": down,
            "unchanged": outcomes.count(0), "lastPriceDate": days[-1].isoformat(),
            "method": "asset_history_baseline", "symbol": symbol}


def completed_points(points, zone, now):
    """Only a previous local day is assumed complete; reject bad bars."""
    local_day = now.astimezone(zone).date()
    unique = {}
    for point in points:
        try:
            stamp, close = int(point["t"]), float(point["c"])
            date = dt.datetime.fromtimestamp(stamp, zone).date()
            if date < local_day and stamp <= now.timestamp() and math.isfinite(close) and close > 0:
                unique.setdefault(stamp, close)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
    return [{"t": t, "c": c} for t, c in sorted(unique.items())]


def latest_window(points, now, zone, months=None):
    if not points:
        return None, "No completed daily prices"
    last_day = dt.datetime.fromtimestamp(points[-1]["t"], zone).date()
    age = (now.astimezone(zone).date() - last_day).days
    if age > 7:
        return None, "Latest completed price is more than seven calendar days old"
    # Research evaluated the first available close each month, not daily calls.
    # Require the previous month to be present so a truncated history cannot
    # silently make a later close look like the first one.
    current_month = (now.astimezone(zone).year, now.astimezone(zone).month)
    dates = [dt.datetime.fromtimestamp(p["t"], zone).date() for p in points]
    candidates = [i for i, day in enumerate(dates) if (day.year, day.month) == current_month]
    if not candidates:
        return None, "No completed price in the current month"
    end = candidates[0]
    if end == 0 or (dates[end - 1].year, dates[end - 1].month) == current_month:
        return None, "History does not establish the first monthly close"
    stamps = [p["t"] for p in points]
    anchor = stamps[end]
    indices = onset.window(stamps, end, anchor, months=months)
    if len(indices) < fv.MIN_WINDOW_BARS:
        return None, TOO_FEW_WINDOW_BARS
    # onset's stale-chart fallback is not eligible for a current research call.
    cutoff = onset.months_back(anchor, months) if months else anchor - onset.WINDOW_DAYS * onset.DAY
    if stamps[indices[0]] < cutoff:
        return None, "Insufficient current-window prices"
    return ([points[i]["c"] for i in indices], dates[end]), None


def pse_bullish(rows, symbol, now):
    """Run the studied local filter with live completed PSE history."""
    zone = ZoneInfo("Asia/Manila")
    points = []
    for row in rows:
        try:
            points.append({"t": row[0], "c": row[4]})
        except (IndexError, TypeError):
            continue
    points = completed_points(points, zone, now)
    snapshot, error = latest_window(points, now, zone)
    if error:
        return unavailable(error)
    window, day = snapshot
    # The snapshot and the current feature use the same completed-bar window.
    if trend.classify(window)["label"] != "bullish":
        return result("not_signaled", "Completed-bar trend is not bullish")
    history_data = {"bars": {symbol: [[p["t"], None, p["c"], None] for p in points]}}
    import pse_bull_fund_bear_research as pse_research
    history, _ = pse_research.pse_observations(history_data)
    current = {"symbol": symbol, "date": day, "features": market_forecasts.features(window)}
    estimate = local.estimate(history, current, "bullish")
    if estimate is None:
        return unavailable("Insufficient completed stock-specific historical outcomes")
    if estimate["score"] < local.CALL_THRESHOLD:
        return result("not_signaled", "Stock-specific research filter did not qualify")
    answer = result("signaled", rate=.5247, calls=223)
    answer["signalDate"] = day.isoformat()
    return answer


def pse_bearish(rows, peers, symbol, now, refs):
    """Apply the saved 2026 PSE selector to completed stock and peer data."""
    import market_forecast_backtest as backtest
    import relative_forecast_research as relative

    zone = ZoneInfo("Asia/Manila")
    points = completed_points([{"t": row[0], "c": row[4]} for row in rows
                               if isinstance(row, (list, tuple)) and len(row) > 4], zone, now)
    snapshot, error = latest_window(points, now, zone)
    if error:
        return unavailable(error)
    window, day = snapshot
    if day.year != 2026:
        return unavailable("No frozen Philippine bearish selector for this year")
    fold = next((f for f in refs["pse_bear"]["markets"]["PSE"]["folds"]
                 if f["year"] == day.year), None)
    choice = fold and fold.get("selected_rule")
    if not choice:
        return result("abstained", "The annual bearish selector did not qualify")
    # Only this rule was selected for the frozen 2026 fold. Do not silently
    # apply it if a future annual selection has different requirements.
    if choice["rule"] != "local_momentum":
        return unavailable("The selected annual bearish rule is not supported")
    bars = {symbol: [[p["t"], None, p["c"], None] for p in points]}
    history, _ = backtest.observations({"bars": bars})
    current = {"symbol": symbol, "date": day, "features": market_forecasts.features(window)}
    estimate = local.estimate(history, current, "bearish")
    if estimate is None:
        return unavailable("Not enough completed stock history for the bearish rule")
    if estimate["score"] < local.CALL_THRESHOLD:
        return result("not_signaled", "Bearish stock-history filter did not qualify")
    try:
        raw = peers()
    except Exception:
        return unavailable("Could not retrieve Philippine peer prices")
    expected = refs.get("pse_universe", set())
    if not isinstance(raw, dict) or len(set(raw) & expected) < max(11, math.ceil(len(expected) * .8)):
        return unavailable("Too many Philippine peer histories are missing")
    cleaned = {}
    for name, rows in raw.items():
        if name not in expected:
            continue
        pts = completed_points([{"t": r[0], "c": r[4]} for r in rows
                                if isinstance(r, (list, tuple)) and len(r) > 4], zone, now)
        cleaned[name] = [[p["t"], None, p["c"], None] for p in pts]
    prepared = relative.prepare_bars(cleaned, {name: "Asia/Manila" for name in cleaned})
    peer_values = relative.peer_returns(prepared, day)
    relative_values = relative.relative_features(current, peer_values)
    if relative_values is None:
        return unavailable("Too few current Philippine peer prices to rank this stock")
    if relative_values[1] > .25:
        return result("not_signaled", "Bearish peer-strength filter did not qualify")
    answer = result("signaled", rate=.52, calls=1275)
    answer["signalDate"] = day.isoformat()
    answer["peerCount"] = len(peer_values) - int(symbol in peer_values)
    return answer


def evaluate(symbol, data, refs, now, fetch_pse, fetch_pse_peers=None):
    """Return independent directions. Unknown, missing and abstained are distinct."""
    market = market_for(symbol, data, refs)
    out = {"market": market, "asOf": now.isoformat(), "bullish": None, "bearish": None,
           "note": "Research-only historical hit rates, not probabilities for this asset. Three-month outcomes; repeatedly inspected samples."}
    if market is None:
        out["bullish"] = unavailable("Asset identity or data source is outside the studied universe")
        out["bearish"] = unavailable("Asset identity or data source is outside the studied universe")
        return out
    if data.get("cached"):
        out["bullish"] = unavailable("Chart source is offline; current research judgment unavailable")
        out["bearish"] = unavailable("Chart source is offline; current research judgment unavailable")
        return out
    if market == "PSE":
        try:
            rows = fetch_pse(symbol)
        except Exception:
            out["bullish"] = unavailable("Could not retrieve completed stock history")
            out["bearish"] = unavailable("Could not retrieve completed stock history")
            return out
        try:
            out["bullish"] = pse_bullish(rows, symbol, now)
        except Exception:
            out["bullish"] = unavailable("Could not evaluate stock history")
        try:
            out["bearish"] = pse_bearish(rows, fetch_pse_peers or (lambda: {}), symbol, now, refs)
        except Exception:
            out["bearish"] = unavailable("Could not evaluate Philippine bearish research")
        return out
    symbol = symbol.upper()
    zone_name = refs["timezones"].get(symbol)
    try:
        zone = ZoneInfo(zone_name)
    except (TypeError, ValueError, KeyError):
        out["bullish"] = unavailable("Exchange timezone not verified")
        out["bearish"] = unavailable("Exchange timezone not verified")
        return out
    points = completed_points(data.get("points") or [], zone, now)
    snapshot, error = latest_window(points, now, zone, months=3)
    if error:
        out["bullish"] = unavailable(error)
        out["bearish"] = unavailable(error)
        return out
    window, signal_day = snapshot
    if now.year != 2026:
        out["bullish"] = unavailable("The frozen research models are valid only for the 2026 test fold")
        out["bearish"] = unavailable("The frozen research models are valid only for the 2026 test fold")
        return out
    # These folds were fit strictly before 2026. They are retrospective,
    # research-only decisions, not a claim of verified live accuracy.
    if market in ("us_equity", "fund"):
        fold = next(x for x in refs["extended"]["markets"][market]["folds"] if x["year"] == 2026)
        label = fold["bins"][str(fv.score_bin(trend.classify(window)["score"]))]["direction"]
        out["bullish"] = (result("signaled", rate=.6077 if market == "us_equity" else .5820,
                                  calls=62535 if market == "us_equity" else 13166)
                          if label == "bullish" else result("not_signaled", "Frozen score-bin model abstained"))
        if market == "fund":
            bear_fold = next(x for x in refs["fund_bear"]["markets"]["fund"]["folds"] if x["year"] == 2026)
            out["bearish"] = (result("abstained", "2026 fund bearish selector did not qualify")
                              if bear_fold["choice"] is None else
                              unavailable("Requires refreshed fund and peer-market histories"))
        else:
            out["bearish"] = unavailable("Requires refreshed stock and peer-market histories")
    elif market in ("currency", "crypto"):
        fold = next(x for x in refs["models"]["markets"][market]["folds"] if x["year"] == 2026)
        direction = "bullish" if market == "currency" else "bearish"
        fitted = (fold.get("models") or {}).get(direction)
        if fitted is None:
            out[direction] = result("abstained", "Frozen 2026 research model did not qualify")
        else:
            values = market_forecasts.features(window)
            # The original currency study withheld both directions on conflict.
            # Independent threshold scores were not the reported experiment.
            conflict = (market == "currency" and
                        sum(bool(m) and market_forecasts.score(m, values) >= m["validation"]["threshold"]
                            for m in fold["models"].values()) > 1)
            passed = market_forecasts.score(fitted, values) >= fitted["validation"]["threshold"]
            out[direction] = (result("signaled", rate=.5270 if market == "currency" else .5836,
                                      calls=2854 if market == "currency" else 1585)
                              if passed and not conflict else result("abstained" if conflict else "not_signaled",
                                  "Original model withheld conflicting directions" if conflict else "Research threshold not met"))
        other = "bearish" if direction == "bullish" else "bullish"
        out[other] = unavailable("Requires refreshed asset and peer-market histories")
    for direction in ("bullish", "bearish"):
        if out[direction]["status"] == "signaled":
            out[direction]["signalDate"] = signal_day.isoformat()
    return out
