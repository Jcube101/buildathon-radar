import sys

from buildathon_radar.agent import run_agent
from buildathon_radar.deliver import send_digest, send_failure_email
from buildathon_radar.digest import build_digest
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
        send_digest(digest)

    sys.exit(0)

except Exception as e:
    print(f"\nFATAL ERROR: {e}")
    if not dry_run:
        try:
            send_failure_email(str(e))
        except Exception as email_error:
            print(f"  ERROR: Could not send failure email: {email_error}")
    sys.exit(1)
