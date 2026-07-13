# Buildathon Radar

A personal AI agent that scans Devpost and Devfolio every week, filters for
events genuinely relevant to an AI product manager based in Bengaluru, India,
and emails a ranked digest every Sunday at 5:00 PM IST.

It exists because two real events were nearly missed: the Google DeepMind
Bangalore Hackathon (found on Twitter, too late) and India Builds with Claude,
Razorpay x Anthropic (surfaced only by a mentor). This agent replaces luck with
a weekly scan.

## How it works

Devpost and Devfolio are fetched via their public JSON APIs, normalised into a
common item shape, and deduplicated against `cache.json` (45 day TTL). The
survivors are sent to Claude (`claude-sonnet-5`), which scores and tiers each
event and returns structured JSON, not prose. A programmatic guard then checks
that every URL Claude returned actually came from the fetched data; anything
that does not match is dropped. Every factual field in the final email (venue,
host, date, prize) is rendered from the original source data, never from
Claude's output, so a hallucinated detail is not just discouraged, it is
structurally impossible. See `spec.md` for the full architecture and
`learnings.md` for why it is built this way.

## Setup

```
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

`.env` must contain `ANTHROPIC_API_KEY`, `EMAIL_ADDRESS`, and `EMAIL_PASSWORD`
(a Gmail app password, not the account password). See `.env.example`.

## Running

```
venv/bin/python main.py --dry-run   # fetches live, calls Claude, prints the digest, sends nothing, writes no cache
venv/bin/python main.py             # the real run: fetches, scores, sends the email, writes cache.json and archive/
```

## Tests

```
venv/bin/pytest
```

All tests mock the Claude API call. No test makes a live network or API request.

## Scheduling

Runs automatically every Sunday at 5:00 PM IST via a `systemctl --user` timer.
See `scheduler/systemd/README.md` for install and log commands.

## Morning proof-of-life

Note: enabling the systemd timer during the build triggered an immediate real
run (a `Persistent=true` first-enable side effect, see `learnings.md`), so a
real digest email has already been sent once, tonight, and `cache.json` and
`archive/` already exist. Check the inbox first; the proof-of-life may already
be sitting there.

If you want to run it again by hand (it will only pick up events not already
in `cache.json`, so expect a shorter digest than tonight's):

```
cd ~/projects/buildathon-radar
venv/bin/python main.py
```

A healthy result looks like: the digest prints to the console and an email
titled "Buildathon Radar" arrives at jobjoseph99@gmail.com within a minute or
two. After that, the Sunday timer takes over on its own, next firing
2026-07-19 17:00 IST.
