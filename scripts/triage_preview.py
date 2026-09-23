#!/usr/bin/env python
"""Eyeball Jev triage against the real current crop before enabling it.

Runs a live fetch (dry-run, so the cache is not touched and nothing is
deduplicated away) and triages every listing, printing what would have been
kept and what would have been dropped. Makes no Claude call and sends no
email. This is a manual review tool; it is not wired into the weekly run.

    venv/bin/python scripts/triage_preview.py
    venv/bin/python scripts/triage_preview.py --limit 40
    venv/bin/python scripts/triage_preview.py --no-log

Read the per-source pass rates before changing MIN_FIT_SCORE. A source whose
pass rate collapses to near zero is usually a missing-field problem in
fetcher.py, not a genuine relevance signal.
"""

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from buildathon_radar import triage
from buildathon_radar.fetcher import fetch_events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="cap items triaged")
    parser.add_argument("--no-log", action="store_true", help="skip triage_log write")
    parser.add_argument(
        "--threshold",
        type=float,
        default=triage.MIN_FIT_SCORE,
        help=(
            "fit_score value to report a counterfactual for. fit_score does "
            f"not gate; this only drives the what-if line (default {triage.MIN_FIT_SCORE})"
        ),
    )
    args = parser.parse_args()

    print("Fetching live listings (dry run, cache untouched)...")
    items, health = fetch_events(dry_run=True)
    for name, info in health.items():
        state = f"ERROR: {info['error']}" if info["error"] else f"{info['count']} items"
        print(f"  {name}: {state}")

    if args.limit:
        items = items[: args.limit]
    if not items:
        print("\nNo items fetched; nothing to triage.")
        return 1

    print(f"\nTriaging {len(items)} listings with {triage.JEV_MODEL}...")
    client = triage._make_client()
    if client is None:
        print("No TypeSafe client (is TYPESAFE_API_KEY set?). Aborting preview.")
        return 1

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=triage.MAX_WORKERS) as pool:
        verdicts = list(pool.map(lambda it: triage.triage_item(client, it), items))

    if not args.no_log:
        triage.log_verdicts(verdicts)
        print("Wrote verdicts to triage_log in tracker.db")

    kept = [v for v in verdicts if v["passed"]]
    dropped = [v for v in verdicts if not v["passed"]]

    def _num(value):
        return f"{value:.2f}" if value is not None else "  - "

    def row(v):
        # fconf is confidence in the fit_score; cconf is confidence in the
        # category. Only cconf feeds the gate, so they are kept distinct.
        cat = (v["category"] or "-")[:17]
        src = (v["source"] or "-")[:9]
        over = "OVER" if v["is_over"] else "    "
        return (
            f"  {_num(v['fit_score']):>5} {_num(v['fit_confidence']):>5}  "
            f"{cat:<17} {_num(v['category_confidence']):>5}  {src:<9} "
            f"r={_num(v['is_remote'])} p={_num(v['has_real_prize'])} {over}  "
            f"{(v['title'] or '')[:46]}"
        )

    header = (
        "    fit fconf  category          cconf  source    "
        "remote prize        title"
    )

    print(f"\n{'=' * 100}\nWOULD REACH CLAUDE ({len(kept)}/{len(verdicts)})\n{'=' * 100}")
    print(header)
    for v in sorted(kept, key=lambda x: -(x["fit_score"] or 0)):
        print(row(v))

    print(f"\n{'=' * 100}\nWOULD BE DROPPED ({len(dropped)}/{len(verdicts)})\n{'=' * 100}")
    print(header)
    for v in sorted(dropped, key=lambda x: -(x["fit_score"] or 0)):
        print(row(v))

    # A low pass rate here is not automatically a bug. Luma is a general
    # Bengaluru events feed, so most of its listings genuinely are not AI
    # events; read the dropped titles before concluding anything is broken.
    print(f"\n{'=' * 100}\nPASS RATE BY SOURCE\n{'=' * 100}")
    by_source = collections.defaultdict(lambda: [0, 0])
    for v in verdicts:
        by_source[v["source"] or "?"][1] += 1
        if v["passed"]:
            by_source[v["source"] or "?"][0] += 1
    for src, (passed, total) in sorted(by_source.items()):
        pct = 100 * passed / total if total else 0
        print(f"  {src:<18} {passed:3d}/{total:3d} kept  {pct:5.1f}%")

    print(f"\n{'=' * 100}\nCATEGORY DISTRIBUTION\n{'=' * 100}")
    for cat, n in collections.Counter(
        v["category"] or "(failed)" for v in verdicts
    ).most_common():
        gate = "  [GATED]" if cat in triage.DROP_CATEGORIES else ""
        print(f"  {cat:<20} {n:3d}{gate}")

    # Confident enough to act on vs. kept only because confidence was low.
    near = [
        v
        for v in verdicts
        if v["category"] in triage.DROP_CATEGORIES
        and v["category_confidence"] is not None
        and v["category_confidence"] < triage.MIN_DROP_CONFIDENCE
    ]
    print(
        f"\n{'=' * 100}\nKEPT DESPITE A GATED CATEGORY "
        f"(confidence < {triage.MIN_DROP_CONFIDENCE}) - {len(near)} items\n{'=' * 100}"
    )
    print("These are where the confidence floor is doing the work. Sanity-check them.")
    print(header)
    for v in sorted(near, key=lambda x: -(x["category_confidence"] or 0)):
        print(row(v))

    # fit_score does not gate; this is the calibration data for deciding
    # whether it ever should.
    scored = [v["fit_score"] for v in verdicts if v["fit_score"] is not None]
    if scored:
        print(f"\n{'=' * 100}\nFIT_SCORE DISTRIBUTION (not gating)\n{'=' * 100}")
        hist = collections.Counter(round(s * 4) / 4 for s in scored)
        for bucket in sorted(hist):
            print(f"  {bucket:4.2f}  {'#' * hist[bucket]} ({hist[bucket]})")
        would_cut = sum(1 for s in scored if s < args.threshold)
        band = sum(1 for s in scored if abs(s - args.threshold) <= 0.35)
        print(
            f"\n  Counterfactual: a fit_score gate at {args.threshold} would drop "
            f"{would_cut}/{len(scored)}, with {band} sitting within 0.35 of the cut."
        )
        if band > len(scored) / 4:
            print("  That band is crowded - the cut would be close to arbitrary.")

    failed = [v for v in verdicts if v["fit_score"] is None]
    if failed:
        print(f"\nFAILED OPEN ({len(failed)}) - these would pass through to Claude:")
        for v in failed[:10]:
            print(f"  {v['reason']}: {(v['title'] or '')[:60]}")

    usage_note = "no Claude call was made; no email was sent"
    print(f"\nPreview complete ({usage_note}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
