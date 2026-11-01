#!/usr/bin/env python
"""Check the AI company watchlist against live news before trusting it.

Runs only the watchlist news search (no other sources, no cache, no Claude
call, no email) and prints what it would hand to Claude this week, grouped
by company. This is a manual review tool; it is not wired into the weekly run.

    venv/bin/python scripts/watchlist_preview.py
    venv/bin/python scripts/watchlist_preview.py --company ElevenLabs --company Runway
    venv/bin/python scripts/watchlist_preview.py --raw   # per-query counts and rejections
    venv/bin/python scripts/watchlist_preview.py --jev   # also show Jev's open-contest verdicts

If every query errors, the news endpoint has changed or is blocked: the
weekly digest's source-health footer will show the same error.
"""

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from buildathon_radar.ai_companies import AI_COMPANIES
from buildathon_radar.fetcher import fetch_watchlist


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--company", action="append", default=[],
        help="limit to this company name (repeatable); default is all 100",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="also print each news query with how many results came back and why each was rejected",
    )
    parser.add_argument(
        "--jev", action="store_true",
        help="run Jev triage on the candidates (needs TYPESAFE_API_KEY; nothing is logged)",
    )
    args = parser.parse_args()

    companies = AI_COMPANIES
    if args.company:
        wanted = {c.lower() for c in args.company}
        companies = [c for c in AI_COMPANIES if c["name"].lower() in wanted]
        if not companies:
            print("No matching company names. Names are as listed in buildathon_radar/ai_companies.py.")
            return 1

    stats = []
    items, error = fetch_watchlist(companies=companies, stats=stats)

    if args.raw:
        for st in stats:
            status = f"ERROR {st['error']}" if st["error"] else f"{st['raw']} results, {st['kept']} kept"
            print(f"QUERY {st['query'][:120]}\n  {status}")
            for line in st["rejected"]:
                print(f"    - {line}")
        print()
    if error:
        print(f"ERROR: every news query failed: {error}")
        return 1

    verdict_for = {}
    if args.jev and items:
        from buildathon_radar.triage import triage_items

        _, verdicts = triage_items(items, enabled=True, log=False)
        verdict_for = {v["url"]: v for v in verdicts}
        if not verdicts:
            print("Jev did not run (TYPESAFE_API_KEY missing or client error); see warning above.\n")

    by_company = collections.defaultdict(list)
    for item in items:
        by_company[item["host"]].append(item)

    print(f"{len(items)} candidate announcements from {len(companies)} companies\n")
    for name in sorted(by_company):
        print(name)
        for item in by_company[name]:
            prize = f"  [{item['prize']}]" if item["prize"] else ""
            print(f"  {item['published']}  {item['title']}{prize}")
            print(f"    {item['url']}")
            v = verdict_for.get(item["url"])
            if v:
                print(f"    Jev: {'KEEP' if v['passed'] else 'DROP'} ({v['reason']})")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
