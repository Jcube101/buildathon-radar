# LEARNINGS.md: why it is built this way

## Structured picks instead of free markdown

signal-digest lets Claude author the entire digest body as markdown; no code
checks any of it. That is fine for a reading digest where a wrong detail is
merely embarrassing, but this agent's whole purpose is to get someone to a
specific place at a specific time. A hallucinated venue or date is not a minor
error here, it is the failure mode the project exists to prevent.

So Claude's job was narrowed on purpose: it only scores, tiers, and writes a
one-line "why it matters." It returns strict JSON keyed by URL. Code re-joins
each pick to the original fetched item by that URL and renders every factual
field (title, host, location, mode, dates, prize) from the source data, never
from Claude's output. This makes the anti-hallucination guard a mechanical set
membership check instead of a hope that the prompt was followed. A
hallucinated venue is not just discouraged, it is structurally impossible,
because the venue in the email never came from the model in the first place.

## The extended-thinking incident

This project has its own version of signal-digest's documented hallucination
incident, but the failure mode was different: total silence, not invention.

The first live `--dry-run` attempt raised `'ThinkingBlock' object has no
attribute 'text'`. The original code assumed `response.content[0]` was always
a text block, ported unchanged from a mental model of the older, non-thinking
Opus call in signal-digest. `claude-sonnet-5` can return a leading
`ThinkingBlock` before the text block, so `content[0].text` broke immediately
against the real API, not a test.

Fixing that exposed a second, worse problem. With extended thinking left on
its default behaviour and a real batch of 90 events, the model spent its
entire 4000-token budget on internal reasoning and returned `stop_reason:
max_tokens` with a single `thinking` block and no text block at all. Not
malformed JSON, not a bad pick, just nothing. Bumping `max_tokens` would not
have reliably fixed this, since thinking token usage scales with problem size
and there was no guarantee 8000 or even 16000 tokens would leave room for the
actual output on a busier week. The real fix was to disable extended thinking
for this call entirely (`thinking={"type": "disabled"}`): this is a scoring
and JSON-formatting task, not one where visible chain-of-thought reasoning
earns anything, and disabling it removed the failure mode at its root rather
than making the token budget a bigger moving target. `max_tokens` was raised
to 8000 anyway, as headroom for the plain-text output.

The lesson: a prompt and call shape ported from a different model generation
is not verified until it has been run live against the model it now targets,
not just unit-tested against a mock. The mocked test suite could not have
caught this, because the mock never has an opinion about `ThinkingBlock` or
token budgets. Only the live dry run did.

## Cache-everything, not just picks

Every item that survives the fetch and reaches Claude gets cached, not just
the ones that end up in a digest. This means a rejected event is not
re-scored (and re-billed) every single week within the 45 day TTL. The
tradeoff: if an event's listing improves after Claude first saw and rejected
it (a vague hackathon fleshes out its theme, say), the improvement will not be
re-evaluated until the cache entry expires. Given the volume (roughly 90
events, 5 to 12 picks), this was judged worth the token savings.

## Why 45 days, not signal-digest's 21

signal-digest's articles are read once and forgotten; a 21 day TTL is
generous for that. A hackathon's registration window commonly spans four to
eight weeks. A 21 day TTL would let an event fall out of cache and be
re-announced mid-window, which reads as a bug ("didn't I already see this?").
45 days comfortably outlasts a typical window, and an event still open after
that point resurfacing once doubles as a soft deadline reminder.

## Why Devfolio over Unstop

Both work. Devfolio was chosen because its first real recon result was
exactly the class of event this agent exists to catch: an in-person Bengaluru
AI hackathon. Unstop's result set skewed heavily toward college and
student-eligibility hackathons, and its payloads were roughly ten times
heavier for a similar or smaller signal yield. Unstop stays as a documented,
verified-working v2 option rather than a v1 source, so the token cost of
filtering it stays out of the weekly bill unless it is actually needed.

## Persistent=true fires immediately on first enable

`systemctl --user enable --now buildathon-radar.timer` was expected to just
arm the timer for the coming Sunday. Instead, journalctl showed the service
ran within a second of enabling it, a full real (non-dry) run, cache write,
archive write, and a real email sent, on a Monday. `Persistent=true` means
systemd keeps a per-timer stamp of the last time it fired; if that stamp does
not exist yet (a brand new timer, exactly this case), systemd treats the
timer as having missed every scheduled occurrence since it could have first
run and fires it immediately to catch up. This is documented systemd
behaviour, not a bug, but it is easy to miss when adapting a unit file
example that assumes the timer is being installed onto a machine where a
same-named timer has run before.

The practical lesson for next time: on a genuinely first-ever install of a
`Persistent=true` timer, either enable it without `--now` and let the first
real fire happen at its actual scheduled time, or accept and plan for the
fact that `--now` will trigger an immediate real run. There was no way to
detect this from the unit file text alone; it only showed up by checking
`journalctl` for the service right after enabling, which is worth doing on
every new timer, not just this one.

## Geography must not become a prestige penalty

Bengaluru in-person events are what this agent was built to catch, so the
rubric weights geography heavily. But the person it is built for has also
personally won a notable global online buildathon, and the two real misses
that motivated this project were both physical Bengaluru events, not evidence
that online events do not matter. The rubric was deliberately shaped so theme
fit, host prestige, and scale alone can sum to 70, the `must_see` threshold,
with zero geography points. A prestigious online hackathon from a major AI lab
does not need to be in Bengaluru to earn the top tier. This was confirmed live
in the first successful dry run: a Gemini-branded XPRIZE hackathon and an
OpenAI-hosted event both landed in `must_see`, entirely online, purely on
theme and host.
