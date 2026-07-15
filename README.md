# Buildathon Radar

A personal AI agent that scans Devpost, Devfolio, and Luma every week (a
fourth source, Cerebral Valley, is built and tested but currently gated off,
see below), filters for events genuinely relevant to an AI product manager
based in Bengaluru, India, and emails a ranked digest every Sunday at 5:00
PM IST.

It exists because two real events were nearly missed: the Google DeepMind
Bangalore Hackathon (found on Twitter, too late, was listed on Cerebral
Valley) and India Builds with Claude, Razorpay x Anthropic (surfaced only by
a mentor, was listed on Luma). This agent replaces luck with a weekly scan.

## How it works

Four sources are fetched via free, public JSON APIs (three live, one gated),
normalised into a common item shape, and deduplicated against `cache.json`.
The same real-world event listed on more than one source collapses into a
single entry rather than being shown twice. The survivors are sent to
Claude (`claude-sonnet-5`), which applies a set of hard exclusions (student
and college-run events, platforms hard to access from India, hardware and
chip-level challenges, and events whose eligibility is genuinely restricted
to students even under a non-college host), then scores and tiers what
remains and returns structured JSON, not prose. A programmatic guard checks
that every URL Claude returned actually came from the fetched data; anything
that does not match is dropped. Every factual field in the final email
(venue, host, date, prize) is rendered from the original source data, never
from Claude's output, so a hallucinated detail is not just discouraged, it
is structurally impossible.

Each event card in the email carries Track and Applied buttons. Tapping one
hits a small always-on tracker service that records the action and shows a
confirmation page; tracked events reappear as reminders in future digests,
and applied events show up in a participation log at the bottom of every
email. A separate page on the same service shows everything currently
tracked or applied, without waiting for Sunday.

See `SPEC.md` for the full architecture and data contracts, and
`LEARNINGS.md` for why it is built this way.

## Setup

```
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

`.env` must contain `ANTHROPIC_API_KEY`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`
(a Gmail app password, not the account password), and `TRACKER_SECRET` (a
random secret used to sign the email's Track/Applied links). See
`.env.example`.

## Running

```
venv/bin/python main.py --dry-run   # fetches live, calls Claude, prints the digest, sends nothing, writes no cache
venv/bin/python main.py             # the real run: fetches, scores, sends the email, writes cache.json and archive/
```

## Tests

```
venv/bin/pytest
```

All tests mock the Claude API call. No test makes a live network or API
request.

## Scheduling

The weekly digest runs automatically every Sunday at 5:00 PM IST via a
`systemctl --user` timer. The tracker service (Track/Applied endpoints, plus
a read-only view of everything tracked or applied) runs continuously as a
second, independent `systemctl --user` service. See
`scheduler/systemd/README.md` for install and log commands for both.
