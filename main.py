import sys
from datetime import datetime

from buildathon_radar import tracker_store
from buildathon_radar.agent import run_agent
from buildathon_radar.deliver import get_date_range, send_digest, send_failure_email
from buildathon_radar.digest import build_digest, build_html_digest
from buildathon_radar.fetcher import fetch_events
from buildathon_radar.guard import validate_picks

dry_run = "--dry-run" in sys.argv

try:
    items, source_health = fetch_events(dry_run=dry_run)
    agent_result = run_agent(items)
    valid_picks, dropped_picks = validate_picks(agent_result["picks"], items)
    digest = build_digest(
        valid_picks, dropped_picks, source_health, agent_result["week_note"]
    )

    print("\n" + "=" * 60)
    print("BUILDATHON RADAR - WEEKLY DIGEST")
    print("=" * 60 + "\n")
    print(digest)

    if dry_run:
        print("\nDRY RUN - cache not updated, email not sent")
    else:
        tracked_events, applied_events = [], []
        try:
            tracker_conn = tracker_store.connect()
            tracker_store.upsert_seen(tracker_conn, [p["item"] for p in valid_picks])
            today_str = datetime.now().strftime("%Y-%m-%d")
            tracked_events = tracker_store.get_tracked_open(tracker_conn, today_str)
            applied_events = tracker_store.get_applied_open(tracker_conn, today_str)
            tracker_conn.close()
        except Exception as e:
            print(f"  WARNING: Tracker store unavailable this run: {e}")
            tracked_events, applied_events = [], []

        html_digest = build_html_digest(
            valid_picks,
            dropped_picks,
            source_health,
            agent_result["week_note"],
            get_date_range(),
            tracked_events=tracked_events,
            applied_events=applied_events,
        )
        send_digest(digest, html_digest)

    sys.exit(0)

except Exception as e:
    print(f"\nFATAL ERROR: {e}")
    if not dry_run:
        try:
            send_failure_email(str(e))
        except Exception as email_error:
            print(f"  ERROR: Could not send failure email: {email_error}")
    sys.exit(1)
