"""Does version 2's behaviour hold in a stretch of history it was not shaped on?

The classifier is descriptive, so this never looks at future returns. It
compares two *eras* of each asset's own history on the properties v2 was
tuned for: how often a 63-bar window carries a label, and how often the label
changes from one bar to the next (flicker).

Honest limit: `research/market-history.json.gz` was already seen while the
thresholds were chosen, so a split of it is a consistency check, not a true
holdout. A true holdout is bars dated after 2026-10-30 (the file's first
`collected_at`); `--since 2026-10-30` scores only windows whose newest bar is
after that day, once the history is refreshed. See docs/long-term-test.md.
Writes `research/holdout-stability.json` (or `holdout-since-<date>.json`).

    python3 lab/holdout_stability.py [--split 0.7] [--stride 1]
    python3 lab/holdout_stability.py --since 2026-10-30
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import _paths  # noqa: F401  (puts the project folder on sys.path)
import trend
from bigjson import BigJson

ROOT = pathlib.Path(__file__).resolve().parent.parent
WINDOW = 63


def era_stats(closes: list[float], stride: int) -> dict:
    labels = []
    for end in range(WINDOW, len(closes) + 1, stride):
        labels.append(trend.classify(closes[end - WINDOW:end])["label"])
    if not labels:
        return {"windows": 0}
    changes = sum(1 for a, b in zip(labels, labels[1:]) if a != b)
    n = len(labels)
    return {
        "windows": n,
        "labelled": round(sum(l != "neutral" for l in labels) / n, 4),
        "bullish": round(labels.count("bullish") / n, 4),
        "bearish": round(labels.count("bearish") / n, 4),
        "changes_per_100": round(100 * changes / max(n - 1, 1), 3),
    }


def pooled(rows: list[dict]) -> dict:
    total = sum(r["windows"] for r in rows) or 1
    out = {"windows": total}
    for key in ("labelled", "bullish", "bearish", "changes_per_100"):
        out[key] = round(sum(r[key] * r["windows"] for r in rows) / total, 4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", type=float, default=0.7, help="share of each series in the early era")
    ap.add_argument("--stride", type=int, default=1, help="step between windows (1 = every bar)")
    ap.add_argument("--since", help="YYYY-MM-DD: score only windows ending after this day")
    args = ap.parse_args()

    data = json.loads(BigJson(ROOT / "research" / "market-history.json").read_text())
    if args.since:
        cutoff = int(dt.datetime.fromisoformat(args.since).replace(tzinfo=dt.timezone.utc).timestamp())
        rows = []
        for bars in data["bars"].values():
            bars = [b for b in bars if b[2] is not None]
            first = next((i for i, b in enumerate(bars) if b[0] > cutoff), None)
            if first is None or first < WINDOW - 1:
                continue
            closes = [b[2] for b in bars]
            # Start WINDOW-1 bars early so the first new window is whole.
            stats = era_stats(closes[first - WINDOW + 1:], args.stride)
            if stats["windows"] >= 2:
                rows.append(stats)
        report = {"collected_at": data["collected_at"], "since": args.since,
                  "assets": len(rows), "holdout": pooled(rows) if rows else "no new bars yet"}
        out = ROOT / "research" / f"holdout-since-{args.since}.json"
        out.write_text(json.dumps(report, indent=2))
        json.dump(report, sys.stdout, indent=2)
        print()
        return 0

    early, late = [], []
    for symbol, bars in data["bars"].items():
        closes = [b[2] for b in bars if b[2] is not None]
        cut = int(len(closes) * args.split)
        if cut < WINDOW + 10 or len(closes) - cut < WINDOW + 10:
            continue
        # The late era starts WINDOW bars early so its first window is whole.
        early.append(era_stats(closes[:cut], args.stride))
        late.append(era_stats(closes[cut - WINDOW:], args.stride))

    report = {"collected_at": data["collected_at"], "split": args.split,
              "assets": len(early), "early": pooled(early), "late": pooled(late)}
    out = ROOT / "research" / "holdout-stability.json"
    out.write_text(json.dumps(report, indent=2))
    json.dump(report, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
