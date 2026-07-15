# CLAUDE.md

Context for Claude or any assistant working in this repo.

## What this is

Buildathon Radar is a personal AI agent that scans Devpost, Devfolio, and
Luma every week (Cerebral Valley is built and tested but currently gated
off, see Known limitations), filters events for relevance to an AI product
manager based in Bengaluru, India, and emails a ranked digest every Sunday
at 5:00 PM IST. It is the sibling project to signal-digest, reusing its
spine (normalised item dict, single Claude call, `cache.json` dedup,
markdown to HTML email, `--dry-run`, systemd timer) but rebuilding the
source and hallucination-guard layers from scratch.

## Owner and machine

Owner: Job, an AI product manager in Bengaluru, India. Runs on jobpi, a Raspberry Pi 5 on Debian 13, user
jcube, project at `/home/jcube/projects/buildathon-radar`. Timezone
Asia/Kolkata. No sudo is used anywhere in this project; scheduling is
`systemctl --user` with lingering already enabled for jcube.

## Stack

Python 3.13. Dependencies: `anthropic`, `requests`, `python-dotenv`,
`markdown`, `pytest` (see `requirements.txt`). Model: `claude-sonnet-5`, called
with extended thinking explicitly disabled (see `LEARNINGS.md` for why).

## Structure

```
buildathon_radar/
    fetcher.py         Devpost/Devfolio/Luma/Cerebral Valley fetch, normalise, cache.json dedup
                       (ENABLE_CV_SOURCE near the top gates Cerebral Valley off by default)
    agent.py           claude-sonnet-5 call, scoring rubric, strict JSON output
    guard.py           programmatic anti-hallucination URL check
    digest.py          markdown/HTML assembly from validated picks (code-owned, not Claude)
    deliver.py         markdown to HTML, local archive, Gmail SMTP send
    tracker_store.py   SQLite tracker store (v2): schema, upsert, state transitions, signed tokens
    tracker_service.py v2 FastAPI app: GET /, /track, /applied, /list
main.py          orchestrator, --dry-run flag, top-level fatal handler
tests/           pytest, Claude client always mocked, fixtures under tests/fixtures/
scheduler/systemd/   digest service + timer, tracker service unit, install README
```

## How it works, in one paragraph

All sources are free public JSON APIs, no scraping, no keys beyond what is
already in `.env`. Fetched items are deduplicated against `cache.json` (per-event
records, date-aware resurface logic) and normalised into a dict that includes
`event_id`. Claude scores and tiers the survivors and returns JSON picks (url,
tier, score, why), not prose. `guard.py` checks every returned URL against the
fetched set and drops anything that does not match. `digest.py` then renders
the email from the matched source items, not from Claude's text, so no fact in
the email can be a hallucination. `deliver.py` sends it over Gmail SMTP and
archives a copy locally. On a non-dry run, `main.py` also upserts every
emailed pick into `tracker.db` (v2, ROADMAP.md 2.2/2.3) as `seen`; a separate
always-on FastAPI service (`tracker_service.py`, exposed at
`https://radar.job-joseph.com`) handles the email's Track/Applied button
clicks, and the digest renders a tracked-reminder strip and a participation
log from that store. The same service also serves `/list`, a read-only page
showing everything currently tracked or applied, for checking in without
waiting for Sunday.

## Commands

```
venv/bin/pytest                     # full mocked test suite
venv/bin/python main.py --dry-run   # live fetch + live Claude call, no send, no cache write
venv/bin/python main.py             # the real weekly run
systemctl --user list-timers        # confirm the Sunday 17:00 IST schedule
journalctl --user -u buildathon-radar.service   # read digest run logs
systemctl --user status buildathon-tracker.service    # tracker service status
journalctl --user -u buildathon-tracker.service       # tracker service logs
curl -s https://radar.job-joseph.com/                 # tracker health check
curl -s https://radar.job-joseph.com/list             # everything currently tracked or applied
```

## Known limitations

- Cerebral Valley is fully built and tested (`fetch_cerebralvalley` in
  `fetcher.py`) but gated off: `ENABLE_CV_SOURCE` defaults to `False`.
  Luma went live alone so its real weekly behaviour could be observed
  before adding a second new source at once; flip `ENABLE_CV_SOURCE` to
  `True` about a week after 2026-07-15 to activate it (see `ROADMAP.md`).
- Luma's own IP-geo-scoped `cat-ai` category feed is documented but not
  used; only the deterministic Bengaluru place feed is wired in.
- Luma and Cerebral Valley are both undocumented public JSON APIs, the same
  standing Devpost's list API has had since v1: they can change or vanish
  without notice. The source-health footer is the tripwire.
- Devpost's list API has no ISO dates, only a human string; date parsing is
  best-effort and falls back to `"Unknown"` on anything it cannot parse.
- The cache suppresses an event for 45 days after first sight, including
  events Claude rejected, so a rejected event is not re-scored weekly. An
  event whose listing improves after rejection will not be re-evaluated
  within that window.
- `ROADMAP.md` is forward-looking: shipped status and what comes next.
  `docs/BUILD-HISTORY.md` is the archived original build plan and endpoint
  recon. `SPEC.md` and this file are the living architecture references.
  `docs/V2-TRACKER-PLAN.md` is the full architecture and build plan for the
  v2 tracker (Units A and B: Track/Applied buttons, the participation log),
  now shipped; see `SPEC.md`'s v2 tracker section for the current summary.
  `docs/V2-SOURCING-PLAN.md` is the full recon and build plan for the Luma
  and Cerebral Valley sourcing expansion; see `SPEC.md`'s Sources section
  for the current summary.
- The tracker service (`tracker_service.py`) fails fast at startup if
  `TRACKER_SECRET` is unset in `.env`; it must never run without the ability
  to verify signed links. Lifecycle states beyond `seen`/`tracked`/`applied`
  (an `over` state with a recorded outcome), calendar integration, and
  cross-source entity resolution are deliberately deferred (ROADMAP.md 2.4,
  2.5, 2.6) and not built.
