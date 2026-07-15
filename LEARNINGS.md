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

## "No API" is not the same as "no free API"

Both Luma and Cerebral Valley looked, at a glance, like scraping-only
sources: neither publishes developer docs, and Cerebral Valley's own
`/events` page ships zero event data in its server-rendered HTML (it is
fully client-fetched). Neither actually required scraping. Luma's discover
pages call a plain JSON endpoint (`api.luma.com/discover/get-paginated-events`)
directly, unauthenticated, exactly the shape Devpost's `devpost.com/api/hackathons`
turned out to be back in v1. Cerebral Valley's was harder to find but no
less real: downloading `cerebralvalley.ai/events`'s ~35 JS chunks and
grepping them for fetch/URL construction surfaced `api.cerebralvalley.ai/v1/public/event/pull`
directly. The lesson repeats from v1: absence of documentation is not
evidence of absence of a free API. Before reaching for scraping or a paid
service, check what the site's own frontend actually calls, first via the
rendered page's embedded JSON (Luma's `__NEXT_DATA__`), then by tracing the
client-side JS bundles if the page is fully client-rendered (Cerebral
Valley). Both approaches were plain reconnaissance, no browser automation,
no headless rendering.

## Cerebral Valley's endpoint ignores every date/sort parameter it accepts

`api.cerebralvalley.ai/v1/public/event/pull?approved=true` returns its
entire event history, sorted ascending by start date, oldest first, with no
way to ask for "upcoming only." Probing plausible parameter names
(`upcoming`, `timeframe`, `startsAfter`, `order`, `sort`, `past`,
`minEndDateTime`) confirmed each is silently accepted and silently ignored;
the frontend evidently filters client-side after fetching everything. The
practical fix, and the one this build uses, is to read `totalCount` cheaply
(a `limit=1` call) and page backward from the tail until a page's earliest
event crosses into the past, rather than trying to guess a working filter
parameter. Worth remembering for any future undocumented API: a parameter
name that "looks right" and returns 200 is not evidence that it does
anything; only a response whose content actually changes is evidence.

## A live near-miss is worth more than a hypothetical one

ROADMAP.md's entity-resolution section (2.6) had deferred fuzzy or
LLM-assisted cross-source matching pending "real observed collisions," on
the theory that designing against a hypothetical is guesswork. The first
live four-source scan, on the same day Luma and Cerebral Valley were
added, produced exactly one real duplicate ("Build with Gemini XPRIZE" on
Devpost and Cerebral Valley) and, in the same scan, one real false-positive
candidate: two differently named hackathons on the same date sharing
two-thirds of their normalized words. That single scan did more to settle
the fuzzy-matching question than any amount of design discussion could
have: it is direct evidence that a similarity threshold loose enough to
catch real duplicates would also catch real false positives, in the same
data set, on the same day. The fix shipped is deliberately narrow (exact
normalized-title match within a date window, nothing looser) precisely
because the counterexample was sitting right there in the first live pull.

## A same-run duplicate that only shows up when merging same-day discoveries

Building the exact-title merge surfaced an edge case that had nothing to
do with title matching itself: `_should_show`'s resurface logic was written
to answer "should an already-known event resurface this week," reasoning
about a record's age since it was first cached. It was never designed to
answer "was this record created a few milliseconds ago, earlier in this
same function call." When two sources discover the same event for the
first time ever, in the same run, and its date happens to already be
inside the 14 day resurface window, the record the first source creates
looks, from `_should_show`'s point of view, exactly like a legitimately
resurfacing event to the second source's occurrence, so it would show
again, doubling the digest. The fix is a same-run-only guard
(`ids_shown_this_run`) that caps every `event_id` at one shown item per
run regardless of what `_should_show` computes. Nothing about this was
visible from reading `_should_show` in isolation; it only surfaced by
tracing through what happens when a second source's item for a brand-new
event lands on top of the first source's item within the same call.

## Passwordless sudo rules match the exact command, not the intent

Setting up the tracker's Cloudflare Tunnel entry needed `sudo systemctl
status cloudflared` to confirm the restart worked. The bare command ran
without a password, as expected from the existing NOPASSWD rule, but adding
`--no-pager` to keep the output clean made sudo prompt for a password. The
sudoers rule is an exact-command match, not a match on the underlying binary
or intent, so any extra flag falls outside it and sudo falls back to asking.
The practical fix is to just use the plain command as written in the
sudoers file rather than adding convenience flags, and to expect this on
any other passwordless rule on this Pi.

## Verifying an exclusion against "the events from last time" does not work

Asked to confirm two specific "students only" events were now excluded, the
obvious move was to re-run `--dry-run` and diff against the prior run. It
did not work: live source feeds change day to day, and the two events in
question were simply gone from today's pull, present or absent regardless
of the rubric change, so a before/after diff on live data proved nothing
either way. The reliable check was a targeted live call: build two synthetic
events matching the exact pattern described (a non-college host, wording
like "students only" and "must be a currently enrolled student"), plus one
inclusive-mention control ("open to students, professionals, and
researchers"), and call `run_agent` directly. That produced a real,
repeatable answer (both exclusions fired, the control was kept and scored
normally) that a live re-fetch could not have guaranteed. The lesson: when
verifying a filter change against real-world examples that were only ever
observed once, do not assume the same examples will still be live to
re-check against; reconstruct them as inputs instead.
