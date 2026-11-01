#!/usr/bin/env python
"""Check the AI company watchlist against live news before trusting it.

Runs only the watchlist news search (no other sources, no cache, no Claude
call, no email) and prints what it would hand to Claude this week, grouped
by company. This is a manual review tool; it is not wired into the weekly run.

    venv/bin/python scripts/watchlist_preview.py
    venv/bin/python scripts/watchlist_preview.py --company ElevenLabs --company Runway

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
    args = parser.parse_args()

    companies = AI_COMPANIES
    if args.company:
        wanted = {c.lower() for c in args.company}
        companies = [c for c in AI_COMPANIES if c["name"].lower() in wanted]
        if not companies:
            print("No matching company names. Names are as listed in buildathon_radar/ai_companies.py.")
            return 1

    items, error = fetch_watchlist(companies=companies)
    if error:
        print(f"ERROR: every news query failed: {error}")
        return 1

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
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
