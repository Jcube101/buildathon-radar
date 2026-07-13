# CLAUDE.md

Context for Claude or any assistant working in this repo.

## What this is

Buildathon Radar is a personal AI agent that scans Devpost and Devfolio every
week, filters events for relevance to an AI product manager based in
Bengaluru, India, and emails a ranked digest every Sunday at 5:00 PM IST. It
is the sibling project to signal-digest, reusing its spine (normalised item
dict, single Claude call, `cache.json` dedup, markdown to HTML email,
`--dry-run`, systemd timer) but rebuilding the source and hallucination-guard
layers from scratch.

## Owner and machine

Owner: Job, an AI product manager in Bengaluru, India. Runs on jobpi, a Raspberry Pi 5 on Debian 13, user
jcube, project at `/home/jcube/projects/buildathon-radar`. Timezone
Asia/Kolkata. No sudo is used anywhere in this project; scheduling is
`systemctl --user` with lingering already enabled for jcube.

## Stack

Python 3.13. Dependencies: `anthropic`, `requests`, `python-dotenv`,
`markdown`, `pytest` (see `requirements.txt`). Model: `claude-sonnet-5`, called
with extended thinking explicitly disabled (see `learnings.md` for why).

## Structure

```
buildathon_radar/
    fetcher.py   Devpost + Devfolio fetch, normalise, cache.json dedup
    agent.py     claude-sonnet-5 call, scoring rubric, strict JSON output
    guard.py     programmatic anti-hallucination URL check
    digest.py    markdown assembly from validated picks (code-owned, not Claude)
    deliver.py   markdown to HTML, local archive, Gmail SMTP send
main.py          orchestrator, --dry-run flag, top-level fatal handler
tests/           pytest, Claude client always mocked, fixtures under tests/fixtures/
scheduler/systemd/   service + timer units and install README
```

## How it works, in one paragraph

Both sources are free public JSON APIs, no scraping, no keys beyond what is
already in `.env`. Fetched items are deduplicated against `cache.json` (45 day
TTL) and normalised into an 11-key dict. Claude scores and tiers the survivors
and returns JSON picks (url, tier, score, why), not prose. `guard.py` checks
every returned URL against the fetched set and drops anything that does not
match. `digest.py` then renders the email from the matched source items, not
from Claude's text, so no fact in the email can be a hallucination. `deliver.py`
sends it over Gmail SMTP and archives a copy locally.

## Commands

```
venv/bin/pytest                     # full mocked test suite
venv/bin/python main.py --dry-run   # live fetch + live Claude call, no send, no cache write
venv/bin/python main.py             # the real weekly run
systemctl --user list-timers        # confirm the Sunday 17:00 IST schedule
journalctl --user -u buildathon-radar.service   # read run logs
```

## Known limitations

- v1 sources are Devpost and Devfolio only. Cerebral Valley and Luma, the two
  sources that would have caught the actual missed events motivating this
  project, are v2 backlog, not built (see `spec.md` and `ROADMAP.md`).
- Devpost's list API has no ISO dates, only a human string; date parsing is
  best-effort and falls back to `"Unknown"` on anything it cannot parse.
- The cache suppresses an event for 45 days after first sight, including
  events Claude rejected, so a rejected event is not re-scored weekly. An
  event whose listing improves after rejection will not be re-evaluated
  within that window.
- `ROADMAP.md` in the repo root is the original planning document with the
  full endpoint recon and resolved open questions. Treat it as historical
  record; `spec.md` and this file are the living references.
